"""
测试 - 案件超时自动关闭 (P4-L3 2026-08-08)
- 超时 N 小时的"待审核"自动改"已关闭"
- 没超时的不动
- "审核中" 不动 (只处理"待审核")
- hours=0 关闭此功能
- 写 audit (AUTO_CLOSE_CASE, operator=system)
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


class TestAutoCloseTimeoutCases:
    """auto_close_timeout_cases 行为测试"""

    @pytest.mark.asyncio
    async def test_closes_only_overdue_pending_cases(self):
        """只关超过阈值且 status='待审核' 的案件"""
        from app.service.case import auto_close_timeout_cases

        now = datetime.now()
        cases = [
            SimpleNamespace(
                case_id="cas_overdue_1", case_status="待审核",
                create_time=now - timedelta(hours=30),  # 30h 前创建, 超 24h
                reviewer=None, review_time=None, review_comment=None,
            ),
            SimpleNamespace(
                case_id="cas_overdue_2", case_status="待审核",
                create_time=now - timedelta(hours=25),
                reviewer=None, review_time=None, review_comment=None,
            ),
            SimpleNamespace(
                case_id="cas_fresh", case_status="待审核",
                create_time=now - timedelta(hours=2),    # 2h 前, 未超时
                reviewer=None, review_time=None, review_comment=None,
            ),
            SimpleNamespace(
                case_id="cas_reviewing", case_status="审核中",  # 审核中不动
                create_time=now - timedelta(hours=50),
                reviewer=None, review_time=None, review_comment=None,
            ),
        ]

        class _FakeDB:
            def __init__(self):
                self.added_logs = []
                self.commits = 0
            async def execute(self, stmt):
                # mock SQL 过滤: status='待审核' AND create_time < threshold (24h 前)
                threshold = datetime.now() - timedelta(hours=24)
                filtered = [c for c in cases
                            if c.case_status == "待审核" and c.create_time < threshold]
                class _R:
                    def __init__(self, data): self.data = data
                    def scalars(self):
                        class _S:
                            def __init__(self, d): self.d = d
                            def all(self): return self.d
                        return _S(self.data)
                return _R(filtered)
            def add(self, obj):
                self.added_logs.append(obj)
            async def commit(self):
                self.commits += 1

        db = _FakeDB()
        closed = await auto_close_timeout_cases(db, hours=24)
        # 应该关 2 个 (cas_overdue_1, cas_overdue_2), cas_fresh 和 cas_reviewing 不动
        assert closed == 2, f"应关 2 个, 实际 {closed}"
        assert cases[0].case_status == "已关闭"   # cas_overdue_1
        assert cases[1].case_status == "已关闭"   # cas_overdue_2
        assert cases[2].case_status == "待审核"   # cas_fresh
        assert cases[3].case_status == "审核中"   # cas_reviewing
        # reviewer / review_time / review_comment 被填
        assert cases[0].reviewer == "system"
        assert cases[0].review_time is not None
        assert "24" in cases[0].review_comment
        # audit log 应有 2 条
        import json as _json
        assert len(db.added_logs) == 2
        for log in db.added_logs:
            assert log.action_type == "AUTO_CLOSE_CASE"
            assert log.operator == "system"
            # record_action 内部把 dict → JSON 字符串
            before = _json.loads(log.before_value) if isinstance(log.before_value, str) else log.before_value
            after = _json.loads(log.after_value) if isinstance(log.after_value, str) else log.after_value
            assert before["case_status"] == "待审核"
            assert after["case_status"] == "已关闭"
        # commit 1 次 (1 个事务)
        assert db.commits == 1

    @pytest.mark.asyncio
    async def test_zero_hours_disables(self):
        """hours=0 → 关闭此功能, 不查 DB 不写库"""
        from app.service.case import auto_close_timeout_cases

        class _FakeDB:
            def __init__(self):
                self.executed = False
            async def execute(self, stmt):
                self.executed = True
                return None

        db = _FakeDB()
        closed = await auto_close_timeout_cases(db, hours=0)
        assert closed == 0
        assert not db.executed, "hours=0 不应调 DB"

    @pytest.mark.asyncio
    async def test_no_overdue_returns_zero(self):
        """没超时案件 → 返回 0, 不写 audit, 不 commit"""
        from app.service.case import auto_close_timeout_cases

        class _FakeDB:
            def __init__(self):
                self.added = []
                self.commits = 0
            async def execute(self, stmt):
                class _R:
                    def scalars(self):
                        class _S:
                            def all(self): return []
                        return _S()
                return _R()
            def add(self, obj):
                self.added.append(obj)
            async def commit(self):
                self.commits += 1

        db = _FakeDB()
        closed = await auto_close_timeout_cases(db, hours=24)
        assert closed == 0
        assert len(db.added) == 0
        assert db.commits == 0   # 关键: 没超时就不 commit

    @pytest.mark.asyncio
    async def test_reviewing_and_closed_never_closed(self):
        """状态机: 只有'待审核'会被自动关, 终态(已通过/已拒绝/已关闭) 和'审核中' 不动"""
        from app.service.case import auto_close_timeout_cases

        now = datetime.now()
        cases = [
            SimpleNamespace(case_id="c1", case_status="待审核",
                            create_time=now - timedelta(hours=99),
                            reviewer=None, review_time=None, review_comment=None),
            SimpleNamespace(case_id="c2", case_status="审核中",
                            create_time=now - timedelta(hours=99),
                            reviewer=None, review_time=None, review_comment=None),
            SimpleNamespace(case_id="c3", case_status="已通过",
                            create_time=now - timedelta(hours=99),
                            reviewer=None, review_time=None, review_comment=None),
            SimpleNamespace(case_id="c4", case_status="已拒绝",
                            create_time=now - timedelta(hours=99),
                            reviewer=None, review_time=None, review_comment=None),
            SimpleNamespace(case_id="c5", case_status="已关闭",
                            create_time=now - timedelta(hours=99),
                            reviewer=None, review_time=None, review_comment=None),
        ]

        class _FakeDB:
            def __init__(self):
                self.added = []
            async def execute(self, stmt):
                class _R:
                    def scalars(self):
                        class _S:
                            def all(self): return [c for c in cases if c.case_status == "待审核"]
                        return _S()
                return _R()
            def add(self, obj): self.added.append(obj)
            async def commit(self): pass

        db = _FakeDB()
        closed = await auto_close_timeout_cases(db, hours=24)
        assert closed == 1
        # 只有 c1 (待审核) 变成已关闭
        assert cases[0].case_status == "已关闭"
        assert cases[1].case_status == "审核中"   # 审核中不动
        assert cases[2].case_status == "已通过"   # 终态不动
        assert cases[3].case_status == "已拒绝"   # 终态不动
        assert cases[4].case_status == "已关闭"   # 已是不动 (虽然被返回, 但 SQL 已 WHERE case_status=待审核, 所以这条不会被 SELECT)

    @pytest.mark.asyncio
    async def test_default_hours_from_settings(self):
        """hours=None → 用 settings.CASE_TIMEOUT_HOURS"""
        from app.config import settings
        from app.service.case import auto_close_timeout_cases

        class _FakeDB:
            async def execute(self, stmt):
                class _R:
                    def scalars(self):
                        class _S:
                            def all(self): return []
                        return _S()
                return _R()
            def add(self, obj): pass
            async def commit(self): pass

        db = _FakeDB()
        closed = await auto_close_timeout_cases(db)  # 不传 hours
        assert closed == 0
        # 验证 settings 有这个字段
        assert hasattr(settings, "CASE_TIMEOUT_HOURS")
        assert isinstance(settings.CASE_TIMEOUT_HOURS, int)
        assert settings.CASE_TIMEOUT_HOURS > 0
