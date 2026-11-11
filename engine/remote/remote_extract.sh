#!/usr/bin/env bash
# remote_extract.sh <model.mph> <domains> <label=expr[@domains][,label=expr...]> [study] [cores] [tag]
#
# Solve on the remote host ONCE and bring back only a tiny CSV of min/max/mean
# time series for every probe.  No multi-hundred-MB .mph file is downloaded.
#
#   model.mph  local model whose study step already contains the tlist
#   domains    default comma separated domain ids, e.g. "2" or "3,4" (may be "-")
#   exprs      "phi=phi@3,4,5,6,7;Hd=pfd.Hd@3,4,5,6,7;SiC_hoop=solid.sphi@2"
#              every expression may carry its own @domains; without @ the
#              default domain list is used.  ONE solve covers all probes.
#   study      default std1
#   cores      default 30
#   tag        optional CSV suffix -> <model>_<tag>_ts.csv
#
# Mechanism: a driver class is generated with the model path / domains /
# expressions baked in, compiled on the remote host with comsolcompile, run
# with comsolbatch, and its stdout (parsed from the batch log) is downloaded.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/remote_guard.sh"

MODEL="${1:?usage: remote_extract.sh <model.mph> <domains> <label=expr[@doms],...> [study] [cores] [tag]}"
DOMAINS="${2:?domains required, e.g. 2 or 3,4 (use - if every expr has @domains)}"
EXPRS="${3:?expressions required, e.g. SiC_hoop=solid.sphi@2,phi=phi@3,4}"
STUDY="${4:-std1}"
CORES="${5:-30}"
TAG="${6:-}"

MODEL_ABS="$(cd "$(dirname "$MODEL")" && pwd)/$(basename "$MODEL")"
BASE="$(basename "$MODEL_ABS")"
STEM="${BASE%.mph}"
DIR="$(dirname "$MODEL_ABS")"
if [ -n "$TAG" ]; then
    CSV_LOCAL="$DIR/${STEM}_${TAG}_ts.csv"
else
    CSV_LOCAL="$DIR/${STEM}_ts.csv"
fi
TEMPLATE="$HERE/ExtractTS.template.java"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
[ -f "$MODEL_ABS" ] || { echo "ERROR: model not found: $MODEL_ABS"; exit 1; }
[ -f "$TEMPLATE" ] || { echo "ERROR: template missing: $TEMPLATE"; exit 1; }

# --- bake inputs into the driver source (ASCII only) -------------------------
JAVA_SRC="$WORK/ExtractGen.java"
DOM_ARR=""; LAB_ARR=""; EX_ARR=""; DIM_ARR=""
IFS=";" read -ra PAIRS <<< "$EXPRS"
for p in "${PAIRS[@]}"; do
    [ -z "$p" ] && continue
    lab="${p%%=*}"; rest="${p#*=}"
    if [[ "$rest" == *"@"* ]]; then
        ex="${rest%@*}"; dm="${rest##*@}"
    else
        ex="$rest"; dm="$DOMAINS"
    fi
    [ "$dm" = "-" ] && { echo "ERROR: expr '$p' has no @domains and default domains is '-'"; exit 1; }
    dim=2
    if [[ "$dm" == b* ]]; then dim=1; dm="${dm#b}"; fi
    dm_clean="$(printf '%s' "$dm" | tr -d ' ')"
    DOM_ARR="${DOM_ARR:+$DOM_ARR, }new int[]{$dm_clean}"
    DIM_ARR="${DIM_ARR:+$DIM_ARR, }$dim"
    LAB_ARR="${LAB_ARR:+$LAB_ARR, }\"$(printf '%s' "$lab" | sed 's/[^A-Za-z0-9_]/_/g')\""
    EX_ARR="${EX_ARR:+$EX_ARR, }\"$ex\""
done
[ -n "$DOM_ARR" ] || { echo "ERROR: no expressions parsed from '$EXPRS'"; exit 1; }
sed -e "s|__MODEL__|${STEM}_out.mph|g" \
    -e "s|__DOMAINS__|$DOM_ARR|g" \
    -e "s|__DIMS__|$DIM_ARR|g" \
    -e "s|__LABELS__|$LAB_ARR|g" \
    -e "s|__EXPRS__|$EX_ARR|g" \
    "$TEMPLATE" > "$JAVA_SRC"
python - "$JAVA_SRC" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
assert "__" not in s.replace("__main__", ""), "placeholder left in driver source"
open(p, "w", encoding="utf-8").write(s)
print("driver source ready")
PY

RD="run_$(date +%Y%m%d_%H%M%S)"
RWIN="${RG_BASE_WIN}\\$RD"
echo "[rext] host=$RG_HOST cores=$CORES study=$STUDY run=$RD"
rg_assert_run_id "$RD" || exit 1
rg_ssh "mkdir $RD" "mkdir $RWIN" || exit 1
rg_scp "upload model" "$MODEL_ABS" "$RG_HOST:$RG_BASE_UNIX/$RD/$BASE" || { echo "ERROR: upload model failed"; exit 1; }
rg_scp "upload driver" "$JAVA_SRC" "$RG_HOST:$RG_BASE_UNIX/$RD/ExtractGen.java" || { echo "ERROR: upload driver failed"; exit 1; }

echo "[rext] solving ...  study=${STUDY:-（全部，按模型顺序）}"
IFS="," read -ra STUDY_LIST <<< "$STUDY"
_clean=()
for x in "${STUDY_LIST[@]}"; do [ -n "$x" ] && _clean+=("$x"); done
STUDY_LIST=("${_clean[@]}")
RC=0; IDX=0; IN_FILE="$BASE"
if [ "${#STUDY_LIST[@]}" -eq 0 ]; then
    rg_ssh "comsolbatch $RD" "cd /d $RWIN && \"${RG_BATCH}\" -np $CORES -batchlog ${STEM}_run.txt -batchlogout -inputfile $IN_FILE -outputfile ${STEM}_out.mph"
    RC=$?
else
    for ST in "${STUDY_LIST[@]}"; do
        IDX=$((IDX+1))
        echo "[rext]   -> 第 ${IDX} 步: ${ST}"
        rg_ssh "comsolbatch $RD" "cd /d $RWIN && \"${RG_BATCH}\" -np $CORES -study $ST -batchlog ${STEM}_run.txt -batchlogout -inputfile $IN_FILE -outputfile ${STEM}_s${IDX}_out.mph"
        RC=$?
        [ "$RC" != "0" ] && break
        IN_FILE="${STEM}_s${IDX}_out.mph"
    done
    [ "$RC" = "0" ] && rg_ssh "chained output" "cd /d $RWIN && copy /y \"${STEM}_s${IDX}_out.mph\" \"${STEM}_out.mph\" >nul"
fi
echo "[rext] solve rc=$RC, compiling driver ..."
rg_ssh "comsolcompile $RD" "cd /d $RWIN && \"${RG_COMPILE}\" ExtractGen.java" 2>&1 | tail -4

echo "[rext] extracting ..."
rg_ssh "run extractor $RD" "cd /d $RWIN && \"${RG_BATCH}\" -inputfile ExtractGen.class" > "$WORK/extract_stdout.txt" 2>&1 || true
OK=0
if [ -s "$WORK/extract_stdout.txt" ] && grep -q "TSV " "$WORK/extract_stdout.txt"; then
    python - "$WORK/extract_stdout.txt" "$CSV_LOCAL" "$LAB_ARR" <<'PY'
import sys
log, out, labels = sys.argv[1], sys.argv[2], sys.argv[3]
rows = [l for l in open(log, encoding="utf-8", errors="ignore").read().splitlines() if l.startswith("TSV ")]
cols = ["t_d"]
for lab in labels.split(", "):
    lab = lab.strip().strip('"')
    if not lab:
        continue
    cols += [lab + "_min", lab + "_max", lab + "_mean"]
with open(out, "w", encoding="utf-8") as f:
    f.write(",".join(cols) + "\n")
    for r in rows:
        f.write(",".join(r.split()[1:]) + "\n")
print("parsed rows:", len(rows))
PY
    OK=1
else
    echo "[rext] WARN: no TSV in extract log; tail:"
    tail -15 "$WORK/extract_stdout.txt" 2>/dev/null || true
fi
rg_scp "download solver log" "$RG_HOST:$RG_BASE_UNIX/$RD/${STEM}_run.txt" "$DIR/${STEM}_run.txt" 2>/dev/null || true

if [ "$OK" = "1" ]; then
    if [ "${KEEP_SOLVED:-0}" = "1" ]; then
        ARCH="${STEM}_${TAG:-x}_solved.mph"
        if [ -n "${SAVE_DIR_WIN:-}" ]; then
            TARGET_DIR_WIN="$SAVE_DIR_WIN"
        else
            TARGET_DIR_WIN="$(rg_resolve_save_dir "$RG_BASE_WIN")"
        fi
        if rg_mkdir_win "$TARGET_DIR_WIN"; then
            rg_ssh "save solved model" "move /y \"$RWIN\\${STEM}_out.mph\" \"$TARGET_DIR_WIN\\$ARCH\"" >/dev/null 2>&1 || true
            if rg_ssh "verify saved" "if exist \"$TARGET_DIR_WIN\\$ARCH\" (echo YES) else (echo NO)" 2>/dev/null | tr -d '\r' | grep -q YES; then
                echo "[rext] 解模型已保存 -> ${TARGET_DIR_WIN}\\$ARCH"
            else
                echo "[rext] WARN: 解模型保存失败（目录存在但复制失败）"
            fi
        else
            echo "[rext] WARN: 无法创建保存目录 $TARGET_DIR_WIN（远程可能没有非 C 盘可写）"
        fi
    fi

    rg_cleanup "$RD" "$BASE" "ExtractGen.java" "ExtractGen.class" "extract_log.txt" "ExtractGen_M.mph" \
        "${STEM}_out.mph" "${STEM}_run.txt" "${STEM}_out.mph.recovery" "${STEM}_out.mph.status" "ExtractGen.class.status" \
        "${STEM}_s1_out.mph" "${STEM}_s1_out.mph.recovery" "${STEM}_s1_out.mph.status" \
        "${STEM}_s2_out.mph" "${STEM}_s2_out.mph.recovery" "${STEM}_s2_out.mph.status" \
        "${STEM}_s3_out.mph" "${STEM}_s3_out.mph.recovery" "${STEM}_s3_out.mph.status"
    rg_verify_no_residue "$RD" || true
    echo "[rext] done: csv=$CSV_LOCAL"
else
    echo "[rext] extraction failed -> keeping remote dir: $RWIN"
fi
