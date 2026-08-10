"""
测试 - AI Agent session 锁 (防并发丢消息)
【P2-S4 修复 2026-08-07】_sessions 加 asyncio.Lock, 避免并发写丢消息.
2026-08-07: 撤回了 P2-S3 的 X-User-Id 鉴权 (软鉴权, 没意义), 本文件只保留锁测试.
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent import chat as chat_module


class TestSessionLock:
    """_sessions_lock 保护并发写."""

    @pytest.mark.asyncio
    async def test_concurrent_chat_does_not_lose_messages(self, monkeypatch):
        """10 个并发 chat 同一 session, 消息历史应该全保留 (不丢)"""
        # mock ainvoke: 模拟"接收 history + 加上 AI 回复"
        from langchain_core.messages import AIMessage
        async def fake_ainvoke(state):
            return {"messages": list(state["messages"]) + [AIMessage(content="ok")]}
        fake_agent = MagicMock(ainvoke=fake_ainvoke)
        monkeypatch.setattr(chat_module, "get_agent", lambda: fake_agent)

        # 用同一 session_id 并发 10 个 chat
        async def one_chat(i):
            await chat_module.chat(f"msg-{i}", session_id="sess_concurrent")

        await asyncio.gather(*[one_chat(i) for i in range(10)])

        # 关键断言: 10 条 "msg-X" 全在历史里
        history = chat_module._sessions.get("sess_concurrent", [])
        history_text = " ".join(
            (m.content if hasattr(m, "content") else str(m)) for m in history
        )
        for i in range(10):
            assert f"msg-{i}" in history_text, (
                f"msg-{i} 应在历史里, 实际历史前 200 字符: {history_text[:200]}"
            )

    @pytest.mark.asyncio
    async def test_lock_exists_and_is_asyncio_lock(self):
        """_sessions_lock 存在且是 asyncio.Lock 类型"""
        assert hasattr(chat_module, "_sessions_lock")
        assert isinstance(chat_module._sessions_lock, type(asyncio.Lock()))
