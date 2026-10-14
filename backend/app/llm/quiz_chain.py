"""出题 Chain -- 用 LangChain 把「用户输入 + 参考资料」变成「结构化题目」.

这个文件是干什么的:
调 DeepSeek 生成题目的最后一环. 它做两件事:
1. 拼提示词 (系统提示词 + 用户提示词 + 搜索上下文)
2. 调 LLM 生成 JSON, 再解析 + 校验成 QuizOutput (结构化题目)

怎么保证 LLM 输出稳定 JSON (面试重点):
大模型输出是自由文本, 容易胡来. 这里用了「三层保险」:
1. 提示词约束: 系统提示词里明确要求输出 JSON 格式
2. _extract_json: 兼容 LLM 把 JSON 包在 ```json ``` 代码块里的情况
3. QuizOutput.model_validate: 用 Pydantic 校验, 字段对不上直接报错
"""

import json
import re

import structlog
from langchain_core.prompts import ChatPromptTemplate

from app.llm.langchain_factory import get_chat_model
from app.models.quiz import QuizOutput
from app.prompts.quiz_prompt import QUIZ_HUMAN_PROMPT, QUIZ_SYSTEM_PROMPT, SEARCH_CONTEXT_TEMPLATE

logger = structlog.get_logger()


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON, 兼容 markdown 代码块包裹.

    LLM 经常把 JSON 包在 ```json ... ``` 里返回, 直接 json.loads 会失败,
    所以先用正则把代码块剥掉, 再解析.
    """
    # 尝试提取 ```json ... ``` (或 ``` ... ```) 包裹的内容
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = match.group(1).strip() if match else text.strip()
    return json.loads(raw)


async def generate_quiz(
    user_input: str,
    question_count: int = 5,
    difficulty: str = "mixed",
    search_context: str = "",
) -> QuizOutput:
    """调 DeepSeek 生成一套结构化题目.

    参数:
        user_input: 用户输入的学习内容
        question_count: 出几题 (3~10)
        difficulty: 难度 (easy/medium/hard/mixed)
        search_context: 联网搜索/RAG 拿到的参考资料 (可为空)
    返回:
        QuizOutput: 经过 Pydantic 校验的结构化题目
    """
    llm = get_chat_model(temperature=0.4)  # 出题用稍高温度 (0.4), 题目更有变化; 搜索决策才用 0.1

    # 把参考资料包进一个模板段落; 没资料就留空
    search_context_section = (
        SEARCH_CONTEXT_TEMPLATE.format(search_context=search_context)
        if search_context
        else ""
    )

    # 拼提示词: 系统提示词 (定规则) + 用户提示词 (带参数)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", QUIZ_SYSTEM_PROMPT),
            ("human", QUIZ_HUMAN_PROMPT),
        ]
    )

    # LangChain 的「链」: prompt -> llm, 把填好参数的提示词喂给 LLM
    chain = prompt | llm

    result = await chain.ainvoke(
        {
            "user_input": user_input,
            "question_count": question_count,
            "difficulty": difficulty,
            "search_context_section": search_context_section,
        }
    )

    content = result.content
    logger.debug("llm_quiz_raw_response", content_length=len(content), content_preview=content[:200] if content else "<empty>")

    if not content:
        raise ValueError("LLM 返回内容为空")

    # 三层保险: 提取 JSON -> Pydantic 校验成 QuizOutput (字段对不上会抛错)
    data = _extract_json(content)
    return QuizOutput.model_validate(data)
