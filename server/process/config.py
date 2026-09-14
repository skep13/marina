"""Loads character_config.yaml from the repo root."""
from pathlib import Path
import functools
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "character_config.yaml"


@functools.lru_cache(maxsize=1)
def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(path_str):
    p = Path(path_str)
    return p if p.is_absolute() else (REPO_ROOT / p)
