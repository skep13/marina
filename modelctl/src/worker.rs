//! Background worker: all blocking HTTP/SSH work runs here so the TUI never
//! freezes. The UI sends `Job`s; the worker streams back `Msg`s.

use std::sync::mpsc::{Receiver, Sender};
use std::thread::JoinHandle;

use crate::client::{Client, ModelInfo, RunningInfo};
use crate::ssh::{DownloadStatus, Ssh};

pub enum Job {
    /// Re-read `/v1/models` and `/running`.
    Refresh,
    /// Swap to / load a model, then refresh.
    Load(String),
    /// Unload everything, then refresh.
    Unload,
    /// Read llama-swap's config.yaml from lab3.
    LoadConfig,
    /// Validate, back up, and atomically write a new config.yaml.
    SaveConfig(String),
    /// Begin a Hugging Face download on lab3.
    StartDownload {
        repo: String,
        filename: String,
        revision: String,
    },
    /// Poll an in-flight download once.
    PollDownload { filename: String },
    /// Stop the worker thread.
    Quit,
}

pub enum Msg {
    Models {
        models: Vec<ModelInfo>,
        running: Vec<RunningInfo>,
    },
    Config(String),
    ConfigSaved(String),
    Notice(String),
    Error(String),
    DownloadStarted {
        filename: String,
        total: u64,
    },
    DownloadProgress(DownloadStatus),
}

pub struct Worker {
    pub tx: Sender<Job>,
    pub rx: Receiver<Msg>,
    handle: Option<JoinHandle<()>>,
}

impl Worker {
    pub fn spawn(client: Client, ssh: Ssh) -> Self {
        let (job_tx, job_rx) = std::sync::mpsc::channel::<Job>();
        let (msg_tx, msg_rx) = std::sync::mpsc::channel::<Msg>();

        let handle = std::thread::spawn(move || {
            run(client, ssh, job_rx, msg_tx);
        });

        Self {
            tx: job_tx,
            rx: msg_rx,
            handle: Some(handle),
        }
    }

    pub fn send(&self, job: Job) {
        let _ = self.tx.send(job);
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        let _ = self.tx.send(Job::Quit);
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}

fn run(client: Client, ssh: Ssh, jobs: Receiver<Job>, out: Sender<Msg>) {
    while let Ok(job) = jobs.recv() {
        match job {
            Job::Quit => break,
            Job::Refresh => refresh(&client, &out),
            Job::Load(model) => {
                match client.load(&model) {
                    Ok(()) => {
                        let _ = out.send(Msg::Notice(format!("loaded {model}")));
                    }
                    Err(e) => {
                        let _ = out.send(Msg::Error(format!("load {model}: {e}")));
                    }
                }
                refresh(&client, &out);
            }
            Job::Unload => {
                match client.unload() {
                    Ok(()) => {
                        let _ = out.send(Msg::Notice("unloaded all models".into()));
                    }
                    Err(e) => {
                        let _ = out.send(Msg::Error(format!("unload: {e}")));
                    }
                }
                refresh(&client, &out);
            }
            Job::LoadConfig => match ssh.read_config() {
                Ok(text) => {
                    let _ = out.send(Msg::Config(text));
                }
                Err(e) => {
                    let _ = out.send(Msg::Error(format!("read config: {e}")));
                }
            },
            Job::SaveConfig(text) => match ssh.write_config(&text) {
                Ok(backup) => {
                    let _ = out.send(Msg::ConfigSaved(backup));
                    refresh(&client, &out);
                }
                Err(e) => {
                    let _ = out.send(Msg::Error(format!("save config: {e}")));
                }
            },
            Job::StartDownload {
                repo,
                filename,
                revision,
            } => match ssh.start_download(&repo, &filename, &revision) {
                Ok(total) => {
                    let _ = out.send(Msg::DownloadStarted {
                        filename: filename.clone(),
                        total,
                    });
                }
                Err(e) => {
                    let _ = out.send(Msg::Error(format!("download: {e}")));
                }
            },
            Job::PollDownload { filename } => match ssh.poll_download(&filename) {
                Ok(status) => {
                    let _ = out.send(Msg::DownloadProgress(status));
                }
                Err(e) => {
                    let _ = out.send(Msg::Error(format!("poll: {e}")));
                }
            },
        }
    }
}

fn refresh(client: &Client, out: &Sender<Msg>) {
    let models = match client.list_models() {
        Ok(m) => m,
        Err(e) => {
            let _ = out.send(Msg::Error(format!("list models: {e}")));
            return;
        }
    };
    let running = client.running().unwrap_or_default();
    let _ = out.send(Msg::Models { models, running });
}
