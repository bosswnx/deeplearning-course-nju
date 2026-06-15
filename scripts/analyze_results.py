"""
实验结果分析与报告生成

用法:
    python scripts/analyze_results.py --results-dir results/ --output results/analysis.md
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


def load_results(results_dir):
    """加载所有策略的实验结果"""
    all_results = {}

    for strategy in ["basic", "diagnostic", "iterative"]:
        strat_dir = os.path.join(results_dir, strategy)
        if not os.path.isdir(strat_dir):
            continue

        results = []
        summary = None

        for fname in sorted(os.listdir(strat_dir)):
            fpath = os.path.join(strat_dir, fname)
            if fname == "_summary.json":
                with open(fpath, "r", encoding="utf-8") as f:
                    summary = json.load(f)
            elif fname.endswith(".json"):
                with open(fpath, "r", encoding="utf-8") as f:
                    results.append(json.load(f))

        all_results[strategy] = {"results": results, "summary": summary}

    return all_results


def analyze(all_results):
    """分析实验结果"""
    analysis = {}

    for strategy, data in all_results.items():
        results = data["results"]
        summary = data["summary"]

        if not results:
            continue

        # 按项目统计
        by_project = defaultdict(lambda: {"total": 0, "fixed": 0})
        total = len(results)
        fixed = 0
        total_attempts = 0
        fixed_attempts = []

        for r in results:
            proj = r.get("project", "Unknown")
            by_project[proj]["total"] += 1

            if r.get("fixed"):
                fixed += 1
                by_project[proj]["fixed"] += 1
                fixed_attempts.append(r.get("total_attempts", 0))

            total_attempts += r.get("total_attempts", 0)

        avg_attempts_for_fix = (
            sum(fixed_attempts) / len(fixed_attempts) if fixed_attempts else 0
        )

        analysis[strategy] = {
            "total": total,
            "fixed": fixed,
            "fix_rate": round(fixed / max(total, 1) * 100, 2),
            "avg_attempts_per_bug": round(total_attempts / max(total, 1), 2),
            "avg_attempts_for_fix": round(avg_attempts_for_fix, 2),
            "by_project": dict(by_project),
            "api_stats": summary.get("api_stats", {}) if summary else {},
        }

    return analysis


def generate_report(analysis, model_name, output_path):
    """生成 Markdown 格式的分析报告"""
    lines = []
    lines.append("# 实验结果分析报告\n")
    lines.append(f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **模型**: {model_name}\n")

    # =================== 总体对比表 ===================
    lines.append("## 1. 各策略总体修复效果对比\n")
    lines.append("| 策略 | 总缺陷数 | 正确修复数 | 修复率 | 平均尝试次数(每bug) | 修复平均尝试次数 |")
    lines.append("|------|---------|-----------|--------|-------------------|----------------|")

    for strategy in ["basic", "diagnostic", "iterative"]:
        if strategy not in analysis:
            continue
        a = analysis[strategy]
        lines.append(
            f"| {strategy.capitalize()} "
            f"| {a['total']} "
            f"| {a['fixed']} "
            f"| {a['fix_rate']}% "
            f"| {a['avg_attempts_per_bug']} "
            f"| {a['avg_attempts_for_fix']} |"
        )

    # =================== 按项目对比 ===================
    lines.append("\n## 2. 各项目修复效果对比\n")

    # 收集所有项目名
    all_projects = set()
    for strategy, a in analysis.items():
        all_projects.update(a["by_project"].keys())
    all_projects = sorted(all_projects)

    header = "| 项目 |"
    sep = "|------|"
    for strategy in ["basic", "diagnostic", "iterative"]:
        if strategy in analysis:
            header += f" {strategy.capitalize()} |"
            sep += "--------|"
    lines.append(header)
    lines.append(sep)

    for proj in all_projects:
        row = f"| {proj} |"
        for strategy in ["basic", "diagnostic", "iterative"]:
            if strategy in analysis:
                bp = analysis[strategy]["by_project"].get(proj, {"total": 0, "fixed": 0})
                row += f" {bp['fixed']}/{bp['total']} |"
        lines.append(row)

    # =================== API 消耗 ===================
    lines.append("\n## 3. API 调用统计\n")
    lines.append("| 策略 | 调用次数 | 输入Token | 输出Token | 预估成本(元) |")
    lines.append("|------|---------|----------|----------|------------|")

    for strategy in ["basic", "diagnostic", "iterative"]:
        if strategy not in analysis:
            continue
        stats = analysis[strategy].get("api_stats", {})
        lines.append(
            f"| {strategy.capitalize()} "
            f"| {stats.get('total_calls', 'N/A')} "
            f"| {stats.get('total_input_tokens', 'N/A')} "
            f"| {stats.get('total_output_tokens', 'N/A')} "
            f"| {stats.get('estimated_cost_rmb', 'N/A')} |"
        )

    # =================== 结论 ===================
    lines.append("\n## 4. 结论\n")

    if len(analysis) >= 2:
        rates = {s: a["fix_rate"] for s, a in analysis.items()}
        best = max(rates, key=rates.get)
        lines.append(f"- **最优策略**: {best.capitalize()} (修复率 {rates[best]}%)")

        if "basic" in rates and "diagnostic" in rates:
            diff = rates["diagnostic"] - rates["basic"]
            lines.append(f"- Diagnostic 策略相比 Basic 策略修复率{'提升' if diff > 0 else '下降'} {abs(diff):.2f}%")

        if "basic" in rates and "iterative" in rates:
            diff = rates["iterative"] - rates["basic"]
            lines.append(f"- Iterative 策略相比 Basic 策略修复率{'提升' if diff > 0 else '下降'} {abs(diff):.2f}%")

    report = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report


def main():
    parser = argparse.ArgumentParser(description="Analyze experiment results")
    parser.add_argument("--results-dir", required=True, help="Path to results directory")
    parser.add_argument("--output", default="results/analysis.md", help="Output report path")
    parser.add_argument("--model", default=config.DEEPSEEK_MODEL, help="Model name for report")
    args = parser.parse_args()

    results_dir = os.path.join(config.PROJECT_ROOT, args.results_dir)
    output_path = os.path.join(config.PROJECT_ROOT, args.output)

    all_results = load_results(results_dir)
    if not all_results:
        print("No results found!")
        sys.exit(1)

    analysis = analyze(all_results)
    report = generate_report(analysis, args.model, output_path)

    print(report)
    print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    main()
