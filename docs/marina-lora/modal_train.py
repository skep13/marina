"""Train Marina's voice adapter (LoRA on Gemma 4 26B-A4B-it) on Modal.

Steps, each its own Modal function with a hard timeout so spend stays bounded:
  download  CPU   google/gemma-4-26B-A4B-it -> volume (once, ~52 GB)
  prep      CPU   data.jsonl -> token ids + loss masks, rendered with her
                  live system prompt and tools (as the bridge sends them)
  train     H100  bf16 base, LoRA r16 on the text model's attention
  convert   CPU   PEFT adapter -> GGUF for llama.cpp (--lora on lab3)

Usage (from this folder, with data.jsonl and snapshot.json next to it):
  modal run modal_train.py::download
  modal run modal_train.py::main --max-steps 20        # cheap test
  modal run modal_train.py::main                        # full run
  modal volume get marina-lora out/marina-voice-f16.gguf .
"""
import json
import os

import modal

app = modal.App("marina-lora")
vol = modal.Volume.from_name("marina-lora", create_if_missing=True)
V = "/vol"
BASE = f"{V}/base"
BASE_ID = "google/gemma-4-26B-A4B-it"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("torch", "transformers>=5", "peft", "accelerate", "safetensors",
                 "huggingface_hub[hf_transfer]", "sentencepiece", "numpy", "gguf")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .run_commands("git clone --depth 1 https://github.com/ggml-org/llama.cpp /llama.cpp")
)


@app.function(image=image, volumes={V: vol}, timeout=60 * 60, cpu=4, memory=8192)
def download():
    from huggingface_hub import snapshot_download
    snapshot_download(BASE_ID, local_dir=BASE)
    vol.commit()
    print("base downloaded:", sorted(os.listdir(BASE)))


def fix_msg(m):
    m = dict(m)
    if m.get("tool_calls"):
        m["tool_calls"] = [{"type": "function", "function": {
            "name": c["function"]["name"],
            "arguments": json.loads(c["function"].get("arguments") or "{}")}}
            for c in m["tool_calls"]]
    return m


def build_example(tok, system, tools, msgs):
    """One conversation -> (token ids, loss mask), or (None, reason).

    Each of her turns is laid out the way llama.cpp serves it with thinking
    off: the generation prompt (which ends in an empty thought block,
    <|channel>thought\\n<channel|>) and then her reply. The loss covers her
    reply from its first token. A finished turn re-rendered by the template
    has no thought block, so taking the reply's start from the generation
    prompt (as the first run did) skipped its first 4 tokens and trained
    her turns in a context she never sees when serving.
    """
    def text(ms, gen=False):
        return tok.apply_chat_template(
            [{"role": "system", "content": system}] + ms, tools=tools or None,
            tokenize=False, add_generation_prompt=gen, enable_thinking=False)

    def ids(s):
        return tok(s, add_special_tokens=False).input_ids

    out, mask, done = [], [], ""
    for i, m in enumerate(msgs):
        if m["role"] != "assistant":
            continue
        base, gen, full = text(msgs[:i]), text(msgs[:i], True), text(msgs[:i + 1])
        if not (base.startswith(done) and gen.startswith(base) and full.startswith(base)):
            return None, "prefix mismatch"
        gen_tail, reply = gen[len(base):], full[len(base):]
        k = 0                                   # shared turn header, "<|turn>model\n"
        while k < min(len(gen_tail), len(reply)) and gen_tail[k] == reply[k]:
            k += 1
        k = reply.rfind("\n", 0, k) + 1         # whole lines only: both go on with "<|"
        if not reply[k:].strip():
            return None, "empty reply"
        hers = 0 if m.get("train") is False else 1   # clean_data marks overlong replies
        for seg, train in ((base[len(done):], 0), (gen_tail, 0), (reply[k:], hers)):
            t = ids(seg) if seg else []
            out += t; mask += [train] * len(t)
        done = full
    if not out:
        return None, "no turns"
    return out, mask


@app.function(image=image, volumes={V: vol}, timeout=30 * 60, cpu=4, memory=16384)
def prep(max_len: int = 12288):
    """Each conversation becomes one sequence; loss only on her turns."""
    from collections import Counter
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(BASE)
    snap = json.load(open(f"{V}/data/snapshot.json"))
    system, tools = snap["system"], snap["tools"]

    out, skipped = [], Counter()
    for line in open(f"{V}/data/data.jsonl"):
        msgs = [fix_msg(m) for m in json.loads(line)["messages"]]
        ids, mask = build_example(tok, system, tools, msgs)
        if ids is None:
            skipped[mask] += 1
            continue
        if len(ids) > max_len:
            skipped["too long"] += 1
            continue
        out.append({"ids": ids, "mask": mask})
    os.makedirs(f"{V}/prep", exist_ok=True)
    json.dump(out, open(f"{V}/prep/train.json", "w"))
    vol.commit()
    lens = sorted(len(o["ids"]) for o in out)
    print(f"{len(out)} sequences, skipped {skipped}; tokens: median {lens[len(lens)//2]}, "
          f"max {lens[-1]}, total {sum(lens)}; trainable {sum(sum(o['mask']) for o in out)}")
    # One example, rendered, to check the template by eye.
    print(tok.decode(out[0]["ids"])[-1500:])


@app.function(image=image, volumes={V: vol}, gpu="H100", timeout=200 * 60,
              memory=65536, cpu=8)
def train(max_steps: int = 0, epochs: float = 1.0, lr: float = 1e-4, accum: int = 8,
          rank: int = 16):
    import math, random, time
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForImageTextToText

    data = json.load(open(f"{V}/prep/train.json"))
    random.Random(0).shuffle(data)
    t = time.time()
    model = AutoModelForImageTextToText.from_pretrained(BASE, dtype=torch.bfloat16,
                                                        device_map="cuda")
    print(f"loaded in {time.time()-t:.0f}s; GPU {torch.cuda.memory_allocated()/2**30:.1f} GiB",
          flush=True)
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=rank, lora_alpha=2 * rank, lora_dropout=0.0,
        target_modules=r".*language_model.*\.self_attn\.(q_proj|k_proj|v_proj|o_proj)"))
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    total = max_steps or math.ceil(len(data) * epochs / accum)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / 10) * 0.5 * (1 + math.cos(math.pi * min(s, total) / total)))
    model.train()
    step, seen, t0, run_loss = 0, 0, time.time(), []
    while step < total:
        for ex in data:
            ids = torch.tensor([ex["ids"]], device="cuda")
            mask = torch.tensor(ex["mask"], device="cuda", dtype=torch.bool)
            # Logits only where the next token is hers: the vocab is 262k, so
            # full-sequence logits for an 8K prompt would cost ~8 GB for nothing.
            keep = torch.nonzero(mask[1:]).squeeze(1)
            logits = model(input_ids=ids, logits_to_keep=keep).logits[0]
            loss = torch.nn.functional.cross_entropy(
                logits.float(), ids[0, keep + 1]) / accum
            loss.backward()
            run_loss.append(loss.item() * accum)
            seen += 1
            if seen % accum:
                continue
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            step += 1
            if step % 5 == 0 or step == total:
                el = time.time() - t0
                print(f"step {step}/{total} loss {sum(run_loss)/len(run_loss):.3f} "
                      f"lr {sched.get_last_lr()[0]:.2e} {el/step:.1f}s/step "
                      f"peak {torch.cuda.max_memory_allocated()/2**30:.0f} GiB", flush=True)
                run_loss = []
            if step % 50 == 0:
                model.save_pretrained(f"{V}/out/adapter"); vol.commit()
            if step >= total:
                break
    model.save_pretrained(f"{V}/out/adapter")
    vol.commit()
    print("saved adapter", os.listdir(f"{V}/out/adapter"))


@app.function(image=image, volumes={V: vol}, timeout=30 * 60, cpu=4, memory=32768)
def convert():
    import subprocess
    out = f"{V}/out/marina-voice-f16.gguf"
    subprocess.run(["python", "/llama.cpp/convert_lora_to_gguf.py", f"{V}/out/adapter",
                    "--base", BASE, "--outfile", out, "--outtype", "f16"], check=True)
    vol.commit()
    print("gguf:", out, os.path.getsize(out) // 2**20, "MiB")


@app.function(image=image, volumes={V: vol}, gpu="H100", timeout=90 * 60,
              memory=65536, cpu=8)
def dpo(epochs: int = 2, lr: float = 2e-5, beta: float = 0.1, nll: float = 0.1,
        accum: int = 4):
    """Preference step on the owner's picks (prefs.jsonl: context, chosen,
    rejected), starting from the SFT adapter, which is also the reference.

    Loss per pair: -log sigmoid(beta * (chosen margin - rejected margin)),
    margins being the policy's summed log-prob of her reply minus the
    reference's, plus a small NLL on the chosen reply so a few hundred pairs
    can't pull her off her own voice."""
    import math, random, time
    import torch
    import torch.nn.functional as F
    from peft import PeftModel
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE)
    snap = json.load(open(f"{V}/data/snapshot.json"))
    pairs = []
    for line in open(f"{V}/data/prefs.jsonl"):
        p = json.loads(line)
        ctx = [dict(fix_msg(m), train=False) for m in p["context"]]
        sides = []
        for reply in (p["chosen"], p["rejected"]):
            ids, mask = build_example(tok, snap["system"], snap["tools"],
                                      ctx + [{"role": "assistant", "content": reply}])
            if ids is None:
                break
            sides.append((ids, mask))
        if len(sides) == 2:
            pairs.append(sides)
    print(f"{len(pairs)} preference pairs", flush=True)

    model = AutoModelForImageTextToText.from_pretrained(BASE, dtype=torch.bfloat16,
                                                        device_map="cuda")
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = PeftModel.from_pretrained(model, f"{V}/out/adapter", is_trainable=True)

    def logp(ids, mask):
        ids = torch.tensor([ids], device="cuda")
        mask = torch.tensor(mask, device="cuda", dtype=torch.bool)
        keep = torch.nonzero(mask[1:]).squeeze(1)
        logits = model(input_ids=ids, logits_to_keep=keep).logits[0].float()
        lp = torch.log_softmax(logits, -1).gather(1, ids[0, keep + 1][:, None]).squeeze(1)
        return lp.sum(), len(keep)

    model.eval()
    with torch.no_grad():
        ref = [[logp(*s)[0].item() for s in pair] for pair in pairs]
    print("reference log-probs done", flush=True)

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    order = list(range(len(pairs)))
    total = math.ceil(len(pairs) * epochs / accum)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / 5) * 0.5 * (1 + math.cos(math.pi * min(s, total) / total)))
    model.train()
    step, seen, t0, log = 0, 0, time.time(), []
    for ep in range(epochs):
        random.Random(ep).shuffle(order)
        for i in order:
            (c, r), (rc, rr) = pairs[i], ref[i]
            pc, nc = logp(*c)
            pr, _ = logp(*r)
            margin = beta * ((pc - rc) - (pr - rr))
            loss = (-F.logsigmoid(margin) + nll * (-pc / nc)) / accum
            loss.backward()
            log.append((margin.item() > 0, margin.item()))
            seen += 1
            if seen % accum:
                continue
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            step += 1
            if step % 5 == 0 or step == total:
                acc = sum(a for a, _ in log) / len(log)
                print(f"dpo step {step}/{total} epoch {ep + 1} picked-reply preferred {acc:.0%} "
                      f"margin {sum(m for _, m in log) / len(log):.3f} "
                      f"{(time.time() - t0) / step:.1f}s/step", flush=True)
                log = []
    model.save_pretrained(f"{V}/out/adapter")
    vol.commit()
    print("saved DPO adapter", flush=True)


@app.local_entrypoint()
def main(max_steps: int = 0, epochs: float = 1.0, skip_upload: bool = False,
         sft: bool = True, prefs: bool = True):
    """Full run: SFT on data.jsonl, then DPO on prefs.jsonl if it's there.
    --no-sft runs only DPO, from the SFT adapter already on the volume."""
    here = os.path.dirname(os.path.abspath(__file__))
    has_prefs = prefs and os.path.exists(f"{here}/prefs.jsonl")
    if not skip_upload:
        with vol.batch_upload(force=True) as up:
            up.put_file(f"{here}/data.jsonl", "/data/data.jsonl")
            up.put_file(f"{here}/snapshot.json", "/data/snapshot.json")
            if has_prefs:
                up.put_file(f"{here}/prefs.jsonl", "/data/prefs.jsonl")
    if sft:
        prep.remote()
        train.remote(max_steps=max_steps, epochs=epochs)
        backup_sft.remote()
    else:
        restore_sft.remote()
    if has_prefs:
        dpo.remote()
    convert.remote()


@app.function(image=image, volumes={V: vol}, timeout=10 * 60)
def backup_sft():
    import shutil
    shutil.rmtree(f"{V}/out/adapter-sft", ignore_errors=True)
    shutil.copytree(f"{V}/out/adapter", f"{V}/out/adapter-sft")
    vol.commit()


@app.function(image=image, volumes={V: vol}, timeout=10 * 60)
def restore_sft():
    import shutil
    shutil.rmtree(f"{V}/out/adapter", ignore_errors=True)
    shutil.copytree(f"{V}/out/adapter-sft", f"{V}/out/adapter")
    vol.commit()
