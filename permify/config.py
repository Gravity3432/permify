from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

APP_DIR = Path.home() / ".permify"
CONFIG_FILE = APP_DIR / "config.json"
LIBCRED_FILE = APP_DIR / "librespot_credentials.json"
SPOTIPY_CACHE = APP_DIR / "spotipy_token_cache"
ART_CACHE = APP_DIR / "art_cache"

REDIRECT_URI = "http://127.0.0.1:4616/callback"

# Scopes the Web API side needs (browse + remote control).
SCOPES = (
    "user-read-private user-read-email user-read-currently-playing "
    "user-read-playback-state user-modify-playback-state "
    "user-library-read user-library-modify "
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private "
    "user-top-read user-read-recently-played"
)

DEFAULTS: Dict[str, Any] = {
    "client_id": "",
    "theme": "aurora",
    "layout": "revamp",       # revamp | classic
    "device_name": "Termify",
    "volume": 60,
    "quality": "high",          # normal | high | very_high  (audio quality of the embedded player)
    "mode": "auto",             # auto | stream | remote
    "image_size": 300,
    "prebuffer_ms": 250,        # start-of-track cushion (can't be 0 - physics)
}

ORDERED_THEMES = [
    "aurora", "sunset", "ocean", "candy", "vampire", "mono",
    "chroma", "rainbow", "neon", "synthwave", "toxic", "inferno",
    "ice", "gold", "plasma",
]


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.exists():
            cfg.update(json.loads(CONFIG_FILE.read_text()))
    except Exception:
        pass
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


def ensure_dirs() -> None:
    for p in (APP_DIR, ART_CACHE):
        p.mkdir(parents=True, exist_ok=True)
