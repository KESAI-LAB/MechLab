#!/usr/bin/env bash
# =============================================================================
#  engine/mock_engine.sh — M 演示模式（Mock）：低碳钢单轴拉伸 · 约 15 秒
#
#  不连远程、不启动 COMSOL：按节奏回放"求解步骤"，然后把代表性的
#  应力-应变数据、曲线图、摘要复制到模型目录。
#
#  用法: mock_engine.sh <model.mph> "<spec>" [study] [cores] [tag]
#  环境:
#    MOCK_DELAY         每步间隔秒数（默认 0.43；20 步 + 收尾 ≈ 15 s）
#    MOCK_OPEN_FIGURE   完成后是否自动打开曲线图（默认 1；自动化测试可设 0）
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="$HERE/mock_data/low_carbon_steel"
MODEL="${1:?usage: mock_engine.sh <model.mph> '<spec>' [study] [cores] [tag]}"
SPEC="${2:-demo}"
STUDY="${3:-std1}"
CORES="${4:-1}"
TAG="${5:-mock}"
DELAY="${MOCK_DELAY:-0.43}"

MODEL_ABS="$(cd "$(dirname "$MODEL")" && pwd)/$(basename "$MODEL")"
BASE="$(basename "$MODEL_ABS")"
STEM="${BASE%.mph}"
DIR="$(dirname "$MODEL_ABS")"
PREFIX="$DIR/${STEM}_${TAG}"

[ -f "$DATA/steps.txt" ] || { echo "[M] ERROR: 缺少演示数据 $DATA/steps.txt"; exit 1; }

echo "[M] ================= 演示模式：低碳钢单轴拉伸 ================="
echo "[M] 不连接远程机器，不启动 COMSOL；数据为代表性合成数据（演示用）"
echo "[M] 模型   $MODEL_ABS"
echo "[M] 探针   $SPEC"
echo "[M] 研究步 $STUDY   核数 $CORES   标签 $TAG"
echo "[M] 材料   Q235 低碳钢  E=206 GPa  nu=0.30"
echo "[M]        ReH=250 MPa  ReL=235 MPa  Rm=420 MPa  A=26%"
echo "[M] 网格   8,421 单元 / 17,205 自由度   求解器 PARDISO"
echo "[M] 求解中 ..."

while IFS= read -r line; do
    echo "    $line"
    sleep "$DELAY"
done < "$DATA/steps.txt"

echo "[M] 求解完成 rc=0"
echo "[M] 后处理：提取载荷/应力/应变 -> CSV；绘制曲线 -> PNG"

cp "$DATA/tensile.csv"        "${PREFIX}_tensile.csv"
cp "$DATA/ts.csv"             "${PREFIX}_ts.csv"
cp "$DATA/summary.json"       "${PREFIX}_summary.json"
cp "$DATA/stress_strain.png"  "${PREFIX}_stress_strain.png"

echo "[M] 输出："
echo "    CSV   ${PREFIX}_tensile.csv"
echo "    TS    ${PREFIX}_ts.csv"
echo "    图    ${PREFIX}_stress_strain.png"
echo "    摘要  ${PREFIX}_summary.json"
echo "[M] 关键指标："
sed 's/^/    /' "${PREFIX}_summary.json"
echo "[M] 完成 -> ${PREFIX}_tensile.csv"

if [ "${MOCK_OPEN_FIGURE:-1}" = "1" ] && [ -f "${PREFIX}_stress_strain.png" ]; then
    if command -v cygpath >/dev/null 2>&1; then
        WPNG="$(cygpath -w "${PREFIX}_stress_strain.png" 2>/dev/null || echo "${PREFIX}_stress_strain.png")"
    else
        WPNG="${PREFIX}_stress_strain.png"
    fi
    cmd //c start "" "$WPNG" >/dev/null 2>&1 || true
    echo "[M] 已自动打开曲线图"
fi
