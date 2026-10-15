# -*- coding: utf-8 -*-
"""用户数据目录(%LOCALAPPDATA%\\Glance)与偏好持久化。"""
import functools
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULTS = {
    "theme": None,     # None=跟随系统;"light"/"dark"=显式
    "win_w": 780,      # 高度按内容自适应,只记宽度
}
_MIN_WIN_W = 320
_MAX_WIN_W = 6000


@functools.lru_cache(maxsize=None)
def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Glance"
    root.mkdir(parents=True, exist_ok=True)
    return root


def atomic_write_text(path: Path, text: str) -> None:
    """先写临时文件再替换,进程中途退出也不会留下半截文件。"""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _path() -> Path:
    return data_dir() / "settings.json"


def load() -> dict:
    out = dict(_DEFAULTS)
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return out
    except (OSError, ValueError):
        log.warning("读取设置失败,使用默认值", exc_info=True)
        return out
    if not isinstance(data, dict):
        return out
    if data.get("theme") in ("light", "dark"):
        out["theme"] = data["theme"]
    try:
        width = int(data.get("win_w"))
    except (TypeError, ValueError):
        width = None
    if width is not None and _MIN_WIN_W <= width <= _MAX_WIN_W:
        out["win_w"] = width
    return out


def save(patch: dict) -> None:
    cur = load()
    cur.update({k: v for k, v in patch.items() if k in _DEFAULTS})
    try:
        atomic_write_text(_path(), json.dumps(cur, ensure_ascii=False, indent=2))
    except OSError:
        log.warning("保存设置失败", exc_info=True)
