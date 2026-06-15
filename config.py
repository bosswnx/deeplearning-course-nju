"""
全局配置文件
"""
import os

# ======================== DeepSeek API 配置 ========================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"  # 或 deepseek-v4-pro

# LLM 采样参数
TEMPERATURE = 0.8
TOP_P = 0.95
MAX_TOKENS = 8192  # 提高输出上限，避免长方法/思考模式下代码被截断

# DeepSeek-V4 思考模式：False=非思考(更快，适合修复任务)，True=思考模式
# 关闭思考模式可大幅缩短响应时间并降低代码块被截断的风险
ENABLE_THINKING = False

# ======================== Defects4J 配置 ========================
DEFECTS4J_HOME = os.environ.get("DEFECTS4J_HOME", os.path.expanduser("~/defects4j"))
DEFECTS4J_BIN = os.path.join(DEFECTS4J_HOME, "framework", "bin", "defects4j")

# 实验使用的项目和缺陷范围（Defects4J v1.2 的 6 个经典项目）
# 每个项目选取部分缺陷，控制总实验规模
PROJECTS = {
    "Chart":  list(range(1, 27)),     # 26 bugs
    "Lang":   list(range(1, 66)),     # 65 bugs
    "Math":   list(range(1, 107)),    # 106 bugs
    "Time":   list(range(1, 28)),     # 27 bugs
    "Closure": list(range(1, 134)),   # 133 bugs
    "Mockito": list(range(1, 39)),    # 38 bugs
}

# 如果你想快速测试，取消下面的注释，只用少量缺陷
# PROJECTS = {
#     "Chart": [1, 3, 5, 7, 9],
#     "Lang":  [1, 6, 10, 22, 33],
#     "Math":  [2, 5, 11, 30, 70],
# }

# ======================== 实验参数配置 ========================
# 每个缺陷的最大补丁尝试次数
MAX_ATTEMPTS_BASIC = 5        # Basic 策略：5 次独立尝试
MAX_ATTEMPTS_DIAGNOSTIC = 5   # Diagnostic 策略：5 次独立尝试
MAX_BREADTH = 3               # Iterative 策略：广度 3
MAX_DEPTH = 3                 # Iterative 策略：深度 3（总计最多 9 次）

# 实验重复次数
NUM_REPEATS = 1  # 设为 3 可以取平均，但 API 开销 ×3

# 超时设置（秒）
COMPILE_TIMEOUT = 120
TEST_TIMEOUT = 300

# ======================== 路径配置 ========================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
CHECKOUT_DIR = os.path.join(PROJECT_ROOT, "checkouts")  # Defects4J checkout 临时目录
