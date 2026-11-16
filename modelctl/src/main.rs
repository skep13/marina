//! modelctl — a fast, keyboard-driven TUI for managing the LLM models that
//! llama-swap serves to the homelab (lab3).
//!
//!   * list models + see which is loaded, load/swap or unload with a keystroke
//!   * view/edit llama-swap's config.yaml (safe: backup + validate + atomic)
//!   * pull GGUF files from Hugging Face onto lab3 with live progress

mod app;
mod client;
mod config;
mod ssh;
mod theme;
mod ui;
mod worker;

use std::io::{self, Stdout, Write};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use clap::Parser;
use crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use crossterm::execute;
use ratatui::prelude::*;

use app::{App, DlField, Screen};
use client::Client;
use config::{AppConfig, Overrides};
use ssh::Ssh;
use worker::{Job, Msg, Worker};

#[derive(Parser, Debug)]
#[command(
    name = "modelctl",
    about = "Manage the LLM models llama-swap serves to lab3 (list/swap, config, HF downloads)"
)]
struct Cli {
    /// llama-swap host (default 192.168.1.15 or $MODELCTL_HOST).
    #[arg(long)]
    host: Option<String>,
    /// llama-swap port (default 8080).
    #[arg(long)]
    port: Option<u16>,
    /// SSH target for lab3 (default root@<host>).
    #[arg(long)]
    ssh: Option<String>,
    /// API key (otherwise $MODELCTL_API_KEY, $MARINA_LAB3_KEY, or the key file).
    #[arg(long)]
    api_key: Option<String>,
    /// Remote models directory (default /models).
    #[arg(long)]
    models_dir: Option<String>,
    /// Remote llama-swap config path (default /opt/llama-swap/config.yaml).
    #[arg(long)]
    config_path: Option<String>,
    /// Print the model list and exit (no TUI).
    #[arg(long)]
    list: bool,
    /// Load/swap to the named model and exit (no TUI).
    #[arg(long, value_name = "MODEL")]
    load: Option<String>,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let ov = Overrides {
        host: cli.host.clone(),
        port: cli.port,
        ssh_target: cli.ssh.clone(),
        api_key: cli.api_key.clone(),
        models_dir: cli.models_dir.clone(),
        remote_config_path: cli.config_path.clone(),
        key_file: None,
    };
    let cfg = AppConfig::load(&ov).context("loading configuration")?;
    let client = Client::new(&cfg.base_url, &cfg.api_key)?;

    if cli.list {
        return print_models(&client);
    }

    if let Some(model) = &cli.load {
        eprintln!("loading {model}…");
        client.load(model)?;
        println!("loaded {model}");
        return print_models(&client);
    }

    let ssh = Ssh {
        target: cfg.ssh_target.clone(),
        models_dir: cfg.models_dir.clone(),
        config_path: cfg.remote_config_path.clone(),
        binary: cfg.remote_binary.clone(),
    };
    let worker = Worker::spawn(client, ssh);
    worker.send(Job::Refresh);

    let mut term = setup_terminal().context("setting up terminal")?;
    let app = App::new(cfg);
    let res = run_app(&mut term, app, &worker);
    restore_terminal(&mut term).ok();
    res
}

fn print_models(client: &Client) -> Result<()> {
    let models = client.list_models()?;
    let running = client.running().unwrap_or_default();
    println!("{:<20} {:<10} {:>8}  caps", "MODEL", "STATE", "CTX");
    for m in &models {
        let state = if m.loaded { "loaded" } else { "unloaded" };
        let mut caps = Vec::new();
        if m.vision {
            caps.push("vision");
        }
        if m.tools {
            caps.push("tools");
        }
        let ttl = running
            .iter()
            .find(|r| r.model == m.id)
            .map(|r| if r.ttl == 0 { " ttl=resident".into() } else { format!(" ttl={}s", r.ttl) })
            .unwrap_or_default();
        println!(
            "{:<20} {:<10} {:>8}  {}{}",
            m.id,
            state,
            m.context_length,
            caps.join(","),
            ttl
        );
    }
    Ok(())
}

type Tui = Terminal<CrosstermBackend<Stdout>>;

fn setup_terminal() -> Result<Tui> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    Ok(Terminal::new(backend)?)
}

fn restore_terminal(term: &mut Tui) -> Result<()> {
    disable_raw_mode()?;
    execute!(term.backend_mut(), LeaveAlternateScreen)?;
    term.show_cursor()?;
    Ok(())
}

fn run_app(term: &mut Tui, mut app: App, worker: &Worker) -> Result<()> {
    let mut last_poll = Instant::now();
    loop {
        term.draw(|f| ui::draw(f, &mut app))?;

        // Handle any queued worker messages.
        while let Ok(msg) = worker.rx.try_recv() {
            handle_msg(&mut app, msg);
        }

        // Poll an in-flight download about once a second.
        if app.screen == Screen::Download {
            if let Some(dl) = &app.download {
                if !dl.finished && dl.error.is_none() && last_poll.elapsed() >= Duration::from_millis(900) {
                    worker.send(Job::PollDownload {
                        filename: dl.filename.clone(),
                    });
                    last_poll = Instant::now();
                }
            }
        }

        // Input, with a short timeout so the loop keeps draining the worker.
        if event::poll(Duration::from_millis(150))? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    if handle_key(&mut app, key, worker, term)? {
                        break;
                    }
                }
            }
        }

        if app.should_quit {
            break;
        }
    }
    Ok(())
}

fn handle_msg(app: &mut App, msg: Msg) {
    match msg {
        Msg::Models { models, running } => {
            app.models = models;
            app.running = running;
            app.clamp_selection();
            app.busy = false;
            let summary = app.loaded_summary();
            app.set_status(summary);
        }
        Msg::Config(text) => {
            app.config_text = text;
            app.busy = false;
            app.set_status(format!("config loaded · {}", app.cfg.remote_config_path));
        }
        Msg::ConfigSaved(backup) => {
            app.busy = false;
            app.set_status("config saved · llama-swap will reload");
            app.toast(
                app::ToastKind::Success,
                format!("config saved (backup {backup})"),
            );
        }
        Msg::Notice(s) => {
            app.toast(app::ToastKind::Success, s.clone());
            app.set_status(s);
        }
        Msg::Error(e) => {
            app.busy = false;
            app.toast(app::ToastKind::Error, e.clone());
            app.set_error(e);
        }
        Msg::DownloadStarted { filename, total } => {
            app.busy = false;
            app.download = Some(app::Download::new(filename.clone(), total));
            app.toast(app::ToastKind::Info, format!("downloading {filename} on lab3"));
            app.set_status(format!("download started · {filename}"));
        }
        Msg::DownloadProgress(status) => {
            let mut done_name: Option<String> = None;
            let mut err_msg: Option<String> = None;
            if let Some(dl) = &mut app.download {
                dl.update(status.downloaded, status.finished, status.running, status.error.clone());
                if status.finished {
                    done_name = Some(dl.filename.clone());
                } else if let Some(err) = &status.error {
                    err_msg = Some(err.clone());
                }
            }
            if let Some(name) = done_name {
                app.toast(app::ToastKind::Success, format!("download complete · {name}"));
                app.set_status(format!("download complete · {name}"));
            } else if let Some(err) = err_msg {
                app.toast(app::ToastKind::Error, format!("download: {err}"));
                app.set_error(format!("download: {err}"));
            }
        }
    }
}

/// Returns Ok(true) to quit.
fn handle_key(app: &mut App, key: KeyEvent, worker: &Worker, term: &mut Tui) -> Result<bool> {
    // Global: Ctrl+C always quits.
    if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('c') {
        return Ok(true);
    }

    // Help overlay: any key dismisses it.
    if app.show_help {
        app.show_help = false;
        return Ok(false);
    }

    // Confirmation dialog takes precedence.
    if app.confirm_unload {
        match key.code {
            KeyCode::Char('y') | KeyCode::Char('Y') => {
                app.confirm_unload = false;
                app.busy = true;
                app.set_status("unloading…");
                worker.send(Job::Unload);
            }
            _ => {
                app.confirm_unload = false;
                app.set_status("cancelled");
            }
        }
        return Ok(false);
    }

    match app.screen {
        Screen::Download => return handle_download_key(app, key, worker),
        Screen::Config => handle_config_key(app, key, worker, term)?,
        Screen::Models => handle_models_key(app, key, worker),
    }
    Ok(false)
}

fn handle_models_key(app: &mut App, key: KeyEvent, worker: &Worker) {
    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Char('?') => app.show_help = true,
        KeyCode::Up | KeyCode::Char('k') => app.select_up(),
        KeyCode::Down | KeyCode::Char('j') => app.select_down(),
        KeyCode::Char('l') | KeyCode::Enter => {
            if let Some(m) = app.selected_model() {
                let id = m.id.clone();
                app.busy = true;
                app.set_status(format!("loading {id}… (may take a while for a big MoE)"));
                worker.send(Job::Load(id));
            }
        }
        KeyCode::Char('u') => {
            app.confirm_unload = true;
        }
        KeyCode::Char('r') => {
            app.busy = true;
            app.set_status("refreshing…");
            worker.send(Job::Refresh);
        }
        KeyCode::Char('2') => {
            app.screen = Screen::Config;
            if app.config_text.is_empty() {
                app.busy = true;
                worker.send(Job::LoadConfig);
            }
        }
        KeyCode::Char('3') => {
            app.screen = Screen::Download;
        }
        _ => {}
    }
}

fn handle_config_key(app: &mut App, key: KeyEvent, worker: &Worker, term: &mut Tui) -> Result<()> {
    match key.code {
        KeyCode::Char('q') | KeyCode::Esc => app.should_quit = true,
        KeyCode::Char('?') => app.show_help = true,
        KeyCode::Char('1') => app.screen = Screen::Models,
        KeyCode::Char('3') => app.screen = Screen::Download,
        KeyCode::Down | KeyCode::Char('j') => app.config_scroll = app.config_scroll.saturating_add(1),
        KeyCode::Up | KeyCode::Char('k') => app.config_scroll = app.config_scroll.saturating_sub(1),
        KeyCode::PageDown => app.config_scroll = app.config_scroll.saturating_add(10),
        KeyCode::PageUp => app.config_scroll = app.config_scroll.saturating_sub(10),
        KeyCode::Char('r') => {
            app.busy = true;
            app.set_status("reloading config…");
            worker.send(Job::LoadConfig);
        }
        KeyCode::Char('e') => {
            if app.config_text.is_empty() {
                app.set_error("config not loaded yet");
                return Ok(());
            }
            edit_config(app, worker, term)?;
        }
        _ => {}
    }
    Ok(())
}

fn handle_download_key(app: &mut App, key: KeyEvent, worker: &Worker) -> Result<bool> {
    match key.code {
        KeyCode::Esc => app.screen = Screen::Models,
        // Repo ids / filenames never contain '?', so use it for help.
        KeyCode::Char('?') => app.show_help = true,
        KeyCode::Tab | KeyCode::Down => {
            app.dl_field = match app.dl_field {
                DlField::Repo => DlField::File,
                DlField::File => DlField::Revision,
                DlField::Revision => DlField::Repo,
            };
        }
        KeyCode::BackTab | KeyCode::Up => {
            app.dl_field = match app.dl_field {
                DlField::Repo => DlField::Revision,
                DlField::File => DlField::Repo,
                DlField::Revision => DlField::File,
            };
        }
        KeyCode::Backspace => {
            field_mut(app).pop();
        }
        KeyCode::Enter => {
            let repo = app.dl_repo.trim().to_string();
            let file = app.dl_file.trim().to_string();
            let rev = {
                let r = app.dl_rev.trim();
                if r.is_empty() { "main".to_string() } else { r.to_string() }
            };
            if repo.is_empty() || file.is_empty() {
                app.set_error("repo id and filename are required");
            } else {
                app.busy = true;
                app.download = None;
                app.set_status(format!("starting download of {file} on lab3…"));
                worker.send(Job::StartDownload {
                    repo,
                    filename: file,
                    revision: rev,
                });
            }
        }
        KeyCode::Char(c) => {
            field_mut(app).push(c);
        }
        _ => {}
    }
    Ok(false)
}

fn field_mut(app: &mut App) -> &mut String {
    match app.dl_field {
        DlField::Repo => &mut app.dl_repo,
        DlField::File => &mut app.dl_file,
        DlField::Revision => &mut app.dl_rev,
    }
}

/// Suspend the TUI, open the config in $EDITOR, then validate + save on return.
fn edit_config(app: &mut App, worker: &Worker, term: &mut Tui) -> Result<()> {
    let editor = std::env::var("VISUAL")
        .or_else(|_| std::env::var("EDITOR"))
        .unwrap_or_else(|_| "vi".to_string());

    // Write current config to a temp file.
    let dir = std::env::temp_dir();
    let path = dir.join(format!("modelctl-config-{}.yaml", std::process::id()));
    std::fs::write(&path, &app.config_text).context("writing temp config")?;

    // Leave the TUI so the editor owns the terminal.
    restore_terminal(term)?;

    let status = std::process::Command::new(&editor)
        .arg(&path)
        .status()
        .with_context(|| format!("launching editor `{editor}`"));

    // Re-enter the TUI regardless of how the editor exited.
    *term = setup_terminal()?;
    term.clear()?;

    let status = status?;
    if !status.success() {
        app.set_error(format!("{editor} exited abnormally; config not changed"));
        let _ = std::fs::remove_file(&path);
        return Ok(());
    }

    let edited = std::fs::read_to_string(&path).context("reading edited config")?;
    let _ = std::fs::remove_file(&path);

    if edited == app.config_text {
        app.set_status("no changes");
        return Ok(());
    }

    // Keep the view in sync and let the worker validate+back up+write.
    app.config_text = edited.clone();
    app.busy = true;
    app.set_status("validating & saving to lab3…");
    worker.send(Job::SaveConfig(edited));
    // Make sure prompt flush doesn't swallow anything.
    io::stdout().flush().ok();
    Ok(())
}
