# -*- coding: utf-8 -*-
"""把 dist/Glance 与安装脚本打包成 release/Glance-Setup(.zip)。"""
import os
import shutil
import sys
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
  全局热键 Ctrl+Alt+S 随时呼出;即使从托盘完全退出,该热键也会冷启动 Glance。
  在资源管理器中呼出会自动限定到当前目录。
  ↑↓ 选择 · Enter 打开 · Ctrl+Enter 定位 · Ctrl+C 复制路径 · Esc 隐藏。

依赖:
  文件索引引擎已内置,无需单独安装或开启 Everything,也不会显示其窗口或托盘图标。
  仅需 WebView2 运行时(Win10/11 多数已自带,安装脚本会自动检测补装)。
  首次启动会在后台建立索引;所需时间取决于磁盘数量和文件数。

卸载:
  双击 Uninstall-Glance.bat,按提示授予管理员权限。
"""


def main():
    if not os.path.isdir(DIST):
        print("找不到 dist/Glance,请先运行:python build.py")
        sys.exit(1)
    os.makedirs(REL, exist_ok=True)
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    shutil.copytree(DIST, os.path.join(OUT, "Glance"))
    for s in SCRIPTS:
        shutil.copy(os.path.join(HERE, "scripts", s), os.path.join(OUT, s))
    shutil.copy(os.path.join(HERE, "THIRD_PARTY_NOTICES.txt"),
                os.path.join(OUT, "THIRD_PARTY_NOTICES.txt"))
    with open(os.path.join(OUT, "README.txt"), "w", encoding="utf-8-sig") as f:
        f.write(README)

    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(OUT):
            for fn in files:
                fp = os.path.join(root, fn)
                z.write(fp, os.path.relpath(fp, REL))
    print("release:", ZIP, round(os.path.getsize(ZIP) / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
