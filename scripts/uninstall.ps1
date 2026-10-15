<# Glance 卸载脚本：移除应用、专属索引服务、自启和快捷方式。不会触碰用户自己的 Everything。 #>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$IndexData = Join-Path $env:LOCALAPPDATA 'Glance\Indexer'

if (-not (Test-Administrator)) {
  Info '需要管理员权限移除索引服务，正在请求授权…'
  Invoke-Elevated $PSCommandPath ''
}

Stop-GlanceAll
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
