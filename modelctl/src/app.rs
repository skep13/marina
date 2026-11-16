//! TUI application state and input handling.

use std::time::{Duration, Instant};

use ratatui::widgets::TableState;

use crate::client::{ModelInfo, RunningInfo};
use crate::config::AppConfig;
use crate::theme;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Screen {
    Models,
    Config,
    Download,
}

impl Screen {
    pub fn index(self) -> usize {
        match self {
            Screen::Models => 0,
            Screen::Config => 1,
            Screen::Download => 2,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum DlField {
    Repo,
    File,
    Revision,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum ToastKind {
    Info,
    Success,
    Error,
}

/// A transient, auto-dismissing notification for action results.
pub struct Toast {
    pub text: String,
    pub kind: ToastKind,
    born: Instant,
}

const TOAST_TTL: Duration = Duration::from_millis(4500);

impl Toast {
    pub fn alive(&self) -> bool {
        self.born.elapsed() < TOAST_TTL
    }
}

/// An in-flight (or just-finished) download, tracked for the progress bar.
pub struct Download {
    pub filename: String,
    pub total: u64,
    pub downloaded: u64,
    pub finished: bool,
    pub running: bool,
    pub error: Option<String>,
    pub speed_bps: f64,
    last_bytes: u64,
    last_tick: Instant,
}

impl Download {
    pub fn new(filename: String, total: u64) -> Self {
        Self {
            filename,
            total,
            downloaded: 0,
            finished: false,
            running: true,
            error: None,
            speed_bps: 0.0,
            last_bytes: 0,
            last_tick: Instant::now(),
        }
    }

    pub fn update(&mut self, downloaded: u64, finished: bool, running: bool, error: Option<String>) {
        let now = Instant::now();
        let dt = now.duration_since(self.last_tick).as_secs_f64();
        if dt > 0.2 && downloaded >= self.last_bytes {
            let inst = (downloaded - self.last_bytes) as f64 / dt;
            // Exponential smoothing so the rate does not jitter.
            self.speed_bps = if self.speed_bps == 0.0 {
                inst
            } else {
                0.6 * self.speed_bps + 0.4 * inst
            };
            self.last_bytes = downloaded;
            self.last_tick = now;
        }
        self.downloaded = downloaded;
        self.finished = finished;
        self.running = running;
        self.error = error;
    }

    pub fn fraction(&self) -> f64 {
        if self.finished {
            return 1.0;
        }
        if self.total == 0 {
            return 0.0;
        }
        (self.downloaded as f64 / self.total as f64).clamp(0.0, 1.0)
    }

    /// Rough ETA in seconds from smoothed rate (None if unknown).
    pub fn eta_secs(&self) -> Option<u64> {
        if self.finished || self.total == 0 || self.speed_bps < 1.0 {
            return None;
        }
        let remaining = self.total.saturating_sub(self.downloaded) as f64;
        Some((remaining / self.speed_bps) as u64)
    }
}

pub struct App {
    pub cfg: AppConfig,
    pub screen: Screen,

    pub models: Vec<ModelInfo>,
    pub running: Vec<RunningInfo>,
    pub selected: usize,
    pub table_state: TableState,

    pub status: String,
    pub is_error: bool,
    pub busy: bool,

    pub config_text: String,
    pub config_scroll: u16,

    pub dl_repo: String,
    pub dl_file: String,
    pub dl_rev: String,
    pub dl_field: DlField,
    pub download: Option<Download>,

    pub toast: Option<Toast>,
    pub show_help: bool,
    pub confirm_unload: bool,

    /// App clock, drives the spinner animation.
    pub start: Instant,

    pub should_quit: bool,
}

impl App {
    pub fn new(cfg: AppConfig) -> Self {
        let mut table_state = TableState::default();
        table_state.select(Some(0));
        Self {
            cfg,
            screen: Screen::Models,
            models: Vec::new(),
            running: Vec::new(),
            selected: 0,
            table_state,
            status: "connecting to llama-swap…".into(),
            is_error: false,
            busy: true,
            config_text: String::new(),
            config_scroll: 0,
            dl_repo: String::new(),
            dl_file: String::new(),
            dl_rev: "main".into(),
            dl_field: DlField::Repo,
            download: None,
            toast: None,
            show_help: false,
            confirm_unload: false,
            start: Instant::now(),
            should_quit: false,
        }
    }

    pub fn set_status(&mut self, msg: impl Into<String>) {
        self.status = msg.into();
        self.is_error = false;
    }

    pub fn set_error(&mut self, msg: impl Into<String>) {
        self.status = msg.into();
        self.is_error = true;
    }

    pub fn toast(&mut self, kind: ToastKind, text: impl Into<String>) {
        self.toast = Some(Toast {
            text: text.into(),
            kind,
            born: Instant::now(),
        });
    }

    /// The live toast, if one is still within its display window.
    pub fn live_toast(&self) -> Option<&Toast> {
        self.toast.as_ref().filter(|t| t.alive())
    }

    /// Current spinner glyph (animated off the app clock).
    pub fn spinner(&self) -> &'static str {
        let i = (self.start.elapsed().as_millis() / 110) as usize % theme::SPINNER.len();
        theme::SPINNER[i]
    }

    pub fn selected_model(&self) -> Option<&ModelInfo> {
        self.models.get(self.selected)
    }

    pub fn select_up(&mut self) {
        if self.selected > 0 {
            self.selected -= 1;
            self.table_state.select(Some(self.selected));
        }
    }

    pub fn select_down(&mut self) {
        if self.selected + 1 < self.models.len() {
            self.selected += 1;
            self.table_state.select(Some(self.selected));
        }
    }

    pub fn clamp_selection(&mut self) {
        if !self.models.is_empty() && self.selected >= self.models.len() {
            self.selected = self.models.len() - 1;
        }
        self.table_state.select(Some(self.selected));
    }

    pub fn ttl_for(&self, model: &str) -> Option<u64> {
        self.running
            .iter()
            .find(|r| r.model == model)
            .map(|r| r.ttl)
    }

    /// llama-swap's `/running` state for a model (e.g. "ready", "loading").
    pub fn run_state(&self, model: &str) -> Option<&str> {
        self.running
            .iter()
            .find(|r| r.model == model)
            .map(|r| r.state.as_str())
    }

    /// A short summary of what's loaded, for the status line.
    pub fn loaded_summary(&self) -> String {
        let loaded: Vec<&str> = self
            .models
            .iter()
            .filter(|m| m.loaded)
            .map(|m| m.id.as_str())
            .collect();
        if loaded.is_empty() {
            "no model loaded — GPU free".to_string()
        } else {
            format!("loaded: {}", loaded.join(", "))
        }
    }
}
