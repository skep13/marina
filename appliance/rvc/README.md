# Her RVC voice

Kokoro speaks, then RVC turns that into her voice model's voice, on lab3's
CPU (ct110) so it never competes with the model on the GPU. About 0.6 s of
work per second of speech once warm. If it fails or is down, she just speaks
in plain Kokoro.

Setup (once, in ct110):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /opt/rvc && uv venv -p 3.10 .venv
uv pip install -p .venv/bin/python torch==2.1.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cpu
uv pip install -p .venv/bin/python rvc-python "setuptools<70"
```

The model (`.pth` + `.index`) goes in `/opt/rvc/models/<name>/`; it isn't in
git. Copy `rvc_server.py` to `/opt/rvc/` and `marina-rvc.service` to
`/etc/systemd/system/`, then `systemctl enable --now marina-rvc`.

Turn it on in `character_config.yaml`:

```yaml
tts:
  rvc:
    url: "http://127.0.0.1:8790"
```
