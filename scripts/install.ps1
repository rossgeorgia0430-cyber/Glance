<#
  Glance 安装脚本。
  - 安装到 %ProgramFiles%\Glance（索引服务以 LocalSystem 运行，程序目录必须防普通用户篡改）
  - 内置并安装 Glance 专属索引服务，不安装/启动桌面版 Everything
  - 创建开始菜单 + 桌面快捷方式
  - 登录自启；常驻进程提供 Ctrl+Alt+S 全局热键
#>
[CmdletBinding()]
param([switch]$NoShortcut, [switch]$NoAutostart, [switch]$Quiet)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$ExeName = 'Glance.exe'
$ServiceDisplayName = 'Glance Index Service'

if (-not (Test-Administrator)) {
  Info '需要管理员权限安装受保护的索引服务，正在请求授权…'
  $extra = @()
  if ($NoShortcut) { $extra += '-NoShortcut' }
  if ($NoAutostart) { $extra += '-NoAutostart' }
  if ($Quiet) { $extra += '-Quiet' }
  Invoke-Elevated $PSCommandPath ($extra -join ' ')
}

# [1/7] 定位安装载荷
$Payload = $null
foreach ($c in @((Join-Path $PSScriptRoot $AppName), (Join-Path $PSScriptRoot "payload\$AppName"), (Join-Path $PSScriptRoot "..\dist\$AppName"))) {
  if (Test-Path (Join-Path $c $ExeName)) { $Payload = (Resolve-Path $c).Path; break }
}
if (-not $Payload) { throw "找不到程序载荷($ExeName)。请在解压后的目录运行本脚本。" }
Info "载荷：$Payload"

# [2/7] 停旧版本和旧索引服务
Info '停止旧版本…'
Stop-GlanceAll
Start-Sleep -Milliseconds 500  # sc delete 是异步的，给服务控制管理器留点时间释放旧服务再重装

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

# [6/7] 快捷方式。不要给 .lnk 设置 Hotkey：Shell 会优先占用该组合键，
# 使常驻进程的 RegisterHotKey 失败；随后每次按键都会冷启动一个新进程再走
# 单实例转发，既慢，也会错过呼出瞬间的 Explorer 前台窗口。
if (-not $NoShortcut) {
  $wsh = New-Object -ComObject WScript.Shell
  $startDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
  $desktopDir = [Environment]::GetFolderPath('Desktop')
  foreach ($dir in @($startDir, $desktopDir)) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    $lnk = Join-Path $dir "$AppName.lnk"
    $sc = $wsh.CreateShortcut($lnk)
    $sc.TargetPath = $Exe
    $sc.WorkingDirectory = $Target
    $sc.IconLocation = "$Exe,0"
    $sc.Description = 'Glance —— 文件搜索'
    # 覆盖同名快捷方式时会保留原有热键，必须显式清空（原因见上）。
    $sc.Hotkey = ''
    $sc.Save()
  }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($wsh)
  Info '已创建快捷方式（全局热键由常驻进程提供）'
}

# [7/7] 登录自启（隐藏常驻）
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if (-not $NoAutostart) {
  Set-ItemProperty -LiteralPath $RunKey -Name $AppName -Value "`"$Exe`" --tray" -Force
  Info '已设置登录自启（后台常驻）'
} else {
  Remove-ItemProperty -LiteralPath $RunKey -Name $AppName -Force -ErrorAction SilentlyContinue
}

Info '安装完成。'
# 本脚本运行在提权环境，直接启动会让 Glance 以管理员权限运行；经 explorer 转发可回落到普通用户权限。
if (-not $Quiet) { Start-Process -FilePath 'explorer.exe' -ArgumentList "`"$Exe`"" }
