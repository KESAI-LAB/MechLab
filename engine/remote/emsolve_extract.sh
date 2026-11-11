#!/usr/bin/env bash
# emsolve_extract.sh <model.mph> <cores> <tag> "<LABEL=EXPR@dom,...>"
#
# Solve the study AND extract the probe time series in one COMSOL process on the E
# host (no 7 GB solved model is saved, because the host cannot re-load it), then
# bring back only the small CSV.
#
# The batch is launched through schtasks /RU SYSTEM so it survives the ssh session.
# Everything happens in one run_YYYYmmdd_HHMMSS directory which is removed afterwards;
# the scheduled task is deleted on every exit path.
#
# Prereq: source engine/remote/env_evior.sh first.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/remote_guard.sh"

[ -n "${RG_BATCH:-}" ] && [ -n "${RG_COMPILE:-}" ] || { echo "ERROR: source engine/remote/env_evior.sh first"; exit 1; }
MODEL="${1:?model}"; CORES="${2:-22}"; TAG="${3:?tag}"; SPEC="${4:?probe spec}"; STUDIES="${5:-}"
MODEL_ABS="$(cd "$(dirname "$MODEL")" && pwd)/$(basename "$MODEL")"
BASE="$(basename "$MODEL")"; STEM="${BASE%.mph}"
OUTCSV="$(dirname "$MODEL_ABS")/${STEM}_${TAG}_ts.csv"
WORK="$(mktemp -d)"
PY="${PY:-python.exe}"

RD="run_$(date +%Y%m%d_%H%M%S)"
RWIN="${RG_BASE_WIN}\\$RD"
rg_assert_run_id "$RD" || exit 1
echo "[ext] host=$RG_HOST dir=$RWIN cores=$CORES tag=$TAG"

cleanup_task() {
  rg_ssh "del ext task" "schtasks /Delete /TN comsol_extract_${TAG} /F" >/dev/null 2>&1 || true
}
trap 'cleanup_task; rm -rf "$WORK"' EXIT

rg_ssh "mkdir" "mkdir $RWIN" || { echo "ERROR mkdir"; exit 1; }

# ---- generate the java + bat ------------------------------------------------
RG_COMPILE_WIN="$RG_COMPILE" RG_BATCH_WIN="$RG_BATCH" \
"$PY" - "$HERE" "$WORK" "$BASE" "$TAG" "$RWIN" "$CORES" "$SPEC" "$STUDIES" <<'PY'
import os, sys
here, work, model, tag, rwin, cores, spec, studies = sys.argv[1:9]
compile_ = os.environ["RG_COMPILE_WIN"]
batch_ = os.environ["RG_BATCH_WIN"]
groups, labels, exprs = [], [], []
for item in spec.split(";"):
    item = item.strip()
    if not item: continue
    lab, rest = item.split("=", 1)
    ex, doms = rest.rsplit("@", 1)
    groups.append("new int[]{" + doms + "}")
    labels.append('"' + lab + '"')
    exprs.append('"' + ex + '"')
tpl = open(os.path.join(here, "SolveExtract.template.java"), encoding="utf-8").read()
src = (tpl.replace("__MODEL__", model)
          .replace("__DOMAINS__", ", ".join(groups))
          .replace("__LABELS__", ", ".join(labels))
          .replace("__EXPRS__", ", ".join(exprs))
          .replace("__STUDIES__", ", ".join('"' + t.strip() + '"' for t in studies.split(",") if t.strip()))
          .replace("__TLIST__", os.environ.get("TLIST",
                   "0 50 100 150 200 250 300 350 400 440 450 500 550 600 650 700 750 800 850 900 950 1000")))
open(os.path.join(work, "SolveExtract.java"), "w", encoding="ascii", newline="\r\n").write(src)
bat = ["@echo off", "cd /d " + rwin,
       '"%s" SolveExtract.java' % compile_,
       '"%s" -np %s -inputfile SolveExtract.class > solve_stdout.log 2>&1' % (batch_, cores)]
open(os.path.join(work, "run.bat"), "w", encoding="ascii", newline="\r\n").write("\r\n".join(bat) + "\r\n")
print("[ext] java + bat generated")
PY
[ $? -eq 0 ] || { echo "ERROR generate"; exit 1; }

tar -czf "$WORK/m.tgz" -C "$(dirname "$MODEL_ABS")" "$BASE" -C "$WORK" run.bat SolveExtract.java \
  || { echo "ERROR tar"; exit 1; }
rg_scp "upload bundle" "$WORK/m.tgz" "$RG_HOST:$RG_BASE_UNIX/$RD/m.tgz" || { echo "ERROR upload"; exit 1; }
rg_ssh "unpack" "cd /d $RWIN && tar -xzf m.tgz && del /q m.tgz" || { echo "ERROR unpack"; exit 1; }

# ---- launch -----------------------------------------------------------------
rg_ssh "run ext task" "schtasks /Create /TN comsol_extract_${TAG} /TR \"$RWIN\\run.bat\" /SC ONCE /ST 23:59 /RU SYSTEM /RL HIGHEST /F && schtasks /Run /TN comsol_extract_${TAG}" >/dev/null 2>&1
echo "[ext] task started, polling ..."

STATE=""
for i in $(seq 1 240); do
  sleep 45
  LINE=$(rg_ssh "state" "cd /d $RWIN && findstr /C:\"MODEL_LOADED\" /C:\"SOLVED_IN_MIN\" /C:\"EXTRACT_DONE\" /C:\"FAIL\" /C:\"Exception\" solve_stdout.log" 2>/dev/null | tr -d '\r' | tail -1)
  if [ -n "${LINE:-}" ] && [ "$LINE" != "$STATE" ]; then STATE="$LINE"; echo "[ext] $(date +%H:%M:%S) ${LINE:0:120}"; fi
  if rg_ssh "done?" "cd /d $RWIN && findstr /C:\"EXTRACT_DONE\" solve_stdout.log" >/dev/null 2>&1; then
    echo "[ext] finished at $(date +%H:%M:%S)"; break
  fi
  [ $((i % 8)) -eq 0 ] && echo "[ext] $(date +%H:%M:%S) still running (${i}×45 s)"
done

# ---- parse the TSV lines into a CSV ----------------------------------------
rg_ssh "dump stdout" "cd /d $RWIN && type solve_stdout.log" 2>/dev/null | tr -d '\r' > "$WORK/stdout.txt"
"$PY" - "$WORK/stdout.txt" "$OUTCSV" "$SPEC" <<'PY'
import sys
src, out, spec = sys.argv[1:4]
rows = [l for l in open(src, encoding="utf-8", errors="ignore").read().splitlines() if l.startswith("TSV ")]
labels = [s.split("=")[0].strip() for s in spec.split(";") if s.strip()]
head = ["t_d"]
for lab in labels: head += [lab + "_min", lab + "_max", lab + "_mean"]
with open(out, "w", encoding="utf-8") as f:
    f.write(",".join(head) + "\n")
    for r in rows:
        f.write(",".join(r.split()[1:]) + "\n")
print("rows:", len(rows), "->", out)
PY

# the plot / PNG export happens AFTER EXTRACT_DONE inside the same batch process;
# wait for its marker before downloading, otherwise the files are not there yet.
for i in $(seq 1 40); do
  if grep -qE 'FIG_OK|FIG_FAIL' "$WORK/stdout.txt" 2>/dev/null; then break; fi
  sleep 8
  rg_ssh "stdout poll" "type ${RWIN}\\solve_stdout.log 2>nul" 2>/dev/null \
    | grep -qE 'FIG_OK|FIG_FAIL' && break
done
# ---- report the ready-made plot-group markers (pgphi / pgsph) --------------
echo "[ext] plot markers: $(grep -E 'PLOT_OK|PLOT_FAIL|FIG_OK|FIG_FAIL' "$WORK/stdout.txt" 2>/dev/null | head -3 | tr '\n' ' ')"

# ---- bring back the ready-made colour figures ------------------------------
FIGDIR="$RG_WS/figures/runs/$TAG"
mkdir -p "$FIGDIR"
got=0
for f in phi_full_100 phi_full_250 phi_full_440 phi_full_1000 phi_zoom_100 phi_zoom_250 phi_zoom_440 phi_zoom_1000 sph_full_440 sph_zoom_440 sph_full_1000; do
  if rg_scp "figure $f" "$RG_HOST:$RG_BASE_UNIX/$RD/$f.png" "$FIGDIR/$f.png" >/dev/null 2>&1; then
    got=$((got + 1))
  fi
done
echo "[ext] figures downloaded: $got -> $FIGDIR"

# ---- optionally archive the solved model before the zero-residue cleanup ----
if [ "${KEEP_SOLVED:-0}" = "1" ]; then
  # the in-process model.save() runs AFTER the figure export; wait for its marker before moving
  for i in $(seq 1 80); do
    if rg_ssh "save poll" "type ${RWIN}\solve_stdout.log 2>nul" 2>/dev/null | grep -q "SOLVED_MODEL_SAVED"; then break; fi
    sleep 15
  done
  # comsolbatch keeps SolveExtract_M.mph locked until it exits: wait for the process to go away
  for i in $(seq 1 60); do
    n=$(rg_ssh "batch poll" "tasklist /FI \"IMAGENAME eq comsolbatch.exe\" /NH 2>nul | find /c \"comsolbatch\"" 2>/dev/null | tr -d '\r\n ')
    [ "$n" = "0" ] && break
    sleep 10
  done
  sleep 8
  if [ -n "${SAVE_DIR_WIN:-}" ]; then
    STORE_DIR_WIN="$SAVE_DIR_WIN"
  else
    STORE_DIR_WIN="$(rg_resolve_save_dir "$RG_BASE_WIN")"
  fi
  ARCHIVE_NAME="${STEM}_${TAG}_solved.mph"
  ok=0
  if rg_mkdir_win "$STORE_DIR_WIN"; then
    for k in 1 2 3 4 5 6; do
      rg_ssh "archive solved model" "move /y \"$RWIN\\SolveExtract_M.mph\" \"$STORE_DIR_WIN\\$ARCHIVE_NAME\"" >/dev/null 2>&1 || true
      if rg_ssh "verify archive" "if exist \"$STORE_DIR_WIN\\$ARCHIVE_NAME\" (echo YES) else (echo NO)" 2>/dev/null | tr -d '\r' | grep -q YES; then
        ok=1
        break
      fi
      sleep 15
    done
  else
    echo "[ext] WARN: 保存目录不可创建：$STORE_DIR_WIN（远程可能没有非 C 盘可写）"
  fi

fi

# ---- zero residue (incl. the ~7 GB model comsolbatch writes on exit) --------
rg_cleanup "$RD" "$BASE" run.bat SolveExtract.java SolveExtract.class SolveExtract.class.status \
  solve_stdout.log SolveExtract_M.mph SolveExtract_out.mph \
  phi_full_100.png phi_full_250.png phi_full_440.png phi_full_1000.png \
  phi_zoom_100.png phi_zoom_250.png phi_zoom_440.png phi_zoom_1000.png \
  sph_full_440.png sph_zoom_440.png sph_full_1000.png >/dev/null 2>&1 || true
# COMSOL leaves short-lived "~model*.mph" copies behind; delete them by mask, then rmdir
rg_ssh "del temp models $RD" "del /f /q \"${RWIN}\~model*.mph\" 2>nul & echo ok" >/dev/null 2>&1 || true
rg_ssh "rmdir-if-empty $RD" "rmdir ${RWIN} 2>nul & dir /b ${RWIN} 2>nul" >/dev/null 2>&1 || true
rg_verify_no_residue "$RD" || echo "[guard] WARNING: residue left in $RWIN (inspect manually)"
echo "[ext] done -> $OUTCSV"
