"""LangChain ChatOpenAI 工厂 -- 统一创建 LLM 实例.

这个文件是干什么的:
封装「怎么创建 DeepSeek 的 LLM 客户端」, 供各处的 Chain/Agent 调用.
用「工厂函数」的好处: LLM 的配置 (model/base_url/api_key) 集中在一处,
改配置只改这里或 .env, 不用到处改.
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import get_settings


@lru_cache()
def get_chat_model(temperature: float = 0.4) -> ChatOpenAI:
    """创建 (并缓存) 一个 DeepSeek 的 ChatOpenAI 实例.

    参数:
        temperature: 随机性 0~1. 越低越稳定 (搜索 Agent 用 0.1), 越高越有创意 (出题用 0.4).
    返回:
        ChatOpenAI 实例 (LangChain 的标准 LLM 接口)

    为什么 DeepSeek 用 ChatOpenAI 类:
    DeepSeek 提供了 OpenAI 兼容的接口, 所以直接复用 langchain_openai 的 ChatOpenAI,
    只要把 base_url 指向 DeepSeek 即可.
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,  # 指向 DeepSeek 而不是 OpenAI
        api_key=settings.deepseek_api_key,
        temperature=temperature,
        max_tokens=4096,
    )
