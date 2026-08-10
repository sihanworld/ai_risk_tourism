"""
测试 - 评估历史 (P3-S9 2026-08-08)
- list_assessments 列表 + 筛选
- get_assessment_detail 详情
- 案件 active_only 默认筛选
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ============================================================
# 案件 active_only 筛选 (P3-S9 列表默认看"待办")
# ============================================================

class TestCaseListActiveOnly:
    """案件列表加 active_only=True 参数, 只查待审核 + 审核中."""

    @pytest.mark.asyncio
    async def test_active_only_filters_to_pending_and_reviewing(self):
        """active_only=True → WHERE case_status IN ('待审核', '审核中')

        SQLAlchemy 用参数化查询, 字面值在 bind params 里, 不在 str(stmt) 里.
        改用检查 stmt.whereclause 结构 (或直接调 .execute 看 db.execute 的 stmt).
        """
        from app.service import case as case_service
        from sqlalchemy.sql import Select

        captured_stmt = None

        class _FakeResult:
            def __init__(self, n=0): self.n = n
            def scalar(self): return self.n
            def all(self): return []

        class _FakeDB:
            async def execute(self, stmt):
                nonlocal captured_stmt
                if captured_stmt is None:
                    captured_stmt = stmt
                return _FakeResult()

        db = _FakeDB()
        await case_service.get_case_list(db, active_only=True, page=1, page_size=20)
        assert captured_stmt is not None
        # 检查 whereclause 含 case_status.in_(...)
        where_str = str(captured_stmt.whereclause)
        # SQLAlchemy 渲染: case_status IN (__[POSTCOMPILE_xxx]) → 占位符
        assert "case_status" in where_str and "IN" in where_str.upper(), (
            f"active_only=True 应加 case_status IN 过滤, 实际 where: {where_str}"
        )

    @pytest.mark.asyncio
    async def test_active_only_false_no_filter(self):
        """active_only=False (默认) → 不加 case_status 过滤"""
        from app.service import case as case_service

        captured = {}

        class _FakeResult:
            def scalar(self): return 0
            def all(self): return []

        class _FakeDB:
            async def execute(self, stmt):
                captured['sql'] = str(stmt)
                return _FakeResult()

        db = _FakeDB()
        await case_service.get_case_list(db, active_only=False, page=1, page_size=20)
        # 不应有 case_status IN 过滤
        assert "审核中" not in captured['sql'] or "case_status" not in captured['sql'], (
            f"active_only=False 不该有 case_status 过滤, 实际 SQL: {captured['sql']}"
        )


# ============================================================
# list_assessments / get_assessment_detail (P3-S9 评估历史)
# ============================================================

class TestListAssessments:
    """评估历史列表: 4 维筛选 (decision / risk_level / event_type / user_id) + 分页."""

    @pytest.mark.asyncio
    async def test_returns_assessment_items_with_event_type(self):
        """列表应含 event_type (从 risk_event 表 JOIN 来)"""
        from app.service import case as case_service

        # 模拟 2 行 (assessment, event_type) tuple
        fake_a1 = SimpleNamespace(
            assessment_id="ast1", event_id="evt1", user_id="U1",
            final_score=85, risk_level="极高", decision="拒绝",
            rule_count=2, ml_score=0.85, ml_decision="拒绝",
            create_time="2026-08-08 00:00:00",
        )
        fake_a2 = SimpleNamespace(
            assessment_id="ast2", event_id="evt2", user_id="U2",
            final_score=20, risk_level="低", decision="通过",
            rule_count=0, ml_score=0.1, ml_decision="通过",
            create_time="2026-08-08 00:01:00",
        )

        class _FakeResult:
            def __init__(self, data):
                self.data = data
            def scalar(self): return self.data if isinstance(self.data, int) else 2
            def all(self): return self.data if not isinstance(self.data, int) else []

        class _FakeDB:
            def __init__(self):
                self.call_count = 0
            async def execute(self, stmt):
                self.call_count += 1
                if self.call_count == 1:
                    return _FakeResult(2)  # count
                return _FakeResult([(fake_a1, "下单"), (fake_a2, "支付")])  # paged

        db = _FakeDB()
        result = await case_service.list_assessments(db, page=1, page_size=20)
        assert result.total == 2
        assert len(result.items) == 2
        # event_type 从 JOIN 拿
        assert result.items[0].event_type == "下单"
        assert result.items[1].event_type == "支付"
        # ml_score 浮点
        assert result.items[0].ml_score == 0.85
        assert result.items[1].ml_score == 0.1

    @pytest.mark.asyncio
    async def test_event_type_unknown_when_no_event(self):
        """assessment.event_id 在 risk_event 表没匹配 → event_type = '未知'"""
        from app.service import case as case_service

        fake_a = SimpleNamespace(
            assessment_id="ast1", event_id="evt_orphan", user_id="U1",
            final_score=50, risk_level="中", decision="标记",
            rule_count=1, ml_score=None, ml_decision=None,
            create_time="2026-08-08 00:00:00",
        )

        class _FakeResult:
            def scalar(self): return 1
            def all(self): return [(fake_a, None)]  # LEFT JOIN 匹配不上, event_type = None

        class _FakeDB:
            def __init__(self):
                self.call_count = 0
            async def execute(self, stmt):
                self.call_count += 1
                if self.call_count == 1: return _FakeResult()
                return _FakeResult()

        db = _FakeDB()
        result = await case_service.list_assessments(db, page=1, page_size=20)
        assert result.items[0].event_type == "未知"
        assert result.items[0].ml_score is None


class TestGetAssessmentDetail:
    """评估详情: 基础字段 + 命中规则 + ML + 事件快照."""

    @pytest.mark.asyncio
    async def test_detail_with_triggered_rules(self):
        """详情应 parse rule_results JSON → triggered_rules 列表"""
        from app.service import case as case_service

        fake_a = SimpleNamespace(
            assessment_id="ast1", event_id="evt1", user_id="U1",
            final_score=95, risk_level="极高", decision="拒绝",
            rule_count=2, rule_results=(
                '[{"rule_id":"R002","rule_name":"单笔极端高额订单","rule_category":"订单欺诈",'
                '"risk_level":"极高","risk_score":95,"action":"拒绝","description":null}]'
            ),
            ml_score=0.92, ml_decision="拒绝",
            create_time="2026-08-08 00:00:00",
        )
        fake_ev = SimpleNamespace(
            event_id="evt1", event_type="下单", event_source_id="ORD000123",
            event_data='{"amount": 15000}',
        )

        class _FakeResult:
            def __init__(self, item):
                self.item = item
            def scalar_one_or_none(self):
                return self.item

        class _FakeDB:
            def __init__(self):
                self.call_count = 0
            async def execute(self, stmt):
                self.call_count += 1
                # 1st: 取 assessment; 2nd: 取 event
                return _FakeResult(fake_a if self.call_count == 1 else fake_ev)

        db = _FakeDB()
        result = await case_service.get_assessment_detail(db, "ast1")
        assert result is not None
        assert result.assessment_id == "ast1"
        assert result.event_source_id == "ORD000123"
        assert result.event_data == '{"amount": 15000}'
        assert len(result.triggered_rules) == 1
        assert result.triggered_rules[0].rule_id == "R002"
        assert result.ml_score == 0.92

    @pytest.mark.asyncio
    async def test_detail_not_found_returns_none(self):
        """assessment_id 不存在 → 返回 None"""
        from app.service import case as case_service

        class _FakeResult:
            def scalar_one_or_none(self): return None

        class _FakeDB:
            async def execute(self, stmt): return _FakeResult()

        db = _FakeDB()
        result = await case_service.get_assessment_detail(db, "ast_does_not_exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_detail_corrupt_rule_results_fallback_empty(self):
        """rule_results JSON 解析失败 → triggered_rules 空 list (P3-M5 兜底)"""
        from app.service import case as case_service

        fake_a = SimpleNamespace(
            assessment_id="ast1", event_id="evt1", user_id="U1",
            final_score=50, risk_level="中", decision="标记",
            rule_count=0, rule_results="not valid json {{{",
            ml_score=None, ml_decision=None,
            create_time="2026-08-08 00:00:00",
        )
        fake_ev = SimpleNamespace(
            event_id="evt1", event_type="下单", event_source_id="ORD1", event_data=None,
        )

        class _FakeResult:
            def __init__(self, item): self.item = item
            def scalar_one_or_none(self): return self.item

        class _FakeDB:
            def __init__(self): self.n = 0
            async def execute(self, stmt):
                self.n += 1
                return _FakeResult(fake_a if self.n == 1 else fake_ev)

        db = _FakeDB()
        result = await case_service.get_assessment_detail(db, "ast1")
        assert result.triggered_rules == []   # 兜底空 list
        assert result.rule_count == 0          # 原值保留 (跟 rule_results 无关)
