"""
DeepSeek API 客户端封装
"""
import time
import re
import logging
from openai import OpenAI

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

logger = logging.getLogger(__name__)


class LLMClient:
    """DeepSeek V4 API 客户端"""

    def __init__(self, model=None, api_key=None, base_url=None):
        self.model = model or config.DEEPSEEK_MODEL
        self.client = OpenAI(
            api_key=api_key or config.DEEPSEEK_API_KEY,
            base_url=base_url or config.DEEPSEEK_BASE_URL,
        )
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0

    def chat(self, messages, temperature=None, max_tokens=None):
        """
        发送对话请求

        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
            temperature: 采样温度
            max_tokens: 最大输出 token 数

        Returns:
            str: 模型回复内容
        """
        temperature = temperature if temperature is not None else config.TEMPERATURE
        max_tokens = max_tokens or config.MAX_TOKENS

        max_retries = 3
        for attempt in range(max_retries):
            try:
                kwargs = dict(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    top_p=config.TOP_P,
                    max_tokens=max_tokens,
                )
                # DeepSeek-V4 通过 extra_body 控制思考模式（关闭可加速并减少截断）
                if hasattr(config, "ENABLE_THINKING"):
                    kwargs["extra_body"] = {
                        "thinking": {
                            "type": "enabled" if config.ENABLE_THINKING else "disabled"
                        }
                    }

                response = self.client.chat.completions.create(**kwargs)
                # 记录 token 消耗
                usage = response.usage
                if usage:
                    self.total_input_tokens += usage.prompt_tokens
                    self.total_output_tokens += usage.completion_tokens
                self.total_calls += 1

                return response.choices[0].message.content

            except Exception as e:
                # extra_body 不被支持时，去掉它重试一次
                if "thinking" in str(e).lower() or "extra_body" in str(e).lower():
                    try:
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            temperature=temperature,
                            top_p=config.TOP_P,
                            max_tokens=max_tokens,
                        )
                        usage = response.usage
                        if usage:
                            self.total_input_tokens += usage.prompt_tokens
                            self.total_output_tokens += usage.completion_tokens
                        self.total_calls += 1
                        return response.choices[0].message.content
                    except Exception:
                        pass

                logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** (attempt + 1)
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise

    def extract_code(self, response_text):
        """
        从 LLM 回复中提取 Java 代码块

        鲁棒处理：
        1. 优先匹配完整的 ```java ... ``` / ``` ... ``` 代码块
        2. 若代码块未闭合（被 max_tokens 截断），提取开标记之后的所有内容
        3. 若完全没有代码块标记，但内容看起来像 Java 方法，直接返回

        Args:
            response_text: LLM 的完整回复文本

        Returns:
            str: 提取的 Java 代码，如果提取失败返回 None
        """
        if not response_text:
            return None

        # 1. 完整的 ```java ... ``` 代码块
        pattern = r"```java\s*\n(.*?)```"
        matches = re.findall(pattern, response_text, re.DOTALL)
        if matches:
            return max(matches, key=len).strip()

        # 2. 完整的 ``` ... ``` 代码块
        pattern = r"```[a-zA-Z]*\s*\n(.*?)```"
        matches = re.findall(pattern, response_text, re.DOTALL)
        if matches:
            return max(matches, key=len).strip()

        # 3. 未闭合的代码块（被截断）：取开标记之后的内容
        m = re.search(r"```(?:java|[a-zA-Z]*)\s*\n(.*)$", response_text, re.DOTALL)
        if m:
            code = m.group(1).strip()
            if code:
                logger.warning("Code block appears truncated (no closing ```); using partial content.")
                return code

        # 4. 没有任何代码块标记，但内容像 Java 方法（含花括号和方法特征）
        stripped = response_text.strip()
        if "{" in stripped and "}" in stripped and (
            "public " in stripped or "private " in stripped
            or "protected " in stripped or "return" in stripped
        ):
            logger.warning("No code fence found; treating whole response as code.")
            return stripped

        return None

    def get_stats(self):
        """返回 API 调用统计"""
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_rmb": round(
                self.total_input_tokens / 1_000_000 * 1.0
                + self.total_output_tokens / 1_000_000 * 2.0,
                4,
            ),
        }
