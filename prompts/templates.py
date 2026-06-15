"""
各修复策略的 Prompt 模板
"""

# ======================== 系统提示 ========================
SYSTEM_PROMPT = """You are an expert Java developer specializing in bug fixing.
Your task is to fix a buggy Java method.

CRITICAL OUTPUT RULES (must follow exactly):
1. Return ONLY the complete fixed method, wrapped in a single ```java ... ``` code block.
2. Do NOT include the class declaration, imports, or package statement - only the method itself.
3. Put the code block FIRST in your response. Do NOT write any analysis or explanation before it.
4. Keep the method signature unchanged. Make minimal changes - fix the bug, do not refactor.
5. Keep the response concise so the code block is never truncated."""


# ======================== Basic 策略 ========================
BASIC_PROMPT = """Fix the following buggy Java function.

## Buggy Function
```java
{buggy_code}
```

## Failed Test
```java
{test_code}
```

## Error Message
```
{error_message}
```

Return the complete fixed function wrapped in ```java ... ``` code block."""


# ======================== Diagnostic 策略 - 第1轮：诊断 ========================
DIAGNOSTIC_PHASE1_PROMPT = """Analyze the following buggy Java function and diagnose the root cause of the bug.

## Buggy Function
```java
{buggy_code}
```

## Failed Test
```java
{test_code}
```

## Error Message
```
{error_message}
```

Please:
1. Explain what this function is supposed to do
2. Identify the exact location and root cause of the bug
3. Describe what the correct behavior should be
4. Suggest the specific fix needed

Be concise and precise in your diagnosis."""


# ======================== Diagnostic 策略 - 第2轮：修复 ========================
DIAGNOSTIC_PHASE2_PROMPT = """Based on the following bug diagnosis, generate the fixed function.

## Buggy Function
```java
{buggy_code}
```

## Bug Diagnosis
{diagnosis}

Return the complete fixed function wrapped in ```java ... ``` code block.
Only return the fixed function, no explanation needed."""


# ======================== Iterative 策略 - 首轮 ========================
ITERATIVE_FIRST_PROMPT = """Fix the following buggy Java function.

## Buggy Function
```java
{buggy_code}
```

## Failed Test
```java
{test_code}
```

## Error Message
```
{error_message}
```

Return the complete fixed function wrapped in ```java ... ``` code block."""


# ======================== Iterative 策略 - 后续轮 ========================
ITERATIVE_FOLLOWUP_PROMPT = """Your previous fix attempt was incorrect. Here is the feedback:

## Original Buggy Function
```java
{buggy_code}
```

## Your Previous Fix
```java
{previous_patch}
```

## Test Results for Your Fix
{test_feedback}

Please analyze why your fix was wrong and generate a corrected version.
Return the complete fixed function wrapped in ```java ... ``` code block."""
