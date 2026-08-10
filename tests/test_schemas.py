"""
测试 - Pydantic schemas 字段验证
不需要 DB, 直接构造 / 校验 Pydantic model
"""
import pytest
from pydantic import ValidationError

from app.schemas import (
    RiskCheckRequest,
    CaseReviewRequest,
    RuleCreate,
    AgentChatRequest,
)


class TestRiskCheckRequest:
    """测试 RiskCheckRequest 字段验证"""

    def test_valid_request(self):
        """合法 event_type → 通过"""
        req = RiskCheckRequest(
            event_type="下单",
            source_id="order_001",
            user_id="1001",
        )
        assert req.event_type == "下单"
        assert req.user_id == "1001"
        # 可选字段默认 None
        assert req.order_id is None
        assert req.receive_id is None
        assert req.event_data is None

    def test_all_4_event_types(self):
        """4 个合法 event_type 都能过"""
        for et in ["下单", "支付", "售后申请", "物流投诉"]:
            req = RiskCheckRequest(event_type=et, source_id="x", user_id="u")
            assert req.event_type == et

    def test_invalid_event_type(self):
        """非法 event_type → ValidationError"""
        with pytest.raises(ValidationError) as exc_info:
            RiskCheckRequest(event_type="未知类型", source_id="x", user_id="u")
        # 确认错误是关于 event_type 字段
        assert "event_type" in str(exc_info.value)

    def test_missing_required_field(self):
        """必填字段 source_id 缺失 → ValidationError"""
        with pytest.raises(ValidationError) as exc_info:
            RiskCheckRequest(event_type="下单", user_id="u")  # 没传 source_id
        assert "source_id" in str(exc_info.value)


class TestCaseReviewRequest:
    """测试 CaseReviewRequest 字段验证"""

    def test_valid_approval(self):
        """合法 decision → 通过"""
        req = CaseReviewRequest(decision="已通过", reviewer="admin")
        assert req.decision == "已通过"
        assert req.reviewer == "admin"
        # 默认值
        assert req.review_comment is None
        assert req.add_to_blacklist is False

    def test_invalid_decision(self):
        """非法 decision → ValidationError"""
        with pytest.raises(ValidationError) as exc_info:
            CaseReviewRequest(decision="已删除", reviewer="admin")
        assert "decision" in str(exc_info.value)


class TestRuleCreate:
    """测试 RuleCreate 字段验证"""

    def test_valid_rule(self):
        """必填字段全填 → 通过"""
        rule = RuleCreate(
            rule_id="R_TEST",
            rule_name="测试规则",
            rule_category="订单欺诈",
            event_type="下单",
            rule_condition={"field": "x", "op": ">", "value": 5},  # dict 不是 str
            risk_level="高",
            risk_score=70,
            action="人工审核",
        )
        assert rule.rule_id == "R_TEST"
        assert rule.risk_score == 70
        # 可选字段默认值
        assert rule.priority == 0
        assert rule.description is None

    def test_rule_score_out_of_range(self):
        """risk_score 超出 0-100 范围 → ValidationError"""
        with pytest.raises(ValidationError) as exc_info:
            RuleCreate(
                rule_id="R1", rule_name="t", rule_category="订单欺诈", event_type="通用",
                rule_condition={"field": "x", "op": ">", "value": 1},
                risk_level="高", risk_score=150,  # 超过 100
                action="人工审核",
            )
        assert "risk_score" in str(exc_info.value)


class TestAgentChatRequest:
    """测试 AgentChatRequest 字段验证"""

    def test_valid_chat(self):
        req = AgentChatRequest(message="今天风控情况怎样?")
        assert req.message == "今天风控情况怎样?"
        # session_id 可选, 默认 None
        assert req.session_id is None
