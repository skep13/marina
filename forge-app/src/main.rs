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
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
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

/// The startup stages shown on the opening screen's heat bar.
#[derive(Debug, Clone, Copy)]
enum Step {
    Key,
    Tap,
    Lab3,
    Harness,
}

impl Step {
    fn id(self) -> &'static str {
        match self {
            Step::Key => "key",
            Step::Tap => "tap",
            Step::Lab3 => "lab3",
            Step::Harness => "harness",
        }
    }
}

#[derive(Debug)]
enum UserEvent {
    Status(Step, String),
    Ready(String),
    Failed { step: Step, title: String, detail: String },
    ServerExited(String),
    /// The YubiKey was unplugged while Forge was running.
    Locked,
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

/// Homebrew's OpenSSH: Apple's build can't talk to FIDO security keys.
const SSH_KEYGEN: &str = "/opt/homebrew/bin/ssh-keygen";
/// Signature namespace, so an unlock signature can't be reused as anything else.
const UNLOCK_NAMESPACE: &str = "forge-unlock";

/// Is a YubiKey plugged in over USB?
fn yubikey_present() -> bool {
    Command::new("/usr/sbin/ioreg")
        .args(["-p", "IOUSB", "-w0"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).to_lowercase().contains("yubikey"))
        .unwrap_or(false)
}

/// Prove the user's YubiKey is here and touched: have it sign a fresh random
/// challenge with its SSH key (`~/.ssh/id_ed25519_sk`, needs a tap) and check
/// the signature against the public key pinned in
/// `~/.forge/yubikey_allowed_signers`.
fn yubikey_unlock() -> Result<(), (Step, String)> {
    let key = home().join(".ssh/id_ed25519_sk");
    let signers = home().join(".forge/yubikey_allowed_signers");
    if !key.exists() || !signers.exists() {
        return Err((
            Step::Key,
            "The YubiKey isn't set up for Forge (missing ~/.ssh/id_ed25519_sk or \
             ~/.forge/yubikey_allowed_signers)."
                .into(),
        ));
    }
    yubikey_sign_and_verify(&key, &signers)
}

fn yubikey_sign_and_verify(
    key: &std::path::Path,
    signers: &std::path::Path,
) -> Result<(), (Step, String)> {
    let tap = |e: String| (Step::Tap, e);
    let mut nonce = [0u8; 32];
    fs::File::open("/dev/urandom")
        .and_then(|mut f| std::io::Read::read_exact(&mut f, &mut nonce))
        .map_err(|e| tap(format!("Couldn't make a challenge: {e}")))?;
    let dir = home().join(".forge/run");
    let _ = fs::create_dir_all(&dir);
    let challenge = dir.join(format!("unlock-{}", std::process::id()));
    let sig = challenge.with_extension("sig");
    let _ = fs::remove_file(&sig);
    fs::write(&challenge, nonce).map_err(|e| tap(format!("Couldn't write the challenge: {e}")))?;

    let result = (|| -> Result<(), String> {
        let out = Command::new(SSH_KEYGEN)
            .args(["-Y", "sign", "-n", UNLOCK_NAMESPACE, "-f"])
            .arg(&key)
            .arg(&challenge)
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("Couldn't run ssh-keygen: {e}"))?;
        if !out.status.success() {
            let err = String::from_utf8_lossy(&out.stderr);
            log_line(&format!("--- yubikey sign failed: {}", err.trim()));
            return Err(if err.contains("device not found") {
                "The YubiKey wasn't found. Plug it in and press Unlock.".into()
            } else {
                "The YubiKey wasn't tapped in time. Press Unlock and tap the gold contact \
                 when it flashes."
                    .into()
            });
        }
        let ok = Command::new(SSH_KEYGEN)
            .args(["-Y", "verify", "-I", "forge", "-n", UNLOCK_NAMESPACE, "-f"])
            .arg(&signers)
            .arg("-s")
            .arg(&sig)
            .stdin(fs::File::open(&challenge).map_err(|e| e.to_string())?)
            .output()
            .map_err(|e| format!("Couldn't run ssh-keygen: {e}"))?;
        if ok.status.success() {
            Ok(())
        } else {
            log_line(&format!(
                "--- yubikey verify failed: {}",
                String::from_utf8_lossy(&ok.stderr).trim()
            ));
            Err("That key isn't the YubiKey Forge is paired with.".into())
        }
    })();
    let _ = fs::remove_file(&challenge);
    let _ = fs::remove_file(&sig);
    // A missing key sends the user back to the "plug in" stage; anything
    // else is a tap that didn't happen (or the wrong key).
    result.map_err(|e| {
        if e.starts_with("The YubiKey wasn't found") { (Step::Key, e) } else { tap(e) }
    })
}

/// While Forge is unlocked, watch for the YubiKey being unplugged. Stops
/// quietly once `generation` moves on (a retry or relaunch started).
fn watch_yubikey(proxy: EventLoopProxy<UserEvent>, generation: Arc<AtomicU64>, mine: u64) {
    thread::spawn(move || {
        while generation.load(Ordering::SeqCst) == mine {
            if !yubikey_present() {
                // Re-check once so a USB hiccup doesn't lock Forge.
                thread::sleep(Duration::from_millis(800));
                if generation.load(Ordering::SeqCst) == mine && !yubikey_present() {
                    let _ = proxy.send_event(UserEvent::Locked);
                }
                return;
            }
            thread::sleep(Duration::from_secs(2));
        }
    });
}

fn lab3_reachable() -> bool {
    let addr: SocketAddr = LAB3.parse().unwrap();
    TcpStream::connect_timeout(&addr, Duration::from_secs(3)).is_ok()
}

/// Check lab3, start `dsh web`, and report the URL (or the failure) back to
/// the UI thread.
fn launch(proxy: EventLoopProxy<UserEvent>, server: Server, generation: Arc<AtomicU64>) {
    let mine = generation.fetch_add(1, Ordering::SeqCst) + 1;
    thread::spawn(move || {
        let send = |e| {
            let _ = proxy.send_event(e);
        };

        // Forge only opens with the user's YubiKey: plugged in, then tapped.
        if !yubikey_present() {
            send(UserEvent::Status(Step::Key, "Plug in your YubiKey to open Forge.".into()));
            while !yubikey_present() {
                if generation.load(Ordering::SeqCst) != mine {
                    return;
                }
                thread::sleep(Duration::from_secs(1));
            }
        }
        send(UserEvent::Status(
            Step::Tap,
            "Tap your YubiKey to unlock Forge — the gold contact, when it flashes.".into(),
        ));
        if let Err((step, detail)) = yubikey_unlock() {
            send(UserEvent::Failed { step, title: "Forge is locked".into(), detail });
            return;
        }
        log_line("--- unlocked with YubiKey");
        watch_yubikey(proxy.clone(), generation.clone(), mine);

        send(UserEvent::Status(Step::Lab3, "Reaching lab3…".into()));
        // The first connection can trigger macOS's "allow local network"
        // prompt and fail while it is open, so keep trying for a while.
        let mut ok = lab3_reachable();
        for i in 0..10 {
            if ok {
                break;
            }
            if i == 0 {
                send(UserEvent::Status(
                    Step::Lab3,
                    "Waiting for lab3… (if macOS asks to allow local network access, click Allow)"
                        .into(),
                ));
            }
            thread::sleep(Duration::from_secs(3));
            ok = lab3_reachable();
        }
        if !ok {
            send(UserEvent::Failed {
                step: Step::Lab3,
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
                    step: Step::Harness,
                    title: "Forge isn't set up".into(),
                    detail: format!("Couldn't read ~/.forge/lab3.key ({e})."),
                });
                return;
            }
        };
        if !dsh.exists() {
            send(UserEvent::Failed {
                step: Step::Harness,
                title: "Forge isn't set up".into(),
                detail: "DeepSeek Harness is missing from ~/.forge/app.".into(),
            });
            return;
        }

        send(UserEvent::Status(Step::Harness, "Lighting the harness…".into()));
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
                    step: Step::Harness,
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

/// The opening screen (src/splash.html): the heat bar shows which startup
/// stage is running; `error` turns it into the "quenched" failure view.
fn splash(step: Step, status: &str, error: Option<(&str, &str)>) -> String {
    const PAGE: &str = include_str!("splash.html");
    let (mode, title, detail) = match error {
        Some((t, d)) => ("error", t, d),
        None => ("work", "", ""),
    };
    // Locked screens unlock with the YubiKey; everything else retries.
    let button = if title.contains("locked") { "Unlock" } else { "Retry" };
    PAGE.replace("{{STEP}}", step.id())
        .replace("{{MODE}}", mode)
        .replace("{{STATUS}}", &esc(status))
        .replace("{{ERR_TITLE}}", &esc(title))
        .replace("{{ERR_DETAIL}}", &esc(detail))
        .replace("{{BUTTON}}", button)
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
        .with_html(splash(Step::Key, "Waking up…", None))
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
    // Bumped on every (re)launch so stale unlock waits and USB watchers stop.
    let generation = Arc::new(AtomicU64::new(0));
    let mut current_url: Option<String> = None;
    launch(proxy.clone(), server.clone(), generation.clone());

    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(UserEvent::Status(step, s)) => {
                let _ = webview.evaluate_script(&format!(
                    "window.setStep && window.setStep({}, {})",
                    serde_json::to_string(step.id()).unwrap(),
                    serde_json::to_string(&s).unwrap()
                ));
            }
            Event::UserEvent(UserEvent::Ready(url)) => {
                current_url = Some(url.clone());
                let _ = webview.load_url(&url);
            }
            Event::UserEvent(UserEvent::Failed { step, title, detail }) => {
                let _ = webview.load_html(&splash(step, "", Some((&title, &detail))));
            }
            Event::UserEvent(UserEvent::Locked) => {
                generation.fetch_add(1, Ordering::SeqCst);
                stop_server(&server);
                current_url = None;
                log_line("--- locked: YubiKey unplugged");
                let _ = webview.load_html(&splash(
                    Step::Key,
                    "",
                    Some((
                        "Forge is locked",
                        "Your YubiKey was unplugged, so Forge stopped. Plug it back in and press \
                         Unlock. Your sessions are kept.",
                    )),
                ));
            }
            Event::UserEvent(UserEvent::ServerExited(status)) => {
                generation.fetch_add(1, Ordering::SeqCst);
                current_url = None;
                let _ = webview.load_html(&splash(
                    Step::Harness,
                    "",
                    Some(("Forge stopped", &format!("The harness exited ({status}).")))
                ));
            }
            Event::UserEvent(UserEvent::Retry) => {
                stop_server(&server);
                let _ = webview.load_html(&splash(Step::Key, "Waking up…", None));
                launch(proxy.clone(), server.clone(), generation.clone());
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
