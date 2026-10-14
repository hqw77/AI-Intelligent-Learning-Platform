"""知识库 Agentic RAG 检索服务 -- 结合知识库向量检索与联网搜索.

这个文件是干什么的:
出题时, 如果用户指定了私有文档 (doc_id), 就由这里负责「从文档里找参考资料」.
它和 search_service 的区别:
    search_service: 纯联网搜索 Agent (工具都是 Tavily)
    rag_service:     知识库检索 Agent (工具是「查向量库」+ 可选联网)

什么是 Agentic RAG (面试重点):
普通 RAG 是「固定流程」: 先检索 -> 直接喂给 LLM.
Agentic RAG 是「让 Agent 自己决定」: 检索结果不够 -> 换个问法再搜 -> 还不够就联网补.
这里用 LangGraph 的 ReAct Agent 实现, 工具 = 知识库检索 + (可选) 联网搜索.
"""

import asyncio
import time

import structlog

from app.core.config import get_settings
from app.prompts.rag_prompt import RAG_AGENT_SYSTEM_PROMPT
from app.services import vector_store_service

logger = structlog.get_logger()

MAX_CONTEXT_LENGTH = 3000  # 知识摘要最大字符数
AGENT_TIMEOUT_SECONDS = 60  # Agent 整体超时 (秒)


def _build_knowledge_base_tool(user_id: int, doc_id: str):
    """构建「知识库检索」工具 -- 把向量检索包装成 LangChain 的 tool.

    包装成 tool 后, Agent 就能把它当成一个「可调用的工具」:
    传入 query, 返回检索到的文本片段.
    """
    from langchain_core.tools import tool

    @tool
    def search_knowledge_base(query: str) -> str:
        """在用户上传的私有知识库文档中检索与 query 最相关的内容片段, 返回拼接后的文本."""
        try:
            # 在指定文档里检索与 query 最相似的几块
            docs = vector_store_service.similarity_search(user_id=user_id, doc_id=doc_id, query=query)
        except Exception as e:
            logger.warning("kb_retrieval_failed", user_id=user_id, doc_id=doc_id, error=str(e))
            return "知识库检索失败，未获取到内容。"

        if not docs:
            return "知识库中未检索到相关内容。"

        # 把检索到的多个块拼成一段文本返回给 Agent
        return "\n\n".join(doc.page_content for doc in docs)

    return search_knowledge_base


def _build_agent(user_id: int, doc_id: str):
    """构建知识获取 Agent: 知识库检索工具 + (可选) 联网搜索工具.

    tools 列表:
        1. 知识库检索工具 (必有) -- 从用户私有文档里查
        2. Tavily 搜索工具 (可选) -- 知识库内容不足时联网补充
    """
    from langgraph.prebuilt import create_react_agent
    from langchain_openai import ChatOpenAI

    settings = get_settings()

    # 第一个工具: 知识库检索 (限定 user_id/doc_id)
    tools = [_build_knowledge_base_tool(user_id, doc_id)]

    # 若配置了联网搜索, 追加 3 个 Tavily 工具 (用于知识库内容不足时补充)
    if settings.enable_web_search and settings.tavily_api_key:
        from langchain_tavily import TavilyExtract, TavilySearch

        tools.append(
            TavilySearch(
                name="tavily_search_basic",
                description="轻量联网搜索，返回最多 10 条结果的摘要。用于知识库内容不足时补充背景知识。",
                max_results=10,
                include_raw_content=False,
                include_answer=False,
                tavily_api_key=settings.tavily_api_key,
            )
        )
        tools.append(
            TavilySearch(
                name="tavily_search_deep",
                description="深度联网搜索，返回最多 10 条结果的完整内容。用于知识库内容不足以覆盖专业主题时补充。",
                max_results=10,
                include_raw_content=True,
                include_answer=False,
                tavily_api_key=settings.tavily_api_key,
            )
        )
        tools.append(
            TavilyExtract(
                name="tavily_extract",
                description="从指定 URL 提取页面完整内容。",
                extract_depth="basic",
                tavily_api_key=settings.tavily_api_key,
            )
        )

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        temperature=0.1,
    )

    agent = create_react_agent(
        llm,
        tools=tools,
        prompt=RAG_AGENT_SYSTEM_PROMPT,
    )
    return agent


async def fetch_rag_context(user_input: str, user_id: int, doc_id: str) -> str:
    """基于知识库文档 (及可选联网搜索) 获取知识摘要, 用于出题参考资料.

    参数:
        user_input: 用户输入的学习内容
        user_id: 用户 id (限定检索范围)
        doc_id: 知识库文档 id (限定检索范围)
    返回:
        知识摘要字符串; 失败返回空字符串 (降级, 不阻塞出题).
    """
    try:
        logger.info("rag_agent_starting", user_id=user_id, doc_id=doc_id, user_input=user_input[:100])

        t0 = time.monotonic()
        agent = _build_agent(user_id, doc_id)

        # 跑 Agent (多轮 ReAct 循环, 带超时和轮数上限)
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config={"recursion_limit": 10},
            ),
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        elapsed = round((time.monotonic() - t0) * 1000)

        messages = result.get("messages", [])
        logger.info(
            "rag_agent_completed",
            elapsed_ms=elapsed,
            message_count=len(messages),
        )

        # 取 Agent 最终回复 (最后一条消息)
        content = messages[-1].content if messages else ""
        if not content:
            logger.warning("rag_agent_empty_response", user_id=user_id, doc_id=doc_id)
            return ""

        # 截断到最大长度
        if len(content) > MAX_CONTEXT_LENGTH:
            content = content[:MAX_CONTEXT_LENGTH]

        logger.info("rag_context_fetched", user_id=user_id, doc_id=doc_id, length=len(content))
        return content

    except asyncio.TimeoutError:
        # 超时: 降级返回空
        logger.warning(
            "rag_agent_timeout", timeout=AGENT_TIMEOUT_SECONDS, user_id=user_id, doc_id=doc_id
        )
        return ""
    except Exception as e:
        # 异常: 降级返回空
        logger.warning(
            "rag_agent_error", error=str(e), error_type=type(e).__name__, user_id=user_id, doc_id=doc_id
        )
        return ""
