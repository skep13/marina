# Marina voice adapter (LoRA on Gemma 4 26B-A4B)

Goal: a small LoRA adapter that puts Marina's voice into Gemma itself, so her
system prompt can shrink and her style holds without the long persona block.
Tools must keep working: about 20% of the data are tool calls.

## 1. Data: on lab3, free (`gen.py`)

Gemma plays both sides on lab3: a simulator texts like the owner (style
examples are their real messages), and Marina answers on her full live prompt,
tools and samplers. Each reply goes through the bench's checks ("tilts head",
assistant-speak, AI mentions, emoji, markdown, long `*actions*`, worn openers),
gets retried up to three times, and the conversation is cut there if it still fails.

- `snapshot.sh`: saves her live system prompt, 37 tool definitions and the
  owner's last 40 messages to `/root/marina-lora/snapshot.json` (ct110).
- Run: transient unit `marina-lora-gen` (MemoryMax 512M, Nice 10), target
  1500 conversations, 14 h cap. Log: `/root/marina-lora/gen.log`.
  Output: `/root/marina-lora/data.jsonl` (appends; restart resumes).
- Stop: `systemctl stop marina-lora-gen`. Restart: same `systemd-run` line,
  or `KEY=... python3 -I gen.py 1500 14`.
- Records hold no system prompt (the trainer adds one), but the chats mention
  things from her memories (South Wales, Hack Club, college).

## 2. Training: Kaggle, free

Kaggle notebooks: 2x T4 (16 GB each), about 30 GPU hours a week, free once
the account is phone-verified. Base model: `google/gemma-4-26B-A4B-it`
(Apache-2.0, not gated, so no Hugging Face account needed).

Plan: QLoRA, 4-bit base split across both T4s, LoRA on attention only
(rank 16), ~2K-token sequences, checkpoints so a timed-out session can resume.
Data goes up as a **private** Kaggle dataset.

Risks: T4s have no bf16 and Gemma has a history of fp16 trouble; Gemma 4's
MoE layers may not be handled cleanly by Unsloth/PEFT yet; it is tight on memory.
Fallback: Modal's monthly free credit on one H100.

## 3. Convert and deploy

- `convert_lora_to_gguf.py` (llama.cpp) on Kaggle, giving a GGUF adapter of ~100 MB.
- lab3: add `--lora /models/marina-voice.gguf` to the `marina` entry, run
  `docs/marina-bench/bench.py` against plain Gemma, keep it only if it wins.
