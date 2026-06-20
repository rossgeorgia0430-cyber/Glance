# -*- coding: utf-8 -*-
"""用户偏好持久化:%LOCALAPPDATA%\\Glance\\settings.json"""
import json
import os
from pathlib import Path

APP_NAME = "Glance"

_DEFAULTS = {
    "theme": None,     # None=跟随系统;"light"/"dark"=显式
    "win_w": 780,
    "win_h": 540,
}


def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return root


def _path() -> Path:
    return data_dir() / "settings.json"


def load() -> dict:
    out = dict(_DEFAULTS)
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if data.get("theme") in ("light", "dark", None):
                out["theme"] = data.get("theme")
            for k in ("win_w", "win_h"):
                try:
                    v = int(data.get(k))
                    if 320 <= v <= 6000:
                        out[k] = v
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    return out


def save(patch: dict) -> None:
    try:
        cur = load()
        cur.update({k: v for k, v in patch.items() if k in _DEFAULTS})
        p = _path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass
