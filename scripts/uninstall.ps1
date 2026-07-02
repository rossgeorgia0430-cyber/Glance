<# Glance 卸载脚本：移除应用、专属索引服务、自启和快捷方式。不会触碰用户自己的 Everything。 #>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$AppName = 'Glance'
$ServiceName = 'Everything (Glance)'
$Target = Join-Path $env:ProgramFiles $AppName
$LegacyTarget = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$IndexData = Join-Path $env:LOCALAPPDATA 'Glance\Indexer'

function Info($m) { Write-Host "[Glance] $m" }

function Test-Administrator {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($id)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
  Info '需要管理员权限移除索引服务，正在请求授权…'
  $relaunchArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
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

Get-Process $AppName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

foreach ($base in @($Target, $LegacyTarget)) {
  foreach ($name in @('GlanceIndexer.exe', 'Everything.exe')) {
    $indexer = Join-Path $base "_internal\glance\bin\$name"
    if (Test-Path -LiteralPath $indexer) {
      try { & $indexer -instance Glance -quit | Out-Null } catch {}
      try { & $indexer -instance Glance -uninstall-service | Out-Null } catch {}
    }
  }
  # -quit 是异步 IPC，仅按路径强杀本安装目录内的残留进程，绝不误伤用户自己的 Everything。
  if (Test-Path -LiteralPath $base) {
    $full = [IO.Path]::GetFullPath($base).TrimEnd('\')
    Get-Process -ErrorAction SilentlyContinue | Where-Object {
      try { $_.Path -and $_.Path.StartsWith($full + '\', [StringComparison]::OrdinalIgnoreCase) }
      catch { $false }
    } | ForEach-Object {
      try { $_.Kill(); $_.WaitForExit(3000) | Out-Null } catch {}
    }
  }
}

try {
  $svc = Get-Service -Name $ServiceName -ErrorAction Stop
  if ($svc.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue }
  & sc.exe delete $ServiceName | Out-Null
} catch {}
Info '已移除 Glance 索引服务'

Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
  -Name $AppName -Force -ErrorAction SilentlyContinue

foreach ($lnk in @((Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"),
                   (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"))) {
  if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force }
}

Remove-SafeTree $Target $env:ProgramFiles
Remove-SafeTree $LegacyTarget (Join-Path $env:LOCALAPPDATA 'Programs')
Remove-SafeTree $IndexData (Join-Path $env:LOCALAPPDATA 'Glance')

Info '卸载完成。用户偏好与使用历史已保留。'
