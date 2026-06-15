# LLM-APR: 基于大语言模型的自动化程序修复实验

## 实验概述

本实验使用 DeepSeek-V4 大语言模型，在 Defects4J 基准数据集上评估 LLM 驱动的自动化程序修复（APR）效果。

实验设计三种修复策略进行对比：
1. **Basic**: 直接将缺陷代码输入 LLM，单轮生成补丁
2. **Diagnostic**: 分两轮对话（先诊断缺陷原因，再生成补丁）
3. **Iterative**: 迭代修复，若补丁未通过测试则将失败信息反馈给 LLM 再次生成

## 环境要求

### 系统
- Ubuntu 20.04+ (推荐) 或 macOS
- Java 8 (JDK 1.8)
- Python 3.10+
- Git, SVN, Perl 5.0.12+

### Python 依赖
```bash
pip install -r requirements.txt
```

### Defects4J 安装
```bash
# 1. 克隆 Defects4J
git clone https://github.com/rjust/defects4j.git
cd defects4j
git checkout tags/v2.0.1 -b v2.0.1

# 2. 初始化
./init.sh

# 3. 添加到 PATH
export PATH=$PATH:$(pwd)/framework/bin

# 4. 验证安装
defects4j info -p Lang
```

### DeepSeek API
```bash
export DEEPSEEK_API_KEY="your_api_key_here"
```

## 快速开始

```bash
# 1. 提取缺陷数据（需要先安装 Defects4J）
python scripts/extract_bugs.py --output data/bugs.json

# 2. 运行实验（三种策略依次执行）
python scripts/run_experiment.py \
    --bugs data/bugs.json \
    --strategy all \
    --model deepseek-v4-flash \
    --output results/

# 3. 分析结果
python scripts/analyze_results.py --results-dir results/ --output results/analysis.md
```

## 目录结构

```
apr_experiment/
├── README.md               # 本文件
├── requirements.txt        # Python 依赖
├── config.py               # 全局配置
├── data/                   # 缺陷数据
│   └── bugs.json           # 提取的缺陷信息
├── prompts/                # 提示模板
│   └── templates.py        # 各策略的 Prompt 模板
├── scripts/
│   ├── extract_bugs.py     # 从 Defects4J 提取缺陷数据 + 定位缺陷方法行范围
│   ├── java_utils.py       # Java 方法定位与行级替换工具
│   ├── run_experiment.py   # 主实验脚本
│   ├── llm_client.py       # DeepSeek API 封装
│   ├── patch_validator.py  # 补丁验证
│   └── analyze_results.py  # 结果分析与可视化
└── results/                # 实验结果
    ├── basic/
    ├── diagnostic/
    └── iterative/
```

## 补丁应用机制（重要）

为保证 LLM 生成的补丁能正确编译，本实验采用**方法级行号替换**：

1. **提取阶段**：`extract_bugs.py` 通过 `defects4j export -p lines.buggy` 获取缺陷行号，再用 `java_utils.find_enclosing_method` 通过括号配对法定位包含缺陷的方法起止行，单独保存 `buggy_method_code`、`method_start`、`method_end`。
2. **提示阶段**：只把**缺陷方法**（而非整个文件）放进 prompt，并明确要求模型「只返回方法、不要 package/import/class」。
3. **应用阶段**：`build_patched_source` 用 `java_utils.replace_method` 把模型返回的方法替换回原文件对应行，**保留 package、import、class 声明**，从而保证编译通过。

> 之前版本的 bug：当模型只返回一个方法时，旧代码把它当成整个 .java 文件覆盖写入，丢失了 package/import/class，导致必然 compile_error。现已修复。

## 关于 DeepSeek-V4 思考模式

DeepSeek-V4-Flash 默认开启思考模式，响应慢且输出长，代码块易被 `max_tokens` 截断。本实验在 `config.py` 中默认设置 `ENABLE_THINKING = False`（关闭思考模式），并将 `MAX_TOKENS` 提高到 8192。`llm_client.extract_code` 也增加了对**截断/未闭合代码块**的兜底提取逻辑。

