# MechLab installer script（由 IExpress 自解压包调用）
$ErrorActionPreference = "Stop"

$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $env:LOCALAPPDATA "Programs\MechLab"
$zip = Join-Path $src "MechLab.zip"
$exe = Join-Path $target "MechLab.exe"

Write-Host "=============================================="
Write-Host "  MechLab v2.0-dev 安装"
Write-Host "  目标目录: $target"
Write-Host "=============================================="

New-Item -ItemType Directory -Force -Path $target | Out-Null
Write-Host "正在解压（约 1-2 分钟）..."
Expand-Archive -LiteralPath $zip -DestinationPath $target -Force

$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "MechLab.lnk"
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = $target
$lnk.Description = "MechLab v2.0-dev · COMSOL 提交 / 文献报告"
$lnk.IconLocation = "$exe,0"
$lnk.Save()
Write-Host "已创建桌面快捷方式: $lnkPath"

$startMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
$smLnkPath = Join-Path $startMenu "MechLab.lnk"
$smLnk = $ws.CreateShortcut($smLnkPath)
$smLnk.TargetPath = $exe
$smLnk.WorkingDirectory = $target
$smLnk.Description = "MechLab v2.0-dev"
$smLnk.IconLocation = "$exe,0"
$smLnk.Save()
Write-Host "已创建开始菜单快捷方式"

Write-Host "启动 MechLab..."
Start-Process -FilePath $exe -WorkingDirectory $target
Write-Host "安装完成。"
Start-Sleep -Seconds 2
