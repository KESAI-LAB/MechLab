#!/usr/bin/env bash
# =============================================================================
#  engine/local_extract.sh  —  K（本机）提交引擎
#
#  用法:
#     local_extract.sh <model.mph> "<label=expr@doms;...>" [study] [cores] [tag]
#
#  与 A/E 机的引擎等价：在本机把 ExtractGen.java 编译好，solve 一次，
#  然后只把 min/max/mean 时间序列写回 CSV。
#  结果:  <模型目录>/<模型名>_<tag>_ts.csv
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"          # v2 仓库根目录

# --- 本机 COMSOL 安装路径（可用环境变量覆盖） -------------------------------
COMSOL_BIN="${COMSOL_BIN:-/f/Program Files/COMSOL/COMSOL64/Multiphysics/bin/win64}"
BATCH="${BATCH:-$COMSOL_BIN/comsolbatch.exe}"
COMPILE="${COMPILE:-$COMSOL_BIN/comsolcompile.exe}"
TEMPLATE="${TEMPLATE:-$HERE/ExtractTS.template.java}"

MODEL="${1:?usage: local_extract.sh <model.mph> '<label=expr@doms;...>' [study] [cores] [tag]}"
EXPRS="${2:?探针表达式必填}"
STUDY="${3:-std1}"
CORES="${4:-8}"
TAG="${5:-}"

MODEL_ABS="$(cd "$(dirname "$MODEL")" && pwd)/$(basename "$MODEL")"
BASE="$(basename "$MODEL_ABS")"
STEM="${BASE%.mph}"
DIR="$(dirname "$MODEL_ABS")"
if [ -n "$TAG" ]; then CSV_OUT="$DIR/${STEM}_${TAG}_ts.csv"; else CSV_OUT="$DIR/${STEM}_ts.csv"; fi

[ -f "$MODEL_ABS" ] || { echo "ERROR: 模型不存在: $MODEL_ABS"; exit 1; }
[ -f "$TEMPLATE" ]  || { echo "ERROR: 模板缺失: $TEMPLATE"; exit 1; }
[ -f "$BATCH" ]     || { echo "ERROR: comsolbatch 不存在: $BATCH"; exit 1; }

RUN_ID="run_$(date +%Y%m%d_%H%M%S)"

# --- 把探针列表拼成 Java 数组字面量 -----------------------------------------
DOM_ARR=""; LAB_ARR=""; EX_ARR=""; DIM_ARR=""
HDR="t_d"
IFS=";" read -ra PAIRS <<< "$EXPRS"
for p in "${PAIRS[@]}"; do
    [ -z "$p" ] && continue
    lab="${p%%=*}"; rest="${p#*=}"
    if [[ "$rest" == *"@"* ]]; then ex="${rest%@*}"; dm="${rest##*@}"; else ex="$rest"; dm=""; fi
    [ -z "$dm" ] && { echo "ERROR: 探针 '$p' 缺少 @域（如 solid.sphi@2）"; exit 1; }
    dim=2
    if [[ "$dm" == b* ]]; then dim=1; dm="${dm#b}"; fi
    dm="$(printf '%s' "$dm" | tr -d ' ')"
    lab_clean="$(printf '%s' "$lab" | sed 's/[^A-Za-z0-9_]/_/g')"
    DOM_ARR="${DOM_ARR:+$DOM_ARR, }new int[]{$dm}"
    DIM_ARR="${DIM_ARR:+$DIM_ARR, }$dim"
    LAB_ARR="${LAB_ARR:+$LAB_ARR, }\"$lab_clean\""
    EX_ARR="${EX_ARR:+$EX_ARR, }\"$ex\""
    HDR="$HDR,${lab_clean}_min,${lab_clean}_max,${lab_clean}_mean"
done
[ -n "$DOM_ARR" ] || { echo "ERROR: 没有解析到任何探针"; exit 1; }

# --- 私有运行目录 -----------------------------------------------------------
RUNDIR="$DIR/.runs/$RUN_ID"
mkdir -p "$RUNDIR"
cp "$MODEL_ABS" "$RUNDIR/$BASE"
sed -e "s|__MODEL__|${STEM}_out.mph|g" \
    -e "s|__DOMAINS__|$DOM_ARR|g" \
    -e "s|__DIMS__|$DIM_ARR|g" \
    -e "s|__LABELS__|$LAB_ARR|g" \
    -e "s|__EXPRS__|$EX_ARR|g" \
    "$TEMPLATE" > "$RUNDIR/ExtractGen.java"

echo "[K] 本机提交  cores=$CORES  study=$STUDY  run=$RUN_ID"
echo "[K] 工作目录  $RUNDIR"

# --- 求解（支持逗号分隔的多个研究步，按顺序链式求解）-----------------------
IFS="," read -ra _parts <<< "$STUDY"
STUDY_LIST=()
for x in "${_parts[@]}"; do [ -n "$x" ] && STUDY_LIST+=("$x"); done
echo "[K] 求解中 ...  研究步=${STUDY:-（全部，按模型顺序）}"
RC=0; IDX=0; IN_FILE="$BASE"
if [ "${#STUDY_LIST[@]}" -eq 0 ]; then
    ( cd "$RUNDIR" && "$BATCH" -np "$CORES" -batchlog "${STEM}_run.txt" -batchlogout -inputfile "$IN_FILE" \
          -outputfile "${STEM}_out.mph" ) 2>&1 | tee -a "$RUNDIR/solve.log"
    RC=${PIPESTATUS[0]}
else
    : > "$RUNDIR/solve.log"
    for ST in "${STUDY_LIST[@]}"; do
        IDX=$((IDX+1))
        echo "[K]   -> 第 ${IDX} 步: ${ST}"
        ( cd "$RUNDIR" && "$BATCH" -np "$CORES" -study "$ST" -batchlog "${STEM}_run.txt" -batchlogout -inputfile "$IN_FILE" \
              -outputfile "${STEM}_s${IDX}_out.mph" ) 2>&1 | tee -a "$RUNDIR/solve.log"
        RC=${PIPESTATUS[0]}
        [ "$RC" != "0" ] && break
        IN_FILE="${STEM}_s${IDX}_out.mph"
    done
    [ "$RC" = "0" ] && cp "$RUNDIR/${STEM}_s${IDX}_out.mph" "$RUNDIR/${STEM}_out.mph"
fi
echo "[K] 求解结束 rc=$RC"

# --- 编译并运行提取器 -------------------------------------------------------
echo "[K] 编译提取器 ..."
( cd "$RUNDIR" && "$COMPILE" ExtractGen.java ) > "$RUNDIR/compile.log" 2>&1
if [ ! -f "$RUNDIR/ExtractGen.class" ]; then
    echo "[K] 提取器编译失败，保留目录: $RUNDIR"
    tail -6 "$RUNDIR/compile.log" 2>/dev/null
    exit 1
fi
echo "[K] 提取数据 ..."
( cd "$RUNDIR" && "$BATCH" -inputfile ExtractGen.class ) > "$RUNDIR/extract.log" 2>&1 || true

if grep -q "^TSV " "$RUNDIR/extract.log" 2>/dev/null; then
    { echo "$HDR"
      grep "^TSV " "$RUNDIR/extract.log" | sed 's/^TSV //; s/ /,/g'
    } > "$CSV_OUT"
    cp "$RUNDIR/${STEM}_run.txt" "$DIR/${STEM}_run.txt" 2>/dev/null || true
    if [ "${KEEP_SOLVED:-0}" = "1" ] && [ -f "$RUNDIR/${STEM}_out.mph" ]; then
        SAVE_DIR="${SAVE_DIR:-$DIR/solved}"
        mkdir -p "$SAVE_DIR"
        SAVE_NAME="${STEM}_${TAG:-x}_solved.mph"
        cp "$RUNDIR/${STEM}_out.mph" "$SAVE_DIR/$SAVE_NAME" \
            && echo "[K] 解模型已保存 -> $SAVE_DIR/$SAVE_NAME"
    fi
    rm -rf "$RUNDIR"
    echo "[K] 完成 -> $CSV_OUT"
else
    echo "[K] 提取失败，保留目录: $RUNDIR"
    tail -10 "$RUNDIR/extract.log" 2>/dev/null
    exit 1
fi
