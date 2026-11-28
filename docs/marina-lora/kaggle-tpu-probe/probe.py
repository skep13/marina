# TPU feasibility probe for the Marina voice adapter (Kaggle TPU v5e-8).
# Loads KerasHub's Gemma 4 26B-A4B instruct sharded over 8 chips, adds LoRA,
# checks the Keras tokenizer against Hugging Face's chat template, runs a few
# training steps and one generation.
import glob, os, subprocess, time
os.environ["KERAS_BACKEND"] = "jax"
os.environ.setdefault("XLA_PYTHON_CLIENT_MEM_FRACTION", "0.95")

def sh(cmd):
    print("$", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=False)

sh("free -g | head -2; nproc; ls /dev/accel* /dev/vfio 2>&1 | head; env | grep -iE 'tpu|accel' | head")
import jax as _jax
print("devices before pip:", _jax.devices(), flush=True)
if _jax.devices()[0].platform != "tpu":
    raise SystemExit("NO TPU in this session")
sh("pip install -q -U keras keras-hub 'transformers>=5' 2>&1 | tail -2")

import jax, keras, keras_hub, numpy as np
print("jax", jax.__version__, "keras", keras.__version__, "keras_hub", keras_hub.__version__, flush=True)
devs = jax.devices()
print("devices:", len(devs), devs[0].device_kind, flush=True)

def find(pattern):
    hits = sorted(glob.glob(pattern, recursive=True))
    return os.path.dirname(hits[0]) if hits else None

KERAS_DIR = find("/kaggle/input/**/gemma4_instruct_26b_a4b/**/metadata.json")
HF_DIR = find("/kaggle/input/**/gemma-4-26b-a4b-it/**/tokenizer.json")
print("keras preset:", KERAS_DIR, os.listdir(KERAS_DIR) if KERAS_DIR else None, flush=True)
print("hf tokenizer:", HF_DIR, flush=True)

def hbm(tag):
    try:
        s = [d.memory_stats() for d in devs]
        print(f"[{tag}] HBM GiB in use per chip:",
              [round(x["bytes_in_use"] / 2**30, 1) for x in s], flush=True)
    except Exception as e:
        print(f"[{tag}] no memory stats: {e}", flush=True)

mesh = keras.distribution.DeviceMesh((1, len(devs)), ("batch", "model"), devs)
L = keras.distribution.LayoutMap(mesh)
M = "model"
L["token_embedding/embeddings"] = (M, None)
L["decoder_block.*attention.*(query|key|value).kernel"] = (None, M, None)
L["decoder_block.*attention_output.kernel"] = (None, None, M)
L["decoder_block.*ffw_gating.*kernel"] = (None, M)
L["decoder_block.*ffw_linear.kernel"] = (M, None)
L["decoder_block.*moe_expert_bank.*(gate_proj|up_proj|down_proj)"] = (M, None, None)
keras.distribution.set_distribution(
    keras.distribution.ModelParallel(layout_map=L, batch_dim_name="batch"))

t = time.time()
lm = keras_hub.models.Gemma4CausalLM.from_preset(KERAS_DIR, dtype="bfloat16")
print(f"loaded in {time.time()-t:.0f}s; params {lm.count_params()/1e9:.2f} B", flush=True)
hbm("loaded")
bb = lm.backbone
blk = bb.get_layer("decoder_block_0")
for v in (bb.get_layer("token_embedding").weights + blk.weights)[:24]:
    print(f"  {v.path:<60} {str(v.shape):<22} {v.value.sharding.spec}", flush=True)

bb.enable_lora(rank=16)
n_train = sum(int(np.prod(v.shape)) for v in bb.trainable_weights)
print(f"LoRA trainable params: {n_train/1e6:.1f} M in {len(bb.trainable_weights)} tensors", flush=True)
print("  sample:", [v.path for v in bb.trainable_weights[:6]], flush=True)

# Tokenizer check: HF chat template rendering vs Keras tokenizer ids.
from transformers import AutoTokenizer
hf = AutoTokenizer.from_pretrained(HF_DIR)
msgs = [{"role": "system", "content": "You are Marina."},
        {"role": "user", "content": "how was your weekend"},
        {"role": "assistant", "content": "*stretches* Lazy, honestly. Rewatched some old anime. Yours?"}]
full = hf.apply_chat_template(msgs, tokenize=False)
prompt = hf.apply_chat_template(msgs[:2], tokenize=False, add_generation_prompt=True)
print("rendered:", repr(full[:400]), flush=True)
print("prompt is prefix of full:", full.startswith(prompt), flush=True)
hf_ids = hf(full, add_special_tokens=False).input_ids
k_ids = [int(x) for x in np.asarray(lm.preprocessor.tokenizer(full))]
print("ids equal:", hf_ids == k_ids, len(hf_ids), len(k_ids), flush=True)
if hf_ids != k_ids:
    print(" hf:", hf_ids[:40], "\n  k:", k_ids[:40], flush=True)

# A few training steps straight on token ids (HF template), loss on reply only.
SEQ = 1024
def example(full_text, prompt_text):
    ids = hf(full_text, add_special_tokens=False).input_ids[:SEQ + 1]
    n_prompt = len(hf(prompt_text, add_special_tokens=False).input_ids)
    x = np.zeros(SEQ, "int32"); y = np.zeros(SEQ, "int32"); w = np.zeros(SEQ, "float32")
    m = np.zeros(SEQ, "int32")
    n = len(ids) - 1
    x[:n] = ids[:-1]; y[:n] = ids[1:]; m[:n] = 1
    w[max(0, n_prompt - 1):n] = 1.0
    return x, y, w, m

xs, ys, ws, ms = map(np.stack, zip(*[example(full, prompt)] * 8))
pos = np.tile(np.arange(SEQ, dtype="int32"), (8, 1))
inputs = {"token_ids": xs, "padding_mask": ms}
needed = {i.name for i in bb.inputs}
print("backbone inputs:", sorted(needed), flush=True)
if "position_ids" in needed:
    inputs["position_ids"] = pos
lm.preprocessor = None
lm.compile(optimizer=keras.optimizers.Adam(1e-4),
           loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
           weighted_metrics=[], sampler="greedy")
try:
    for i in range(3):
        t = time.time()
        logs = lm.train_on_batch(inputs, ys, sample_weight=ws, return_dict=True)
        print(f"step {i}: {logs} {time.time()-t:.1f}s", flush=True)
    hbm("trained")
except Exception as e:
    import traceback; traceback.print_exc()

print("PROBE DONE", flush=True)
