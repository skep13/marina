//! SSH-driven operations on lab3: read/write llama-swap's config, and run
//! Hugging Face downloads on the box itself (never pulled through the Mac).

use anyhow::{anyhow, bail, Context, Result};
use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone)]
pub struct Ssh {
    pub target: String,
    pub models_dir: String,
    pub config_path: String,
    pub binary: String,
}

/// Snapshot of an in-flight (or finished) download, polled over SSH.
#[derive(Debug, Clone, Default)]
pub struct DownloadStatus {
    pub downloaded: u64,
    pub finished: bool,
    pub running: bool,
    pub error: Option<String>,
}

impl Ssh {
    /// Base `ssh` command with batch-mode flags so it never hangs on a prompt.
    fn cmd(&self) -> Command {
        let mut c = Command::new("ssh");
        c.arg("-o")
            .arg("BatchMode=yes")
            .arg("-o")
            .arg("ConnectTimeout=10")
            .arg("-o")
            .arg("StrictHostKeyChecking=accept-new")
            .arg(&self.target);
        c
    }

    /// Run a remote command, returning stdout. Fails on non-zero exit.
    fn run(&self, remote: &str) -> Result<String> {
        let out = self
            .cmd()
            .arg(remote)
            .stdin(Stdio::null())
            .output()
            .context("spawning ssh")?;
        if !out.status.success() {
            bail!(
                "ssh `{}`: {}{}",
                short(remote),
                String::from_utf8_lossy(&out.stderr).trim(),
                exit_note(&out.status)
            );
        }
        Ok(String::from_utf8_lossy(&out.stdout).to_string())
    }

    /// Read llama-swap's config file from lab3.
    pub fn read_config(&self) -> Result<String> {
        self.run(&format!("cat {}", sq(&self.config_path)))
    }

    /// Write a new config safely: timestamped backup, validate with
    /// `llama-swap -validate`, then atomic rename into place. llama-swap runs
    /// with `-watch-config`, so the rename alone makes it reload.
    ///
    /// Returns the path of the backup it made.
    pub fn write_config(&self, content: &str) -> Result<String> {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let cfg = &self.config_path;
        let backup = format!("{cfg}.bak.{ts}");
        let tmp = format!("{cfg}.modelctl.tmp.{ts}");

        // One remote shell: write stdin to a temp file, back up the current
        // config, validate the temp, and only then atomically move it in.
        let script = format!(
            "set -e; \
             cat > {tmp}; \
             cp -p {cfg} {backup} 2>/dev/null || true; \
             if ! {bin} -validate -config {tmp} >/tmp/modelctl-validate.log 2>&1; then \
               rm -f {tmp}; echo VALIDATE_FAIL; cat /tmp/modelctl-validate.log; exit 3; \
             fi; \
             chmod --reference={cfg} {tmp} 2>/dev/null || true; \
             mv {tmp} {cfg}; \
             echo OK {backup}",
            tmp = sq(&tmp),
            cfg = sq(cfg),
            backup = sq(&backup),
            bin = sq(&self.binary),
        );

        let mut child = self
            .cmd()
            .arg(&script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .context("spawning ssh for config write")?;
        child
            .stdin
            .take()
            .ok_or_else(|| anyhow!("no stdin"))?
            .write_all(content.as_bytes())
            .context("streaming config to lab3")?;
        let out = child.wait_with_output().context("waiting on ssh")?;
        let stdout = String::from_utf8_lossy(&out.stdout);
        if !out.status.success() {
            let stderr = String::from_utf8_lossy(&out.stderr);
            if stdout.contains("VALIDATE_FAIL") {
                let detail = stdout.replace("VALIDATE_FAIL", "");
                bail!("llama-swap rejected the config (not written):\n{}", detail.trim());
            }
            bail!("config write failed: {}{}", stderr.trim(), stdout.trim());
        }
        // stdout is "OK <backup>"
        Ok(backup)
    }

    /// Kick off a Hugging Face download on lab3, detached so it survives the
    /// SSH call. Downloads to `<file>.part`, renames to `<file>` on success.
    /// Resumable (`curl -C -`). Returns the total size in bytes (0 if unknown).
    pub fn start_download(&self, repo: &str, filename: &str, revision: &str) -> Result<u64> {
        validate_repo(repo)?;
        validate_filename(filename)?;
        validate_revision(revision)?;

        let url = format!("https://huggingface.co/{repo}/resolve/{revision}/{filename}");
        let dir = &self.models_dir;
        let part = format!("{dir}/{filename}.part");
        let dest = format!("{dir}/{filename}");
        let log = format!("/tmp/modelctl-dl-{}.log", safe_tag(filename));

        // Guard: refuse to clobber an existing finished file.
        let exists = self
            .run(&format!(
                "test -e {} && echo YES || echo NO",
                sq(&dest)
            ))?
            .trim()
            .to_string();
        if exists == "YES" {
            bail!("{dest} already exists on lab3 — remove it first to re-download");
        }

        // Resolve total size (follow redirects to the CDN). Best-effort.
        let total = self.remote_total_size(&url).unwrap_or(0);

        // Detach with nohup + setsid so the download keeps running after the
        // ssh session exits; curl's output goes to the log we poll.
        let inner = format!(
            "curl -fSL -C - -o {part} {url} && mv {part} {dest}",
            part = sq(&part),
            url = sq(&url),
            dest = sq(&dest),
        );
        self.run(&format!(
            "nohup setsid sh -c {inner} >{log} 2>&1 < /dev/null & echo launched",
            inner = sq(&inner),
            log = sq(&log),
        ))?;
        Ok(total)
    }

    /// HEAD the resolve URL (following redirects) and read the final
    /// Content-Length.
    fn remote_total_size(&self, url: &str) -> Result<u64> {
        let out = self.run(&format!(
            "curl -sIL --max-time 30 {} | awk 'BEGIN{{IGNORECASE=1}} /^content-length:/ {{v=$2}} END{{gsub(/\\r/,\"\",v); print v}}'",
            sq(url)
        ))?;
        out.trim().parse::<u64>().map_err(|_| anyhow!("no content-length"))
    }

    /// Poll a download's progress by stat-ing the files and checking for a
    /// live curl process.
    pub fn poll_download(&self, filename: &str) -> Result<DownloadStatus> {
        validate_filename(filename)?;
        let dir = &self.models_dir;
        let part = format!("{dir}/{filename}.part");
        let dest = format!("{dir}/{filename}");
        let log = format!("/tmp/modelctl-dl-{}.log", safe_tag(filename));

        // Emit: part size | dest size | running flag | last log line
        let script = format!(
            "P=$(stat -c %s {part} 2>/dev/null || echo 0); \
             D=$(stat -c %s {dest} 2>/dev/null || echo -1); \
             if pgrep -f {needle} >/dev/null 2>&1; then R=1; else R=0; fi; \
             echo \"$P|$D|$R\"; \
             tail -n 1 {log} 2>/dev/null",
            part = sq(&part),
            dest = sq(&dest),
            needle = sq(&format!("{}.part", filename)),
            log = sq(&log),
        );
        let out = self.run(&script)?;
        let mut lines = out.lines();
        let head = lines.next().unwrap_or("0|-1|0");
        let logtail = lines.collect::<Vec<_>>().join(" ").trim().to_string();

        let mut parts = head.split('|');
        let p: i64 = parts.next().and_then(|s| s.trim().parse().ok()).unwrap_or(0);
        let d: i64 = parts.next().and_then(|s| s.trim().parse().ok()).unwrap_or(-1);
        let r: i64 = parts.next().and_then(|s| s.trim().parse().ok()).unwrap_or(0);

        let finished = d >= 0; // dest exists => renamed => done
        let running = r == 1;
        let downloaded = if finished {
            d.max(0) as u64
        } else {
            p.max(0) as u64
        };

        // If nothing is running, nothing finished, and the log shows a curl
        // error, surface it.
        let error = if !finished && !running {
            let lower = logtail.to_lowercase();
            if lower.contains("error") || lower.contains("curl:") || lower.contains("fail") {
                Some(logtail.clone())
            } else if downloaded == 0 {
                Some(if logtail.is_empty() {
                    "download not running (no progress)".to_string()
                } else {
                    logtail.clone()
                })
            } else {
                // Stalled partial: no process but a .part exists.
                Some(format!("download stopped at {} bytes: {}", downloaded, logtail))
            }
        } else {
            None
        };

        Ok(DownloadStatus {
            downloaded,
            finished,
            running,
            error,
        })
    }

}

// ---- helpers -------------------------------------------------------------

/// POSIX single-quote a string for safe interpolation into a remote shell.
fn sq(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

fn short(s: &str) -> String {
    if s.len() > 60 {
        format!("{}…", &s[..60])
    } else {
        s.to_string()
    }
}

fn exit_note(status: &std::process::ExitStatus) -> String {
    match status.code() {
        Some(c) => format!(" (exit {c})"),
        None => String::new(),
    }
}

/// A filesystem-safe tag for log file names.
fn safe_tag(s: &str) -> String {
    s.chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect()
}

fn validate_repo(repo: &str) -> Result<()> {
    if repo.is_empty() || !repo.contains('/') {
        bail!("repo id must look like `owner/name`");
    }
    if !repo
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-' | '/'))
    {
        bail!("repo id has invalid characters");
    }
    Ok(())
}

fn validate_filename(name: &str) -> Result<()> {
    if name.is_empty() {
        bail!("filename is empty");
    }
    if name.contains("..") || name.starts_with('/') {
        bail!("filename must be a plain name, not a path");
    }
    if !name
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-' | '/'))
    {
        bail!("filename has invalid characters");
    }
    Ok(())
}

fn validate_revision(rev: &str) -> Result<()> {
    if rev.is_empty() {
        bail!("revision is empty");
    }
    if !rev
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-' | '/'))
    {
        bail!("revision has invalid characters");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn single_quote_escapes() {
        assert_eq!(sq("plain"), "'plain'");
        assert_eq!(sq("a'b"), "'a'\\''b'");
        assert_eq!(sq("/models/x.gguf"), "'/models/x.gguf'");
    }

    #[test]
    fn repo_validation() {
        assert!(validate_repo("TheBloke/Llama-2-7B-GGUF").is_ok());
        assert!(validate_repo("noslash").is_err());
        assert!(validate_repo("bad;rm -rf/x").is_err());
    }

    #[test]
    fn filename_validation() {
        assert!(validate_filename("model.Q4_K_M.gguf").is_ok());
        assert!(validate_filename("../etc/passwd").is_err());
        assert!(validate_filename("/abs").is_err());
        assert!(validate_filename("a b").is_err());
    }

    #[test]
    fn revision_validation() {
        assert!(validate_revision("main").is_ok());
        assert!(validate_revision("v1.0").is_ok());
        assert!(validate_revision("bad rev").is_err());
    }

    #[test]
    fn safe_tag_sanitizes() {
        assert_eq!(safe_tag("a.b/c-d"), "a_b_c_d");
    }
}
