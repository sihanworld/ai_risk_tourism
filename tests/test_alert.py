"""
测试 - 风控告警 (P4-L2)
3 个真实场景: 案件积压 / 规则命中率突降 / 拒绝率过高
教学价值: 让学员理解"风控不是写完规则就完事, 要监控"
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.service import alert as alert_module
from app.service.alert import (
    check_and_alert,
    check_pending_case_backlog,
    check_rule_hit_rate_drop,
    check_blacklist_hit_rate_high,
    run_all_alert_checks,
)
from app.models import RiskAlert


def _mock_db_with_count(count: int):
    """构造 mock db, 让 execute(count query) 返回 count."""
    db = MagicMock()
    added = []
    db.add = lambda obj: added.append(obj)
    async def fake_execute(stmt):
        return MagicMock(scalar=MagicMock(return_value=count))
    db.execute = fake_execute
    db.added = added
    return db


# ===== check_and_alert() 单测 =====

class TestCheckAndAlert:
    """通用 helper: 写 1 条 RiskAlert."""

    @pytest.mark.asyncio
    async def test_writes_alert_with_all_fields(self):
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)
        await check_and_alert(
            db, alert_type="BUSINESS", alert_level="P1",
            title="测试", content="详情",
            metric_name="x", metric_value=10.5, threshold=5.0,
        )
        assert len(added) == 1
        a = added[0]
        assert isinstance(a, RiskAlert)
        assert a.alert_type == "BUSINESS"
        assert a.alert_level == "P1"
        assert a.alert_title == "测试"
        assert a.alert_content == "详情"
        assert a.metric_name == "x"
        assert float(a.metric_value) == 10.5
        assert float(a.threshold) == 5.0
        assert a.status == "PENDING"

    @pytest.mark.asyncio
    async def test_does_not_commit(self):
        db = MagicMock()
        db.add = MagicMock()
        committed = {"n": 0}
        async def fake_commit():
            committed["n"] += 1
        db.commit = fake_commit
        await check_and_alert(db, alert_type="X", alert_level="P0", title="t", content="c")
        assert committed["n"] == 0


# ===== 场景 1: 待审核案件积压 =====

class TestPendingCaseBacklog:
    """count > 阈值 → 触发 P1 告警."""

    @pytest.mark.asyncio
    async def test_triggers_when_count_exceeds_threshold(self, monkeypatch):
        # 60 个待审核, 阈值 50 → 触发
        db = _mock_db_with_count(count=60)
        # 直接修改 settings (mock 一下, 避免改 .env)
        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_PENDING_CASE_THRESHOLD", 50)

        result = await check_pending_case_backlog(db)
        assert result is not None
        assert result.alert_type == "BUSINESS"
        assert result.alert_level == "P1"
        assert "积压" in result.alert_title
        assert float(result.metric_value) == 60
        assert float(result.threshold) == 50

    @pytest.mark.asyncio
    async def test_no_alert_when_count_below_threshold(self, monkeypatch):
        db = _mock_db_with_count(count=10)  # 10 < 50
        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_PENDING_CASE_THRESHOLD", 50)

        result = await check_pending_case_backlog(db)
        assert result is None
        assert len(db.added) == 0


# ===== 场景 2: 规则命中率突降 =====

class TestRuleHitRateDrop:
    """最近 1h 命中率 < 5% → 触发 P2 告警."""

    @pytest.mark.asyncio
    async def test_triggers_when_hit_rate_below_min(self, monkeypatch):
        # 2 次评估, 0 次命中, 总数 > 10 (避免冷启动跳过)
        # 但 SQLAlchemy 用同一个 stmt 多次 execute 返不同值, 我们用 side_effect
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)

        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar=MagicMock(return_value=100))   # total
            else:
                return MagicMock(scalar=MagicMock(return_value=2))     # hit
        db.execute = fake_execute

        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_RULE_HIT_RATE_MIN", 5.0)
        monkeypatch.setattr(settings, "ALERT_CHECK_WINDOW_HOURS", 1)

        result = await check_rule_hit_rate_drop(db)
        assert result is not None
        assert result.alert_type == "MODEL"
        assert result.alert_level == "P2"
        assert "命中率" in result.alert_title
        # 命中率 = 2/100 = 2% < 5% 阈值
        assert float(result.metric_value) < 5.0

    @pytest.mark.asyncio
    async def test_no_alert_when_hit_rate_ok(self, monkeypatch):
        # 100 总, 20 命中 = 20% > 5% 阈值
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)

        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar=MagicMock(return_value=100))
            else:
                return MagicMock(scalar=MagicMock(return_value=20))
        db.execute = fake_execute

        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_RULE_HIT_RATE_MIN", 5.0)

        result = await check_rule_hit_rate_drop(db)
        assert result is None

    @pytest.mark.asyncio
    async def test_skip_when_total_below_min_sample(self, monkeypatch):
        """评估数 < 10 时跳过, 避免冷启动误报"""
        db = MagicMock()
        async def fake_execute(stmt):
            return MagicMock(scalar=MagicMock(return_value=5))  # 太少
        db.execute = fake_execute
        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_RULE_HIT_RATE_MIN", 5.0)

        result = await check_rule_hit_rate_drop(db)
        assert result is None


# ===== 场景 3: 拒绝率过高 =====

class TestBlacklistHitRateHigh:
    """最近 1h 拒绝率 > 30% → 触发 P2 告警."""

    @pytest.mark.asyncio
    async def test_triggers_when_reject_rate_above_max(self, monkeypatch):
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)

        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar=MagicMock(return_value=100))  # total
            else:
                return MagicMock(scalar=MagicMock(return_value=40))   # reject
        db.execute = fake_execute

        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_BLACKLIST_HIT_RATE_MAX", 30.0)

        result = await check_blacklist_hit_rate_high(db)
        assert result is not None
        assert result.alert_level == "P2"
        # 40/100 = 40% > 30% 阈值
        assert float(result.metric_value) > 30.0

    @pytest.mark.asyncio
    async def test_no_alert_when_reject_rate_ok(self, monkeypatch):
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)

        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(scalar=MagicMock(return_value=100))
            else:
                return MagicMock(scalar=MagicMock(return_value=10))   # 10% 正常
        db.execute = fake_execute

        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_BLACKLIST_HIT_RATE_MAX", 30.0)

        result = await check_blacklist_hit_rate_high(db)
        assert result is None


# ===== run_all_alert_checks 集成测试 =====

class TestRunAllAlertChecks:
    """一次性跑 3 个检查."""

    @pytest.mark.asyncio
    async def test_runs_all_three_checks(self, monkeypatch):
        """3 个 check_fn 都跑, 各自决定要不要触发"""
        from app.config import settings
        monkeypatch.setattr(settings, "ALERT_PENDING_CASE_THRESHOLD", 50)
        monkeypatch.setattr(settings, "ALERT_RULE_HIT_RATE_MIN", 5.0)
        monkeypatch.setattr(settings, "ALERT_BLACKLIST_HIT_RATE_MAX", 30.0)

        # 准备 db: 让 3 个检查都返回"超阈值"的数字
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)

        # total=100, hit=1 (1% < 5% → 触发), reject=40 (40% > 30% → 触发)
        # pending_case=60 (60 > 50 → 触发)
        call_count = {"n": 0}
        async def fake_execute(stmt):
            call_count["n"] += 1
            # 第 1 次: pending case count → 60
            # 第 2 次: total assessment → 100
            # 第 3 次: hit count → 1
            # 第 4 次: total assessment → 100
            # 第 5 次: reject count → 40
            values = [60, 100, 1, 100, 40]
            i = min(call_count["n"] - 1, len(values) - 1)
            return MagicMock(scalar=MagicMock(return_value=values[i]))
        db.execute = fake_execute

        results = await run_all_alert_checks(db)
        # 3 个都触发
        assert len(results) == 3
        titles = {a.alert_title for a in results}
        assert any("积压" in t for t in titles)
        assert any("命中率" in t for t in titles)
        assert any("拒绝率" in t for t in titles)
