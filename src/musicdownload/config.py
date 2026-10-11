import json
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / "Documents" / "SpaceOwl" / "musicdownload"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

# 工程内的资源位置（src/musicdownload/config.py -> 工程根目录/resources）
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent
RESOURCE_DIR = PROJECT_ROOT / "resources"
ICON_PATH = RESOURCE_DIR / "icon.svg"

DEFAULT_CONFIG = {
    "download_root": str(DEFAULT_CONFIG_DIR),
    "check_updates_on_startup": True,
    "auto_open_trim": True,
    "download_mode": "video_and_audio",
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
            for key, value in DEFAULT_CONFIG.items():
                data.setdefault(key, value)
            return data
        except Exception:
            return DEFAULT_CONFIG.copy()
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    ensure_config_dir()
    with DEFAULT_CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
