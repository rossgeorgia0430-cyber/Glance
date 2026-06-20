# -*- coding: utf-8 -*-
"""把 dist/Glance 与安装脚本打包成 release/Glance-Setup(.zip)。"""
import os
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist", "Glance")
REL = os.path.join(HERE, "release")
OUT = os.path.join(REL, "Glance-Setup")
ZIP = os.path.join(REL, "Glance-Setup.zip")
SCRIPTS = ["install.ps1", "uninstall.ps1", "Install-Glance.bat", "Uninstall-Glance.bat"]

README = """Glance —— 极简全局文件搜索

安装:
  双击 Install-Glance.bat,按提示授予管理员权限。
  程序安装到 %ProgramFiles%\\Glance,创建开始菜单/桌面快捷方式,
  安装 Glance 专属索引服务,并设置登录自启(后台常驻托盘)。

使用:
  全局热键 Ctrl+Alt+S 随时呼出(Glance 后台常驻时)。若从托盘完全退出,
  可用 Ctrl+Alt+Shift+S 冷启动 Glance。
  在资源管理器中呼出会自动限定到当前目录。
  ↑↓ 选择 · Enter 打开 · Ctrl+Enter 定位 · Ctrl+C 复制路径 · Esc 隐藏。

依赖:
  文件索引引擎已内置,无需单独安装或开启 Everything,也不会显示其窗口或托盘图标。
  仅需 WebView2 运行时(Win10/11 多数已自带,安装脚本会自动检测补装)。
  首次启动会在后台建立索引;所需时间取决于磁盘数量和文件数。

卸载:
  双击 Uninstall-Glance.bat,按提示授予管理员权限。
"""


def remove_tree_with_retry(path, attempts=20, delay=0.3):
    """Windows 杀毒/索引器可能在刚生成分发目录时短暂占用文件。"""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def write_zip():
    """直接从构建产物写入 ZIP，避免临时分发目录被占用时阻断发布。"""
    tmp_zip = ZIP + ".tmp"
    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(DIST):
            for fn in files:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, DIST)
                z.write(fp, os.path.join("Glance-Setup", "Glance", rel))
        for s in SCRIPTS:
            z.write(os.path.join(HERE, "scripts", s), os.path.join("Glance-Setup", s))
        z.write(os.path.join(HERE, "THIRD_PARTY_NOTICES.txt"),
                os.path.join("Glance-Setup", "THIRD_PARTY_NOTICES.txt"))
        z.writestr(os.path.join("Glance-Setup", "README.txt"), README.encode("utf-8-sig"))
    os.replace(tmp_zip, ZIP)


def write_setup_directory():
    """额外保留解压后的本地分发目录；占用时不影响 ZIP 分发。"""
    try:
        if os.path.isdir(OUT):
            remove_tree_with_retry(OUT)
    except PermissionError:
        print("warning: 旧的 release/Glance-Setup 正被占用，已仅更新 ZIP 分发包。")
        return
    os.makedirs(OUT)
    shutil.copytree(DIST, os.path.join(OUT, "Glance"))
    for s in SCRIPTS:
        shutil.copy(os.path.join(HERE, "scripts", s), os.path.join(OUT, s))
    shutil.copy(os.path.join(HERE, "THIRD_PARTY_NOTICES.txt"),
                os.path.join(OUT, "THIRD_PARTY_NOTICES.txt"))
    with open(os.path.join(OUT, "README.txt"), "w", encoding="utf-8-sig") as f:
        f.write(README)


def main():
    if not os.path.isdir(DIST):
        print("找不到 dist/Glance,请先运行:python build.py")
        sys.exit(1)
    os.makedirs(REL, exist_ok=True)
    write_zip()
    write_setup_directory()
    print("release:", ZIP, round(os.path.getsize(ZIP) / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
