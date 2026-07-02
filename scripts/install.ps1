<#
  Glance 安装脚本。
  - 安装到 %ProgramFiles%\Glance（索引服务以 LocalSystem 运行，程序目录必须防普通用户篡改）
  - 内置并安装 Glance 专属索引服务，不安装/启动桌面版 Everything
  - 创建开始菜单 + 桌面快捷方式
  - 登录自启；开始菜单快捷方式同时提供 Ctrl+Alt+S 冷启动
#>
[CmdletBinding()]
param([switch]$NoShortcut, [switch]$NoAutostart, [switch]$Quiet)

$ErrorActionPreference = 'Stop'
$AppName = 'Glance'
$ExeName = 'Glance.exe'
$ServiceName = 'Everything (Glance)'
$ServiceDisplayName = 'Glance Index Service'
$Target = Join-Path $env:ProgramFiles $AppName
$LegacyTarget = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Info($m) { Write-Host "[Glance] $m" }

function Test-Administrator {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($id)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
  Info '需要管理员权限安装受保护的索引服务，正在请求授权…'
  $relaunchArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  if ($NoShortcut) { $relaunchArgs += ' -NoShortcut' }
  if ($NoAutostart) { $relaunchArgs += ' -NoAutostart' }
  if ($Quiet) { $relaunchArgs += ' -Quiet' }
  $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $relaunchArgs -Wait -PassThru
  exit $p.ExitCode
}

function Remove-SafeTree([string]$Path, [string]$AllowedParent) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
  $parent = [IO.Path]::GetFullPath($AllowedParent).TrimEnd('\')
  if (-not $full.StartsWith($parent + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "拒绝删除预期目录之外的路径：$full"
  }
  # 进程退出后文件句柄可能延迟释放，短暂重试再放弃。
  for ($i = 1; $i -le 10; $i++) {
    try { Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop; return }
    catch { if ($i -eq 10) { throw }; Start-Sleep -Milliseconds 300 }
  }
}

function Stop-Indexer([string]$Base) {
  foreach ($name in @('GlanceIndexer.exe', 'Everything.exe')) {
    $indexer = Join-Path $Base "_internal\glance\bin\$name"
    if (Test-Path -LiteralPath $indexer) {
      try { & $indexer -instance Glance -quit | Out-Null } catch {}
      try { & $indexer -instance Glance -uninstall-service | Out-Null } catch {}
    }
  }
  # -quit 是异步 IPC，旧版还可能有残留进程占用安装目录。
  # 仅按可执行文件路径强杀本安装目录内的进程，绝不误伤用户自己的 Everything。
  if (Test-Path -LiteralPath $Base) {
    $full = [IO.Path]::GetFullPath($Base).TrimEnd('\')
    Get-Process -ErrorAction SilentlyContinue | Where-Object {
      try { $_.Path -and $_.Path.StartsWith($full + '\', [StringComparison]::OrdinalIgnoreCase) }
      catch { $false }
    } | ForEach-Object {
      try { $_.Kill(); $_.WaitForExit(3000) | Out-Null } catch {}
    }
  }
}

# [1/7] 定位安装载荷
$Payload = $null
foreach ($c in @((Join-Path $Root $AppName), (Join-Path $Root "payload\$AppName"), (Join-Path $Root "..\dist\$AppName"))) {
  if (Test-Path (Join-Path $c $ExeName)) { $Payload = (Resolve-Path $c).Path; break }
}
if (-not $Payload) { throw "找不到程序载荷($ExeName)。请在解压后的目录运行本脚本。" }
Info "载荷：$Payload"

# [2/7] 停旧版本和旧索引服务
Info '停止旧版本…'
Get-Process $AppName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Stop-Indexer $Target
Stop-Indexer $LegacyTarget
try {
  $svc = Get-Service -Name $ServiceName -ErrorAction Stop
  if ($svc.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue }
  & sc.exe delete $ServiceName | Out-Null
  Start-Sleep -Milliseconds 500
} catch {}

# [3/7] 复制到受保护目录，同时迁移旧的每用户安装
Info "安装到：$Target"
Remove-SafeTree $Target $env:ProgramFiles
Remove-SafeTree $LegacyTarget (Join-Path $env:LOCALAPPDATA 'Programs')
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Path (Join-Path $Payload '*') -Destination $Target -Recurse -Force
$Exe = Join-Path $Target $ExeName
$Indexer = Join-Path $Target '_internal\glance\bin\GlanceIndexer.exe'
if (-not (Test-Path -LiteralPath $Indexer)) { throw "安装载荷缺少索引组件：$Indexer" }

# [4/7] WebView2 运行时
function Test-WebView2 {
  $guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
  foreach ($p in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$guid",
                   "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid",
                   "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$guid")) {
    try { if ((Get-ItemProperty -LiteralPath $p -Name pv -ErrorAction Stop).pv) { return $true } } catch {}
  }
  return $false
}
if (Test-WebView2) { Info 'WebView2：已安装' } else {
  Info 'WebView2：安装中…'
  try {
    $setup = Join-Path $env:TEMP 'MicrosoftEdgeWebview2Setup.exe'
    Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $setup -UseBasicParsing
    Start-Process -FilePath $setup -ArgumentList '/silent', '/install' -Wait -WindowStyle Hidden
  } catch { Info 'WebView2 自动安装失败（Win11 通常已内置），继续。' }
}

# [5/7] Glance 专属索引服务：只提供 NTFS 读取能力，无窗口、无托盘、无桌面应用
Info '安装 Glance 索引服务…'
& $Indexer -instance Glance -install-service | Out-Null
if ($LASTEXITCODE -ne 0) { throw "索引服务安装失败，退出码：$LASTEXITCODE" }
$svc = Get-Service -Name $ServiceName -ErrorAction Stop
Set-Service -Name $ServiceName -DisplayName $ServiceDisplayName `
  -Description '为 Glance 提供本机 NTFS 文件索引访问。' -StartupType Automatic
if ($svc.Status -ne 'Running') { Start-Service -Name $ServiceName }
Info '索引服务：已就绪（后台无界面）'

# [6/7] 快捷方式；Start Menu 的 Hotkey 让 Glance 完全退出后也可冷启动
if (-not $NoShortcut) {
  $wsh = New-Object -ComObject WScript.Shell
  $startDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
  $desktopDir = [Environment]::GetFolderPath('Desktop')
  foreach ($entry in @(@($startDir, $true), @($desktopDir, $false))) {
    $dir = $entry[0]
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    $lnk = Join-Path $dir "$AppName.lnk"
    $sc = $wsh.CreateShortcut($lnk)
    $sc.TargetPath = $Exe
    $sc.WorkingDirectory = $Target
    $sc.IconLocation = "$Exe,0"
    $sc.Description = 'Glance —— 文件搜索'
    if ($entry[1]) { $sc.Hotkey = 'CTRL+ALT+S' }
    $sc.Save()
  }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($wsh)
  Info '已创建快捷方式（Ctrl+Alt+S 支持冷启动）'
}

# [7/7] 登录自启（隐藏常驻）；冷启动快捷键仍可在退出后重新拉起
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if (-not $NoAutostart) {
  Set-ItemProperty -LiteralPath $RunKey -Name $AppName -Value "`"$Exe`" --tray" -Force
  Info '已设置登录自启（后台常驻）'
} else {
  Remove-ItemProperty -LiteralPath $RunKey -Name $AppName -Force -ErrorAction SilentlyContinue
}

Info '安装完成。'
if (-not $Quiet) { Start-Process -FilePath $Exe }
