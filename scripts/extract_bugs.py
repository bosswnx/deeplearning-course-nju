"""
从 Defects4J 提取缺陷信息（缺陷代码、测试代码、错误信息）

用法:
    python scripts/extract_bugs.py --output data/bugs.json [--projects Chart Lang Math]

前提条件:
    - Defects4J 已安装并添加到 PATH
    - Java 8 已安装
"""
import argparse
import json
import os
import re
import subprocess
import shutil
import logging
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from scripts.java_utils import find_enclosing_method, extract_method_code

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_cmd(cmd, cwd=None, timeout=300):
    """运行命令并返回输出"""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def get_defects4j_cmd():
    """获取 defects4j 命令路径"""
    # 优先使用 PATH 中的
    ret, out, _ = run_cmd("which defects4j")
    if ret == 0 and out.strip():
        return "defects4j"
    # 使用配置中的路径
    if os.path.isfile(config.DEFECTS4J_BIN):
        return config.DEFECTS4J_BIN
    raise RuntimeError(
        "defects4j not found! Please install Defects4J and add to PATH.\n"
        "See: https://github.com/rjust/defects4j"
    )


def checkout_bug(d4j_cmd, project, bug_id, work_dir):
    """Checkout 一个 buggy 版本"""
    checkout_path = os.path.join(work_dir, f"{project}_{bug_id}_buggy")
    if os.path.exists(checkout_path):
        shutil.rmtree(checkout_path)

    cmd = f"{d4j_cmd} checkout -p {project} -v {bug_id}b -w {checkout_path}"
    ret, out, err = run_cmd(cmd, timeout=120)
    if ret != 0:
        logger.warning(f"Failed to checkout {project}-{bug_id}: {err[:200]}")
        return None
    return checkout_path


def _get_buggy_lines_from_git(checkout_path, project, bug_id):
    """
    Defects4J v2.0 fallback: 用 git diff 获取缺陷行号。

    Defects4J v2.0 移除了 v1.2 中的 lines.buggy 属性。
    替代方案是通过 git diff 比较 BUGGY_VERSION 和 FIXED_VERSION，
    解析 unified diff 的 hunk header 提取 buggy 行号。

    解析规则（来自 unified diff @@ -old_start,old_count +new_start,new_count @@）:
    - old_count > 0: 取 old_start ~ old_start+old_count-1（被修改/删除的 buggy 行）
    - old_count == 0: 取 old_start（纯新增代码的插入点，bug 是缺失代码）

    返回与 lines.buggy 格式兼容的行号列表。
    """
    tag_buggy = f"D4J_{project}_{bug_id}_BUGGY_VERSION"
    tag_fixed = f"D4J_{project}_{bug_id}_FIXED_VERSION"
    cmd = (
        f"cd {checkout_path} && "
        f'git diff -U0 {tag_buggy} {tag_fixed} -- "*.java"'
    )
    ret, out, err = run_cmd(cmd, cwd=checkout_path)
    if ret != 0:
        logger.warning(f"git diff fallback failed: {err[:200]}")
        return []

    buggy_linenos = set()
    hunk_header_re = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,\d+)? @@")

    for line in out.split("\n"):
        m = hunk_header_re.match(line)
        if m:
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) else 1  # 默认 1 行
            if old_count > 0:
                for lineno in range(old_start, old_start + old_count):
                    buggy_linenos.add(lineno)
            else:
                buggy_linenos.add(old_start)

    return sorted(buggy_linenos)


def get_buggy_method(d4j_cmd, project, bug_id, checkout_path):
    """
    获取缺陷方法的源代码

    步骤:
    1. 用 defects4j export 获取修改的源文件和行号
    2. 从源文件中提取包含缺陷行的完整方法
    3. 行号获取优先使用 lines.buggy (v1.2)，fallback 到 git diff (v2.0)
    """
    # 获取修改的类
    ret, classes, _ = run_cmd(
        f"{d4j_cmd} export -p classes.modified", cwd=checkout_path
    )
    if ret != 0 or not classes.strip():
        return None

    modified_class = classes.strip().split("\n")[0]  # 取第一个修改的类

    # 获取修改的源文件路径
    ret, src_dir, _ = run_cmd(f"{d4j_cmd} export -p dir.src.classes", cwd=checkout_path)
    if ret != 0:
        return None
    src_dir = src_dir.strip()

    # 类名转文件路径
    class_file = modified_class.replace(".", "/") + ".java"
    src_path = os.path.join(checkout_path, src_dir, class_file)

    if not os.path.isfile(src_path):
        # 尝试内部类的情况
        parts = modified_class.split(".")
        for i in range(len(parts) - 1, 0, -1):
            alt_path = "/".join(parts[:i]) + ".java"
            alt_full = os.path.join(checkout_path, src_dir, alt_path)
            if os.path.isfile(alt_full):
                src_path = alt_full
                break
        else:
            logger.warning(f"Source file not found: {src_path}")
            return None

    try:
        with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
            source_code = f.read()
    except Exception as e:
        logger.warning(f"Failed to read {src_path}: {e}")
        return None

    # 获取缺陷行号 — 优先 v1.2 的 lines.buggy，失败则 fallback 到 git diff (v2.0)
    bug_linenos = _get_buggy_lines_from_git(checkout_path, project, bug_id)

    ret, bug_lines_raw, _ = run_cmd(
        f"{d4j_cmd} export -p lines.buggy", cwd=checkout_path
    )
    source = "git"
    if ret == 0 and bug_lines_raw.strip():
        # v1.2 格式: path#lineno (每行一个)，更精确，覆盖 git diff 结果
        d4j_linenos = []
        for entry in bug_lines_raw.strip().split("\n"):
            entry = entry.strip()
            if "#" in entry:
                try:
                    d4j_linenos.append(int(entry.split("#")[-1]))
                except ValueError:
                    pass
        if d4j_linenos:
            bug_linenos = d4j_linenos
            source = "d4j"

    # 定位缺陷所在方法的行范围
    source_lines = source_code.split("\n")
    method_start, method_end = None, None
    buggy_method_code = None

    if bug_linenos:
        # 用第一个缺陷行号定位包含它的方法
        target = bug_linenos[0]
        method_start, method_end = find_enclosing_method(source_lines, target)
        if method_start:
            buggy_method_code = extract_method_code(
                source_lines, method_start, method_end
            )

    rel_src_path = os.path.relpath(src_path, checkout_path)

    logger.info(
        f"  buggy lines (via {source}): {bug_linenos[:5]}{'...' if len(bug_linenos) > 5 else ''}"
    )

    return {
        "source_code": source_code,
        "source_file": src_path,
        "rel_source_file": rel_src_path,
        "modified_class": modified_class,
        "bug_linenos": bug_linenos,
        "method_start": method_start,
        "method_end": method_end,
        "buggy_method_code": buggy_method_code,
    }


def get_trigger_test(d4j_cmd, checkout_path):
    """获取触发缺陷的测试方法"""
    ret, tests, _ = run_cmd(
        f"{d4j_cmd} export -p tests.trigger", cwd=checkout_path
    )
    if ret != 0 or not tests.strip():
        return None, None

    # 格式: package.ClassName::methodName
    test_entry = tests.strip().split("\n")[0]

    # 获取测试源码目录
    ret, test_dir, _ = run_cmd(
        f"{d4j_cmd} export -p dir.src.tests", cwd=checkout_path
    )
    test_dir = test_dir.strip() if ret == 0 else "test"

    # 解析测试类和方法
    if "::" in test_entry:
        test_class, test_method = test_entry.split("::")
    else:
        test_class = test_entry
        test_method = ""

    # 读取测试文件
    test_file = os.path.join(
        checkout_path, test_dir, test_class.replace(".", "/") + ".java"
    )

    test_code = ""
    if os.path.isfile(test_file):
        try:
            with open(test_file, "r", encoding="utf-8", errors="ignore") as f:
                test_code = f.read()
        except:
            pass

    return test_entry, test_code


def get_failing_test_output(d4j_cmd, checkout_path):
    """运行失败测试获取错误信息"""
    ret, out, err = run_cmd(
        f"{d4j_cmd} test", cwd=checkout_path, timeout=config.TEST_TIMEOUT
    )
    # 获取失败测试输出
    failing_tests_file = os.path.join(checkout_path, "failing_tests")
    error_msg = ""
    if os.path.isfile(failing_tests_file):
        try:
            with open(failing_tests_file, "r", encoding="utf-8", errors="ignore") as f:
                error_msg = f.read()
        except:
            pass

    # 截断过长的错误信息
    if len(error_msg) > 3000:
        error_msg = error_msg[:3000] + "\n... (truncated)"

    return error_msg


def extract_single_bug(d4j_cmd, project, bug_id, work_dir):
    """提取单个缺陷的所有信息"""
    logger.info(f"Extracting {project}-{bug_id}...")

    # 1. Checkout buggy 版本
    checkout_path = checkout_bug(d4j_cmd, project, bug_id, work_dir)
    if not checkout_path:
        return None

    try:
        # 2. 获取缺陷代码及方法定位信息
        method_info = get_buggy_method(d4j_cmd, project, bug_id, checkout_path)
        if not method_info or not method_info.get("source_code"):
            return None

        # 3. 获取触发测试
        test_entry, test_code = get_trigger_test(d4j_cmd, checkout_path)

        # 4. 获取错误信息
        error_msg = get_failing_test_output(d4j_cmd, checkout_path)

        bug_info = {
            "project": project,
            "bug_id": bug_id,
            "modified_class": method_info["modified_class"],
            "source_file": method_info["source_file"],
            "rel_source_file": method_info["rel_source_file"],
            "source_code": method_info["source_code"],
            "bug_linenos": method_info["bug_linenos"],
            "method_start": method_info["method_start"],
            "method_end": method_info["method_end"],
            "buggy_method_code": method_info["buggy_method_code"],
            "trigger_test": test_entry,
            "test_code": test_code,
            "error_message": error_msg,
        }

        loc_ok = method_info["method_start"] is not None
        logger.info(
            f"  method localization: "
            f"{'OK lines %d-%d' % (method_info['method_start'], method_info['method_end']) if loc_ok else 'FAILED (will use full-file mode)'}"
        )

        return bug_info

    finally:
        # 清理 checkout 目录
        if os.path.exists(checkout_path):
            shutil.rmtree(checkout_path, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Extract bug info from Defects4J")
    parser.add_argument("--output", default="data/bugs.json", help="Output JSON file")
    parser.add_argument("--projects", nargs="*", default=None, help="Projects to extract")
    parser.add_argument("--max-per-project", type=int, default=None, help="Max bugs per project")
    args = parser.parse_args()

    d4j_cmd = get_defects4j_cmd()
    logger.info(f"Using defects4j: {d4j_cmd}")

    # 选择项目
    projects = config.PROJECTS
    if args.projects:
        projects = {p: v for p, v in projects.items() if p in args.projects}

    # 创建工作目录
    work_dir = config.CHECKOUT_DIR
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    all_bugs = []
    for project, bug_ids in projects.items():
        if args.max_per_project:
            bug_ids = bug_ids[: args.max_per_project]

        for bug_id in bug_ids:
            bug_info = extract_single_bug(d4j_cmd, project, bug_id, work_dir)
            if bug_info:
                all_bugs.append(bug_info)
                logger.info(
                    f"  -> Extracted {project}-{bug_id} "
                    f"(class: {bug_info['modified_class']})"
                )
            else:
                logger.warning(f"  -> Skipped {project}-{bug_id}")

    # 保存
    output_path = os.path.join(config.PROJECT_ROOT, args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_bugs, f, indent=2, ensure_ascii=False)

    logger.info(f"\nExtracted {len(all_bugs)} bugs -> {output_path}")


if __name__ == "__main__":
    main()
