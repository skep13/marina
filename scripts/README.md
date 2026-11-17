# scripts

Occasional helpers. Each one runs from the repo root whatever folder you call it from.

| Script | What |
|---|---|
| `audition-pitch.sh` | Try Marina's voice at a few pitches |
| `bench-llm.sh` | Old LLM speed benchmark (superseded by `ai-bench`) |
| `fix-venv.sh` | Repair `.venv` after the repo folder moves |
| `install_reqs.sh` | Older CUDA install of the Python deps (with `extra-req.txt`); the Mac uses `../setup-mac.sh` |
| `build-dmg.sh` | One Marina Suite disk image with every Mac app, in `dist/` |
| `download-kokoro.sh` | Fetch the Kokoro voice model into `models/kokoro/` (`setup-mac.sh` runs it) |
