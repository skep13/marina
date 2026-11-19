//! Everything the app remembers, kept in one file in the app's own config
//! folder (readable only by you). None of it is sent to the room except the
//! AI's key, which only proves which AI is speaking.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;

#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// The room's address, e.g. https://room.example.net
    pub hub: String,
    /// Your sign-in to the room's website (like a browser cookie).
    pub session: String,
    pub username: String,
    pub agent_name: String,
    /// The AI's key for taking turns (ar_...).
    pub token: String,
    /// Where your model runs: any OpenAI-style API.
    pub model_url: String,
    pub model: String,
    pub model_key: String,
    /// Your AI's personality. Stays on this computer.
    pub persona: String,
    /// Your AI app already gives it a personality and memory: send none.
    pub own_persona: bool,
    pub max_tokens: u32,
    /// Reply budget for project work: plans, tasks and reviews.
    pub task_max_tokens: u32,
    pub temperature: f32,
    /// None: leave it to the model. Some(false): ask thinking models not to think.
    pub thinking: Option<bool>,
    /// Put the AI back in the room when the app opens.
    pub keep_running: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            hub: option_env!("AGENT_ROOM_DEFAULT_HUB").unwrap_or("").to_string(),
            session: String::new(),
            username: String::new(),
            agent_name: String::new(),
            token: String::new(),
            model_url: String::new(),
            model: String::new(),
            model_key: String::new(),
            persona: String::new(),
            own_persona: false,
            max_tokens: 1200,
            task_max_tokens: 6000,
            temperature: 0.8,
            thinking: None,
            keep_running: false,
        }
    }
}

impl Config {
    /// What the window may see: secrets become yes/no.
    pub fn public(&self) -> Value {
        json!({
            "hub": self.hub, "username": self.username, "agent_name": self.agent_name,
            "signed_in": !self.session.is_empty(), "has_token": !self.token.is_empty(),
            "model_url": self.model_url, "model": self.model, "has_model_key": !self.model_key.is_empty(),
            "persona": self.persona, "own_persona": self.own_persona,
            "max_tokens": self.max_tokens, "task_max_tokens": self.task_max_tokens,
            "temperature": self.temperature,
            "thinking": self.thinking, "keep_running": self.keep_running,
        })
    }
}

pub fn load(path: &Path) -> Config {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save(path: &Path, cfg: &Config) -> Result<(), String> {
    let text = serde_json::to_string_pretty(cfg).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    write_private(&tmp, text.as_bytes()).map_err(|e| format!("couldn't save settings: {e}"))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("couldn't save settings: {e}"))
}

#[cfg(unix)]
fn write_private(path: &Path, data: &[u8]) -> std::io::Result<()> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let mut f = std::fs::OpenOptions::new()
        .write(true).create(true).truncate(true).mode(0o600).open(path)?;
    f.write_all(data)
}

#[cfg(not(unix))]
fn write_private(path: &Path, data: &[u8]) -> std::io::Result<()> {
    std::fs::write(path, data) // the per-user AppData folder is private to the user
}
