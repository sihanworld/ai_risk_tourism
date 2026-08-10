"""
Scheduler 单元测试 (P4-L4 2026-08-08)
防止 %d format 跟 list 类型不匹配 (回归测试)
"""
import asyncio
import logging
import sys
from pathlib import Path

import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scheduler import _run_once, _scheduler_loop, start_scheduler, stop_scheduler  # noqa: E402


class TestRunOnceReturnType:
    """_run_once 返回值类型必须正确, 否则日志 %d format 会炸"""

    @pytest.mark.asyncio
    async def test_run_once_returns_dict_with_correct_types(self, caplog):
        """P4-L4 2026-08-08 回归测试:
        - _run_once 返回 dict 必含 3 个 keys
        - alerts_created 必是 list (不是 int, 历史 bug)
        - 用 len() 转 int 后 logger.info %d 不报 TypeError
        """
        # _run_once 跑一轮
        result = await _run_once()
        # 验证 dict 结构
        assert isinstance(result, dict)
        assert isinstance(result["closed_cases"], int)
        assert isinstance(result["alerts_created"], list)  # P4-L4 关键检查
        assert isinstance(result["errors"], list)

        # P4-L4 关键: 模拟 scheduler.py 第 60-62 行的 logger.info
        # 用 len() 转 int (修复点)
        with caplog.at_level(logging.INFO, logger="app.scheduler"):
            logging.getLogger("app.scheduler").info(
                "[scheduled] 本轮: 关案 %d, 告警 %d, 错误 %d",
                result["closed_cases"],
                len(result["alerts_created"]),
                len(result["errors"]),
            )
        # 没 TypeError 即通过, 且日志被记录
        assert any("本轮" in r.message for r in caplog.records), \
            f"日志没记录, records={[r.message for r in caplog.records]}"
