"""
测试 - 操作审计日志 (P4-L1)
任何规则/案件/黑名单变更都写一行 risk_action_log, 出事能追责.
"""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.service import action_log as action_log_module
from app.service.action_log import record_action, orm_to_dict
from app.models import RiskActionLog


# ===== record_action() 单测 =====

class TestRecordAction:
    """单测 record_action() 函数: 不 commit, 只 add 一行."""

    @pytest.mark.asyncio
    async def test_adds_action_log_with_all_fields(self):
        """operator + action_type + target_id + before + after + ip + remark 全填"""
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)

        await record_action(
            db, operator="alice", action_type="CREATE_RULE",
            target_type="rule", target_id="R001",
            after_value={"rule_name": "测试"},
            ip="127.0.0.1",
            remark="测试",
        )
        assert len(added) == 1
        log = added[0]
        assert isinstance(log, RiskActionLog)
        assert log.operator == "alice"
        assert log.action_type == "CREATE_RULE"
        assert log.target_type == "rule"
        assert log.target_id == "R001"
        assert log.before_value is None
        assert log.after_value == json.dumps({"rule_name": "测试"}, ensure_ascii=False)
        assert log.ip == "127.0.0.1"
        assert log.remark == "测试"

    @pytest.mark.asyncio
    async def test_does_not_commit(self):
        """record_action 不 commit, 由调用方合并事务 (跟 add_blacklist 同模式)"""
        db = MagicMock()
        db.add = MagicMock()
        committed = {"n": 0}
        async def fake_commit():
            committed["n"] += 1
        db.commit = fake_commit

        await record_action(
            db, operator="admin", action_type="DELETE_RULE",
            target_type="rule", target_id="R999",
            before_value={"k": "v"},
        )
        assert committed["n"] == 0, "record_action 不该 commit, 让调用方合并事务"

    @pytest.mark.asyncio
    async def test_unicode_chinese_preserved(self):
        """中文内容 ensure_ascii=False, 不被转义"""
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)

        await record_action(
            db, operator="admin", action_type="REVIEW_CASE",
            target_type="case", target_id="cas_001",
            after_value={"comment": "审核通过", "decision": "已通过"},
        )
        log = added[0]
        # 中文原样保留 (不变成 \uXXXX)
        assert "审核通过" in log.after_value
        assert "\\u" not in log.after_value  # ensure_ascii=False 验证


class TestOrmToDict:
    """单测 orm_to_dict 工具: ORM 对象 → dict, 只取 fields 指定的字段."""

    def test_extracts_named_fields(self):
        obj = SimpleNamespace(rule_id="R001", rule_name="测试", risk_score=70, _hidden="secret")
        d = orm_to_dict(obj, ["rule_id", "rule_name", "risk_score"])
        assert d == {"rule_id": "R001", "rule_name": "测试", "risk_score": 70}

    def test_missing_fields_default_to_none(self):
        obj = SimpleNamespace(rule_id="R001")
        d = orm_to_dict(obj, ["rule_id", "rule_name"])  # rule_name 不存在
        assert d == {"rule_id": "R001", "rule_name": None}


# ===== 路由层 hook 集成测试 =====

class TestRuleRouterHook:
    """rule.py 的 4 个操作都要写 action_log."""

    @pytest.mark.asyncio
    async def test_create_rule_writes_log(self):
        from app.routers.rule import api_create_rule
        from app.schemas import RuleCreate

        # mock db
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)
        # mock execute: 返回 None (规则不存在, 通过查重)
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        async def fake_commit():
            pass
        db.commit = fake_commit

        data = RuleCreate(
            rule_id="R_TEST", rule_name="测试规则",
            rule_category="预订欺诈", event_type="预订",
            rule_condition={"field": "x", "op": ">", "value": 5},
            risk_level="高", risk_score=70, action="人工审核",
        )
        # 改 _rule_to_response 让它对 mock 兼容 (返回 mock 而不是 ORM 对象)
        from app.routers import rule as rule_router_module
        original_rule_to_resp = rule_router_module._rule_to_response
        def fake_rule_to_resp(_rule):
            return MagicMock(rule_id=data.rule_id, is_enabled=1)
        rule_router_module._rule_to_response = fake_rule_to_resp
        try:
            await api_create_rule(data=data, db=db)
        finally:
            rule_router_module._rule_to_response = original_rule_to_resp

        # 验证: 加了 1 条 rule + 1 条 action_log
        log_entries = [x for x in added if isinstance(x, RiskActionLog)]
        assert len(log_entries) == 1
        log = log_entries[0]
        assert log.action_type == "CREATE_RULE"
        assert log.target_id == "R_TEST"
        assert log.before_value is None
        assert log.after_value is not None
        assert "测试规则" in log.after_value

    @pytest.mark.asyncio
    async def test_delete_rule_writes_log_with_before(self):
        from app.routers.rule import api_delete_rule

        # mock rule 存在
        rule = SimpleNamespace(
            rule_id="R_DEL", rule_name="要删的规则",
            risk_level="高", risk_score=70, action="人工审核",
            is_enabled=1, priority=10,
        )
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)
        # SQLAlchemy AsyncSession.delete 是 async, 用 AsyncMock
        db.delete = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=rule)))
        async def fake_commit():
            pass
        db.commit = fake_commit

        await api_delete_rule(rule_id="R_DEL", db=db)

        log_entries = [x for x in added if isinstance(x, RiskActionLog)]
        assert len(log_entries) == 1
        log = log_entries[0]
        assert log.action_type == "DELETE_RULE"
        assert log.target_id == "R_DEL"
        assert log.before_value is not None
        assert log.after_value is None
        assert "要删的规则" in log.before_value


class TestBlacklistHook:
    """blacklist 增删都要写 action_log."""

    @pytest.mark.asyncio
    async def test_add_blacklist_writes_log(self):
        from app.service.case import add_blacklist
        from app.schemas import BlacklistCreate

        # mock db: 不存在 (新加)
        bl_new = SimpleNamespace(
            blacklist_id=10, blacklist_type="用户", blacklist_value="u1",
            reason="test", expire_time=None, create_time=None,
        )
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)
        # 第 1 次查 (查重) = None, 第 2 次 flush 完 = bl_new
        db.execute = AsyncMock(side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ])
        async def fake_flush():
            pass
        db.flush = fake_flush
        async def fake_commit():
            pass
        db.commit = fake_commit

        request = BlacklistCreate(blacklist_type="用户", blacklist_value="u1", reason="test")
        # 直接调用 add_blacklist 测 hook
        # 我们需要 mock 出添加的 RiskBlacklist
        # 简化: 用 monkeypatch 替换 RiskBlacklist 构造
        from app.models import RiskBlacklist
        original_init = RiskBlacklist.__init__
        def fake_init(self, **kwargs):
            original_init(self, **kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)
            self.blacklist_id = 10
        RiskBlacklist.__init__ = fake_init
        try:
            await add_blacklist(db, request)
        finally:
            RiskBlacklist.__init__ = original_init

        log_entries = [x for x in added if isinstance(x, RiskActionLog)]
        assert len(log_entries) == 1
        log = log_entries[0]
        assert log.action_type == "ADD_BLACKLIST"
        assert log.target_type == "blacklist"
        assert log.before_value is None  # 新增, before=None
        assert log.after_value is not None


class TestCaseReviewHook:
    """case 审核要写 action_log."""

    @pytest.mark.asyncio
    async def test_review_case_writes_log(self):
        from app.service.case import review_case
        from app.schemas import CaseReviewRequest

        case = SimpleNamespace(
            case_id="cas_test", case_status="待审核", user_id="1001",
        )
        db = MagicMock()
        added = []
        db.add = lambda obj: added.append(obj)
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=case)))
        async def fake_commit():
            pass
        db.commit = fake_commit

        # mock get_case_detail
        from app.service import case as case_module
        async def fake_get_detail(_db, _cid):
            return SimpleNamespace(case_id="cas_test", case_status="已通过")
        case_module.get_case_detail = fake_get_detail

        request = CaseReviewRequest(decision="已通过", reviewer="alice", review_comment="OK")
        await review_case(db, "cas_test", request)

        log_entries = [x for x in added if isinstance(x, RiskActionLog)]
        assert len(log_entries) == 1
        log = log_entries[0]
        assert log.action_type == "REVIEW_CASE"
        assert log.target_id == "cas_test"
        assert log.operator == "alice"  # 审核人即操作人
        assert log.before_value is not None
        assert "待审核" in log.before_value
        assert log.after_value is not None
        assert "已通过" in log.after_value
