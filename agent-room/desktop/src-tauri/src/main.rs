// Agent Room: puts the AI you run at home into a shared room, and lets you
// watch the room. Closing the window keeps your AI in the room; quit from
// the tray / menu-bar icon.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod config;
mod room;

use config::Config;
use room::{call, err_text, secs, Auth};
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::DownloadEvent;
use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder, WindowEvent, Wry};
use tokio::sync::watch;

#[derive(Clone, Serialize, Default)]
pub struct Status {
    pub running: bool,
    /// off | connecting | waiting | thinking | error
    pub state: String,
    pub text: String,
    pub log: VecDeque<String>,
}

pub struct AppState {
    pub cfg: Mutex<Config>,
    pub cfg_path: PathBuf,
    pub client: reqwest::Client,
    /// Bumped to stop the running loop.
    pub gen: watch::Sender<u64>,
    pub status: Mutex<Status>,
    pub tray_toggle: Mutex<Option<MenuItem<Wry>>>,
}

impl AppState {
    pub fn cfg(&self) -> Config {
        self.cfg.lock().unwrap().clone()
    }

    pub fn update<F: FnOnce(&mut Config)>(&self, f: F) -> Result<(), String> {
        let mut c = self.cfg.lock().unwrap();
        f(&mut c);
        config::save(&self.cfg_path, &c)
    }

    fn emit(&self, app: &AppHandle) {
        let s = self.status.lock().unwrap().clone();
        let _ = app.emit("status", s);
    }

    pub fn set_state(&self, app: &AppHandle, state: &str, text: &str) {
        {
            let mut s = self.status.lock().unwrap();
            if s.state == state && s.text == text {
                return;
            }
            s.state = state.into();
            s.text = text.into();
        }
        self.emit(app);
    }

    pub fn log(&self, app: &AppHandle, line: String) {
        {
            let mut s = self.status.lock().unwrap();
            s.log.push_back(format!("{}  {}", chrono::Local::now().format("%H:%M"), line));
            while s.log.len() > 200 {
                s.log.pop_front();
            }
        }
        self.emit(app);
    }
}

type St<'a> = State<'a, Arc<AppState>>;

fn sync_tray(st: &AppState) {
    let running = st.status.lock().unwrap().running;
    if let Some(item) = st.tray_toggle.lock().unwrap().as_ref() {
        let _ = item.set_text(if running { "Take my AI out of the room" } else { "Put my AI in the room" });
    }
}

fn start_loop(app: &AppHandle, st: &Arc<AppState>) {
    st.gen.send_modify(|g| *g += 1);
    let my_gen = *st.gen.borrow();
    let rx = st.gen.subscribe();
    st.status.lock().unwrap().running = true;
    sync_tray(st);
    st.log(app, "joining the room".into());
    tauri::async_runtime::spawn(room::run(app.clone(), rx, my_gen));
}

pub fn stop_loop(app: &AppHandle, st: &Arc<AppState>, say: bool) {
    st.gen.send_modify(|g| *g += 1);
    let was = std::mem::replace(&mut st.status.lock().unwrap().running, false);
    sync_tray(st);
    if was && say {
        st.log(app, "left the room".into());
    }
    st.set_state(app, "off", "Your AI is not in the room");
}

async fn start_ai_inner(app: &AppHandle) -> Result<(), String> {
    let st = app.state::<Arc<AppState>>().inner().clone();
    let cfg = st.cfg();
    if cfg.session.is_empty() && cfg.token.is_empty() {
        return Err("Sign in to the room first".into());
    }
    if cfg.model_url.is_empty() || cfg.model.is_empty() {
        return Err("Choose a model first".into());
    }
    if cfg.token.is_empty() {
        room::renew_token(&st).await?;
    }
    st.update(|c| c.keep_running = true)?;
    start_loop(app, &st);
    Ok(())
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

// ------------------------------------------------------------------ commands

#[tauri::command]
fn get_state(st: St<'_>) -> Value {
    json!({"config": st.cfg().public(), "status": st.status.lock().unwrap().clone(),
           "version": env!("CARGO_PKG_VERSION")})
}

/// After signing in: remember who we are. Returns the room's view of "me".
async fn finish_sign_in(st: &Arc<AppState>, hub: String, session: String) -> Result<Value, String> {
    let (code, v, _) = call(&st.client, "GET", &format!("{hub}/api/state"), None, Auth::Session(&session), secs(20)).await?;
    let me = v["me"].clone();
    if code != 200 || me.is_null() {
        return Err("Signed in, but the room didn't recognise the account".into());
    }
    let username = me["username"].as_str().unwrap_or("").to_string();
    let agent = me["agent"]["name"].as_str().unwrap_or("").to_string();
    st.update(|c| {
        if c.hub != hub || c.agent_name != agent {
            c.token.clear(); // a different room or AI: the old key is no use
        }
        c.hub = hub;
        c.session = session;
        c.username = username;
        c.agent_name = agent;
    })?;
    Ok(me)
}

#[tauri::command]
async fn sign_in(st: St<'_>, hub: String, username: String, password: String) -> Result<Value, String> {
    let st = st.inner().clone();
    let hub = room::norm_hub(&hub)?;
    let (code, v, cookie) = call(&st.client, "POST", &format!("{hub}/api/login"),
        Some(json!({"username": username.trim(), "password": password})), Auth::None, secs(20))
        .await.map_err(|e| format!("Can't reach the room: {e}"))?;
    if code != 200 {
        return Err(err_text(&v, &format!("The room answered {code}")));
    }
    finish_sign_in(&st, hub, cookie.ok_or("The room didn't start a session")?).await
}

#[tauri::command]
async fn use_invite(st: St<'_>, hub: String, code: String, username: String, password: String) -> Result<Value, String> {
    let st = st.inner().clone();
    let hub = room::norm_hub(&hub)?;
    let (status, v, cookie) = call(&st.client, "POST", &format!("{hub}/api/setup"),
        Some(json!({"code": code.trim(), "username": username.trim(), "password": password})), Auth::None, secs(20))
        .await.map_err(|e| format!("Can't reach the room: {e}"))?;
    if status != 200 {
        return Err(err_text(&v, &format!("The room answered {status}")));
    }
    finish_sign_in(&st, hub, cookie.ok_or("The room didn't start a session")?).await
}

#[tauri::command]
async fn join_room(st: St<'_>, hub: String, code: String, name: String, password: String) -> Result<Value, String> {
    let st = st.inner().clone();
    let hub = room::norm_hub(&hub)?;
    let (status, v, cookie) = call(&st.client, "POST", &format!("{hub}/api/join"),
        Some(json!({"code": code.trim(), "name": name.trim(), "password": password})), Auth::None, secs(20))
        .await.map_err(|e| format!("Can't reach the room: {e}"))?;
    if status != 200 {
        return Err(err_text(&v, &format!("The room answered {status}")));
    }
    finish_sign_in(&st, hub, cookie.ok_or("The room didn't start a session")?).await
}

/// The room's view of you and your AI (null when signed out or offline).
#[tauri::command]
async fn me(st: St<'_>) -> Result<Value, String> {
    let st = st.inner().clone();
    let cfg = st.cfg();
    if cfg.session.is_empty() {
        return Ok(Value::Null);
    }
    let (code, v, _) = call(&st.client, "GET", &format!("{}/api/state", cfg.hub), None, Auth::Session(&cfg.session), secs(20))
        .await.map_err(|e| format!("Can't reach the room: {e}"))?;
    if code != 200 {
        return Err(err_text(&v, &format!("The room answered {code}")));
    }
    if v["me"].is_null() {
        st.update(|c| c.session.clear())?; // sign-in expired
    }
    Ok(json!({"me": v["me"], "online": v["online"], "topic": v["topic"], "paused": v["paused"]}))
}

#[tauri::command]
async fn save_profile(st: St<'_>, about: String, color: String, skills: Vec<String>) -> Result<Value, String> {
    let st = st.inner().clone();
    let cfg = st.cfg();
    let (code, v, _) = call(&st.client, "POST", &format!("{}/api/me/agent", cfg.hub),
        Some(json!({"about": about, "color": color, "skills": skills})), Auth::Session(&cfg.session), secs(20)).await?;
    if code != 200 {
        return Err(err_text(&v, "The room didn't save that"));
    }
    Ok(v["agent"].clone())
}

#[tauri::command]
async fn detect_models(st: St<'_>) -> Result<Vec<Value>, String> {
    Ok(room::detect(&st.client).await)
}

#[tauri::command]
async fn list_models(st: St<'_>, url: String, key: Option<String>) -> Result<Value, String> {
    let url = room::norm_model_url(&url)?;
    let key = key.filter(|k| !k.is_empty()).unwrap_or_else(|| st.cfg().model_key);
    let models = room::list_models(&st.client, &url, &key, secs(8)).await?;
    Ok(json!({"url": url, "models": models}))
}

#[derive(serde::Deserialize)]
struct ModelSettings {
    model_url: String,
    model: String,
    /// None: keep the saved key. Some(""): remove it.
    model_key: Option<String>,
    persona: String,
    own_persona: bool,
    max_tokens: u32,
    task_max_tokens: Option<u32>,
    temperature: f32,
    thinking: Option<bool>,
}

#[tauri::command]
fn save_settings(st: St<'_>, s: ModelSettings) -> Result<Value, String> {
    let url = if s.model_url.trim().is_empty() { String::new() } else { room::norm_model_url(&s.model_url)? };
    st.update(|c| {
        c.model_url = url;
        c.model = s.model.trim().to_string();
        if let Some(k) = s.model_key {
            c.model_key = k.trim().to_string();
        }
        c.persona = s.persona;
        c.own_persona = s.own_persona;
        c.max_tokens = s.max_tokens.clamp(64, 8192);
        if let Some(t) = s.task_max_tokens {
            c.task_max_tokens = t.clamp(256, 32768);
        }
        c.temperature = s.temperature.clamp(0.0, 2.0);
        c.thinking = s.thinking;
    })?;
    Ok(st.cfg().public())
}

#[tauri::command]
async fn test_model(st: St<'_>) -> Result<Value, String> {
    let cfg = st.cfg();
    if cfg.model_url.is_empty() || cfg.model.is_empty() {
        return Err("Choose a model first".into());
    }
    let name = if cfg.agent_name.is_empty() { "Tester".to_string() } else { cfg.agent_name.clone() };
    let t0 = std::time::Instant::now();
    let raw = room::ask_model(&st.client, &cfg, &room::build_messages(&cfg, &room::test_turn(&name)), "chat").await?;
    Ok(json!({"reply": room::clean(&raw, &name), "seconds": t0.elapsed().as_secs_f32()}))
}

#[tauri::command]
async fn start_ai(app: AppHandle) -> Result<(), String> {
    start_ai_inner(&app).await
}

#[tauri::command]
fn stop_ai(app: AppHandle, st: St<'_>) -> Result<(), String> {
    let st = st.inner().clone();
    stop_loop(&app, &st, true);
    st.update(|c| c.keep_running = false)
}

#[tauri::command]
async fn open_room(app: AppHandle) -> Result<(), String> {
    let st = app.state::<Arc<AppState>>().inner().clone();
    let cfg = st.cfg();
    if cfg.hub.is_empty() {
        return Err("Sign in to the room first".into());
    }
    let mut url = format!("{}/", cfg.hub);
    if !cfg.session.is_empty() {
        // a one-time code, so the page opens already signed in
        if let Ok((200, v, _)) = call(&st.client, "POST", &format!("{}/api/me/handoff", cfg.hub), None,
                                      Auth::Session(&cfg.session), secs(15)).await {
            if let Some(p) = v["path"].as_str() {
                url = format!("{}{}", cfg.hub, p);
            }
        }
    }
    let u = tauri::Url::parse(&url).map_err(|e| e.to_string())?;
    if let Some(w) = app.get_webview_window("room") {
        w.navigate(u).map_err(|e| e.to_string())?;
        let _ = w.show();
        let _ = w.set_focus();
        return Ok(());
    }
    let downloads = app.path().download_dir().ok();
    WebviewWindowBuilder::new(&app, "room", WebviewUrl::External(u))
        .title("The room")
        .inner_size(1120.0, 840.0)
        .min_inner_size(420.0, 480.0)
        .on_download(move |_w, ev| {
            if let DownloadEvent::Requested { url, destination } = ev {
                let name = destination.file_name().map(|n| n.to_owned())
                    .or_else(|| url.path_segments().and_then(|s| s.last()).map(|s| format!("{s}.md").into()))
                    .unwrap_or_else(|| "agent-room-document.md".into());
                if let Some(d) = &downloads {
                    *destination = d.join(name);
                }
            }
            true
        })
        .build()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
async fn sign_out(app: AppHandle) -> Result<(), String> {
    let st = app.state::<Arc<AppState>>().inner().clone();
    stop_loop(&app, &st, true);
    let cfg = st.cfg();
    if !cfg.session.is_empty() {
        let _ = call(&st.client, "POST", &format!("{}/api/logout", cfg.hub), None, Auth::Session(&cfg.session), secs(10)).await;
    }
    if let Some(w) = app.get_webview_window("room") {
        let _ = w.close();
    }
    st.update(|c| {
        c.session.clear();
        c.token.clear();
        c.username.clear();
        c.agent_name.clear();
        c.keep_running = false;
    })
}

// ------------------------------------------------------------------ app

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let dir = app.path().app_config_dir()?;
            std::fs::create_dir_all(&dir)?;
            let path = dir.join("config.json");
            let cfg = config::load(&path);
            let (gen, _) = watch::channel(0u64);
            let st = Arc::new(AppState {
                cfg: Mutex::new(cfg.clone()),
                cfg_path: path,
                client: reqwest::Client::builder()
                    .user_agent(concat!("agent-room-app/", env!("CARGO_PKG_VERSION")))
                    .build()?,
                gen,
                status: Mutex::new(Status { state: "off".into(), text: "Your AI is not in the room".into(), ..Default::default() }),
                tray_toggle: Mutex::new(None),
            });
            app.manage(st.clone());

            let open = MenuItem::with_id(app, "open", "Open Agent Room", true, None::<&str>)?;
            let toggle = MenuItem::with_id(app, "toggle", "Put my AI in the room", true, None::<&str>)?;
            let watch_room = MenuItem::with_id(app, "room", "Watch the room", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Agent Room", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(app, &[&open, &toggle, &watch_room, &sep, &quit])?;
            *st.tray_toggle.lock().unwrap() = Some(toggle.clone());
            let mut tray = TrayIconBuilder::with_id("tray")
                .tooltip("Agent Room")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, ev| match ev.id().as_ref() {
                    "open" => show_main(app),
                    "toggle" => {
                        let st = app.state::<Arc<AppState>>().inner().clone();
                        if st.status.lock().unwrap().running {
                            stop_loop(app, &st, true);
                            let _ = st.update(|c| c.keep_running = false);
                        } else {
                            let app = app.clone();
                            tauri::async_runtime::spawn(async move {
                                if let Err(e) = start_ai_inner(&app).await {
                                    let st = app.state::<Arc<AppState>>().inner().clone();
                                    st.set_state(&app, "error", &e);
                                    show_main(&app);
                                }
                            });
                        }
                    }
                    "room" => {
                        let app = app.clone();
                        tauri::async_runtime::spawn(async move {
                            let _ = open_room(app).await;
                        });
                    }
                    "quit" => app.exit(0),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            if cfg.keep_running && !cfg.model.is_empty() && (!cfg.token.is_empty() || !cfg.session.is_empty()) {
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = start_ai_inner(&handle).await {
                        let st = handle.state::<Arc<AppState>>().inner().clone();
                        st.set_state(&handle, "error", &e);
                    }
                });
            }
            Ok(())
        })
        .on_window_event(|window, ev| {
            if let WindowEvent::CloseRequested { api, .. } = ev {
                if window.label() == "main" {
                    let st = window.app_handle().state::<Arc<AppState>>().inner().clone();
                    if st.status.lock().unwrap().running {
                        api.prevent_close(); // keep the AI in the room; quit from the tray
                        let _ = window.hide();
                    } else {
                        window.app_handle().exit(0);
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_state, sign_in, use_invite, join_room, me, save_profile, detect_models, list_models,
            save_settings, test_model, start_ai, stop_ai, open_room, sign_out
        ])
        .build(tauri::generate_context!())
        .expect("error while starting Agent Room");

    app.run(|_app, ev| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen { .. } = ev {
            show_main(_app);
        }
        let _ = ev;
    });
}
