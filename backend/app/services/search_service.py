"""知识获取服务 -- 用 LangGraph ReAct Agent 联网搜索获取最新知识.

这个文件是干什么的:
当用户出题 (没上传私有文档) 时, 这里负责「联网搜资料」:
用一个大模型驱动的 Agent, 让它自己决定搜什么, 搜几轮, 要不要深入,
最终返回一段「知识摘要」喂给后面的出题环节 (quiz_chain), 让题目内容更新, 更准.

什么是 ReAct Agent (面试核心概念):
ReAct = Reasoning (推理) + Acting (行动).
普通的大模型调用是「一问一答」: 给它问题, 它直接答.
而 Agent 是「多轮循环」: 大模型先思考要不要查资料 -> 调用搜索工具 ->
拿到结果再思考够不够 -> 不够就再搜一轮 -> 觉得够了才输出最终答案.
这里的「大脑」是 DeepSeek, 「手脚」是 3 个 Tavily 搜索工具.

核心流程总览:
fetch_knowledge_context(user_input):
    1) 检查开关 (enable_web_search / tavily_api_key, 没配就返回空)
    2) _build_agent() 构建 Agent (DeepSeek + 3 个 Tavily 工具)
    3) agent.ainvoke() 跑 Agent (多轮 ReAct 循环, 带超时和轮数上限)
    4) 取 Agent 最终回复, 截断后返回
    失败/超时 -> 返回空字符串 (降级, 不阻塞出题)
"""

import asyncio
import time

import structlog

from app.core.config import get_settings
from app.prompts.search_prompt import SEARCH_AGENT_SYSTEM_PROMPT

logger = structlog.get_logger()

MAX_CONTEXT_LENGTH = 5000  # 知识摘要的最大字符数, 防止喂给出题 LLM 的上下文过长
AGENT_TIMEOUT_SECONDS = 120  # Agent 整体超时 (秒), 防止无限搜索拖垮请求


def _build_agent():
    """构建联网搜索 Agent: DeepSeek (大脑) + 3 个 Tavily 工具 (手脚).

    返回: (agent, tool_logger)
        agent: LangGraph 的 ReAct Agent, 调用 .ainvoke() 就能跑起来
        tool_logger: 回调处理器, 把每次工具调用/LLM 决策写进日志 (可观测性)
    """
    from langchain_core.callbacks import AsyncCallbackHandler
    from langgraph.prebuilt import create_react_agent
    from langchain_openai import ChatOpenAI
    from langchain_tavily import TavilyExtract, TavilySearch

    settings = get_settings()

    class _ToolLogger(AsyncCallbackHandler):
        """回调处理器: 专门记录 Agent 每一步干了什么, 方便调试和观测.

        本身不影响 Agent 行为, 纯粹是「在旁边记日志」的旁观者.
        """

        async def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
            # 工具开始被调用时: 记录工具名和入参
            tool_name = serialized.get("name", "unknown")
            logger.info("tool_call_start", tool=tool_name, input=str(input_str)[:500])

        async def on_tool_end(self, output, *, run_id, **kwargs):
            # 工具调用结束: 记录返回内容的长度和预览
            logger.info("tool_call_end", output_length=len(str(output)), output_preview=str(output)[:500])

        async def on_tool_error(self, error, *, run_id, **kwargs):
            # 工具调用报错: 记录错误
            logger.warning("tool_call_error", error=str(error)[:300])

        async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
            # LLM 开始推理时: 记录用的是哪个模型
            logger.debug("llm_call_start", model=serialized.get("kwargs", {}).get("model", "unknown"))

        async def on_llm_end(self, response, *, run_id, **kwargs):
            # LLM 推理结束: 重点记录它「决定调用哪些工具」 (这是 Agent 的决策核心)
            try:
                gen = response.generations[0][0]
                msg = getattr(gen, "message", None)
                if msg and getattr(msg, "tool_calls", None):
                    # 这一轮 LLM 决定调工具了, 记录工具名和参数
                    logger.info("llm_tool_decision", tool_calls=[
                        {"name": tc["name"], "args": str(tc["args"])[:200]}
                        for tc in msg.tool_calls
                    ])
                else:
                    # 这一轮没调工具 (说明 Agent 觉得资料够了, 要输出了)
                    content = getattr(msg, "content", "") if msg else str(gen)[:200]
                    logger.debug("llm_call_end", content_preview=str(content)[:200])
            except Exception:
                logger.debug("llm_call_end", raw=str(response)[:200])

    tool_logger = _ToolLogger()

    # 工具 1: 轻量搜索 -- 只返回摘要, 快速. 适合首轮广泛搜索, 快速了解主题全貌.
    tavily_search_basic = TavilySearch(
        name="tavily_search_basic",
        description="轻量搜索，返回最多 10 条结果的摘要。适合首轮广泛搜索，快速了解主题全貌，帮助判断正确领域。",
        max_results=10,
        include_raw_content=False,  # 不要完整正文, 只要摘要, 快
        include_answer=False,
        tavily_api_key=settings.tavily_api_key,
    )

    # 工具 2: 深度搜索 -- 返回完整页面内容. 适合深入了解专业, 小众主题.
    tavily_search_deep = TavilySearch(
        name="tavily_search_deep",
        description="深度搜索，返回最多 10 条结果的完整页面内容。适合深入了解专业、小众或容易混淆的主题，获取详细知识。",
        max_results=10,
        include_raw_content=True,  # 要完整正文, 深但慢
        include_answer=False,
        tavily_api_key=settings.tavily_api_key,
    )

    # 工具 3: URL 提取 -- 从指定网址抓全文. 适合用户输入里带了网址的情况.
    tavily_extract = TavilyExtract(
        name="tavily_extract",
        description="从指定 URL 提取页面完整内容。当用户输入包含网址时使用。",
        extract_depth="basic",
        tavily_api_key=settings.tavily_api_key,
    )

    # 把 3 个工具打包, Agent 会自己决定「什么时候用哪个」
    tools = [tavily_search_basic, tavily_search_deep, tavily_extract]

    # Agent 的「大脑」: DeepSeek. temperature=0.1 低温度, 让搜索决策更稳定, 少胡来
    llm = ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0.1,
        callbacks=[tool_logger],  # 挂上日志回调
    )

    # 核心: create_react_agent 把「大脑 + 工具 + 提示词」组装成一个 ReAct Agent
    agent = create_react_agent(
        llm,                          # 大脑: DeepSeek
        tools=tools,                  # 手脚: 3 个搜索工具
        prompt=SEARCH_AGENT_SYSTEM_PROMPT,  # 系统提示词: 告诉 Agent 它的角色和任务
    )

    return agent, tool_logger


async def fetch_knowledge_context(user_input: str) -> str:
    """获取知识上下文: 跑联网搜索 Agent, 返回一段知识摘要.

    参数:
        user_input: 用户输入的学习内容 (关键词 / 一段话 / 网址)
    返回:
        知识摘要字符串; 任何失败 (未配置/超时/异常) 都返回空字符串, 不抛异常.
    """
    settings = get_settings()

    # 1) 配置开关检查: 没开搜索, 或没配 Tavily Key, 直接降级返回空
    if not settings.enable_web_search:
        logger.info("web_search_disabled")
        return ""

    if not settings.tavily_api_key:
        logger.warning("tavily_api_key_not_configured")
        return ""

    try:
        logger.info("search_agent_starting", user_input=user_input[:100])

        t0 = time.monotonic()
        agent, tool_logger = _build_agent()
        logger.debug("search_agent_built", elapsed_ms=round((time.monotonic() - t0) * 1000))

        # 2) 跑 Agent: asyncio.wait_for 设整体超时, 防止 Agent 无限搜索拖死请求
        t1 = time.monotonic()
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config={
                    "recursion_limit": 10,     # 最多「思考+行动」循环 10 轮, 防死循环
                    "callbacks": [tool_logger],  # 挂上日志回调
                },
            ),
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        elapsed = round((time.monotonic() - t1) * 1000)

        # 3) 打印 Agent 完整消息链路 (调试用): 看它每一轮想了什么, 调了什么工具
        messages = result.get("messages", [])
        logger.info(
            "search_agent_completed",
            elapsed_ms=elapsed,
            message_count=len(messages),
            message_types=[type(m).__name__ for m in messages],
        )
        for i, msg in enumerate(messages):
            msg_type = type(msg).__name__
            content_preview = str(getattr(msg, "content", ""))[:200]
            tool_calls = getattr(msg, "tool_calls", None)
            logger.debug(
                "search_agent_message",
                index=i,
                type=msg_type,
                content_preview=content_preview,
                tool_calls=len(tool_calls) if tool_calls else 0,
            )

        # 4) 取 Agent 最终回复 (消息列表最后一条就是 Agent 的最终答案)
        content = result["messages"][-1].content
        if not content:
            logger.warning("search_agent_empty_response")
            return ""

        # 5) 截断到最大长度, 防止上下文过长
        if len(content) > MAX_CONTEXT_LENGTH:
            content = content[:MAX_CONTEXT_LENGTH]
            logger.info("search_context_truncated", original_length=len(result["messages"][-1].content))

        logger.info("search_context_fetched", length=len(content))
        return content

    except asyncio.TimeoutError:
        # 超时: 记录日志, 返回空 (降级, 不让出题失败)
        elapsed = round((time.monotonic() - t1) * 1000) if 't1' in dir() else -1
        logger.warning("search_agent_timeout", timeout=AGENT_TIMEOUT_SECONDS, elapsed_ms=elapsed, user_input=user_input[:100])
        return ""
    except Exception as e:
        # 任何其他异常: 记录日志, 返回空 (降级, 不让出题失败)
        logger.warning("search_agent_error", error=str(e), error_type=type(e).__name__, user_input=user_input[:100])
        return ""
