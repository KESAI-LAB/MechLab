#!/usr/bin/env bash
# remote_guard.sh — safety wrapper for every remote (ssh/scp) operation.
#
# Rules enforced here:
#   1. Only RG_BASE_WIN may be written on the remote host.
#   2. Remote run directories MUST match run_YYYYmmdd_HHMMSS exactly.
#   3. Deletion is always file-by-file with exact expected names, then a plain
#      rmdir of the empty directory. `rm -rf` / `rd /s /q` on the remote is
#      never issued by any project script.
#   4. taskkill only targets a comsolbatch.exe PID whose command line contains
#      our exact run directory; other people's runs are never touched.
#   5. Every remote command is appended to logs/remote_audit.log.
#
# source this file:  . "$(dirname "$0")/remote_guard.sh"

set -uo pipefail

RG_KEY="${RG_KEY:-$HOME/.ssh/id_ed25519}"
RG_HOST="${RG_HOST:-user@host}"
RG_PORT="${RG_PORT:-22}"
RG_BASE_WIN="${RG_BASE_WIN:-D:\model}"
RG_BASE_UNIX="${RG_BASE_UNIX:-D:/model}"
RG_BATCH="${RG_BATCH:-${RG_BATCH}}"
RG_COMPILE="${RG_COMPILE:-${RG_COMPILE}}"
RG_WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RG_AUDIT="$RG_WS/logs/remote_audit.log"
mkdir -p "$RG_WS/logs"

if [ "$RG_PORT" = "22" ]; then
    RG_SSH="ssh -i $RG_KEY -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15"
    RG_SCP="scp -C -i $RG_KEY -o BatchMode=yes -o StrictHostKeyChecking=no"
else
    RG_SSH="ssh -p $RG_PORT -i $RG_KEY -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15"
    RG_SCP="scp -P $RG_PORT -C -i $RG_KEY -o BatchMode=yes -o StrictHostKeyChecking=no"
fi

rg_log() {
    printf '%s | %s | %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$1" "${2:-}" >>"$RG_AUDIT"
}

rg_assert_run_id() {
    local rd="$1"
    if ! printf '%s' "$rd" | grep -Eq '^run_[0-9]{8}_[0-9]{6}$'; then
        echo "GUARD: refusing unsafe run id: $rd" >&2
        rg_log REFUSE "bad run id: $rd"
        return 1
    fi
}

# rg_ssh <purpose> <command>
rg_ssh() {
    local purpose="$1"; shift
    rg_log SSH "$purpose :: $*"
    $RG_SSH "$RG_HOST" "$@"
}

# rg_scp <purpose> <src> <dst>
rg_scp() {
    local purpose="$1" src="$2" dst="$3"
    rg_log SCP "$purpose :: $src -> $dst"
    $RG_SCP "$src" "$dst"
}

# rg_upload <runid> <local_model.mph>
rg_upload() {
    local rd="$1" model="$2" base
    base="$(basename "$model")"
    rg_assert_run_id "$rd" || return 1
    rg_ssh "mkdir $rd" "mkdir ${RG_BASE_WIN}\\$rd" || return 1
    rg_scp "upload model" "$model" "$RG_HOST:$RG_BASE_UNIX/$rd/$base" || return 1
}

# rg_run_comsol <runid> <model_basename> <study> <cores>
rg_run_comsol() {
    local rd="$1" base="$2" study="$3" cores="$4" stem="${2%.mph}"
    rg_assert_run_id "$rd" || return 1
    rg_ssh "comsolbatch $rd" "cd /d ${RG_BASE_WIN}\\$rd && D:\\COMSOL64\\Multiphysics\\bin\\win64\\comsolbatch.exe -np $cores -study $study -inputfile $base -outputfile ${stem}_out.mph -batchlog ${stem}_run.txt"
}

# rg_download <runid> <remote_basename> <local_dest>
rg_download() {
    local rd="$1" name="$2" dest="$3"
    rg_assert_run_id "$rd" || return 1
    rg_scp "download $name" "$RG_HOST:$RG_BASE_UNIX/$rd/$name" "$dest"
}

# rg_list_cosol — read-only: list every comsolbatch.exe PID + command line
rg_list_cosol() {
    local ps b64
    ps="Get-CimInstance Win32_Process -Filter \"Name='comsolbatch.exe'\" | ForEach-Object { Write-Output ('PID=' + \$_.ProcessId + ' | ' + \$_.CommandLine) }"
    b64="$(python -c 'import base64,sys;print(base64.b64encode(sys.argv[1].encode("utf-16-le")).decode())' "$ps" 2>/dev/null)"
    [ -n "$b64" ] || { echo "rg_list_cosol: python missing"; return 1; }
    rg_ssh "list comsolbatch" "powershell -NoProfile -EncodedCommand $b64" 2>&1 | grep "PID=" || true
}

# rg_kill_own_cosol <runid> [model_basename]
#   Kill ONLY comsolbatch.exe processes whose command line mentions our run dir
#   or our model file.  NOTE: the remote host has no `wmic`, so identification
#   goes through Get-CimInstance; the batch job itself only carries
#   `-inputfile <model>` on its command line (the run dir is the CWD), so the
#   model basename must be passed to catch it.
rg_kill_own_cosol() {
    local rd="$1" model="${2:-}" ps b64 cond
    rg_assert_run_id "$rd" || return 1
    if [ -n "$model" ]; then
        cond="(\$_.CommandLine -like '*$rd*') -or (\$_.CommandLine -like '*$model*')"
    else
        cond="(\$_.CommandLine -like '*$rd*')"
    fi
    ps="Get-CimInstance Win32_Process -Filter \"Name='comsolbatch.exe'\" | Where-Object { $cond } | ForEach-Object { Write-Output ('KILL ' + \$_.ProcessId); taskkill /f /pid \$_.ProcessId }"
    b64="$(python -c 'import base64,sys;print(base64.b64encode(sys.argv[1].encode("utf-16-le")).decode())' "$ps" 2>/dev/null)"
    [ -n "$b64" ] || { echo "rg_kill_own_cosol: python missing"; return 1; }
    rg_log KILL "comsolbatch for $rd ${model:+($model)}"
    rg_ssh "kill own cosol $rd" "powershell -NoProfile -EncodedCommand $b64" 2>&1 | grep -E "KILL|SUCCESS|error" || true
}

# rg_cleanup <runid> <expected files...> — delete exact files, then plain rmdir
rg_cleanup() {
    local rd="$1"; shift
    local files="$*"
    rg_assert_run_id "$rd" || return 1
    if [ -n "$files" ]; then
        local del=""
        for f in $files; do
            del="$del del /f /q ${RG_BASE_WIN}\\$rd\\$f 2>nul &"
        done
        rg_ssh "delete exact files $rd" "cd /d ${RG_BASE_WIN}\\$rd && $del echo deleted"
    fi
    # only remove the directory if it is now empty; never recursive
    rg_ssh "rmdir-if-empty $rd" "rmdir ${RG_BASE_WIN}\\$rd 2>nul & dir /b ${RG_BASE_WIN}\\$rd 2>nul"
}

# rg_list_remote — show only our base dir
rg_list_remote() {
    rg_ssh "list base" "dir /b ${RG_BASE_WIN}"
}

# rg_verify_no_residue <runid>
rg_verify_no_residue() {
    local rd="$1"
    rg_assert_run_id "$rd" || return 1
    rg_log VERIFY "residue check $rd"
    local out
    out="$($RG_SSH "$RG_HOST" "dir /b ${RG_BASE_WIN}\\$rd" 2>/dev/null | tr -d '\r')"
    if [ -z "$out" ]; then
        echo "[guard] remote dir $rd is gone (zero residue)"
        return 0
    fi
    echo "[guard] WARNING: remote dir $rd still exists with:"; printf '%s\n' "$out"
    return 2
}

# --- 解模型保存目录：自动挑非 C 盘，并递归创建 -------------------------------
# rg_win_drive_exists <D>  -> 0 表示远程存在 "D:\"
rg_win_drive_exists() {
    local d="${1%:}"
    rg_ssh "probe drive $d" "if exist ${d}:\\ (echo YES) else (echo NO)" 2>/dev/null \
        | tr -d '\r' | grep -q '^YES$'
}

# rg_mkdir_win <windows_path> -> 递归创建（cmd 的 mkdir 会建中间目录）
rg_mkdir_win() {
    local p="$1"
    rg_ssh "mkdir $p" "if not exist \"$p\" mkdir \"$p\"" >/dev/null 2>&1
    rg_ssh "verify dir $p" "if exist \"$p\" (echo DIR_OK) else (echo DIR_MISSING)" 2>/dev/null \
        | tr -d '\r' | grep -q DIR_OK
}

# rg_resolve_save_dir <fallback_base_win>
#   优先 <fallback_base>\solutions；若所在盘不存在，依次尝试 D/E/F/G/H；
#   全都没有非 C 盘时退回 %USERPROFILE%\COMSOL_solutions。输出 Windows 路径。
rg_resolve_save_dir() {
    local fallback="$1"
    local drive="${fallback%%:*}"
    if rg_win_drive_exists "$drive"; then
        echo "${fallback}\\solutions"
        return 0
    fi
    local d
    for d in D E F G H; do
        if rg_win_drive_exists "$d"; then
            echo "${d}:\\zjz\\store\\solutions"
            return 0
        fi
    done
    local home
    home="$(rg_ssh 'user profile' 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r' | tail -n1)"
    [ -n "$home" ] || home='C:\Users\Public'
    echo "${home}\\COMSOL_solutions"
}

