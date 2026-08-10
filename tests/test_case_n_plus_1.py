"""
测试 - 案件列表的 N+1 修复
【P2-S8 修复 2026-08-07】原代码循环里 N 次 SELECT assessment, 应改成 1 次 LEFT JOIN.
"""
from collections import namedtuple
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.service.case import get_case_list


# SQLAlchemy 2.x Row-like: 支持 row[0] (取列) 和 row.field_name (按名取)
_Row = namedtuple("_Row", ["case", "final_score", "risk_level"])


def _make_case(case_id: str, status: str = "待审核") -> SimpleNamespace:
    return SimpleNamespace(
        case_id=case_id,
        assessment_id=f"ast_{case_id}",
        user_id="1001",
        case_status=status,
        case_category="订单欺诈",
        source_id=f"order_{case_id}",
        event_type="下单",
        create_time=None,
    )


class TestCaseListNPlusOne:
    """get_case_list 应该 2 次 SQL (count + page), 不是 1+N 次."""

    @pytest.mark.asyncio
    async def test_no_filter_executes_2_sqls(self):
        """没过滤: 2 次 SQL (count + page), 不管有多少 case"""
        cases = [_make_case(f"c{i}") for i in range(20)]
        rows = [_Row(case=c, final_score=80, risk_level="极高") for c in cases]

        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar=MagicMock(return_value=20))
            else:
                return MagicMock(all=MagicMock(return_value=rows))

        db = MagicMock(execute=AsyncMock(side_effect=fake_execute))
        result = await get_case_list(db, status=None, category=None, page=1, page_size=20)

        # 关键断言: 不管 page 大小, SQL 次数恒为 2 (不是 1+N)
        assert call_count["n"] == 2, (
            f"应只发 2 次 SQL (count + page), 实际 {call_count['n']} 次, "
            f"可能没修好 N+1"
        )
        assert result.total == 20
        assert len(result.items) == 20
        # 验证 final_score / risk_level 从 JOIN 拿过来了
        assert result.items[0].final_score == 80
        assert result.items[0].risk_level == "极高"

    @pytest.mark.asyncio
    async def test_with_status_filter_uses_where(self):
        """带 status 过滤: 也只 2 次 SQL"""
        c1 = _make_case("c1", status="已通过")
        rows = [_Row(case=c1, final_score=50, risk_level="中")]

        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar=MagicMock(return_value=1))
            else:
                return MagicMock(all=MagicMock(return_value=rows))

        db = MagicMock(execute=AsyncMock(side_effect=fake_execute))
        result = await get_case_list(db, status="已通过", category=None, page=1, page_size=20)
        assert call_count["n"] == 2
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty(self):
        """没 case 时返回空列表, 不报错"""
        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar=MagicMock(return_value=0))
            else:
                return MagicMock(all=MagicMock(return_value=[]))

        db = MagicMock(execute=AsyncMock(side_effect=fake_execute))
        result = await get_case_list(db)
        assert result.total == 0
        assert result.items == []
        assert call_count["n"] == 2  # 还是 2 次 SQL (count 0 + page 0)
