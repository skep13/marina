# Running the LLM on your server

The Mac handles microphone, speech recognition, voice and avatar. The only thing
it sends elsewhere is the conversation itself.

## Which box

You have two candidates. They are not close.

### Beelink SER9 — yes, use this one

Ryzen AI 9 HX 370 (4 Zen 5 + 8 Zen 5c cores, 24 threads), Radeon 890M (RDNA 3.5),
**32 GB RAM**. This is a genuinely capable inference box — the RAM is what matters
most, and 32 GB is four times what either other machine has.

What fits, at Q4 quantization:

| Model size | RAM | Expect | Good for |
|---|---|---|---|
| 3–4B | ~3 GB | very fast | snappy, a bit dim |
| **7–8B** | **~5 GB** | **fast** | **the sweet spot here** |
| 12–14B | ~9 GB | usable | noticeably better writing |
| 24–32B | ~18 GB | slow | fits, but too slow to talk to |

Go with **8B at Q4**. Marina's replies get spoken aloud, so they're short — you are
paying for latency far more than for depth, and a 14B model saying the same
sentence two seconds later is a worse experience, not a better one.

Two things worth doing on that box:

- **Raise the iGPU memory allocation in BIOS** (UMA Frame Buffer). The Radeon
  890M can take 8–16 GB out of your 32, which lets Ollama offload properly.
- **Use the Vulkan or ROCm backend**, not CPU-only. On CPU alone the Zen 5 cores
  are decent but you're leaving the iGPU idle.

The XDNA 2 NPU (50 TOPS) exists but the tooling for it (FastFlowLM) is early and
mostly Windows-oriented. Ignore it for now; the iGPU is the practical path.

### ThinkPad T470 — no

7th-gen dual-core Intel, 8 GB, Intel HD 620, no usable GPU compute. It could run
a 1–3B model at a few tokens/second, which is slower than you can listen and dim
enough that you'd notice. There is nothing in this project it does better than
the other two machines. Leave it out.

---

## Setting it up

On the SER9:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b            # or llama3.1:8b, gemma3:12b
```

By default Ollama binds to localhost only. To let the Mac reach it:

```bash
sudo systemctl edit ollama
```

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

```bash
sudo systemctl restart ollama
```

Confirm from the Mac:

```bash
curl http://beelink.local:11434/api/tags
```

---

## Point Marina at it

In `character_config.yaml`:

```yaml
llm:
  base_url: "http://beelink.local:11434/v1"
  api_key: "ollama"          # ignored, but must be non-empty
  model: "qwen3:8b"
  temperature: 1.0
  max_tokens: 2048
```

That's the only change. The client speaks the OpenAI chat-completions API, which
Ollama, llama.cpp, LM Studio and vLLM all implement — so any of them work here,
as does OpenAI itself if you leave `base_url` empty.

Check it took:

```bash
curl -s http://127.0.0.1:8765/health
```

should report your `llm_endpoint` and model.

---

## Two things that will bite you

**Thinking models.** `qwen3` and similar emit `<think>…</think>` reasoning
before the answer. Marina will read that out loud. Either pick a non-reasoning
model, or disable it — for Qwen3, append `/no_think` to the system prompt in
`character_config.yaml`.

**Prompt discipline.** Small local models follow instructions less reliably than
GPT-4.1-mini. The stock system prompt already asks for no markdown, lists or
emoji, because all of those get spoken literally. If your model starts narrating
asterisks, tighten that prompt before blaming the model.

---

## Security

Ollama has no authentication. `OLLAMA_HOST=0.0.0.0` exposes it to your whole LAN,
which is fine at home and not fine on a network you don't control. Do not
port-forward it. If you want it from outside, put both machines on Tailscale and
use the tailnet address in `base_url`.
