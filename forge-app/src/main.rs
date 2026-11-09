//! Forge.app — a native macOS window for the Forge coding agent.
//!
//! Starts the DeepSeek Harness web server (configured in ~/.forge to use the
//! `forge` model on lab3), waits for its tokenised URL, and shows it in a
//! WebKit window. Quitting the app stops the server.

use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Write},
    net::{SocketAddr, TcpStream},
    os::unix::process::CommandExt,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

use muda::{accelerator::Accelerator, Menu, MenuEvent, MenuItem, PredefinedMenuItem, Submenu};
use tao::{
    dpi::LogicalSize,
    event::{Event, WindowEvent},
    event_loop::{ControlFlow, EventLoopBuilder, EventLoopProxy},
    window::WindowBuilder,
};
use wry::{NewWindowResponse, WebViewBuilder};

/// Where llama-swap on lab3 listens (reached over the ethernet cable).
const LAB3: &str = "192.168.1.15:8080";
const NODE_BIN: &str = "/opt/homebrew/opt/node@24/bin";

#[derive(Debug)]
enum UserEvent {
    Status(String),
    Ready(String),
    Failed { title: String, detail: String },
    ServerExited(String),
    Retry,
    Menu(MenuEvent),
}

type Server = Arc<Mutex<Option<Child>>>;

fn home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/".into()))
}

fn log_line(msg: &str) {
    let path = home().join(".forge/app.log");
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(f, "{msg}");
    }
}

/// Stop the harness server and everything it spawned (it runs in its own
/// process group).
fn stop_server(server: &Server) {
    if let Some(mut child) = server.lock().unwrap().take() {
        let pgid = child.id() as i32;
        unsafe {
            libc::kill(-pgid, libc::SIGTERM);
        }
        for _ in 0..30 {
            if let Ok(Some(_)) = child.try_wait() {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        unsafe {
            libc::kill(-pgid, libc::SIGKILL);
        }
        let _ = child.wait();
    }
}

fn lab3_reachable() -> bool {
    let addr: SocketAddr = LAB3.parse().unwrap();
    TcpStream::connect_timeout(&addr, Duration::from_secs(3)).is_ok()
}

/// Check lab3, start `dsh web`, and report the URL (or the failure) back to
/// the UI thread.
fn launch(proxy: EventLoopProxy<UserEvent>, server: Server) {
    thread::spawn(move || {
        let send = |e| {
            let _ = proxy.send_event(e);
        };
        send(UserEvent::Status("Checking the connection to lab3…".into()));
        // The first connection can trigger macOS's "allow local network"
        // prompt and fail while it is open, so keep trying for a while.
        let mut ok = lab3_reachable();
        for i in 0..10 {
            if ok {
                break;
            }
            if i == 0 {
                send(UserEvent::Status(
                    "Waiting for lab3… (if macOS asks to allow local network access, click Allow)"
                        .into(),
                ));
            }
            thread::sleep(Duration::from_secs(3));
            ok = lab3_reachable();
        }
        if !ok {
            send(UserEvent::Failed {
                title: "Can't reach lab3".into(),
                detail: format!(
                    "Nothing answered at {LAB3}. Check the ethernet cable. If it is plugged in, \
                     unplug the USB ethernet adapter from the Mac for a few seconds and plug it \
                     back in, then press Retry."
                ),
            });
            return;
        }

        let forge = home().join(".forge");
        let dsh = forge.join("app/node_modules/.bin/dsh");
        let key = match fs::read_to_string(forge.join("lab3.key")) {
            Ok(k) => k.trim().to_string(),
            Err(e) => {
                send(UserEvent::Failed {
                    title: "Forge isn't set up".into(),
                    detail: format!("Couldn't read ~/.forge/lab3.key ({e})."),
                });
                return;
            }
        };
        if !dsh.exists() {
            send(UserEvent::Failed {
                title: "Forge isn't set up".into(),
                detail: "DeepSeek Harness is missing from ~/.forge/app.".into(),
            });
            return;
        }

        send(UserEvent::Status("Starting Forge…".into()));
        let path = format!(
            "{NODE_BIN}:{}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            home().join(".local/bin").display()
        );
        // Run dsh under a tiny sh supervisor in its own process group: if this
        // app dies without cleaning up (force quit, crash), the supervisor
        // notices within ~2s and takes the whole group down, so no orphaned
        // server is left running.
        const SUPERVISOR: &str = r#"app=$1; shift
"$@" & srv=$!
stop() { trap '' TERM INT HUP; kill -TERM 0 2>/dev/null; exit 143; }
trap stop TERM INT HUP
while kill -0 "$app" 2>/dev/null && kill -0 "$srv" 2>/dev/null; do sleep 2; done
kill -0 "$app" 2>/dev/null || stop
wait "$srv"; exit $?"#;
        let child = Command::new("/bin/sh")
            .arg("-c")
            .arg(SUPERVISOR)
            .arg("forge-supervisor")
            .arg(std::process::id().to_string())
            .arg(&dsh)
            .args(["--profile", "web", "--no-open", "--port", "0"])
            .current_dir(home())
            .env("PATH", path)
            .env("DSH_HOME", forge.join("home"))
            .env("DSH_TELEMETRY_MODE", "DISABLED")
            .env("FORGE_LAB3_KEY", key)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn();
        let mut child = match child {
            Ok(c) => c,
            Err(e) => {
                send(UserEvent::Failed {
                    title: "Forge didn't start".into(),
                    detail: format!("Couldn't run DeepSeek Harness: {e}"),
                });
                return;
            }
        };
        log_line(&format!("--- started dsh web (pid {})", child.id()));

        let stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        *server.lock().unwrap() = Some(child);

        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                log_line(&format!("[err] {line}"));
            }
        });

        let mut announced = false;
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            log_line(&line);
            if !announced {
                if let Some(i) = line.find("http://127.0.0.1:") {
                    let url = line[i..].split_whitespace().next().unwrap_or("").to_string();
                    announced = true;
                    send(UserEvent::Ready(url));
                }
            }
        }

        // stdout closed: the server has exited (or is exiting).
        let status = server
            .lock()
            .unwrap()
            .as_mut()
            .and_then(|c| c.wait().ok())
            .map(|s| s.to_string());
        if let Some(status) = status {
            log_line(&format!("--- dsh web exited: {status}"));
            send(UserEvent::ServerExited(status));
        }
    });
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

/// The loading / error screen shown before the harness UI is ready.
fn splash(status: &str, error: Option<(&str, &str)>) -> String {
    let body = match error {
        None => format!(
            r#"<div class="spin"></div><p id="status">{}</p>"#,
            esc(status)
        ),
        Some((title, detail)) => format!(
            r#"<h2>{}</h2><p class="detail">{}</p>
               <button onclick="window.ipc.postMessage('retry')">Retry</button>
               <p class="hint">Log: ~/.forge/app.log</p>"#,
            esc(title),
            esc(detail)
        ),
    };
    format!(
        r#"<!doctype html><html><head><meta charset="utf-8"><style>
:root {{ --bg:#f6f4ef; --fg:#1d1b18; --muted:#6b665d; --accent:#d9682b; --line:#e2ddd2; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#16140f; --fg:#efe9df; --muted:#9a9284; --accent:#ef8a4c; --line:#2c2820; }}
}}
html,body {{ height:100%; margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif; }}
body {{ display:flex; align-items:center; justify-content:center; -webkit-user-select:none; }}
.card {{ text-align:center; max-width:440px; padding:24px; }}
h1 {{ font-size:34px; letter-spacing:-0.02em; margin:0 0 4px; }}
h1 span {{ color:var(--accent); }}
.sub {{ color:var(--muted); margin:0 0 32px; font-size:13px; }}
h2 {{ font-size:18px; margin:0 0 8px; }}
.detail {{ color:var(--muted); margin:0 0 20px; }}
.hint {{ color:var(--muted); font-size:12px; margin-top:18px; }}
#status {{ color:var(--muted); }}
.spin {{ width:26px; height:26px; margin:0 auto 14px; border-radius:50%;
  border:3px solid var(--line); border-top-color:var(--accent); animation:s 0.9s linear infinite; }}
@keyframes s {{ to {{ transform:rotate(360deg); }} }}
button {{ font:inherit; padding:8px 22px; border-radius:8px; border:1px solid var(--line);
  background:var(--accent); color:#fff; cursor:pointer; }}
</style></head><body><div class="card">
<h1><span>◆</span> Forge</h1><p class="sub">KAT-Coder on lab3 · DeepSeek Harness</p>
{body}
</div><script>window.setStatus = t => {{ const e = document.getElementById('status'); if (e) e.textContent = t; }};</script>
</body></html>"#
    )
}

fn build_menu() -> (Menu, MenuItem, MenuItem, MenuItem) {
    let menu = Menu::new();
    let quit = MenuItem::new("Quit Forge", true, "CmdOrCtrl+Q".parse::<Accelerator>().ok());
    let reload = MenuItem::new("Reload", true, "CmdOrCtrl+R".parse::<Accelerator>().ok());
    let browser = MenuItem::new(
        "Open in Browser",
        true,
        "CmdOrCtrl+Shift+O".parse::<Accelerator>().ok(),
    );

    let app = Submenu::with_items(
        "Forge",
        true,
        &[
            &PredefinedMenuItem::about(Some("About Forge"), None),
            &PredefinedMenuItem::separator(),
            &PredefinedMenuItem::hide(None),
            &PredefinedMenuItem::hide_others(None),
            &PredefinedMenuItem::show_all(None),
            &PredefinedMenuItem::separator(),
            &quit,
        ],
    )
    .unwrap();
    let edit = Submenu::with_items(
        "Edit",
        true,
        &[
            &PredefinedMenuItem::undo(None),
            &PredefinedMenuItem::redo(None),
            &PredefinedMenuItem::separator(),
            &PredefinedMenuItem::cut(None),
            &PredefinedMenuItem::copy(None),
            &PredefinedMenuItem::paste(None),
            &PredefinedMenuItem::select_all(None),
        ],
    )
    .unwrap();
    let view = Submenu::with_items(
        "View",
        true,
        &[&reload, &browser, &PredefinedMenuItem::separator(), &PredefinedMenuItem::fullscreen(None)],
    )
    .unwrap();
    let window = Submenu::with_items(
        "Window",
        true,
        &[&PredefinedMenuItem::minimize(None), &PredefinedMenuItem::close_window(None)],
    )
    .unwrap();
    menu.append_items(&[&app, &edit, &view, &window]).unwrap();
    (menu, quit, reload, browser)
}

fn open_external(url: &str) {
    let _ = Command::new("/usr/bin/open").arg(url).spawn();
}

fn main() -> wry::Result<()> {
    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();

    let (menu, quit_item, reload_item, browser_item) = build_menu();
    menu.init_for_nsapp();
    {
        let proxy = proxy.clone();
        MenuEvent::set_event_handler(Some(move |e| {
            let _ = proxy.send_event(UserEvent::Menu(e));
        }));
    }

    let window = WindowBuilder::new()
        .with_title("Forge")
        .with_inner_size(LogicalSize::new(1280.0, 860.0))
        .with_min_inner_size(LogicalSize::new(760.0, 520.0))
        .build(&event_loop)
        .unwrap();

    let ipc_proxy = proxy.clone();
    let webview = WebViewBuilder::new()
        .with_html(splash("Starting…", None))
        .with_devtools(cfg!(debug_assertions))
        .with_ipc_handler(move |req| {
            if req.body() == "retry" {
                let _ = ipc_proxy.send_event(UserEvent::Retry);
            }
        })
        // Links that try to open a new window go to the default browser.
        .with_new_window_req_handler(|url, _| {
            open_external(&url);
            NewWindowResponse::Deny
        })
        .build(&window)?;

    let server: Server = Arc::new(Mutex::new(None));
    let mut current_url: Option<String> = None;
    launch(proxy.clone(), server.clone());

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(UserEvent::Status(s)) => {
                let _ = webview.evaluate_script(&format!(
                    "window.setStatus && window.setStatus({})",
                    serde_json::to_string(&s).unwrap()
                ));
            }
            Event::UserEvent(UserEvent::Ready(url)) => {
                current_url = Some(url.clone());
                let _ = webview.load_url(&url);
            }
            Event::UserEvent(UserEvent::Failed { title, detail }) => {
                let _ = webview.load_html(&splash("", Some((&title, &detail))));
            }
            Event::UserEvent(UserEvent::ServerExited(status)) => {
                current_url = None;
                let _ = webview.load_html(&splash(
                    "",
                    Some(("Forge stopped", &format!("The harness exited ({status}).")))
                ));
            }
            Event::UserEvent(UserEvent::Retry) => {
                stop_server(&server);
                let _ = webview.load_html(&splash("Starting…", None));
                launch(proxy.clone(), server.clone());
            }
            Event::UserEvent(UserEvent::Menu(e)) => {
                if e.id == *quit_item.id() {
                    stop_server(&server);
                    *control_flow = ControlFlow::Exit;
                } else if e.id == *reload_item.id() {
                    match &current_url {
                        Some(u) => {
                            let _ = webview.load_url(u);
                        }
                        None => {
                            let _ = proxy.send_event(UserEvent::Retry);
                        }
                    }
                } else if e.id == *browser_item.id() {
                    if let Some(u) = &current_url {
                        open_external(u);
                    }
                }
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                stop_server(&server);
                *control_flow = ControlFlow::Exit;
            }
            Event::LoopDestroyed => stop_server(&server),
            _ => {}
        }
    });
}
