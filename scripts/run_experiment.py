"""
主实验脚本

用法:
    # 运行所有策略
    python scripts/run_experiment.py --bugs data/bugs.json --strategy all --output results/

    # 只运行 basic 策略
    python scripts/run_experiment.py --bugs data/bugs.json --strategy basic --output results/

    # 运行 diagnostic 策略，指定模型
    python scripts/run_experiment.py --bugs data/bugs.json --strategy diagnostic --model deepseek-v4-pro
"""
import argparse
import json
import os
import time
import logging
from datetime import datetime
from tqdm import tqdm

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from scripts.llm_client import LLMClient
from scripts.patch_validator import PatchValidator
from scripts.java_utils import replace_method
from prompts.templates import (
    SYSTEM_PROMPT,
    BASIC_PROMPT,
    DIAGNOSTIC_PHASE1_PROMPT,
    DIAGNOSTIC_PHASE2_PROMPT,
    ITERATIVE_FIRST_PROMPT,
    ITERATIVE_FOLLOWUP_PROMPT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("experiment.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def build_patched_source(bug_info, patched_code):
    """
    将 LLM 生成的修复代码重建为完整源文件。

    两种模式：
    - method 模式（首选）：bug_info 含 method_start/method_end，将修复方法替换回原文件对应行
    - full-file 模式（兜底）：如果定位失败，或 LLM 返回了完整文件，则按完整文件处理

    Args:
        bug_info: 缺陷信息字典
        patched_code: LLM 生成并经 extract_code 提取后的 Java 代码

    Returns:
        str: 重建后的完整源文件内容；失败返回 None
    """
    if not patched_code:
        return None

    original_source = bug_info["source_code"]

    # 如果 LLM 误返回了完整文件（含 package/import/class），直接使用
    looks_like_full_file = (
        "class " in patched_code
        and ("import " in patched_code or "package " in patched_code)
    )
    if looks_like_full_file:
        return patched_code

    # method 模式：用行号替换
    method_start = bug_info.get("method_start")
    method_end = bug_info.get("method_end")
    if method_start and method_end:
        try:
            return replace_method(
                original_source, method_start, method_end, patched_code
            )
        except Exception as e:
            logger.warning(f"replace_method failed: {e}")
            return None

    # 定位失败且 LLM 只返回了方法片段 —— 无法安全重建，跳过
    logger.warning(
        "No method line range available and patch is not a full file; skipping patch."
    )
    return None


class ExperimentRunner:
    """实验运行器"""

    def __init__(self, model=None):
        self.llm = LLMClient(model=model)
        self.validator = PatchValidator()

    def _get_buggy_code(self, bug_info, max_len=6000):
        """
        返回用于 prompt 的缺陷代码。
        优先使用定位到的缺陷方法（buggy_method_code），更聚焦；
        若定位失败则退回完整源文件。
        """
        method_code = bug_info.get("buggy_method_code")
        if method_code:
            return self._truncate(method_code, max_len)
        return self._truncate(bug_info["source_code"], max_len)

    # ====================== Basic 策略 ======================
    def run_basic(self, bug_info, max_attempts=None):
        """
        Basic 策略：直接生成补丁，多次独立尝试

        Returns:
            dict: 修复结果
        """
        max_attempts = max_attempts or config.MAX_ATTEMPTS_BASIC
        project = bug_info["project"]
        bug_id = bug_info["bug_id"]

        logger.info(f"[Basic] {project}-{bug_id}: Starting (max {max_attempts} attempts)")

        results = {
            "strategy": "basic",
            "project": project,
            "bug_id": bug_id,
            "attempts": [],
            "fixed": False,
            "total_attempts": 0,
        }

        prompt = BASIC_PROMPT.format(
            buggy_code=self._get_buggy_code(bug_info, 6000),
            test_code=self._truncate(bug_info.get("test_code", "N/A"), 3000),
            error_message=self._truncate(bug_info.get("error_message", "N/A"), 2000),
        )

        for attempt in range(max_attempts):
            logger.info(f"  Attempt {attempt + 1}/{max_attempts}")

            # 调用 LLM
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = self.llm.chat(messages)
            patched_code = self.llm.extract_code(response)

            attempt_result = {
                "attempt": attempt + 1,
                "response": response,
                "patched_code": patched_code,
                "validation": None,
            }

            if patched_code:
                # 验证补丁
                patched_source = build_patched_source(
                    bug_info, patched_code
                )
                if patched_source:
                    validation = self.validator.validate_patch(
                        project, bug_id, patched_source,
                        bug_info.get("source_file", "")
                    )
                    attempt_result["validation"] = validation

                    if validation["status"] == "pass":
                        logger.info(f"  -> FIXED at attempt {attempt + 1}!")
                        results["fixed"] = True
                        results["total_attempts"] = attempt + 1
                        results["attempts"].append(attempt_result)
                        return results

                    logger.info(f"  -> {validation['status']}")
                else:
                    logger.info("  -> Failed to apply patch")
            else:
                logger.info("  -> Failed to extract code from response")

            results["attempts"].append(attempt_result)

        results["total_attempts"] = max_attempts
        return results

    # ====================== Diagnostic 策略 ======================
    def run_diagnostic(self, bug_info, max_attempts=None):
        """
        Diagnostic 策略：先诊断后修复，两轮对话

        Returns:
            dict: 修复结果
        """
        max_attempts = max_attempts or config.MAX_ATTEMPTS_DIAGNOSTIC
        project = bug_info["project"]
        bug_id = bug_info["bug_id"]

        logger.info(f"[Diagnostic] {project}-{bug_id}: Starting")

        results = {
            "strategy": "diagnostic",
            "project": project,
            "bug_id": bug_id,
            "attempts": [],
            "fixed": False,
            "total_attempts": 0,
        }

        for attempt in range(max_attempts):
            logger.info(f"  Attempt {attempt + 1}/{max_attempts}")

            # 第1轮：诊断
            diag_prompt = DIAGNOSTIC_PHASE1_PROMPT.format(
                buggy_code=self._get_buggy_code(bug_info, 6000),
                test_code=self._truncate(bug_info.get("test_code", "N/A"), 3000),
                error_message=self._truncate(bug_info.get("error_message", "N/A"), 2000),
            )
            messages_phase1 = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": diag_prompt},
            ]
            diagnosis = self.llm.chat(messages_phase1)

            # 第2轮：基于诊断生成修复
            fix_prompt = DIAGNOSTIC_PHASE2_PROMPT.format(
                buggy_code=self._get_buggy_code(bug_info, 6000),
                diagnosis=diagnosis,
            )
            messages_phase2 = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": fix_prompt},
            ]
            response = self.llm.chat(messages_phase2)
            patched_code = self.llm.extract_code(response)

            attempt_result = {
                "attempt": attempt + 1,
                "diagnosis": diagnosis,
                "response": response,
                "patched_code": patched_code,
                "validation": None,
            }

            if patched_code:
                patched_source = build_patched_source(
                    bug_info, patched_code
                )
                if patched_source:
                    validation = self.validator.validate_patch(
                        project, bug_id, patched_source,
                        bug_info.get("source_file", "")
                    )
                    attempt_result["validation"] = validation

                    if validation["status"] == "pass":
                        logger.info(f"  -> FIXED at attempt {attempt + 1}!")
                        results["fixed"] = True
                        results["total_attempts"] = attempt + 1
                        results["attempts"].append(attempt_result)
                        return results

                    logger.info(f"  -> {validation['status']}")

            results["attempts"].append(attempt_result)

        results["total_attempts"] = max_attempts
        return results

    # ====================== Iterative 策略 ======================
    def run_iterative(self, bug_info, max_breadth=None, max_depth=None):
        """
        Iterative 策略：广度+深度迭代修复

        广度：多次独立尝试
        深度：每次尝试中，如果测试部分通过，基于反馈迭代修复

        Returns:
            dict: 修复结果
        """
        max_breadth = max_breadth or config.MAX_BREADTH
        max_depth = max_depth or config.MAX_DEPTH
        project = bug_info["project"]
        bug_id = bug_info["bug_id"]

        logger.info(f"[Iterative] {project}-{bug_id}: Starting (B={max_breadth}, D={max_depth})")

        results = {
            "strategy": "iterative",
            "project": project,
            "bug_id": bug_id,
            "attempts": [],
            "fixed": False,
            "total_attempts": 0,
        }

        total_attempts = 0

        for b in range(max_breadth):
            logger.info(f"  Breadth {b + 1}/{max_breadth}")

            # 首轮修复
            first_prompt = ITERATIVE_FIRST_PROMPT.format(
                buggy_code=self._get_buggy_code(bug_info, 6000),
                test_code=self._truncate(bug_info.get("test_code", "N/A"), 3000),
                error_message=self._truncate(bug_info.get("error_message", "N/A"), 2000),
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": first_prompt},
            ]
            response = self.llm.chat(messages)
            patched_code = self.llm.extract_code(response)
            total_attempts += 1

            if not patched_code:
                logger.info(f"    Depth 1: Failed to extract code")
                results["attempts"].append({
                    "breadth": b + 1, "depth": 1,
                    "response": response, "patched_code": None, "validation": None
                })
                continue

            # 验证首轮补丁
            patched_source = build_patched_source(
                bug_info, patched_code
            )
            if not patched_source:
                continue

            validation = self.validator.validate_patch(
                project, bug_id, patched_source, bug_info.get("source_file", "")
            )

            results["attempts"].append({
                "breadth": b + 1, "depth": 1,
                "response": response, "patched_code": patched_code,
                "validation": validation,
            })

            if validation["status"] == "pass":
                logger.info(f"    -> FIXED at breadth {b+1}, depth 1!")
                results["fixed"] = True
                results["total_attempts"] = total_attempts
                return results

            # 深度迭代（仅当测试失败时，编译失败直接跳过）
            if validation["status"] == "compile_error":
                logger.info(f"    Depth 1: compile_error, skip depth")
                continue

            prev_patch = patched_code
            for d in range(2, max_depth + 1):
                logger.info(f"    Depth {d}/{max_depth}")

                # 构建反馈提示
                test_feedback = (
                    f"Status: {validation['status']}\n"
                    f"Failed tests: {validation['tests_failed']}\n"
                    f"Error: {validation['error_message'][:1500]}"
                )
                followup_prompt = ITERATIVE_FOLLOWUP_PROMPT.format(
                    buggy_code=self._get_buggy_code(bug_info, 4000),
                    previous_patch=prev_patch,
                    test_feedback=test_feedback,
                )
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": followup_prompt},
                ]
                response = self.llm.chat(messages)
                patched_code = self.llm.extract_code(response)
                total_attempts += 1

                if not patched_code:
                    logger.info(f"    Depth {d}: Failed to extract code")
                    break

                patched_source = build_patched_source(
                    bug_info, patched_code
                )
                if not patched_source:
                    break

                validation = self.validator.validate_patch(
                    project, bug_id, patched_source, bug_info.get("source_file", "")
                )
                results["attempts"].append({
                    "breadth": b + 1, "depth": d,
                    "response": response, "patched_code": patched_code,
                    "validation": validation,
                })

                if validation["status"] == "pass":
                    logger.info(f"    -> FIXED at breadth {b+1}, depth {d}!")
                    results["fixed"] = True
                    results["total_attempts"] = total_attempts
                    return results

                if validation["status"] == "compile_error":
                    logger.info(f"    Depth {d}: compile_error, break depth")
                    break

                prev_patch = patched_code

        results["total_attempts"] = total_attempts
        return results

    def _truncate(self, text, max_len):
        """截断文本"""
        if not text:
            return "N/A"
        if len(text) <= max_len:
            return text
        return text[:max_len] + "\n... (truncated)"


def run_full_experiment(bugs, strategy, model, output_dir):
    """运行完整实验"""
    runner = ExperimentRunner(model=model)

    # 选择策略
    strategies = {
        "basic": runner.run_basic,
        "diagnostic": runner.run_diagnostic,
        "iterative": runner.run_iterative,
    }

    if strategy == "all":
        strategy_list = ["basic", "diagnostic", "iterative"]
    else:
        strategy_list = [strategy]

    for strat_name in strategy_list:
        strat_func = strategies[strat_name]
        strat_dir = os.path.join(output_dir, strat_name)
        os.makedirs(strat_dir, exist_ok=True)

        logger.info(f"\n{'='*60}")
        logger.info(f"Running strategy: {strat_name}")
        logger.info(f"Total bugs: {len(bugs)}")
        logger.info(f"{'='*60}\n")

        all_results = []
        fixed_count = 0

        for bug in tqdm(bugs, desc=f"[{strat_name}]"):
            bug_key = f"{bug['project']}-{bug['bug_id']}"

            # 检查是否已有结果（断点续传）
            result_file = os.path.join(strat_dir, f"{bug_key}.json")
            if os.path.isfile(result_file):
                logger.info(f"Skipping {bug_key} (already processed)")
                with open(result_file, "r") as f:
                    result = json.load(f)
                all_results.append(result)
                if result.get("fixed"):
                    fixed_count += 1
                continue

            try:
                result = strat_func(bug)
            except Exception as e:
                logger.error(f"Error processing {bug_key}: {e}")
                result = {
                    "strategy": strat_name,
                    "project": bug["project"],
                    "bug_id": bug["bug_id"],
                    "fixed": False,
                    "error": str(e),
                }

            # 保存单个结果
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False, default=str)

            all_results.append(result)
            if result.get("fixed"):
                fixed_count += 1

            logger.info(
                f"Progress: {fixed_count}/{len(all_results)} fixed "
                f"({fixed_count/len(all_results)*100:.1f}%)"
            )

        # 保存汇总结果
        summary = {
            "strategy": strat_name,
            "model": model or config.DEEPSEEK_MODEL,
            "timestamp": datetime.now().isoformat(),
            "total_bugs": len(bugs),
            "total_processed": len(all_results),
            "total_fixed": fixed_count,
            "fix_rate": round(fixed_count / max(len(all_results), 1) * 100, 2),
            "api_stats": runner.llm.get_stats(),
        }

        summary_file = os.path.join(strat_dir, "_summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"\n[{strat_name}] Summary: {fixed_count}/{len(all_results)} fixed "
                     f"({summary['fix_rate']}%)")
        logger.info(f"API Stats: {runner.llm.get_stats()}")


def main():
    parser = argparse.ArgumentParser(description="Run APR experiment")
    parser.add_argument("--bugs", required=True, help="Path to bugs.json")
    parser.add_argument(
        "--strategy",
        choices=["basic", "diagnostic", "iterative", "all"],
        default="all",
        help="Repair strategy to use",
    )
    parser.add_argument("--model", default=None, help="LLM model name")
    parser.add_argument("--output", default="results/", help="Output directory")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of bugs")
    args = parser.parse_args()

    # 检查 API key
    if not config.DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set! Run: export DEEPSEEK_API_KEY='your_key'")
        sys.exit(1)

    # 加载缺陷数据
    bugs_path = os.path.join(config.PROJECT_ROOT, args.bugs)
    with open(bugs_path, "r", encoding="utf-8") as f:
        bugs = json.load(f)

    if args.limit:
        bugs = bugs[: args.limit]

    logger.info(f"Loaded {len(bugs)} bugs from {bugs_path}")

    output_dir = os.path.join(config.PROJECT_ROOT, args.output)
    os.makedirs(output_dir, exist_ok=True)

    run_full_experiment(bugs, args.strategy, args.model, output_dir)


if __name__ == "__main__":
    main()
