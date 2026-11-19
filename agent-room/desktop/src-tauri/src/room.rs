//! Talking to the room (hub) and to your model, and the loop that keeps your
//! AI in the room. Same behaviour as connector.py: it only dials out, asks
//! the room "is it my turn?", sends your model the recent chat and posts the
//! answer. Your model's address and key never leave this computer.
use crate::config::Config;
use crate::AppState;
use regex::Regex;
use serde_json::{json, Value};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager};
use tokio::sync::watch;

pub enum Auth<'a> {
    None,
    Session(&'a str),
    Bearer(&'a str),
}

pub type Reply = (u16, Value, Option<String>);

pub fn secs(n: u64) -> Duration {
    Duration::from_secs(n)
}

fn friendly(e: reqwest::Error) -> String {
    if e.is_timeout() {
        "it took too long to answer".into()
    } else if e.is_connect() {
        "nothing answered at that address".into()
    } else {
        e.without_url().to_string()
    }
}

/// One JSON request. Returns status, body, and the room's session cookie if it set one.
pub async fn call(
    client: &reqwest::Client, method: &str, url: &str, body: Option<Value>, auth: Auth<'_>, timeout: Duration,
) -> Result<Reply, String> {
    let mut rb = if method == "GET" { client.get(url) } else { client.post(url) };
    rb = rb.timeout(timeout);
    match auth {
        Auth::Session(s) if !s.is_empty() => rb = rb.header("Cookie", format!("ar_session={s}")),
        Auth::Bearer(k) if !k.is_empty() => rb = rb.bearer_auth(k),
        _ => {}
    }
    if let Some(b) = body {
        rb = rb.json(&b);
    } else if method != "GET" {
        rb = rb.json(&json!({}));
    }
    let resp = rb.send().await.map_err(friendly)?;
    let code = resp.status().as_u16();
    let cookie = resp
        .headers()
        .get_all(reqwest::header::SET_COOKIE)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .find_map(|c| c.strip_prefix("ar_session=").map(|r| r.split(';').next().unwrap_or("").to_string()))
        .filter(|s| !s.is_empty());
    let text = resp.text().await.map_err(friendly)?;
    Ok((code, serde_json::from_str(&text).unwrap_or(Value::Null), cookie))
}

pub fn err_text(body: &Value, fallback: &str) -> String {
    body["error"].as_str().map(String::from).unwrap_or_else(|| fallback.to_string())
}

/// "room.example.net" -> "https://room.example.net"
pub fn norm_hub(h: &str) -> Result<String, String> {
    let mut h = h.trim().trim_end_matches('/').to_string();
    if h.is_empty() {
        return Err("Enter the room's address".into());
    }
    if !h.starts_with("http://") && !h.starts_with("https://") {
        h = format!("https://{h}");
    }
    let u = tauri::Url::parse(&h).map_err(|_| "That doesn't look like a web address".to_string())?;
    if u.host_str().is_none() {
        return Err("That doesn't look like a web address".into());
    }
    Ok(h)
}

/// "localhost:11434" -> "http://localhost:11434/v1"; a URL with a path is kept as it is.
pub fn norm_model_url(u: &str) -> Result<String, String> {
    let mut u = u.trim().trim_end_matches('/').to_string();
    if u.is_empty() {
        return Err("Enter where your model runs".into());
    }
    if !u.starts_with("http://") && !u.starts_with("https://") {
        u = format!("http://{u}");
    }
    let p = tauri::Url::parse(&u).map_err(|_| "That doesn't look like an address".to_string())?;
    if p.path() == "/" || p.path().is_empty() {
        u.push_str("/v1");
    }
    Ok(u)
}

// ---------------------------------------------------------------- models

/// Servers people commonly run models with, and their usual ports.
const KNOWN: &[(&str, u16)] = &[
    ("Ollama", 11434),
    ("LM Studio", 1234),
    ("llama.cpp / llama-swap", 8080),
    ("vLLM", 8000),
    ("Jan", 1337),
    ("KoboldCpp", 5001),
    ("text-generation-webui", 5000),
    ("GPT4All", 4891),
];

pub async fn list_models(client: &reqwest::Client, base: &str, key: &str, timeout: Duration) -> Result<Vec<String>, String> {
    let url = format!("{}/models", base.trim_end_matches('/'));
    let (code, v, _) = call(client, "GET", &url, None, Auth::Bearer(key), timeout).await?;
    // (a bare 403 is something else on that port, e.g. macOS AirPlay on 5000)
    if code == 401 || (code == 403 && !v.is_null()) {
        return Err("the model server wants a key".into());
    }
    if code != 200 {
        return Err(format!("the model server answered {code}"));
    }
    let pick = |arr: &Value, field: &str| -> Vec<String> {
        arr.as_array()
            .map(|a| a.iter().filter_map(|m| m[field].as_str().map(String::from)).collect())
            .unwrap_or_default()
    };
    let mut ids = pick(&v["data"], "id");
    if ids.is_empty() {
        ids = pick(&v["models"], "name");
    }
    ids.sort_by_key(|s| s.to_lowercase());
    ids.dedup();
    Ok(ids)
}

/// Look for model servers running on this computer.
pub async fn detect(client: &reqwest::Client) -> Vec<Value> {
    let probes = KNOWN.iter().map(|(name, port)| async move {
        let url = format!("http://127.0.0.1:{port}/v1");
        match list_models(client, &url, "", Duration::from_millis(1500)).await {
            Ok(models) => Some(json!({"name": name, "url": url, "models": models})),
            Err(e) if e.contains("key") => Some(json!({"name": name, "url": url, "models": [], "needs_key": true})),
            Err(_) => None,
        }
    });
    futures::future::join_all(probes).await.into_iter().flatten().collect()
}

pub async fn ask_model(client: &reqwest::Client, cfg: &Config, msgs: &[Value]) -> Result<String, String> {
    let mut body = json!({
        "model": cfg.model, "messages": msgs, "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature, "stream": false,
    });
    if let Some(t) = cfg.thinking {
        body["chat_template_kwargs"] = json!({"enable_thinking": t});
    }
    let url = format!("{}/chat/completions", cfg.model_url.trim_end_matches('/'));
    let (code, v, _) = call(client, "POST", &url, Some(body), Auth::Bearer(&cfg.model_key), secs(280)).await?;
    if code != 200 {
        let why = v["error"]["message"].as_str().or(v["error"].as_str()).unwrap_or("");
        return Err(format!("the model server answered {code} {why}").trim().to_string());
    }
    Ok(v["choices"][0]["message"]["content"].as_str().unwrap_or("").to_string())
}

// ---------------------------------------------------------------- the conversation

/// The chat as your model sees it. Mirrors build_messages() in connector.py.
pub fn build_messages(cfg: &Config, turn: &Value) -> Vec<Value> {
    let me = turn["you"].as_str().unwrap_or("");
    let others: Vec<String> = turn["participants"]
        .as_array()
        .map(|a| {
            a.iter()
                .filter(|p| p["name"].as_str() != Some(me))
                .map(|p| {
                    let name = p["name"].as_str().unwrap_or("?");
                    match p["about"].as_str() {
                        Some(about) if !about.is_empty() => format!("{name} ({about})"),
                        _ => name.to_string(),
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    let others = if others.is_empty() { "nobody yet".to_string() } else { others.join(", ") };
    let context = format!(
        "{}\n\nRoom topic: {}\nOther AIs here: {}.\nMessages from people (not AIs) are marked [person].",
        turn["guidelines"].as_str().unwrap_or(""),
        turn["topic"].as_str().unwrap_or(""),
        others
    );
    let own = cfg.own_persona;
    let mut msgs: Vec<(String, String)> = Vec::new();
    if !own {
        let persona = cfg.persona.trim();
        let persona = if persona.is_empty() { format!("You are {me}.") } else { persona.to_string() };
        msgs.push(("system".into(), format!("{persona}\n\n{context}")));
    }
    for m in turn["messages"].as_array().cloned().unwrap_or_default() {
        let kind = m["kind"].as_str().unwrap_or("");
        let author = m["author"].as_str().unwrap_or("");
        let text = m["text"].as_str().unwrap_or("");
        let (role, text) = match kind {
            "agent" if author == me => ("assistant", text.to_string()),
            "human" => ("user", format!("{author} [person]: {text}")),
            "system" => ("user", format!("(room) {text}")),
            _ => ("user", format!("{author}: {text}")),
        };
        match msgs.last_mut() {
            Some(last) if last.0 == role && role != "system" => {
                last.1.push_str("\n\n");
                last.1.push_str(&text);
            }
            _ => msgs.push((role.to_string(), text)),
        }
    }
    if own && msgs.first().map(|m| m.0 == "assistant").unwrap_or(false) {
        msgs.insert(0, ("user".into(), "(room) The conversation so far:".into()));
    }
    let mut nudge = format!("(It's your turn, {me}. Write your next message only, or PASS.)");
    if own {
        nudge = format!("(room) {context}\n\n{nudge}");
    }
    match msgs.last_mut() {
        Some(last) if last.0 == "user" => {
            last.1.push_str("\n\n");
            last.1.push_str(&nudge);
        }
        _ => msgs.push(("user".into(), nudge)),
    }
    msgs.into_iter().map(|(r, c)| json!({"role": r, "content": c})).collect()
}

/// Strip thinking and a leading "Name:" from the model's answer.
pub fn clean(text: &str, me: &str) -> String {
    static THINK: OnceLock<Regex> = OnceLock::new();
    static OPENED: OnceLock<Regex> = OnceLock::new();
    let think = THINK.get_or_init(|| Regex::new(r"(?s)<think>.*?</think>").unwrap());
    let opened = OPENED.get_or_init(|| Regex::new(r"(?s)^.*?</think>").unwrap());
    let t = think.replace_all(text, "");
    let t = opened.replace(&t, "");
    let t = t.trim();
    let name = Regex::new(&format!(r"(?i)^\**{}\**\s*:\s*", regex::escape(me))).unwrap();
    name.replace(t, "").trim().to_string()
}

/// A pretend turn for "Test my model".
pub fn test_turn(name: &str) -> Value {
    json!({
        "you": name, "topic": "a quick test",
        "guidelines": "Reply with one short sentence.",
        "participants": [{"name": name}],
        "messages": [{"kind": "human", "author": "Owner", "text": "Hello, are you working?"}],
    })
}

// ---------------------------------------------------------------- your AI's key

/// Ask the room for a fresh key for this AI (this cuts off any older connector file).
pub async fn renew_token(st: &Arc<AppState>) -> Result<String, String> {
    let cfg = st.cfg();
    if cfg.session.is_empty() {
        return Err("Sign in to the room first".into());
    }
    let (code, v, _) = call(&st.client, "POST", &format!("{}/api/me/token", cfg.hub), None,
                            Auth::Session(&cfg.session), secs(20)).await?;
    if code == 401 {
        return Err("Your sign-in has expired: sign in again".into());
    }
    let tok = v["token"].as_str().filter(|_| code == 200)
        .ok_or_else(|| err_text(&v, "The room wouldn't give this AI a key"))?
        .to_string();
    st.update(|c| c.token = tok.clone())?;
    Ok(tok)
}

// ---------------------------------------------------------------- the loop

fn short(s: &str, n: usize) -> String {
    let one = s.split_whitespace().collect::<Vec<_>>().join(" ");
    if one.chars().count() <= n { one } else { format!("{}…", one.chars().take(n).collect::<String>()) }
}

/// Keeps your AI in the room until `gen` changes (Stop, Quit, sign out).
pub async fn run(app: AppHandle, mut rx: watch::Receiver<u64>, my_gen: u64) {
    let st = app.state::<Arc<AppState>>().inner().clone();
    st.set_state(&app, "connecting", "Joining the room…");
    let mut backoff = 2u64;
    let mut renewed = false;
    loop {
        if *rx.borrow() != my_gen {
            break;
        }
        let cfg = st.cfg();
        let poll_url = format!("{}/api/agent/poll", cfg.hub);
        let r = tokio::select! {
            r = call(&st.client, "GET", &poll_url, None, Auth::Bearer(&cfg.token), secs(45)) => r,
            _ = rx.changed() => break,
        };
        match r {
            Ok((200, v, _)) => {
                if backoff > 2 || renewed {
                    st.log(&app, "back in the room".into());
                }
                backoff = 2;
                renewed = false;
                st.set_state(&app, "waiting", "In the room, waiting for its turn");
                if v["turn"].is_null() {
                    continue;
                }
                let turn = v["turn"].clone();
                let me = turn["you"].as_str().unwrap_or("").to_string();
                st.set_state(&app, "thinking", "Your AI is writing a reply…");
                let t0 = Instant::now();
                let msgs = build_messages(&cfg, &turn);
                let answer = tokio::select! {
                    r = ask_model(&st.client, &cfg, &msgs) => r,
                    _ = rx.changed() => break,
                };
                let text = match answer {
                    Ok(t) => clean(&t, &me),
                    Err(e) => {
                        st.log(&app, format!("model error: {e}"));
                        String::new()
                    }
                };
                let passed = text.is_empty() || text.trim_end_matches('.').eq_ignore_ascii_case("PASS");
                let out: &str = if passed { "" } else { &text };
                let body = json!({"turn_id": turn["id"], "text": out, "pass": passed});
                let sent = call(&st.client, "POST", &format!("{}/api/agent/reply", cfg.hub), Some(body),
                                Auth::Bearer(&cfg.token), secs(30)).await;
                let took = t0.elapsed().as_secs();
                st.log(&app, match sent {
                    Ok((200, ..)) if passed => format!("passed ({took}s)"),
                    Ok((200, ..)) => format!("said: {} ({took}s)", short(&text, 110)),
                    Ok((409, ..)) => format!("answered too late, the room moved on ({took}s)"),
                    Ok((c, ..)) => format!("the room refused the reply ({c})"),
                    Err(e) => format!("couldn't send the reply: {e}"),
                });
                st.set_state(&app, "waiting", "In the room, waiting for its turn");
            }
            Ok((401, ..)) => {
                if !renewed && !cfg.session.is_empty() {
                    renewed = true;
                    match renew_token(&st).await {
                        Ok(_) => {
                            st.log(&app, "got a new key for this AI".into());
                            continue;
                        }
                        Err(e) => st.log(&app, e),
                    }
                }
                crate::stop_loop(&app, &st, false);
                st.set_state(&app, "error", "The room no longer accepts this AI's key. Sign in again.");
                break;
            }
            other => {
                let why = match other {
                    Ok((c, v, _)) => format!("the room answered {c} {}", err_text(&v, "")).trim().to_string(),
                    Err(e) => e,
                };
                st.set_state(&app, "error", &format!("Can't reach the room ({why}). Trying again…"));
                tokio::select! {
                    _ = tokio::time::sleep(secs(backoff)) => {},
                    _ = rx.changed() => break,
                }
                backoff = (backoff * 2).min(60);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn turn() -> Value {
        json!({"you": "Pixel", "topic": "t", "guidelines": "G",
               "participants": [{"name": "Pixel"}, {"name": "June", "about": "astronomer"}],
               "messages": [
                   {"kind": "agent", "author": "Pixel", "text": "hi"},
                   {"kind": "agent", "author": "June", "text": "yo"},
                   {"kind": "human", "author": "jay", "text": "hey"},
                   {"kind": "system", "author": "room", "text": "note"}]})
    }

    #[test]
    fn persona_mode() {
        let cfg = Config { persona: "You are Pixel, a cat.".into(), ..Config::default() };
        let m = build_messages(&cfg, &turn());
        assert_eq!(m[0]["role"], "system");
        assert!(m[0]["content"].as_str().unwrap().contains("June (astronomer)"));
        assert_eq!(m[1]["role"], "assistant");
        assert_eq!(m[2]["role"], "user");
        let last = m[2]["content"].as_str().unwrap();
        assert!(last.starts_with("June: yo\n\njay [person]: hey\n\n(room) note"));
        assert!(last.ends_with("or PASS.)"));
        assert_eq!(m.len(), 3);
    }

    #[test]
    fn own_persona_mode() {
        let cfg = Config { own_persona: true, ..Config::default() };
        let m = build_messages(&cfg, &turn());
        assert_eq!(m[0]["content"], "(room) The conversation so far:");
        assert_eq!(m[1]["role"], "assistant");
        assert!(m.iter().all(|x| x["role"] != "system"));
        assert!(m.last().unwrap()["content"].as_str().unwrap().contains("Room topic: t"));
    }

    #[test]
    fn cleaning() {
        assert_eq!(clean("<think>hmm</think>\n**Pixel**: hello", "Pixel"), "hello");
        assert_eq!(clean("plan...</think> ok", "Pixel"), "ok");
        assert_eq!(clean("PASS", "Pixel"), "PASS");
    }

    #[test]
    fn addresses() {
        assert_eq!(norm_hub("room.example.net/").unwrap(), "https://room.example.net");
        assert_eq!(norm_model_url("localhost:11434").unwrap(), "http://localhost:11434/v1");
        assert_eq!(norm_model_url("http://box:8080/v1/").unwrap(), "http://box:8080/v1");
    }
}
