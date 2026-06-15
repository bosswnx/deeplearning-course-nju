"""
Java 源码处理工具：定位缺陷所在方法的行范围、提取方法体
"""
import re


def find_enclosing_method(source_lines, target_lineno):
    """
    给定源码行列表和缺陷行号(1-indexed)，找到包含该行的最内层方法/构造器的行范围。

    采用括号配对法：
    1. 识别候选方法签名行（含修饰符/返回类型/方法名/参数，且其后存在 '{'）
    2. 对每个候选，从签名后的第一个 '{' 开始计数，找到配对的 '}'
    3. 返回包含 target_lineno 的、范围最小的方法

    Args:
        source_lines: list[str]，源文件按行分割（不含换行符）
        target_lineno: int，缺陷行号（1-indexed）

    Returns:
        (start_line, end_line): 1-indexed 闭区间；找不到返回 (None, None)
    """
    # 方法签名的启发式正则：可选修饰符 + 返回类型/构造器 + 方法名 + (
    # 排除控制流关键字 if/for/while/switch/catch 等
    sig_pattern = re.compile(
        r"^\s*"
        r"(?:@\w+(?:\([^)]*\))?\s*)*"  # 注解
        r"(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*"
        r"(?:<[^>]+>\s*)?"            # 泛型
        r"[\w\[\]<>,.\s?]+?\s+"        # 返回类型
        r"(\w+)\s*"                    # 方法名
        r"\([^;{]*"                    # 参数（不含 ; 避免匹配抽象方法声明/字段）
    )
    control_kw = {"if", "for", "while", "switch", "catch", "synchronized", "return", "new"}

    candidates = []  # (start_line, end_line)

    n = len(source_lines)
    i = 0
    while i < n:
        line = source_lines[i]
        m = sig_pattern.match(line)
        if m and m.group(1) not in control_kw:
            # 从当前行起，向后寻找方法体的第一个 '{'（可能跨多行的参数列表）
            found_open = False
            depth = 0
            method_start = i  # 0-indexed
            j = i
            # 扫描至多 20 行寻找 '{'，方法体本身不设上限
            sig_end = i + 20
            while j < n and (j < sig_end or found_open):
                seg = source_lines[j]
                # 如果遇到 ';' 且还没遇到 '{'，说明是抽象方法/字段声明，跳过
                if not found_open and ";" in seg and "{" not in seg.split(";")[0]:
                    break
                if "{" in seg:
                    found_open = True
                if found_open:
                    depth += seg.count("{") - seg.count("}")
                    if depth <= 0 and (seg.count("{") > 0 or seg.count("}") > 0):
                        # 方法体结束
                        candidates.append((method_start + 1, j + 1))  # 1-indexed
                        i = j
                        break
                j += 1
        i += 1

    # 选择包含 target_lineno 的最小范围
    enclosing = [
        (s, e) for (s, e) in candidates if s <= target_lineno <= e
    ]
    if not enclosing:
        return None, None

    enclosing.sort(key=lambda x: x[1] - x[0])
    return enclosing[0]


def extract_method_code(source_lines, start_line, end_line):
    """提取指定行范围的代码（1-indexed 闭区间）"""
    return "\n".join(source_lines[start_line - 1 : end_line])


def replace_method(source_code, start_line, end_line, new_method_code):
    """
    用 new_method_code 替换 source_code 中 [start_line, end_line] 范围的内容，
    返回重建后的完整源文件。

    Args:
        source_code: str，原始完整源文件
        start_line, end_line: 1-indexed 闭区间
        new_method_code: str，LLM 生成的修复后方法

    Returns:
        str: 重建后的完整源文件
    """
    lines = source_code.split("\n")
    new_lines = (
        lines[: start_line - 1]
        + new_method_code.rstrip("\n").split("\n")
        + lines[end_line:]
    )
    return "\n".join(new_lines)
