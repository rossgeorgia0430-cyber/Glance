# Glance

Windows 上的极简全局文件搜索工具。按下 `Ctrl+Alt+S` 随时呼出一个搜索框，输入文件名即可看到结果，无需事先打开任何窗口。

## 特性

- 全局热键 `Ctrl+Alt+S` 呼出，即使 Glance 已从托盘完全退出，该热键也能冷启动它。
- 在资源管理器窗口中呼出时，自动把搜索范围限定在当前目录下。
- frecency（frequency + recency）加权：最近或经常打开的文件排序更靠前。
- 跟随系统的亮/暗主题，也可通过标题栏按钮手动切换。
- 内置私有命名的索引后端（`GlanceIndexer.exe` / `GlanceIndex64.dll`），无需安装或运行桌面版 Everything，也不会出现它的窗口或托盘图标。

## 快捷键

| 按键 | 作用 |
| --- | --- |
| `↑` / `↓` | 选择结果 |
| `Enter` | 打开选中项 |
| `Ctrl+Enter` | 在资源管理器中定位 |
| `Ctrl+C` | 复制路径 |
| `Ctrl+Shift+C` | 复制文件名 |
| `Esc` | 隐藏窗口 |

## 开发运行

需要 Windows 10/11，且系统已具备 WebView2 运行时（多数 Win10/11 已内置）。

```powershell
pip install -r requirements.txt
python run_glance.py
```

首次启动会在后台建立文件索引，用时取决于磁盘数量和文件总数。

## 构建与分发

```powershell
python build.py          # PyInstaller onedir 打包，产出 dist/Glance，并校验关键文件是否齐全
python make_release.py   # 把 dist/Glance 和安装脚本打包成 release/Glance-Setup.zip
python deploy.py         # 一键：编译 → 打包分发 → 本机安装（可选自动启动）
```

`deploy.py` 支持 `--quiet`（安装后不自动启动）、`--no-install`（只编译+打包）、`--no-release`（只编译，跳过 zip）。

## 安装 / 卸载

解压 `release/Glance-Setup.zip` 后，双击运行：

- `Install-Glance.bat`：安装到 `%ProgramFiles%\Glance`，安装 Glance 专属索引服务，创建开始菜单/桌面快捷方式，并设置登录自启（后台常驻托盘）。
- `Uninstall-Glance.bat`：移除程序、索引服务、自启项和快捷方式（不会保留或触碰用户自己安装的 Everything）。

两者都需要管理员权限，因为索引服务以 LocalSystem 运行，安装目录必须防止普通用户篡改；脚本会自动弹出 UAC 提权请求。

## 架构简述

```
glance/
  app.py        主程序：单实例控制、窗口生命周期、暴露给前端 JS 的 js_api
  window.py      Win32 原生窗口行为（无边框窗口的缩放/拖动/圆角/暗色标题栏）
  everything.py  索引后端封装，通过 ctypes 走本地 IPC 查询文件
  focus.py       呼出瞬间抓取前台资源管理器窗口所在目录
  frecency.py    打开历史加权排序（最近/常用文件靠前）
  hotkey.py      全局热键注册与消息循环
  tray.py        系统托盘图标与菜单
  settings.py    用户偏好持久化（%LOCALAPPDATA%\Glance\settings.json）
```

## 已知限制

安装脚本在提权后运行，写入的登录自启注册表项（`HKCU`）和快捷方式都落在**提权账户**的用户配置（HKCU/APPDATA）下。如果你日常登录账户和用于安装的管理员账户不是同一个，自启项和快捷方式可能出现在管理员账户而不是日常账户下，需要手动处理（例如在日常账户下重新创建快捷方式，或手动写入日常账户的自启注册表项）。
