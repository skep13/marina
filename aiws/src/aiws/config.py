"""Where AIWS keeps things. Every path can be moved with an environment
variable, so the same code runs installed, in a VM and from a checkout."""
import os
from pathlib import Path

import yaml

ETC = Path(os.environ.get("AIWS_ETC", "/etc/aiws"))
STATE = Path(os.environ.get("AIWS_STATE", "/var/lib/aiws"))
MODELS_DIR = Path(os.environ.get("AIWS_MODELS", "/var/lib/aiws/models"))

LISTEN = os.environ.get("AIWS_LISTEN", "127.0.0.1:7300")
LLAMA_SWAP_URL = os.environ.get("AIWS_LLAMA_SWAP", "http://127.0.0.1:8080")
LLAMA_SWAP_CONFIG = Path(os.environ.get("AIWS_LLAMA_SWAP_CONFIG",
                                        STATE / "llama-swap.yaml"))


def user_config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "aiws"


def read_yaml_dir(path):
    """All *.yaml in a directory, keyed by file stem. Bad files are reported,
    not fatal: one typo shouldn't take the gateway down."""
    out, errors = {}, {}
    path = Path(path)
    if not path.is_dir():
        return out, errors
    for f in sorted(path.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text()) or {}
            data.setdefault("name", f.stem)
            out[data["name"]] = data
        except Exception as e:
            errors[f.name] = str(e)
    return out, errors


def settings():
    f = ETC / "aiws.yaml"
    return (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
