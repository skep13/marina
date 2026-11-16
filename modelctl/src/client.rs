//! Blocking HTTP client for the llama-swap front door (OpenAI-compatible + admin routes).

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use std::time::Duration;

pub struct Client {
    http: reqwest::blocking::Client,
    base: String,
    key: String,
}

#[derive(Debug, Clone)]
pub struct ModelInfo {
    pub id: String,
    pub loaded: bool,
    pub context_length: u64,
    pub vision: bool,
    pub tools: bool,
}

#[derive(Debug, Clone)]
pub struct RunningInfo {
    pub model: String,
    pub state: String,
    pub ttl: u64,
}

// ---- raw wire types ------------------------------------------------------

#[derive(Deserialize)]
struct ModelsResp {
    data: Vec<ModelEntry>,
}

#[derive(Deserialize)]
struct ModelEntry {
    id: String,
    #[serde(default)]
    context_length: u64,
    #[serde(default)]
    capabilities: Capabilities,
    #[serde(default)]
    status: Status,
}

#[derive(Deserialize, Default)]
struct Capabilities {
    #[serde(default)]
    vision: bool,
    #[serde(default)]
    function_calling: bool,
}

#[derive(Deserialize, Default)]
struct Status {
    #[serde(default)]
    value: String,
}

#[derive(Deserialize)]
struct RunningResp {
    #[serde(default)]
    running: Vec<RunningEntry>,
}

#[derive(Deserialize)]
struct RunningEntry {
    #[serde(default)]
    model: String,
    #[serde(default)]
    state: String,
    #[serde(default)]
    ttl: u64,
}

impl Client {
    pub fn new(base: &str, key: &str) -> Result<Self> {
        let http = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(120))
            .connect_timeout(Duration::from_secs(10))
            .build()
            .context("building HTTP client")?;
        Ok(Self {
            http,
            base: base.trim_end_matches('/').to_string(),
            key: key.to_string(),
        })
    }

    fn get(&self, path: &str) -> reqwest::blocking::RequestBuilder {
        self.http
            .get(format!("{}{}", self.base, path))
            .bearer_auth(&self.key)
    }

    /// `GET /v1/models` — every model llama-swap can serve, with load status.
    pub fn list_models(&self) -> Result<Vec<ModelInfo>> {
        let resp = self
            .get("/v1/models")
            .send()
            .context("GET /v1/models")?;
        let status = resp.status();
        if !status.is_success() {
            return Err(anyhow!("GET /v1/models -> HTTP {status}"));
        }
        let parsed: ModelsResp = resp.json().context("parsing /v1/models")?;
        let mut out: Vec<ModelInfo> = parsed
            .data
            .into_iter()
            .map(|m| ModelInfo {
                id: m.id,
                loaded: m.status.value.eq_ignore_ascii_case("loaded"),
                context_length: m.context_length,
                vision: m.capabilities.vision,
                tools: m.capabilities.function_calling,
            })
            .collect();
        out.sort_by(|a, b| a.id.cmp(&b.id));
        Ok(out)
    }

    /// `GET /running` — models currently resident on the GPU.
    pub fn running(&self) -> Result<Vec<RunningInfo>> {
        let resp = self.get("/running").send().context("GET /running")?;
        if !resp.status().is_success() {
            return Err(anyhow!("GET /running -> HTTP {}", resp.status()));
        }
        let parsed: RunningResp = resp.json().context("parsing /running")?;
        Ok(parsed
            .running
            .into_iter()
            .map(|r| RunningInfo {
                model: r.model,
                state: r.state,
                ttl: r.ttl,
            })
            .collect())
    }

    /// Load / swap to a model without generating tokens: proxy its `/health`,
    /// which forces llama-swap to bring the upstream llama-server up.
    pub fn load(&self, model: &str) -> Result<()> {
        let resp = self
            .get(&format!("/upstream/{}/health", model))
            .timeout(Duration::from_secs(300))
            .send()
            .with_context(|| format!("loading model {model}"))?;
        if !resp.status().is_success() {
            return Err(anyhow!(
                "load {model}: HTTP {} — {}",
                resp.status(),
                resp.text().unwrap_or_default()
            ));
        }
        Ok(())
    }

    /// `POST /unload` — free the GPU (unload all resident models).
    pub fn unload(&self) -> Result<()> {
        let resp = self
            .http
            .post(format!("{}/unload", self.base))
            .bearer_auth(&self.key)
            .send()
            .context("POST /unload")?;
        if !resp.status().is_success() {
            return Err(anyhow!("POST /unload -> HTTP {}", resp.status()));
        }
        Ok(())
    }
}
