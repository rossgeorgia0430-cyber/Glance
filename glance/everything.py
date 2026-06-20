# -*- coding: utf-8 -*-
"""
Everything 后端封装(ctypes 走本地 IPC)。

增强:
- scope_dir:把搜索限定在某目录下。
- 分级容错模糊:子串-AND 优先;命中过少时回退子序列通配,合并去重。
- frecency:把最近/常打开的文件加权置前。
- DLL 路径兼容 PyInstaller(sys._MEIPASS)。
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from rapidfuzz import fuzz

from . import frecency, settings

# --- Everything SDK 常量 ---------------------------------------------------
REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
REQUEST_SIZE = 0x00000010
REQUEST_DATE_MODIFIED = 0x00000040
SORT_DATE_MODIFIED_DESCENDING = 14
EVERYTHING_ERROR_IPC = 2

_INSTANCE_NAME = "Glance"
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008

_BUF_SIZE = 32768
_FUZZY_FALLBACK_THRESHOLD = 25   # 子串命中少于此值才启用子序列回退
_query_lock = threading.RLock()


class EverythingError(RuntimeError):
    pass


def _dll_path():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "GlanceIndex64.dll")]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands += [os.path.join(base, "glance", "GlanceIndex64.dll"),
                  os.path.join(base, "GlanceIndex64.dll")]
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


_dll = None


def _load():
    global _dll
    if _dll is not None:
        return _dll
    path = _dll_path()
    if not os.path.exists(path):
        raise EverythingError(f"找不到索引组件:{path}")
    d = ctypes.WinDLL(path)
    d.Everything_SetSearchW.argtypes = [wintypes.LPCWSTR]
    d.Everything_SetRequestFlags.argtypes = [wintypes.DWORD]
    d.Everything_SetSort.argtypes = [wintypes.DWORD]
    d.Everything_SetMax.argtypes = [wintypes.DWORD]
    d.Everything_SetMatchPath.argtypes = [wintypes.BOOL]
    d.Everything_SetMatchCase.argtypes = [wintypes.BOOL]
    d.Everything_QueryW.argtypes = [wintypes.BOOL]
    d.Everything_QueryW.restype = wintypes.BOOL
    d.Everything_GetNumResults.restype = wintypes.DWORD
    d.Everything_GetResultFullPathNameW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD]
    d.Everything_GetResultFullPathNameW.restype = wintypes.DWORD
    d.Everything_IsFolderResult.argtypes = [wintypes.DWORD]
    d.Everything_IsFolderResult.restype = wintypes.BOOL
    d.Everything_GetResultSize.argtypes = [wintypes.DWORD, ctypes.POINTER(ctypes.c_longlong)]
    d.Everything_GetResultSize.restype = wintypes.BOOL
    d.Everything_GetResultDateModified.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.FILETIME)]
    d.Everything_GetResultDateModified.restype = wintypes.BOOL
    d.Everything_GetLastError.restype = wintypes.DWORD
    d.Everything_GetMajorVersion.restype = wintypes.DWORD
    d.Everything_IsDBLoaded.restype = wintypes.BOOL
    _dll = d
    return _dll


def is_available():
    """Glance 专属命名实例的 IPC 窗口是否存在。

    不用 QueryW 探活：数据库尚未就绪时同步查询可能长时间阻塞。
    定制 SDK 只查找 EVERYTHING_TASKBAR_NOTIFICATION_(Glance)，不会误连
    用户自行安装或退出的默认 Everything 实例。
    """
    try:
        return bool(_load().Everything_GetMajorVersion())
    except Exception:
        return False


def is_ready():
    """IPC 通且索引数据库已加载完成(可返回完整结果)。"""
    if not is_available():
        return False
    try:
        return bool(_load().Everything_IsDBLoaded())
    except Exception:
        return False


# --- 内嵌 Everything:免装、免手动开启 --------------------------------------
def _bundled_exe():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "bin", "GlanceIndexer.exe")]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.insert(0, os.path.join(base, "glance", "bin", "GlanceIndexer.exe"))
    return next((c for c in cands if os.path.exists(c)), None)


def _index_dir():
    p = settings.data_dir() / "Indexer"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path():
    """安装器和卸载器共用的专属配置位置。"""
    return _index_dir() / "Everything.ini"


def _ini_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ntfs_volumes():
    """列出固定 NTFS 卷，预写入配置以跳过 Everything 的首次选择界面。"""
    kernel32 = ctypes.windll.kernel32
    roots = []
    mask = int(kernel32.GetLogicalDrives())
    for i in range(26):
        if not (mask & (1 << i)):
            continue
        root = f"{chr(65 + i)}:\\"
        if kernel32.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
            continue
        fs_name = ctypes.create_unicode_buffer(64)
        if not kernel32.GetVolumeInformationW(
                root, None, 0, None, None, None, fs_name, len(fs_name)):
            continue
        if fs_name.value.upper() != "NTFS":
            continue
        guid = ctypes.create_unicode_buffer(128)
        if not kernel32.GetVolumeNameForVolumeMountPointW(root, guid, len(guid)):
            continue
        roots.append((guid.value.rstrip("\\"), root[:2]))
    return roots


def _write_initial_config(path):
    volumes = _ntfs_volumes()
    lines = [
        "[Everything]",
        "app_data=0",
        "run_as_admin=0",
        "run_in_background=1",
        "show_tray_icon=0",
        "show_in_taskbar=0",
        "check_for_updates_on_startup=0",
        "ipc=1",
        "auto_include_fixed_volumes=1",
        "auto_include_removable_volumes=0",
    ]
    if volumes:
        ones = ",".join("1" for _ in volumes)
        empty = ",".join(_ini_quote("") for _ in volumes)
        lines += [
            "ntfs_volume_guids=" + ",".join(_ini_quote(v[0]) for v in volumes),
            "ntfs_volume_paths=" + ",".join(_ini_quote(v[1]) for v in volumes),
            "ntfs_volume_roots=" + empty,
            "ntfs_volume_includes=" + ones,
            "ntfs_volume_load_recent_changes=" + ones,
            "ntfs_volume_include_onlys=" + empty,
            "ntfs_volume_monitors=" + ones,
        ]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _ensure_config():
    """创建隔离配置，并在每次冷启动前强制保持无窗口/无托盘。"""
    path = config_path()
    if not path.exists():
        _write_initial_config(path)
        return path

    required = {
        "app_data": "0",
        "run_as_admin": "0",
        "run_in_background": "1",
        "show_tray_icon": "0",
        "show_in_taskbar": "0",
        "check_for_updates_on_startup": "0",
        "ipc": "1",
    }
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        seen = set()
        in_section = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_section = stripped.lower() == "[everything]"
                continue
            if not in_section or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip().lower()
            if key in required:
                lines[i] = f"{key}={required[key]}"
                seen.add(key)
        if not any(line.strip().lower() == "[everything]" for line in lines):
            lines.insert(0, "[Everything]")
        lines += [f"{k}={v}" for k, v in required.items() if k not in seen]
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        # 已有配置即使无法修补，也优先保留，避免破坏已建索引。
        pass
    return path


def _launch():
    """后台拉起内置的 Glance 专属命名实例，不依赖系统版 Everything。"""
    exe = _bundled_exe()
    if not exe:
        return False
    try:
        cfg = _ensure_config()
        subprocess.Popen(
            [exe, "-instance", _INSTANCE_NAME, "-config", str(cfg), "-startup"],
            cwd=str(cfg.parent),
            creationflags=_DETACHED_PROCESS | _CREATE_NO_WINDOW,
            close_fds=True,
        )
        return True
    except Exception:
        return False


def ensure_running(timeout=25.0, poll=0.4):
    """确保后端就绪:没运行就拉起内置 Everything,轮询到索引加载完成。

    返回 True 仅表示数据库已就绪。IPC 已连上但仍在建库时返回 False，避免
    前端过早发起同步查询而卡住。
    设计为在后台线程调用,不阻塞 UI。
    """
    if is_ready():
        return True
    if not is_available():
        _launch()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_ready():
            return True
        time.sleep(poll)
    return is_ready()


def shutdown():
    """只退出 Glance 的命名客户端；不会碰用户自己的 Everything。"""
    exe = _bundled_exe()
    if not exe or not is_available():
        return
    try:
        subprocess.run(
            [exe, "-instance", _INSTANCE_NAME, "-quit"],
            creationflags=_CREATE_NO_WINDOW,
            timeout=5,
            check=False,
        )
    except Exception:
        pass


def _filetime_to_epoch(ft):
    val = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    if val == 0:
        return 0.0
    return val / 10_000_000.0 - 11644473600.0


# --- 查询串构造 -------------------------------------------------------------
def _simple(tok):
    return len(tok) >= 2 and tok.isalnum()


def _scope_prefix(scope_dir):
    if not scope_dir:
        return ""
    p = scope_dir.replace("/", "\\").rstrip("\\")
    return f'"{p}\\" '


def _compose(tokens, scope_dir, fuzzy):
    parts = []
    for t in tokens:
        if fuzzy and _simple(t):
            parts.append("*" + "*".join(t) + "*")
        else:
            parts.append(t)
    return _scope_prefix(scope_dir) + " ".join(parts)


def _run(d, search_str, scan, match_path):
    d.Everything_SetSearchW(search_str)
    d.Everything_SetMatchCase(False)
    d.Everything_SetMatchPath(match_path)
    d.Everything_SetRequestFlags(
        REQUEST_FULL_PATH_AND_FILE_NAME | REQUEST_SIZE | REQUEST_DATE_MODIFIED)
    d.Everything_SetSort(SORT_DATE_MODIFIED_DESCENDING)
    d.Everything_SetMax(scan)
    if not d.Everything_QueryW(True):
        err = d.Everything_GetLastError()
        if err == EVERYTHING_ERROR_IPC:
            raise EverythingError("文件索引服务已断开，正在自动恢复。")
        raise EverythingError(f"文件索引查询失败 (错误码 {err})。")

    n = d.Everything_GetNumResults()
    buf = ctypes.create_unicode_buffer(_BUF_SIZE)
    size = ctypes.c_longlong(0)
    ft = wintypes.FILETIME()
    out = []
    for i in range(n):
        d.Everything_GetResultFullPathNameW(i, buf, _BUF_SIZE)
        full = buf.value
        is_dir = bool(d.Everything_IsFolderResult(i))
        size.value = 0
        ft.dwLowDateTime = 0
        ft.dwHighDateTime = 0
        has_size = bool(d.Everything_GetResultSize(i, ctypes.byref(size)))
        has_mtime = bool(d.Everything_GetResultDateModified(i, ctypes.byref(ft)))
        name = os.path.basename(full)
        out.append({
            "name": name,
            "path": full,
            "dir": os.path.dirname(full),
            "is_dir": is_dir,
            "ext": "" if is_dir else os.path.splitext(name)[1].lstrip(".").lower(),
            "size": -1 if is_dir or not has_size else int(size.value),
            "mtime": _filetime_to_epoch(ft) if has_mtime else 0.0,
        })
    return out


def _score(ql, name_lower, full, now):
    base = fuzz.WRatio(ql, name_lower)
    if name_lower == ql:
        base += 60
    elif name_lower.startswith(ql):
        base += 40
    elif ql in name_lower:
        base += 25
    base += frecency.boost(full, now)
    return base


def search(query, limit=60, scan=800, scope_dir=None):
    """返回按相关性排序的结果列表(name/path/dir/is_dir/ext/size/mtime)。"""
    import time
    query = (query or "").strip()
    if not query:
        return []
    with _query_lock:
        if not is_ready():
            ensure_running(timeout=2.0)
        if not is_ready():
            raise EverythingError("正在准备文件索引，请稍候…")

        d = _load()
        tokens = query.split()
        scoped = bool(scope_dir)
        match_path = scoped or (len(tokens) > 1)

        results = _run(d, _compose(tokens, scope_dir, fuzzy=False), scan, match_path)

        # 子串命中过少 → 子序列回退(容错漏字),合并去重
        if len(results) < _FUZZY_FALLBACK_THRESHOLD and all(_simple(t) for t in tokens):
            more = _run(d, _compose(tokens, scope_dir, fuzzy=True), scan,
                        match_path=True if scoped else False)
            seen = {r["path"].lower() for r in results}
            for r in more:
                if r["path"].lower() not in seen:
                    seen.add(r["path"].lower())
                    results.append(r)

        ql = query.lower()
        now = time.time()
        results.sort(key=lambda r: _score(ql, r["name"].lower(), r["path"], now), reverse=True)
        return results[:limit]
