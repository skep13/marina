# Marina voice-adapter training data on Kaggle's free 2x T4.
# Runs her exact production model (unsloth gemma-4-26B-A4B-it UD-Q4_K_M, same
# hash as lab3) in llama.cpp with CUDA, then docs/marina-lora/gen.py with
# several parallel workers. Output: /kaggle/working/data-kaggle.jsonl
import glob, os, subprocess, sys, time, urllib.request

WORKERS = int(os.environ.get("WORKERS", "6"))
TARGET = os.environ.get("TARGET", "2500")
HOURS = os.environ.get("HOURS", "10.5")      # Kaggle stops GPU sessions at 12 h
PER_SLOT = 12288                              # her ~8K prompt + a 6-turn chat
GEN_SRC = None   # push.sh embeds docs/marina-lora/gen.py here (Kaggle pins old dataset versions)

def sh(cmd, check=True):
    print("$", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check)

t0 = time.time()
sh("nvidia-smi --query-gpu=name,memory.total --format=csv; nproc; free -g | head -2")
DATA = os.path.dirname(sorted(glob.glob("/kaggle/input/**/snapshot.json", recursive=True))[0])
print("dataset dir:", DATA, os.listdir(DATA), flush=True)

# Model download runs while llama.cpp compiles.
sh("pip install -q -U 'huggingface_hub[hf_transfer]'")
dl = subprocess.Popen(
    "HF_HUB_ENABLE_HF_TRANSFER=1 python -c \"from huggingface_hub import hf_hub_download; "
    "print(hf_hub_download('unsloth/gemma-4-26B-A4B-it-GGUF', "
    "'gemma-4-26B-A4B-it-UD-Q4_K_M.gguf', local_dir='/tmp/models'))\"", shell=True)
sh("git clone --depth 1 https://github.com/ggml-org/llama.cpp /tmp/llama.cpp")
sh("which cmake nvcc; cmake --version | head -1; ls /usr/local/cuda*/bin/nvcc", check=False)
sh("cmake --version >/dev/null 2>&1 || pip install -q cmake")
os.environ["PATH"] = "/usr/local/cuda/bin:" + os.environ["PATH"]
# Kaggle's CUDA 13 image has no libcuda stub, so CMake can't find
# CUDA::cuda_driver; hand it the driver's own library instead.
libcuda = (sorted(glob.glob("/usr/local/cuda*/lib64/stubs/libcuda.so")) +
           sorted(glob.glob("/usr/lib/x86_64-linux-gnu/libcuda.so*")) +
           sorted(glob.glob("/usr/local/nvidia/lib64/libcuda.so*")))
print("libcuda:", libcuda, flush=True)
DRIVER = f"-DCUDA_cuda_driver_LIBRARY={libcuda[0]} " if libcuda else ""
sh("cd /tmp/llama.cpp && cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 "
   "-DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF " + DRIVER + "> /tmp/cmake.log 2>&1 "
   "&& cmake --build build --target llama-server -j$(nproc) > /tmp/build.log 2>&1 "
   "|| (tail -n 60 /tmp/cmake.log; tail -n 60 /tmp/build.log; exit 1)")
print(f"built in {time.time()-t0:.0f}s", flush=True)
if dl.wait() != 0:
    sys.exit("model download failed")
print(f"model ready at {time.time()-t0:.0f}s", flush=True)

np_ = 2 * WORKERS
srv = subprocess.Popen(
    f"/tmp/llama.cpp/build/bin/llama-server -m /tmp/models/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf "
    f"--host 127.0.0.1 --port 8080 -ngl 999 -np {np_} -c {np_ * PER_SLOT} "
    f"-ctk q8_0 -ctv q8_0 -fa on --jinja --cache-reuse 256 --no-webui "
    f"> /kaggle/working/llama-server.log 2>&1", shell=True)
for _ in range(180):
    try:
        if urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5).status == 200:
            break
    except Exception:
        pass
    if srv.poll() is not None:
        sh("tail -40 /kaggle/working/llama-server.log", check=False)
        sys.exit("llama-server exited")
    time.sleep(5)
print(f"server up at {time.time()-t0:.0f}s", flush=True)
sh("nvidia-smi --query-gpu=memory.used --format=csv", check=False)

env = dict(os.environ, GEN_DIR=DATA, GEN_OUT="/kaggle/working/data-kaggle.jsonl",
           GEN_URL="http://127.0.0.1:8080/v1/chat/completions", WORKERS=str(WORKERS))
hours_left = float(HOURS) - (time.time() - t0) / 3600
GEN = f"{DATA}/gen.py"
if GEN_SRC:
    GEN = "/kaggle/working/gen.py"
    open(GEN, "w").write(GEN_SRC)
print("gen.py configurable:", "GEN_DIR" in open(GEN).read(), flush=True)
os.environ.update(env)   # sh() runs with os.environ
gen = sh(f"python -u {GEN} {TARGET} {hours_left:.2f}", check=False)
srv.terminate()
sh("wc -l /kaggle/working/data-kaggle.jsonl; grep -c 'slot' /kaggle/working/llama-server.log "
   "| head -1; tail -5 /kaggle/working/llama-server.log", check=False)
print("== KAGGLE GEN DONE", flush=True)
# Fail the notebook (not "Successfully ran") when nothing was generated.
out = "/kaggle/working/data-kaggle.jsonl"
if not (os.path.exists(out) and os.path.getsize(out)):
    sys.exit(f"gen.py produced no data (exit {gen.returncode})")
