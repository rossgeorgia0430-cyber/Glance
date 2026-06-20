# -*- coding: utf-8 -*-
"""构建 Glance(PyInstaller onedir)并校验关键件。"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    print(">", " ".join(cmd))
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode:
        sys.exit(r.returncode)


def main():
    run([sys.executable, "gen_icon.py"])
    for d in ("build", "dist"):
        p = os.path.join(HERE, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "Glance.spec"])

    dist = os.path.join(HERE, "dist", "Glance")
    ok = True
    need = [
        "Glance.exe",
        os.path.join("_internal", "glance", "GlanceIndex64.dll"),
        os.path.join("_internal", "glance", "bin", "GlanceIndexer.exe"),
        os.path.join("_internal", "glance", "assets", "index.html"),
        os.path.join("_internal", "glance", "assets", "app.js"),
        os.path.join("_internal", "glance", "assets", "icon.ico"),
        os.path.join("_internal", "THIRD_PARTY_NOTICES.txt"),
    ]
    for n in need:
        exists = os.path.exists(os.path.join(dist, n))
        print(("OK   " if exists else "MISS "), n)
        ok = ok and exists
    # 关键运行时 DLL(名称可能位于子目录)
    allfiles = {f.lower() for _, _, fs in os.walk(dist) for f in fs}
    for dll in ("webview2loader.dll", "python.runtime.dll"):
        found = dll in allfiles
        print(("OK   " if found else "MISS "), dll)
        ok = ok and found

    if not ok:
        print("\n构建校验未通过。")
        sys.exit(2)
    print("\n构建完成:", dist)


if __name__ == "__main__":
    main()
