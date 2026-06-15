#!/bin/bash
# ============================================================
# LLM-APR 实验一键运行脚本
#
# 使用前请确保:
#   1. 已安装 Defects4J 并添加到 PATH
#   2. 已安装 Java 8
#   3. 已设置 DEEPSEEK_API_KEY 环境变量
#   4. 已安装 Python 依赖: pip install -r requirements.txt
#
# 用法:
#   # 完整运行（提取数据 + 三种策略全部运行）
#   bash run.sh full
#
#   # 仅提取缺陷数据
#   bash run.sh extract
#
#   # 快速测试（仅取 5 个缺陷 × basic 策略，验证流程能跑通）
#   bash run.sh quick
#
#   # 仅运行实验（已有 bugs.json）
#   bash run.sh experiment
#
#   # 仅分析结果
#   bash run.sh analyze
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ==================== 环境检查 ====================
check_env() {
    info "检查运行环境..."

    # Java
    if ! command -v java &>/dev/null; then
        error "Java not found! 请安装 JDK 1.8"
    fi
    java_version=$(java -version 2>&1 | head -1)
    info "Java: $java_version"

    # Python
    if ! command -v python3 &>/dev/null; then
        error "Python3 not found!"
    fi
    python_version=$(python3 --version)
    info "Python: $python_version"

    # Defects4J
    if ! command -v defects4j &>/dev/null; then
        if [ -n "$DEFECTS4J_HOME" ] && [ -f "$DEFECTS4J_HOME/framework/bin/defects4j" ]; then
            export PATH="$PATH:$DEFECTS4J_HOME/framework/bin"
            info "Defects4J found at: $DEFECTS4J_HOME"
        else
            error "Defects4J not found!\n  请安装: git clone https://github.com/rjust/defects4j && cd defects4j && ./init.sh\n  然后: export PATH=\$PATH:\$(pwd)/framework/bin"
        fi
    else
        info "Defects4J: $(which defects4j)"
    fi

    # API Key
    if [ -z "$DEEPSEEK_API_KEY" ]; then
        error "DEEPSEEK_API_KEY not set!\n  请运行: export DEEPSEEK_API_KEY='your_key_here'"
    fi
    info "DEEPSEEK_API_KEY: ***$(echo $DEEPSEEK_API_KEY | tail -c 5)"

    # Python 依赖
    python3 -c "import openai, tqdm" 2>/dev/null || {
        warn "缺少 Python 依赖，正在安装..."
        pip install -r requirements.txt
    }

    info "环境检查通过!"
    echo ""
}

# ==================== 步骤 1: 提取缺陷数据 ====================
do_extract() {
    info "========== 步骤 1: 提取缺陷数据 =========="

    if [ -f "data/bugs.json" ]; then
        count=$(python3 -c "import json; print(len(json.load(open('data/bugs.json'))))")
        warn "data/bugs.json 已存在 ($count 个缺陷), 跳过提取"
        warn "如需重新提取，请先删除 data/bugs.json"
        return
    fi

    # 可以通过 --max-per-project 控制数量，快速测试时用 5
    extra_args=""
    if [ "$1" = "quick" ]; then
        extra_args="--projects Chart Lang Math --max-per-project 5"
        info "快速模式: 仅提取 Chart/Lang/Math 各 5 个缺陷"
    fi

    python3 scripts/extract_bugs.py --output data/bugs.json $extra_args

    count=$(python3 -c "import json; print(len(json.load(open('data/bugs.json'))))")
    info "提取完成: $count 个缺陷 -> data/bugs.json"
    echo ""
}

# ==================== 步骤 2: 运行实验 ====================
do_experiment() {
    info "========== 步骤 2: 运行实验 =========="

    if [ ! -f "data/bugs.json" ]; then
        error "data/bugs.json 不存在! 请先运行: bash run.sh extract"
    fi

    strategy="${1:-all}"
    limit_arg=""
    if [ -n "$2" ]; then
        limit_arg="--limit $2"
    fi

    info "策略: $strategy"
    python3 scripts/run_experiment.py \
        --bugs data/bugs.json \
        --strategy "$strategy" \
        --output results/ \
        $limit_arg

    info "实验完成! 结果保存在 results/ 目录"
    echo ""
}

# ==================== 步骤 3: 分析结果 ====================
do_analyze() {
    info "========== 步骤 3: 分析结果 =========="

    if [ ! -d "results" ]; then
        error "results/ 目录不存在! 请先运行实验"
    fi

    python3 scripts/analyze_results.py \
        --results-dir results/ \
        --output results/analysis.md

    info "分析报告: results/analysis.md"
    echo ""
}

# ==================== 主入口 ====================
case "${1:-help}" in
    full)
        check_env
        do_extract
        do_experiment "all"
        do_analyze
        info "全部完成!"
        ;;
    quick)
        check_env
        do_extract "quick"
        do_experiment "basic" ""
        do_analyze
        info "快速测试完成! 请查看 results/analysis.md"
        ;;
    extract)
        check_env
        do_extract "${2:-}"
        ;;
    experiment)
        check_env
        do_experiment "${2:-all}" "${3:-}"
        ;;
    analyze)
        do_analyze
        ;;
    help|*)
        echo ""
        echo "LLM-APR 实验运行脚本"
        echo ""
        echo "用法: bash run.sh <command>"
        echo ""
        echo "命令:"
        echo "  full        完整运行 (提取 + 实验 + 分析)"
        echo "  quick       快速测试 (15个缺陷 × basic策略)"
        echo "  extract     仅提取缺陷数据"
        echo "  experiment  仅运行实验 [strategy] [limit]"
        echo "              e.g. bash run.sh experiment basic 10"
        echo "  analyze     仅分析结果"
        echo "  help        显示此帮助"
        echo ""
        echo "环境变量:"
        echo "  DEEPSEEK_API_KEY    DeepSeek API密钥 (必须)"
        echo "  DEFECTS4J_HOME      Defects4J安装目录"
        echo ""
        ;;
esac
