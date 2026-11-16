"""The model library: /etc/aiws/models.d/*.yaml (shipped) and
~/.config/aiws/models.d (the user's), one file per model.

    name: qwen3.6-35b-a3b
    label: Qwen3.6 35B-A3B
    runtime: llama.cpp            # llama.cpp | remote
    file: Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
    url: https://huggingface.co/...   # for `ai models pull`
    sha256: ...
    mmproj: ...gguf               # vision projector, loaded by vision profiles
    roles: [chat, code, vision]
    gpu_gb: 25.3                  # measured: weights + KV + compute
    ttl: 600                      # unload after idle seconds, 0 = never
    profiles:                     # name -> settings; first is the default
      interactive: {ctx: 32768, slots: 2, kv: q8_0}
      long: {ctx: 131072, slots: 2, kv: q8_0}

    # a model served elsewhere (e.g. ct110 while lab3 still runs PVE)
    runtime: remote
    base_url: http://192.168.1.15:8080
    remote_model: marina
    key_env: AIWS_KEY_LAB3       # read from /etc/aiws/secrets.env

AIWS doesn't run models itself: it writes llama-swap's config from this
library, and llama-swap starts, swaps and unloads llama-server.
"""
import hashlib
import os
from pathlib import Path

import yaml

from aiws import config, store

ROLES = ("chat", "code", "vision", "embed", "asr", "tts", "fast")


def library():
    shipped, e1 = config.read_yaml_dir(config.ETC / "models.d")
    mine, e2 = config.read_yaml_dir(config.user_config_dir() / "models.d")
    shipped.update(mine)
    return shipped, {**e1, **e2}


def profiles(m):
    p = m.get("profiles") or {"default": {}}
    return list(p.items())


def served_names(m):
    """What a client can ask for: `name` (default profile) and `name@profile`."""
    names = [m["name"]]
    for i, (pname, _) in enumerate(profiles(m)):
        if i:
            names.append(f"{m['name']}@{pname}")
    return names


def path_of(m, key="file"):
    f = m.get(key)
    if not f:
        return None
    p = Path(f)
    return p if p.is_absolute() else config.MODELS_DIR / p


def present(m):
    if m.get("runtime") == "remote":
        return True
    p = path_of(m)
    return bool(p and p.exists())


def _server_args(m, prof):
    a = ["${llama}", "-m", str(path_of(m)), "--alias", "${MODEL_ID}",
         "-ngl", str(prof.get("ngl", 999)),
         "-c", str(prof.get("ctx", 8192)),
         "-np", str(prof.get("slots", 1)),
         "-fa", "on", "--jinja", "--metrics"]
    kv = prof.get("kv")
    if kv:
        a += ["-ctk", kv, "-ctv", kv]
    for flag, key in (("-b", "batch"), ("-ub", "ubatch"), ("--cache-ram", "cache_ram"),
                      ("--ctx-checkpoints", "ctx_checkpoints")):
        if key in prof:
            a += [flag, str(prof[key])]
    if prof.get("vision", "vision" in (m.get("roles") or [])) and m.get("mmproj"):
        a += ["--mmproj", str(path_of(m, "mmproj"))]
    if m.get("lora"):
        a += ["--lora", str(path_of(m, "lora"))]
    if "embed" in (m.get("roles") or []):
        a += ["--embeddings"]
    a += [str(x) for x in prof.get("extra", [])]
    return " ".join(a)


def llama_swap_config():
    """llama-swap YAML for every local model whose file is present. Big
    models swap one at a time; models marked `resident: true` (small
    embedders, ASR) stay loaded beside them."""
    lib, _ = library()
    models, big, small = {}, [], []
    for m in lib.values():
        if m.get("runtime", "llama.cpp") != "llama.cpp" or not present(m):
            continue
        for i, (pname, prof) in enumerate(profiles(m)):
            sid = m["name"] if i == 0 else f"{m['name']}@{pname}"
            models[sid] = {"cmd": _server_args(m, prof),
                           "ttl": int(prof.get("ttl", m.get("ttl", 600)))}
            (small if m.get("resident") else big).append(sid)
    cfg = {
        "healthCheckTimeout": 300,
        # llama-server from PATH unless aiws.yaml names one (CUDA on the
        # laptop, Vulkan on lab3).
        "macros": {"llama": f"{config.settings().get('llama_server', 'llama-server')} "
                            "--host 127.0.0.1 --port ${PORT}"},
        "models": models,
        "groups": {},
    }
    if big:
        cfg["groups"]["gpu"] = {"swap": True, "exclusive": False, "members": big}
    if small:
        cfg["groups"]["resident"] = {"swap": False, "exclusive": False,
                                     "persistent": True, "members": small}
    pre = store.get("preload") or [m for m in big[:1]]
    if pre:
        cfg["hooks"] = {"on_startup": {"preload": pre}}
    return cfg


def write_llama_swap_config(path=None):
    path = Path(path or config.LLAMA_SWAP_CONFIG)
    text = ("# Written by aiwsd from the model library. Edit models.d, not this.\n"
            + yaml.safe_dump(llama_swap_config(), sort_keys=False))
    if not path.exists() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text)
        os.replace(tmp, path)  # llama-swap -watch-config picks it up
        return True
    return False


# ---- role resolution ----
def role_map():
    """Global role -> model choice, set from the control centre or `ai models use`."""
    return store.get("roles") or {}


def set_role(role, model):
    rm = role_map()
    rm[role] = model
    store.put("roles", rm)


def resolve(requested, project_roles=None):
    """Turn what a client asked for into (model entry, served name).

    Accepts a served name (`qwen…`, `qwen…@long`), a role alias
    (`ai:code`, or bare `code`), or `ai` = chat. Project choices win
    over the global ones."""
    lib, _ = library()
    req = (requested or "ai:chat").strip()
    if req == "ai":
        req = "ai:chat"
    role = req.split(":", 1)[1] if req.startswith("ai:") else (req if req in ROLES else None)
    if role:
        choice = (project_roles or {}).get(role) or role_map().get(role)
        if not choice:
            choice = next((n for n, m in lib.items()
                           if role in (m.get("roles") or []) and present(m)), None)
        if not choice:
            return None, None
        req = choice
    base = req.split("@", 1)[0]
    m = lib.get(base)
    if not m:
        return None, None
    return m, req


def sha256_file(path, bufsize=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(bufsize):
            h.update(chunk)
    return h.hexdigest()


def secret(name):
    """Values from /etc/aiws/secrets.env (root:aiws 0640), then the environment."""
    f = config.ETC / "secrets.env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"')
    return os.environ.get(name, "")
