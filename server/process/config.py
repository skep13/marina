"""Loads character_config.yaml.

In a checkout the repo is both the asset root and the writable root. Inside
Marina.app the two come apart: the voice model, the avatar and the Python
source ship read-only in the bundle, while the config, the memory and the
chat history have to live somewhere the user can actually write. Electron
sets MARINA_ROOT and MARINA_DATA to keep the two apart; without them
everything falls back to the repo and development works as it always did.
"""
from pathlib import Path
import functools
import os
import shutil
import yaml


def _env_path(name):
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else None


REPO_ROOT = _env_path("MARINA_ROOT") or Path(__file__).resolve().parents[2]
DATA_ROOT = _env_path("MARINA_DATA") or REPO_ROOT

CONFIG_PATH = DATA_ROOT / "character_config.yaml"
DEFAULT_CONFIG = REPO_ROOT / "character_config.example.yaml"


def _seed_config():
    """First run has no config, so start from the shipped defaults."""
    if not DEFAULT_CONFIG.exists():
        raise FileNotFoundError(
            f"No config at {CONFIG_PATH} and no defaults at {DEFAULT_CONFIG}."
        )
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEFAULT_CONFIG, CONFIG_PATH)
    print(f"[config] wrote a starter config to {CONFIG_PATH}", flush=True)


@functools.lru_cache(maxsize=1)
def load_config():
    if not CONFIG_PATH.exists():
        _seed_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(path_str):
    """A read-only asset that ships with the app."""
    p = Path(path_str)
    return p if p.is_absolute() else (REPO_ROOT / p)


def resolve_data(path_str):
    """A file the app writes to. Inside the bundle this is Application Support."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    p = DATA_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
