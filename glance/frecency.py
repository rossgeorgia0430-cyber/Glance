# -*- coding: utf-8 -*-
"""最近打开记录 + 排序加权(frecency = frequency + recency)。

Everything 自身的 run-count 不包含我们应用内的"打开",所以自管一份。
"""
import json
import os
import time

from .settings import data_dir

_HALF_LIFE = 14 * 86400.0   # 两周半衰期
_MAX_BOOST = 35.0           # 加分上限(与 rapidfuzz 0..100 同量级)
_PRUNE_AT = 800
_KEEP = 600

_cache = None


def _path():
    return data_dir() / "frecency.json"


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            d = json.loads(_path().read_text(encoding="utf-8"))
            _cache = d if isinstance(d, dict) else {}
        except Exception:
            _cache = {}
    return _cache


def _key(path: str) -> str:
    return os.path.normpath(path).lower()


def record(path: str) -> None:
    if not path:
        return
    d = _load()
    e = d.get(_key(path)) or {"n": 0, "t": 0.0}
    e["n"] = int(e.get("n", 0)) + 1
    e["t"] = time.time()
    d[_key(path)] = e
    if len(d) > _PRUNE_AT:
        items = sorted(d.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:_KEEP]
        d = dict(items)
        globals()["_cache"] = d
    try:
        p = _path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def boost(path: str, now: float = None) -> float:
    """返回 0.._MAX_BOOST 的加分,并入搜索重排打分。"""
    e = _load().get(_key(path))
    if not e:
        return 0.0
    now = now or time.time()
    age = max(0.0, now - float(e.get("t", 0.0)))
    recency = 0.5 ** (age / _HALF_LIFE)        # 刚打开≈1,一个半衰期≈0.5
    freq = min(1.0, int(e.get("n", 0)) / 5.0)  # 5 次封顶
    return _MAX_BOOST * (0.6 * recency + 0.4 * freq)
