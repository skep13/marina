# qwen-gate — public, keyed API for Qwen3.8-27B only

Lives in ct110 (`marina-brain`) on lab3, beside llama-swap.

- `qwen-gate.py` → `/opt/qwen-gate/`, service `qwen-gate` on `:8090`. OpenAI-compatible
  (`/v1/chat/completions`, `/v1/completions`, `/v1/models`). Every request is pinned to the
  llama-swap model `forge-deep` (Qwen3.8-27B) whatever model name the caller sends.
- Keys: `/etc/qwen-gate/keys`, one per line (`#` comments). Add a line to hand out a key, delete
  it to revoke; read on every request, no restart. The gate reaches llama-swap with
  `/etc/qwen-gate/upstream.key` (a copy of the host's `/etc/appliance/lab3.key`).
- `qwen-tunnel.service`: a Cloudflare quick tunnel (no account) to `127.0.0.1:8090`. Its
  `*.trycloudflare.com` URL **changes on every restart/reboot** — run
  `pct exec 110 -- /usr/local/bin/qwen-url` on lab3 for the current one.
- Cloudflare drops a request that sends nothing for 100 s, so when the model is slow to answer
  the gate sends 200 early plus filler (leading spaces for JSON, `: ` comments for SSE).

Install (from the Mac): copy the three files in, `useradd --system qwen-gate`, chown the key
files `root:qwen-gate 0640`, `apt`/`dpkg` cloudflared, `systemctl enable --now qwen-gate qwen-tunnel`.
