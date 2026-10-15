# -*- coding: utf-8 -*-
"""
Everything 后端封装(ctypes 走本地 IPC)。

增强:
- scope_dir:把搜索限定在某目录下。
- 分级容错模糊:子串-AND 优先;命中过少时回退子序列通配,合并去重。
- frecency:把最近/常打开的文件加权置前。
"""
import ctypes
import logging
import os
import subprocess
import threading
import time
from ctypes import wintypes

from rapidfuzz import fuzz

from . import frecency, settings

log = logging.getLogger(__name__)

# --- Everything SDK 常量 ---------------------------------------------------
REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
REQUEST_SIZE = 0x00000010
REQUEST_DATE_MODIFIED = 0x00000040
SORT_DATE_MODIFIED_DESCENDING = 14
EVERYTHING_ERROR_IPC = 2

_HERE = os.path.dirname(os.path.abspath(__file__))
_DLL_PATH = os.path.join(_HERE, "GlanceIndex64.dll")
_INDEXER_EXE = os.path.join(_HERE, "bin", "GlanceIndexer.exe")
_INSTANCE_NAME = "Glance"
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008

_BUF_SIZE = 32768
_SCAN_LIMIT = 800                # 每次向索引取的候选数,再在本地重排取前 limit 条
_FUZZY_FALLBACK_THRESHOLD = 25   # 子串命中少于此值才启用子序列回退
_DB_SAVE_INTERVAL = 3600.0       # 索引库落盘超过此秒数就在空闲时再存一次

# 每次冷启动前强制写回:专属实例必须无窗口、无托盘、开 IPC、不以管理员运行。
# 限定目录搜索依赖 match_path_when_search_contains_path_separator:
# 范围项带路径分隔符,会单独按全路径匹配,其余关键词仍只匹配文件名。
_FORCED_CONFIG = {
    "app_data": "0",
    "run_as_admin": "0",
    "run_in_background": "1",
    "show_tray_icon": "0",
    "show_in_taskbar": "0",
    "check_for_updates_on_startup": "0",
    "ipc": "1",
    "match_path_when_search_contains_path_separator": "1",
}

# SDK 的查询参数和结果都是进程级全局状态,整次查询必须串行。
_query_lock = threading.Lock()


class EverythingError(RuntimeError):
    pass


class EverythingDisconnectedError(EverythingError):
    """查询过程中索引 IPC 断开，可在后端恢复后安全重试。"""


class SearchSuperseded(Exception):
    """已有更新的查询在等待,本次放弃以免拖慢它。"""


_dll = None


def _load():
    global _dll
    if _dll is not None:
        return _dll
    if not os.path.exists(_DLL_PATH):
        raise EverythingError(f"找不到索引组件:{_DLL_PATH}")
    d = ctypes.WinDLL(_DLL_PATH)
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
    d.Everything_SaveDB.restype = wintypes.BOOL
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
    except (EverythingError, OSError):
        return False


def is_ready():
    """IPC 通且索引数据库已加载完成(可返回完整结果)。"""
    return is_available() and bool(_load().Everything_IsDBLoaded())


# --- 内置索引进程:免装、免手动开启 ------------------------------------------
def _index_dir():
    """专属配置与索引库所在目录;卸载脚本按同一位置清理。"""
    folder = settings.data_dir() / "Indexer"
    folder.mkdir(exist_ok=True)
    return folder


def _db_path():
    return _index_dir() / "Everything.db"


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
    lines = ["[Everything]"]
    lines += [f"{k}={v}" for k, v in _FORCED_CONFIG.items()]
    lines += ["auto_include_fixed_volumes=1", "auto_include_removable_volumes=0"]
    volumes = _ntfs_volumes()
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
    settings.atomic_write_text(path, "\n".join(lines) + "\n")


def _apply_forced_config(lines):
    """在 [Everything] 段里改写或补齐 _FORCED_CONFIG 各项,其余内容原样保留。"""
    lines = list(lines)
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
        if key in _FORCED_CONFIG:
            lines[i] = f"{key}={_FORCED_CONFIG[key]}"
            seen.add(key)
    if not any(line.strip().lower() == "[everything]" for line in lines):
        lines.insert(0, "[Everything]")
    lines += [f"{k}={v}" for k, v in _FORCED_CONFIG.items() if k not in seen]
    return lines


def _ensure_config():
    path = _index_dir() / "Everything.ini"
    if not path.exists():
        _write_initial_config(path)
        return path
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        settings.atomic_write_text(path, "\n".join(_apply_forced_config(lines)) + "\n")
    except (OSError, UnicodeError):
        # 修补失败就沿用原配置启动:重写整份文件会丢掉已建索引的卷设置。
        log.warning("修补索引配置失败,沿用原配置", exc_info=True)
    return path


def _launch():
    """后台拉起内置的 Glance 专属命名实例，不依赖系统版 Everything。"""
    try:
        cfg = _ensure_config()
        # 必须显式指定索引库:默认写在 exe 旁(Program Files,普通用户无写权限),
        # 退出时存不下,每次启动都要全量重建(千万级文件需数分钟);存下后数秒即可就绪。
        subprocess.Popen(
            [_INDEXER_EXE, "-instance", _INSTANCE_NAME, "-config", str(cfg),
             "-db", str(_db_path()), "-startup"],
            cwd=str(cfg.parent),
            creationflags=_DETACHED_PROCESS | _CREATE_NO_WINDOW,
            close_fds=True,
        )
    except OSError:
        log.warning("拉起索引进程失败", exc_info=True)


def ensure_running(timeout, poll=0.4):
    """确保后端就绪:没运行就拉起内置索引进程,轮询到数据库加载完成。

    返回 True 仅表示数据库已就绪。IPC 已连上但仍在建库时返回 False，避免
    前端过早发起同步查询而卡住。会阻塞,只在后台线程调用。
    """
    if is_ready():
        return True
    if not is_available():
        _launch()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_ready():
            return True
        time.sleep(poll)
    return is_ready()


def shutdown():
    """只退出 Glance 的命名客户端；不会碰用户自己的 Everything。"""
    if not is_available():
        return
    try:
        subprocess.run(
            [_INDEXER_EXE, "-instance", _INSTANCE_NAME, "-quit"],
            creationflags=_CREATE_NO_WINDOW,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.warning("退出索引进程失败", exc_info=True)


_next_db_save = 0.0  # time.monotonic() 时刻


def save_db_if_due():
    """索引库上次落盘超过 _DB_SAVE_INTERVAL 就让索引进程保存一次。

    Everything 只在正常退出时存库;索引进程崩溃或被强杀后,库若比 NTFS 变更日志
    能回放的范围还旧,就得整卷重扫。落盘期间索引进程会阻塞数秒,调用方应在空闲时调。
    """
    global _next_db_save
    now = time.monotonic()
    if now < _next_db_save:
        return
    try:
        age = time.time() - _db_path().stat().st_mtime
    except FileNotFoundError:
        age = _DB_SAVE_INTERVAL
    if age < _DB_SAVE_INTERVAL:
        _next_db_save = now + _DB_SAVE_INTERVAL - age
        return
    # 失败也等满一个周期再试:每次尝试都会让索引进程阻塞数秒
    _next_db_save = now + _DB_SAVE_INTERVAL
    with _query_lock:
        d = _load()
        if not d.Everything_SaveDB():
            log.warning("保存索引库失败 (错误码 %d)", d.Everything_GetLastError())


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


def _run(d, search_str, match_path):
    d.Everything_SetSearchW(search_str)
    d.Everything_SetMatchCase(False)
    d.Everything_SetMatchPath(match_path)
    d.Everything_SetRequestFlags(
        REQUEST_FULL_PATH_AND_FILE_NAME | REQUEST_SIZE | REQUEST_DATE_MODIFIED)
    d.Everything_SetSort(SORT_DATE_MODIFIED_DESCENDING)
    d.Everything_SetMax(_SCAN_LIMIT)
    if not d.Everything_QueryW(True):
        err = d.Everything_GetLastError()
        if err == EVERYTHING_ERROR_IPC:
            raise EverythingDisconnectedError("文件索引服务已断开，正在自动恢复。")
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


def _collect(d, tokens, scope_dir, is_stale):
    # 多个关键词时按全路径匹配,可用"目录名 文件名"定位。单个关键词只匹配文件名:
    # 范围项自带路径分隔符,索引会单独按全路径匹配它;若整体开 match_path,
    # 关键词会命中范围目录本身,把范围内所有文件都当成结果。
    match_path = len(tokens) > 1
    results = _run(d, _compose(tokens, scope_dir, fuzzy=False), match_path=match_path)
    if len(results) >= _FUZZY_FALLBACK_THRESHOLD or not all(_simple(t) for t in tokens):
        return results
    # 子串命中过少 → 子序列回退(容错漏字),合并去重。回退查询代价更高,先确认没被取代。
    if is_stale():
        raise SearchSuperseded()
    seen = {r["path"].lower() for r in results}
    for r in _run(d, _compose(tokens, scope_dir, fuzzy=True), match_path=False):
        key = r["path"].lower()
        if key not in seen:
            seen.add(key)
            results.append(r)
    return results


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


def search(query, limit=60, scope_dir=None, is_stale=lambda: False):
    """返回按相关性排序的结果列表(name/path/dir/is_dir/ext/size/mtime)。

    单次查询要扫全部索引(数百毫秒);is_stale() 为真时抛 SearchSuperseded,
    让排队中的旧查询直接让位给最新一次。
    """
    query = (query or "").strip()
    if not query:
        return []
    tokens = query.split()
    with _query_lock:
        if is_stale():
            raise SearchSuperseded()
        if not is_ready():
            ensure_running(timeout=2.0)
        if not is_ready():
            raise EverythingError("正在准备文件索引，请稍候…")

        d = _load()
        # 索引进程可能恰好在查询期间重启。IPC 断开可恢复:就地拉起后重试整次查询一次,
        # 否则这次按键就没有任何结果,也不会有后续动作重放。
        try:
            results = _collect(d, tokens, scope_dir, is_stale)
        except EverythingDisconnectedError:
            if not ensure_running(timeout=3.0, poll=0.15):
                raise
            results = _collect(d, tokens, scope_dir, is_stale)

    ql = query.lower()
    now = time.time()
    results.sort(key=lambda r: _score(ql, r["name"].lower(), r["path"], now), reverse=True)
    return results[:limit]
