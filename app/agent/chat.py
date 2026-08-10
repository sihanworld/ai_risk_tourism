"""
AI Agent 入口 (基于 LangChain DeepAgents).
模型: 阿里云百炼 qwen-plus (settings.LLM_* 配置). 工具: 8 个 @tool.
"""

import asyncio
import logging
from typing import Optional

import ulid
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from deepagents import create_deep_agent

from app.agent.tools import ALL_TOOLS
from app.config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是电商风控系统的AI助手，负责协助风控分析师完成以下工作:

1. **风险检查**: 对指定用户/订单执行实时风控评估
2. **案件管理**: 查询和分析待审核/已处理的风控案件
3. **用户画像**: 查看用户的风险评分、行为特征、历史记录
4. **黑名单管理**: 查询、添加、移除黑名单
5. **数据分析**: 统计仪表盘、趋势分析、规则命中效果
6. **业务查询**: 查看订单、售后、地址等业务数据

工作原则:
- 根据用户问题，选择合适的工具获取数据
- 用中文回答，结果需要简洁清晰
- 对风险数据给出专业的分析解读
- 可以组合多个工具完成复杂分析任务
- 当数据不足时，主动补充查询相关信息
"""

# 全局 Agent 单例 (惰性初始化: 第 1 次 get_agent() 才创建)
# 避免 import 时就建 LLM 连接, 留给真正需要时再建
_agent = None


def _create_agent():
    """构造 1 个 DeepAgent 实例 (LLM + 8 tools + system prompt)."""
    llm = ChatOpenAI(
        model=settings.LLM_MODEL_NAME,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        temperature=0.1,  # 低温=答案更确定, 适合业务场景
    )
    return create_deep_agent(
        model=llm,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def get_agent():
    """获取全局唯一的 Agent 实例 (进程内 1 个就够, 多次创建浪费 LLM 握手)."""
    global _agent
    if _agent is None:
        _agent = _create_agent()
    return _agent


# 会话消息存储 (内存级别, 重启丢失, 不持久化)
_sessions: dict[str, list] = {}
_sessions_lock = asyncio.Lock()


async def chat(
    message: str,
    session_id: Optional[str] = None,
) -> tuple[str, str]:
    """与 AI Agent 对话 (异步). 异常被捕获返 "Agent 执行出错: {e}" 不 raise."""
    if not session_id:
        session_id = f"sess_{ulid.new().str.lower()}"

    # 加锁保护: 避免两个请求同时改同一 session 丢消息
    async with _sessions_lock:
        history = _sessions.get(session_id, [])
        history.append(HumanMessage(content=message))

    agent = get_agent()
    try:
        result = await agent.ainvoke({"messages": history})
        messages = result.get("messages", [])
        if messages:
            reply = messages[-1].content
            # 把完整对话历史保存 (含 tool 调用中间结果)
            async with _sessions_lock:
                _sessions[session_id] = messages
        else:
            reply = "抱歉，未能生成回复。"
    except Exception as e:
        logger.exception("Agent 执行异常")
        reply = f"Agent 执行出错: {e}"

    return reply, session_id


def clear_session(session_id: str) -> bool:
    """清除指定会话的历史消息. 内存存储, 进程重启就全没了."""
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False
