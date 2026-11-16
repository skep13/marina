//! Runtime configuration for modelctl.
//!
//! The llama-swap API key is NEVER hardcoded. It is read, in order, from:
//!   1. `--api-key` / env `MODELCTL_API_KEY`
//!   2. env `MARINA_LAB3_KEY`
//!   3. the key file (default `~/.marina/agent-keys.env`), line `MARINA_LAB3_KEY=...`

use anyhow::{anyhow, Context, Result};
use std::fs;
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct AppConfig {
    /// HTTP base for the llama-swap front door, e.g. `http://192.168.1.15:8080`.
    pub base_url: String,
    /// SSH target for lab3, e.g. `root@192.168.1.15`.
    pub ssh_target: String,
    /// Bearer key for the llama-swap API.
    pub api_key: String,
    /// Directory on lab3 where GGUF model files live, e.g. `/models`.
    pub models_dir: String,
    /// Path to llama-swap's config on lab3.
    pub remote_config_path: String,
    /// Path to the llama-swap binary on lab3 (used for `-validate`).
    pub remote_binary: String,
}

/// CLI-sourced overrides; `None` means "use the default / env".
#[derive(Debug, Default, Clone)]
pub struct Overrides {
    pub host: Option<String>,
    pub port: Option<u16>,
    pub ssh_target: Option<String>,
    pub api_key: Option<String>,
    pub models_dir: Option<String>,
    pub remote_config_path: Option<String>,
    pub key_file: Option<PathBuf>,
}

impl AppConfig {
    pub fn load(ov: &Overrides) -> Result<Self> {
        let host = ov
            .host
            .clone()
            .or_else(|| std::env::var("MODELCTL_HOST").ok())
            .unwrap_or_else(|| "192.168.1.15".to_string());
        let port = ov
            .port
            .or_else(|| std::env::var("MODELCTL_PORT").ok().and_then(|s| s.parse().ok()))
            .unwrap_or(8080);
        let base_url = format!("http://{host}:{port}");

        let ssh_target = ov
            .ssh_target
            .clone()
            .or_else(|| std::env::var("MODELCTL_SSH").ok())
            .unwrap_or_else(|| format!("root@{host}"));

        let api_key = resolve_api_key(ov)?;

        let models_dir = ov
            .models_dir
            .clone()
            .or_else(|| std::env::var("MODELCTL_MODELS_DIR").ok())
            .unwrap_or_else(|| "/models".to_string());

        let remote_config_path = ov
            .remote_config_path
            .clone()
            .or_else(|| std::env::var("MODELCTL_CONFIG_PATH").ok())
            .unwrap_or_else(|| "/opt/llama-swap/config.yaml".to_string());

        let remote_binary = std::env::var("MODELCTL_BINARY")
            .unwrap_or_else(|_| "/opt/llama-swap/llama-swap".to_string());

        Ok(Self {
            base_url,
            ssh_target,
            api_key,
            models_dir,
            remote_config_path,
            remote_binary,
        })
    }
}

fn resolve_api_key(ov: &Overrides) -> Result<String> {
    if let Some(k) = &ov.api_key {
        return Ok(k.trim().to_string());
    }
    if let Ok(k) = std::env::var("MODELCTL_API_KEY") {
        if !k.trim().is_empty() {
            return Ok(k.trim().to_string());
        }
    }
    if let Ok(k) = std::env::var("MARINA_LAB3_KEY") {
        if !k.trim().is_empty() {
            return Ok(k.trim().to_string());
        }
    }
    // Fall back to the key file.
    let path = ov.key_file.clone().unwrap_or_else(default_key_file);
    let contents = fs::read_to_string(&path)
        .with_context(|| format!("reading key file {}", path.display()))?;
    for line in contents.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("MARINA_LAB3_KEY=") {
            let val = rest.trim().trim_matches('"').trim_matches('\'');
            if !val.is_empty() {
                return Ok(val.to_string());
            }
        }
    }
    Err(anyhow!(
        "no API key found: set MODELCTL_API_KEY or MARINA_LAB3_KEY, or add MARINA_LAB3_KEY=... to {}",
        path.display()
    ))
}

fn default_key_file() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".marina").join("agent-keys.env")
}
