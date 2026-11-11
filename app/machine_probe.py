"""新机接入：采集脚本生成 + 输出解析 + 表单建议。

采集脚本是一段 Windows PowerShell，在**新机器**上运行后输出一段带标记的 JSON；
界面把这段输出粘贴回来，解析后自动填入主机、COMSOL 路径、核数、可写目录等。
"""
from __future__ import annotations

import json

BEGIN = "=====MECHLAB-MACHINE-PROBE-BEGIN====="
END = "=====MECHLAB-MACHINE-PROBE-END====="

# 注意：脚本保持纯 ASCII（避免复制到不同代码页的 PowerShell 时乱码）。
PROBE_SCRIPT = r"""# ===== MechLab machine probe (Windows PowerShell) =====
# Run this on the NEW machine. It prints a JSON block between markers.
$ErrorActionPreference = 'SilentlyContinue'

function Test-WritableDir([string]$p) {
  try {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
    $f = Join-Path $p '.mechlab_probe'
    Set-Content -Path $f -Value 'ok' -Encoding ascii
    if (Test-Path $f) { Remove-Item $f -Force; return $true }
  } catch { }
  return $false
}

function Get-ComsolList {
  $roots = @('C:\Program Files\COMSOL','C:\Program Files (x86)\COMSOL',
             'D:\COMSOL64','D:\Program Files\COMSOL','E:\COMSOL64','F:\Program Files\COMSOL')
  $found = @()
  foreach ($r in $roots) {
    if (Test-Path $r) {
      foreach ($sub in (Get-ChildItem $r -Directory)) {
        $b = Join-Path $sub.FullName 'Multiphysics\bin\win64\comsolbatch.exe'
        if (Test-Path $b) {
          $found += [pscustomobject]@{
            batch   = $b
            compile = (Join-Path (Split-Path $b) 'comsolcompile.exe')
            version = $sub.Name
          }
        }
      }
    }
  }
  return $found
}

$os = 'unknown'
try { $os = (Get-CimInstance Win32_OperatingSystem).Caption } catch { }
$cpu = @(Get-CimInstance Win32_Processor)
$cs  = @(Get-CimInstance Win32_ComputerSystem)
$cpuName = ''
$cpuCores = 0
$cpuLogical = 0
if ($cpu.Count -gt 0) {
  $cpuName = $cpu[0].Name
  foreach ($c in $cpu) { $cpuCores += [int]$c.NumberOfCores; $cpuLogical += [int]$c.NumberOfLogicalProcessors }
}
$ramGb = 0
if ($cs.Count -gt 0) { $ramGb = [math]::Round($cs[0].TotalPhysicalMemory / 1GB, 1) }

$ipv4 = @()
try {
  $ipv4 = @(Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress)
} catch { }

$sshdStatus = 'not_installed'
try { $sshdStatus = (Get-Service sshd -ErrorAction Stop).Status.ToString() } catch { }

$port22 = $false
try { $port22 = (@(Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction Stop).Count -gt 0) } catch { }

$sshCap = 'unknown'
try {
  $cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
  if ($cap) { $sshCap = $cap.State }
} catch { }

$comsol = @(Get-ComsolList)

$writable = @()
foreach ($cand in @('D:\model','D:\COMSOL_runs','C:\Users\Public\mechlab','C:\temp')) {
  if (Test-WritableDir $cand) { $writable += $cand }
}

$drives = @()
try {
  foreach ($d in (Get-PSDrive -PSProvider FileSystem)) {
    $drives += [pscustomobject]@{ name = $d.Name; free_gb = [math]::Round($d.Free / 1GB, 1) }
  }
} catch { }

$authKeys = @()
foreach ($p in @((Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'),
                 (Join-Path $env:USERPROFILE '.ssh\authorized_keys'))) {
  if (Test-Path $p) { $authKeys += $p }
}

$admin = $false
try {
  $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }

$result = [ordered]@{
  hostname               = $env:COMPUTERNAME
  user                   = (whoami)
  username               = $env:USERNAME
  os                     = $os
  powershell             = $PSVersionTable.PSVersion.ToString()
  admin                  = $admin
  cpu_name               = $cpuName
  cpu_cores              = $cpuCores
  cpu_logical            = $cpuLogical
  ram_gb                 = $ramGb
  ipv4                   = $ipv4
  sshd                   = $sshdStatus
  ssh_capability         = $sshCap
  ssh_port_22_listening  = $port22
  comsol                 = $comsol
  writable_dirs          = $writable
  drives                 = $drives
  authorized_keys        = $authKeys
  timestamp              = (Get-Date).ToString('s')
}

Write-Output '=====MECHLAB-MACHINE-PROBE-BEGIN====='
$result | ConvertTo-Json -Depth 6
Write-Output '=====MECHLAB-MACHINE-PROBE-END====='
"""


def _as_list(v) -> list:
    """PowerShell ConvertTo-Json 对单元素数组可能输出对象，这里统一成 list。"""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def parse_probe_text(text: str) -> dict:
    """从粘贴的整段输出里取出 JSON。"""
    if not text or BEGIN not in text or END not in text:
        raise ValueError("没找到采集标记：请确认粘贴的是完整输出（包含 BEGIN/END 两行）")
    body = text.split(BEGIN, 1)[1].split(END, 1)[0].strip()
    body = body.lstrip("\ufeff")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("采集输出的格式不对（应为 JSON 对象）")
    return data


def suggest_config(data: dict) -> dict:
    """把采集结果转成表单建议值。"""
    user_raw = str(data.get("user") or "").strip()
    user = user_raw.split("\\")[-1] if user_raw else str(data.get("username") or "")
    ips = [str(x) for x in _as_list(data.get("ipv4"))]
    hostname = str(data.get("hostname") or "")
    host = f"{user}@{ips[0]}" if ips else f"{user}@{hostname}"

    comsol = _as_list(data.get("comsol"))
    first = comsol[0] if comsol else {}
    batch = str(first.get("batch") or "")
    compile_ = str(first.get("compile") or "")

    writable = [str(x) for x in _as_list(data.get("writable_dirs"))]
    base_win = str(writable[0]) if writable else "D:\\model"
    base_unix = base_win.replace("\\", "/")

    cores = int(data.get("cpu_logical") or data.get("cpu_cores") or 8)
    return {
        "label": f"新机 {hostname}" if hostname else "新机",
        "host": host,
        "port": 22,
        "base_win": base_win,
        "base_unix": base_unix,
        "batch": batch,
        "compile": compile_,
        "cores": cores,
    }


def summary_lines(data: dict) -> list[str]:
    """给界面显示的一行行摘要。"""
    comsol = _as_list(data.get("comsol"))
    writable = [str(x) for x in _as_list(data.get("writable_dirs"))]
    ips = ", ".join(str(x) for x in _as_list(data.get("ipv4"))) or "（未采集到）"
    lines = [
        f"主机：{data.get('hostname', '?')}    用户：{data.get('user', '?')}",
        f"系统：{data.get('os', '?')}    PowerShell：{data.get('powershell', '?')}",
        f"CPU：{data.get('cpu_name', '?')}  物理核 {data.get('cpu_cores', '?')} / 逻辑核 {data.get('cpu_logical', '?')}",
        f"内存：{data.get('ram_gb', '?')} GB    IPv4：{ips}",
        f"OpenSSH：sshd={data.get('sshd', '?')}   能力={data.get('ssh_capability', '?')}   "
        f"22 端口监听={data.get('ssh_port_22_listening', '?')}",
        f"COMSOL：找到 {len(comsol)} 个安装" + (f"（{comsol[0].get('batch')}）" if comsol else ""),
        f"可写目录：{', '.join(writable) if writable else '（未找到，请手动填写）'}",
    ]
    if data.get("sshd") != "Running" or not data.get("ssh_port_22_listening"):
        lines.append("⚠ 新机 SSH 未运行：先在向导页点「生成 SSH 启动脚本」，用管理员 PowerShell 运行。")
    return lines


SSH_ENABLE_TEMPLATE = r"""# ===== MechLab: enable OpenSSH Server on this Windows machine =====
# 用「管理员 PowerShell」运行：右键 PowerShell -> 以管理员身份运行 -> 粘贴整段。
$ErrorActionPreference = 'Continue'
$port = 22
$pub = '__PUBKEY__'

Write-Host '[1/5] Check OpenSSH Server capability ...'
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if (-not $cap -or $cap.State -ne 'Installed') {
  Write-Host '      installing OpenSSH.Server (needs network / Windows Update) ...'
  Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
} else {
  Write-Host '      already installed'
}

Write-Host '[2/5] Configure and start sshd ...'
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
Write-Host ('      sshd = ' + (Get-Service sshd).Status)

Write-Host '[3/5] Firewall rule for TCP 22 ...'
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
    -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort $port | Out-Null
}
Write-Host '      firewall ok'

Write-Host '[4/5] Install public key ...'
if ($pub -and $pub -ne '__PUBKEY__') {
  $isAdmin = $false
  try {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
      [Security.Principal.WindowsBuiltInRole]::Administrator)
  } catch { }
  $userKeys = Join-Path $env:USERPROFILE '.ssh\authorized_keys'
  New-Item -ItemType Directory -Force -Path (Split-Path $userKeys) | Out-Null
  if (-not (Test-Path $userKeys)) { New-Item -ItemType File -Path $userKeys | Out-Null }
  if (-not ((Get-Content $userKeys -ErrorAction SilentlyContinue) -contains $pub)) {
    Add-Content -Path $userKeys -Value $pub -Encoding ascii
  }
  if ($isAdmin) {
    $admKeys = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
    New-Item -ItemType Directory -Force -Path (Split-Path $admKeys) | Out-Null
    if (-not (Test-Path $admKeys)) { New-Item -ItemType File -Path $admKeys | Out-Null }
    if (-not ((Get-Content $admKeys -ErrorAction SilentlyContinue) -contains $pub)) {
      Add-Content -Path $admKeys -Value $pub -Encoding ascii
    }
    icacls $admKeys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
  }
  Write-Host '      public key installed'
} else {
  Write-Host '      no public key provided (skipped) - paste one in MechLab and regenerate'
}

Write-Host '[5/5] Done.'
Write-Host ('SSH_READY host=' + $env:COMPUTERNAME + ' port=' + $port)
Write-Host 'Now go back to MechLab and click "Test connection".'
"""


def build_ssh_enable_script(public_key: str = "") -> str:
    """生成"在新机上开启 SSH"的管理员脚本；public_key 可选。"""
    key = (public_key or "").strip().replace("'", "")
    return SSH_ENABLE_TEMPLATE.replace("__PUBKEY__", key if key else "__PUBKEY__")

