"""Single source of truth for loading character_config.yaml.

The upstream project did `open('character_config.yaml')` in three separate
modules, which meant the whole thing only ran if your shell happened to be
cwd'd into the repo root. This resolves the path relative to the repo instead.
"""
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
    """Resolve a config path relative to the repo root if it isn't absolute."""
    p = Path(path_str)
    return p if p.is_absolute() else (REPO_ROOT / p)
