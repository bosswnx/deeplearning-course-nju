"""
补丁验证模块

负责：
1. 将 LLM 生成的补丁应用到缺陷项目
2. 编译并运行测试
3. 返回验证结果（通过/编译失败/测试失败+详细信息）
"""
import os
import re
import shutil
import subprocess
import logging

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

logger = logging.getLogger(__name__)


def run_cmd(cmd, cwd=None, timeout=300):
    """运行命令"""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


class PatchValidator:
    """补丁验证器"""

    def __init__(self, d4j_cmd=None):
        self.d4j_cmd = d4j_cmd or self._find_d4j()

    def _find_d4j(self):
        ret, out, _ = run_cmd("which defects4j")
        if ret == 0 and out.strip():
            return "defects4j"
        if os.path.isfile(config.DEFECTS4J_BIN):
            return config.DEFECTS4J_BIN
        raise RuntimeError("defects4j not found")

    def validate_patch(self, project, bug_id, patched_source, original_source_path):
        """
        验证一个补丁

        Args:
            project: 项目名 (e.g. "Math")
            bug_id: 缺陷编号
            patched_source: LLM 生成的完整修复后源文件内容
            original_source_path: 原始源文件的相对路径（从 checkout 根目录起算）

        Returns:
            dict: {
                "status": "pass" | "compile_error" | "test_fail" | "timeout" | "error",
                "tests_passed": int,
                "tests_failed": int,
                "error_message": str,
                "failing_tests": str,
            }
        """
        work_dir = os.path.join(config.CHECKOUT_DIR, f"{project}_{bug_id}_validate")

        try:
            # 1. Checkout buggy 版本
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir)

            cmd = f"{self.d4j_cmd} checkout -p {project} -v {bug_id}b -w {work_dir}"
            ret, _, err = run_cmd(cmd, timeout=120)
            if ret != 0:
                return self._error_result(f"Checkout failed: {err[:200]}")

            # 2. 获取源文件路径
            ret, src_dir, _ = run_cmd(
                f"{self.d4j_cmd} export -p dir.src.classes", cwd=work_dir
            )
            src_dir = src_dir.strip() if ret == 0 else "src/main/java"

            # 获取修改的类
            ret, classes, _ = run_cmd(
                f"{self.d4j_cmd} export -p classes.modified", cwd=work_dir
            )
            if ret != 0 or not classes.strip():
                return self._error_result("Cannot get modified classes")

            modified_class = classes.strip().split("\n")[0]
            class_file = modified_class.replace(".", "/") + ".java"
            target_path = os.path.join(work_dir, src_dir, class_file)

            # 处理内部类
            if not os.path.isfile(target_path):
                parts = modified_class.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    alt = "/".join(parts[:i]) + ".java"
                    alt_full = os.path.join(work_dir, src_dir, alt)
                    if os.path.isfile(alt_full):
                        target_path = alt_full
                        break

            if not os.path.isfile(target_path):
                return self._error_result(f"Source file not found: {target_path}")

            # 3. 应用补丁 —— 替换源文件内容
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(patched_source)

            # 4. 编译
            ret, out, err = run_cmd(
                f"{self.d4j_cmd} compile", cwd=work_dir, timeout=config.COMPILE_TIMEOUT
            )
            if ret != 0:
                compile_err = (err + out)[-2000:]  # 取最后 2000 字符
                return {
                    "status": "compile_error",
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "error_message": compile_err,
                    "failing_tests": "",
                }

            # 5. 运行测试
            ret, out, err = run_cmd(
                f"{self.d4j_cmd} test", cwd=work_dir, timeout=config.TEST_TIMEOUT
            )

            if ret == -1:  # timeout
                return {
                    "status": "timeout",
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "error_message": "Test execution timed out",
                    "failing_tests": "",
                }

            # 解析测试结果
            failing_tests_file = os.path.join(work_dir, "failing_tests")
            failing_tests = ""
            if os.path.isfile(failing_tests_file):
                with open(failing_tests_file, "r", encoding="utf-8", errors="ignore") as f:
                    failing_tests = f.read()

            if not failing_tests.strip():
                # 所有测试通过！
                # 解析通过数
                passed = 0
                m = re.search(r"(\d+)\s+test", out)
                if m:
                    passed = int(m.group(1))
                return {
                    "status": "pass",
                    "tests_passed": passed,
                    "tests_failed": 0,
                    "error_message": "",
                    "failing_tests": "",
                }
            else:
                # 仍有测试失败
                num_failing = failing_tests.count("--- ")
                # 截断
                if len(failing_tests) > 3000:
                    failing_tests = failing_tests[:3000] + "\n... (truncated)"
                return {
                    "status": "test_fail",
                    "tests_passed": 0,
                    "tests_failed": num_failing,
                    "error_message": failing_tests[:1000],
                    "failing_tests": failing_tests,
                }

        except Exception as e:
            return self._error_result(str(e))

        finally:
            # 清理
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)

    def _error_result(self, msg):
        return {
            "status": "error",
            "tests_passed": 0,
            "tests_failed": 0,
            "error_message": msg,
            "failing_tests": "",
        }
