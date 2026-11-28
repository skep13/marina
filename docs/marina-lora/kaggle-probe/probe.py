# Feasibility probe for the Marina voice adapter on Kaggle's free 2x T4.
# Loads Gemma 4 26B-A4B-it in 4-bit, attaches an attention-only LoRA, runs one
# training step and one short generation, and prints memory at each stage.
import glob, os, subprocess, sys, time

def sh(cmd):
    print("$", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=False)

sh("nvidia-smi --query-gpu=name,memory.total --format=csv")
sh("free -g | head -2; df -h /kaggle/working /tmp | tail -2")
sh("pip install -q -U transformers peft accelerate bitsandbytes 2>&1 | tail -3")

import torch, transformers, peft, bitsandbytes
print("torch", torch.__version__, "transformers", transformers.__version__,
      "peft", peft.__version__, "bnb", bitsandbytes.__version__, flush=True)

MODEL = os.path.dirname(sorted(glob.glob(
    "/kaggle/input/**/gemma-4-26b-a4b-it/**/config.json", recursive=True))[0])
print("model dir", MODEL, os.listdir(MODEL)[:20], flush=True)

def mem(tag):
    used = [f"{torch.cuda.memory_allocated(i)/2**30:.1f}" for i in range(torch.cuda.device_count())]
    print(f"[{tag}] GPU GiB allocated: {used}", flush=True)

from transformers import AutoConfig, AutoTokenizer, BitsAndBytesConfig
cfg = AutoConfig.from_pretrained(MODEL)
print("architectures", cfg.architectures, flush=True)
tok = AutoTokenizer.from_pretrained(MODEL)

bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
t = time.time()
model = None
for cls_name in ("AutoModelForCausalLM", "AutoModelForImageTextToText"):
    try:
        cls = getattr(transformers, cls_name)
        model = cls.from_pretrained(MODEL, quantization_config=bnb, device_map="auto",
                                    max_memory={0: "14GiB", 1: "14GiB", "cpu": "24GiB"},
                                    torch_dtype=torch.float16, low_cpu_mem_usage=True)
        print("loaded with", cls_name, type(model).__name__, f"in {time.time()-t:.0f}s", flush=True)
        break
    except Exception as e:
        print("load failed with", cls_name, repr(e)[:400], flush=True)
if model is None:
    sys.exit(1)
mem("loaded")
print("device map sample", list(getattr(model, "hf_device_map", {}).items())[:8], flush=True)

# What the layers look like: are experts Linear (quantizable) or fused params?
kinds = {}
for name, mod in model.named_modules():
    k = type(mod).__name__
    kinds.setdefault(k, name)
print("module kinds:", {k: v for k, v in list(kinds.items())[:40]}, flush=True)
big = sorted(((p.numel(), n, str(p.dtype)) for n, p in model.named_parameters()), reverse=True)[:8]
print("largest params:", big, flush=True)
fp = sum(p.numel() for p in model.parameters() if p.dtype in (torch.float16, torch.bfloat16, torch.float32))
print(f"params still in float: {fp/1e9:.2f} B", flush=True)

from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
lcfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0, task_type="CAUSAL_LM",
                  target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj)")
try:
    model = get_peft_model(model, lcfg)
except ValueError:
    lcfg.target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"]
    model = get_peft_model(model, lcfg)
model.print_trainable_parameters()
mem("lora")

msgs = [{"role": "system", "content": "You are Marina."},
        {"role": "user", "content": "how was your weekend"},
        {"role": "assistant", "content": "*stretches* Lazy, honestly. Rewatched some old anime. Yours?"}]
text = tok.apply_chat_template(msgs, tokenize=False)
ids = tok(text, return_tensors="pt").input_ids.to(model.device if hasattr(model, "device") else "cuda:0")
print("example tokens", ids.shape[1], flush=True)
model.train()
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-4)
t = time.time()
out = model(input_ids=ids, labels=ids)
out.loss.backward()
opt.step(); opt.zero_grad()
print(f"train step ok: loss {out.loss.item():.3f}, finite={torch.isfinite(out.loss).item()}, {time.time()-t:.1f}s", flush=True)
mem("after step")

# Longer sequence: does a 2K-token example fit?
long_ids = ids.repeat(1, max(1, 2048 // ids.shape[1]))[:, :2048]
t = time.time()
try:
    out = model(input_ids=long_ids, labels=long_ids)
    out.loss.backward(); opt.zero_grad()
    print(f"2K step ok: {time.time()-t:.1f}s", flush=True)
except torch.cuda.OutOfMemoryError as e:
    print("2K step OOM", flush=True)
mem("after 2K")

model.eval()
prompt = tok.apply_chat_template(msgs[:2], tokenize=False, add_generation_prompt=True)
p = tok(prompt, return_tensors="pt").input_ids.to(ids.device)
with torch.no_grad():
    g = model.generate(input_ids=p, max_new_tokens=40, do_sample=False)
print("generation:", tok.decode(g[0, p.shape[1]:], skip_special_tokens=True), flush=True)
print("PROBE DONE", flush=True)
