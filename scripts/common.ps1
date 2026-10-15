<# install.ps1 / uninstall.ps1 共用的常量与函数,由两者 dot-source 引入。 #>

$AppName = 'Glance'
$ServiceName = 'Everything (Glance)'
$Target = Join-Path $env:ProgramFiles $AppName
# 早期版本按用户安装在这里、索引组件名为 Everything.exe;安装和卸载都顺带清理。
# 确认不再有机器装在此处后,连同 Stop-GlanceIndexer 里的 Everything.exe 一起删掉。
$LegacyTarget = Join-Path $env:LOCALAPPDATA "Programs\$AppName"

function Info($m) { Write-Host "[Glance] $m" }

function Test-Administrator {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($id)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Elevated([string]$ScriptPath, [string]$ExtraArgs) {
  # 只等提权进程本身:PS 5.1 的 Start-Process -Wait 会等整棵进程树,
  # 安装脚本最后拉起的 Glance.exe 会让外层一直挂到用户退出应用。
  $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" $ExtraArgs"
  $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList -PassThru
  $p.WaitForExit()
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

function Stop-GlanceIndexer([string]$Base) {
  foreach ($name in @('GlanceIndexer.exe', 'Everything.exe')) {
    $indexer = Join-Path $Base "_internal\glance\bin\$name"
    if (Test-Path -LiteralPath $indexer) {
      try { & $indexer -instance Glance -quit | Out-Null } catch {}
      try { & $indexer -instance Glance -uninstall-service | Out-Null } catch {}
    }
  }
  # -quit 是异步 IPC：先等进程自己退出（退出时才把索引库写盘，强杀会丢库，下次要全量重建），
  # 超时仍残留的再强杀，免得占用安装目录。
  # 只按可执行文件路径处理本安装目录内的进程，绝不误伤用户自己的 Everything。
  if (Test-Path -LiteralPath $Base) {
    $full = [IO.Path]::GetFullPath($Base).TrimEnd('\')
    Get-Process -ErrorAction SilentlyContinue | Where-Object {
      try { $_.Path -and $_.Path.StartsWith($full + '\', [StringComparison]::OrdinalIgnoreCase) }
      catch { $false }
    } | ForEach-Object {
      if (-not $_.WaitForExit(15000)) {
        try { $_.Kill(); $_.WaitForExit(3000) | Out-Null } catch {}
      }
    }
  }
}

function Remove-IndexService {
  $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  if (-not $svc) { return }
  if ($svc.Status -ne 'Stopped') { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue }
  & sc.exe delete $ServiceName | Out-Null
}

function Stop-GlanceAll {
  Get-Process $AppName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Stop-GlanceIndexer $Target
  Stop-GlanceIndexer $LegacyTarget
  Remove-IndexService
}
