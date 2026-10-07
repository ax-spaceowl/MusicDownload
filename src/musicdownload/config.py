import json
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / "Documents" / "SpaceOwl" / "musicdownload"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_CONFIG = {
    "download_root": str(DEFAULT_CONFIG_DIR),
}


def ensure_config_dir() -> None:
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_config_dir()
    if DEFAULT_CONFIG_PATH.exists():
        try:
            with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError
            if "download_root" not in data:
                data["download_root"] = str(DEFAULT_CONFIG_DIR)
            return data
        except Exception:
            return DEFAULT_CONFIG.copy()
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    ensure_config_dir()
    with DEFAULT_CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
