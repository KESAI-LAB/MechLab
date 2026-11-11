<#
MinerU 后端一键安装（Windows PowerShell）
用法（在项目根目录）：
    powershell -ExecutionPolicy Bypass -File scripts/setup_mineru.ps1

做四件事：
  1. 创建独立 venv：.venvs/mineru（不污染主环境）
  2. 安装 MinerU 2.7.6（走清华源；用 uv 解析依赖）
  3. 下载 pipeline 模型到项目内 .venvs/modelscope
  4. 生成 .venvs/mineru/mineru.json，指向本地模型
#>
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venvs\mineru"
$py = Join-Path $venv "Scripts\python.exe"
$uv = Join-Path $venv "Scripts\uv.exe"
$cache = Join-Path $root ".venvs\modelscope"
$cfg = Join-Path $venv "mineru.json"
$index = "https://pypi.tuna.tsinghua.edu.cn/simple"

Write-Host "[1/4] venv: $venv"
if (-not (Test-Path $py)) {
    python -m venv $venv
}

Write-Host "[2/4] uv + MinerU"
& $py -m pip install -q --no-cache-dir -i $index uv
if (-not (Test-Path $uv)) { throw "uv 安装失败" }
$env:UV_CACHE_DIR = Join-Path $root ".venvs\uvcache"
& $uv pip install --python $py -i $index "mineru[core]==2.7.6"
if ($LASTEXITCODE -ne 0) { throw "MinerU 安装失败" }

Write-Host "[3/4] 下载模型（约 3.5 GB，ModelScope）"
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$env:MODELSCOPE_CACHE = $cache
$env:MINERU_MODEL_SOURCE = "modelscope"
& (Join-Path $venv "Scripts\mineru-models-download.exe") -s modelscope -m pipeline

Write-Host "[4/4] 生成本地配置"
$snapRoot = Join-Path $cache "models\OpenDataLab--PDF-Extract-Kit-1.0\snapshots"
$snap = Get-ChildItem $snapRoot -Directory | Select-Object -First 1
if (-not $snap) { throw "找不到模型目录：$snapRoot" }
$config = [ordered]@{
    "latex-delimiter-config" = @{
        display = @{ left = '$$'; right = '$$' }
        inline  = @{ left = '$'; right = '$' }
    }
    "models-dir"      = @{ pipeline = $snap.FullName; vlm = "" }
    "model-source"    = "auto"
    "device-mode"     = "cpu"
    "config_version"  = "1.3.2"
}
$config | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $cfg

Write-Host "完成：MinerU 已安装。打开程序 → 文献→报告 → PDF 后端选 MinerU。"
Write-Host "首次转换会加载模型（CPU 约 1-3 分钟/几页），之后复用。"
