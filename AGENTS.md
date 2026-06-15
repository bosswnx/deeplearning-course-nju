# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

LLM-APR: 大语言模型驱动的自动化程序修复 (Automated Program Repair) 实验项目。使用 DeepSeek-V4 模型在 Defects4J 基准数据集上评估三种修复策略的效果。配套课程报告：`深度学习赋能软件工程课程报告.md`。

## Quick Reference

```bash
# 虚拟环境
source .venv/bin/activate

# 一键完整运行
bash run.sh full

# 快速测试（小规模，仅 Basic 策略）
bash run.sh quick

# 分步运行
bash run.sh extract                           # 提取缺陷数据 -> data/bugs.json
bash run.sh experiment all [limit]             # 运行实验 -> results/
bash run.sh analyze                           # 分析结果 -> results/analysis.md

# 直接运行 Python 脚本
python scripts/extract_bugs.py --output data/bugs.json
python scripts/run_experiment.py --bugs data/bugs.json --strategy all --output results/
python scripts/analyze_results.py --results-dir results/ --output results/analysis.md

# 单独运行某个策略
python scripts/run_experiment.py --bugs data/bugs.json --strategy basic --output results/
python scripts/run_experiment.py --bugs data/bugs.json --strategy diagnostic --output results/
python scripts/run_experiment.py --bugs data/bugs.json --strategy iterative --output results/
```

## Architecture

```
config.py              # 全局配置 (API key, 模型参数, 数据集选择, 超时等)
run.sh                 # 一键运行入口，封装环境检查 + 全流程
prompts/templates.py   # 三种策略的 System/User Prompt 模板
scripts/
├── extract_bugs.py      # 从 Defects4J checkout 缺陷，提取源码/测试/行号信息 -> data/bugs.json
├── java_utils.py        # Java 源码解析：方法定位(括号配对法)、方法级行号替换
├── llm_client.py        # DeepSeek API 客户端 (OpenAI SDK 封装)，含代码提取与统计
├── patch_validator.py   # 补丁验证：checkout -> 替换源码 -> compile -> test
├── run_experiment.py    # 主实验运行：实现 Basic/Diagnostic/Iterative 三种策略，支持断点续传
└── analyze_results.py   # 结果分析：统计修复率/尝试次数/API 成本，生成 Markdown 报告
```

### Pipeline Stages

1. **Extract**: `extract_bugs.py` 调用 `defects4j checkout/export/test` 提取缺陷的源码、触发测试、错误信息和行号，定位缺陷所在方法
2. **Prompt**: `run_experiment.py` 根据策略选择对应的 prompt 模板 (`prompts/templates.py`)，填入缺陷信息和测试代码
3. **Generate**: `llm_client.py` 调用 DeepSeek API 生成修复代码，从回复中提取 Java 代码块
4. **Validate**: `patch_validator.py` 将生成的代码替换到源文件中，调用 `defects4j compile` + `defects4j test` 验证
5. **Analyze**: `analyze_results.py` 汇总三种策略的结果，生成对比报告

### Three Repair Strategies

| Strategy | Mechanism | Config |
|----------|-----------|--------|
| **Basic** | 直接提供缺陷代码和测试信息，要求 LLM 生成修复 | `MAX_ATTEMPTS_BASIC=5` |
| **Diagnostic** | 第1轮让 LLM 分析根因，第2轮基于诊断生成修复 | `MAX_ATTEMPTS_DIAGNOSTIC=5` |
| **Iterative** | 广度B×深度D的层次化迭代，失败反馈驱动改进 | `MAX_BREADTH=3, MAX_DEPTH=3` |

### Key Implementation Details

- **方法定位** (`java_utils.py`): 使用括号配对法而非 AST 解析，通过正则匹配 Java 方法签名，兼容泛型、注解、多种修饰符
- **代码替换** (`java_utils.py`): 方法级行号替换，保留 package/import/class 声明。若 LLM 返回完整文件代码则直接使用
- **断点续传** (`run_experiment.py`): 每个缺陷的结果保存为独立 JSON 文件，已存在的结果文件自动跳过
- **错误处理**: LLM 调用最多3次重试(指数退避)；编译120秒超时、测试300秒超时
- **思考模式**: 默认关闭 (`ENABLE_THINKING=False`) 以加速响应

### Environment Requirements

- Java 8 (必需，Defects4J 依赖)
- Python 3.10+ with venv
- Defects4J v2.0.1 (已安装在 `defects4j/` 目录)
- 需要设置 `DEEPSEEK_API_KEY` 环境变量
- Python 依赖: `openai>=1.30.0`, `tqdm>=4.65.0`

### Config Notes

Defects4J 路径默认为 `~/defects4j`，可通过 `DEFECTS4J_HOME` 环境变量覆盖。

实验使用 Defects4J v1.2 的6个经典项目（Chart, Lang, Math, Time, Closure, Mockito）共395个缺陷，仅包含单函数缺陷。
