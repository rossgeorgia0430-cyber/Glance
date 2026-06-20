# -*- coding: utf-8 -*-
"""一键流水线:编译 → 打包分发 → 本机安装(可选直接启动)。

把"改完代码后要敲的三条命令"合成一条,提高分发/自测效率:
    python deploy.py            # build → make_release → 本机安装并启动
    python deploy.py --quiet    # 安装后不自动启动
    python deploy.py --no-install   # 只 build + 打包,不装本机
    python deploy.py --no-release   # 只 build(+装),跳过 zip 分发包

安装走 scripts/install.ps1,它会自动从 ..\\dist\\Glance 取载荷,
停掉旧实例、复制到 %ProgramFiles%\\Glance、安装专属索引服务、建快捷方式 + 登录自启。
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def step(title):
    print("\n" + "=" * 60)
    print("  " + title)
    print("=" * 60)


def run_py(script):
    r = subprocess.run([sys.executable, os.path.join(HERE, script)], cwd=HERE)
    if r.returncode:
        print(f"[deploy] {script} 失败(退出码 {r.returncode})")
        sys.exit(r.returncode)


def run_install(quiet):
    ps1 = os.path.join(HERE, "scripts", "install.ps1")
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1]
    if quiet:
        args.append("-Quiet")
    r = subprocess.run(args, cwd=os.path.join(HERE, "scripts"))
    if r.returncode:
        print(f"[deploy] 安装失败(退出码 {r.returncode})")
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser(description="Glance 一键编译+打包+安装")
    ap.add_argument("--no-install", action="store_true", help="只编译/打包,不装本机")
    ap.add_argument("--no-release", action="store_true", help="跳过 zip 分发包")
    ap.add_argument("--quiet", action="store_true", help="安装后不自动启动")
    a = ap.parse_args()

    t0 = time.time()

    step("[1] 编译 (PyInstaller onedir)")
    run_py("build.py")

    if not a.no_release:
        step("[2] 打包分发 (release/Glance-Setup.zip)")
        run_py("make_release.py")
    else:
        print("\n[deploy] 跳过分发包 (--no-release)")

    if not a.no_install:
        step("[3] 本机安装" + ("" if a.quiet else " + 启动"))
        run_install(a.quiet)
    else:
        print("\n[deploy] 跳过本机安装 (--no-install)")

    print(f"\n[deploy] 完成,用时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
