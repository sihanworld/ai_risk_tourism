"""
撞黑短路 UI 提示回归测试 (P4-L5 2026-08-10):
- 用户场景: 风控检查时撞黑名单, 前端不能只显示"未加载模型", 必须显示"撞黑名单短路"提示
- 锁住: blocked_by / message 字段在响应里有值, risk_check.html 模板引用 blocked_by
"""
import inspect
from pathlib import Path

import pytest

from app.schemas import RiskCheckResponse
from app.service import event as event_module


# ============================================================
# 1. 后端 _blacklist_reject 必须填 message + blocked_by
# ============================================================

class TestBlacklistRejectResponse:
    """_blacklist_reject 返回的响应里必须有 message (告诉用户为啥拒) + blocked_by."""

    def test_blacklist_reject_has_message(self):
        """_blacklist_reject 必须填 message 字段, 前端直接显示."""
        from app.schemas import RiskCheckRequest
        req = RiskCheckRequest(
            event_type="预订", source_id="ORD001", user_id="U001", order_id="ORD001",
        )
        resp = event_module._blacklist_reject(req, "用户")
        assert resp.message is not None, "撞黑响应必须有 message 字段"
        assert "用户" in resp.message, f"message 应包含黑名单类型, 实际 {resp.message!r}"

    def test_blacklist_reject_has_blocked_by(self):
        from app.schemas import RiskCheckRequest
        req = RiskCheckRequest(
            event_type="预订", source_id="ORD001", user_id="U001", order_id="ORD001",
        )
        resp = event_module._blacklist_reject(req, "地址")
        assert resp.blocked_by == "地址"

    def test_blacklist_reject_ml_score_none(self):
        """撞黑场景 ml_score 必须 None (前端不渲染 ML 块, 避免'未加载模型'误导)."""
        from app.schemas import RiskCheckRequest
        req = RiskCheckRequest(
            event_type="预订", source_id="ORD001", user_id="U001", order_id="ORD001",
        )
        resp = event_module._blacklist_reject(req, "手机号")
        assert resp.ml_score is None
        assert resp.ml_decision is None

    def test_blacklist_reject_assessment_id_marker(self):
        """assessment_id='blacklist_reject' 是前端判断撞黑短路的标志."""
        from app.schemas import RiskCheckRequest
        req = RiskCheckRequest(
            event_type="预订", source_id="ORD001", user_id="U001", order_id="ORD001",
        )
        resp = event_module._blacklist_reject(req, "用户")
        assert resp.assessment_id == "blacklist_reject"
        assert resp.event_id == "blacklist_reject"

    def test_blacklist_reject_rule_count_zero(self):
        """撞黑不跑 7 步, 所以 rule_count=0, triggered_rules=[]."""
        from app.schemas import RiskCheckRequest
        req = RiskCheckRequest(
            event_type="预订", source_id="ORD001", user_id="U001", order_id="ORD001",
        )
        resp = event_module._blacklist_reject(req, "用户")
        assert resp.rule_count == 0
        assert resp.triggered_rules == []


# ============================================================
# 2. RiskCheckResponse schema 接受 message 字段
# ============================================================

class TestRiskCheckResponseSchema:
    """RiskCheckResponse 加了 message 字段 (Optional), 跟原来字段并存."""

    def test_message_field_accepted(self):
        resp = RiskCheckResponse(
            assessment_id="asm_test", event_id="evt_test", user_id="U001",
            final_score=100, risk_level="极高",
            decision="拒绝", rule_count=0, triggered_rules=[],
            features={}, create_time="2026-01-01",
            message="撞黑名单: 用户",
            blocked_by="用户",
        )
        assert resp.message == "撞黑名单: 用户"
        assert resp.blocked_by == "用户"

    def test_message_field_optional(self):
        """不传 message 应该 OK (向后兼容, 旧代码不传这个字段)."""
        resp = RiskCheckResponse(
            assessment_id="asm_test", event_id="evt_test", user_id="U001",
            final_score=10, risk_level="低",
            decision="通过", rule_count=1, triggered_rules=[],
            features={}, create_time="2026-01-01",
        )
        assert resp.message is None
        assert resp.blocked_by is None

    def test_ml_score_field_optional(self):
        """ml_score 仍 Optional, 默认 None."""
        resp = RiskCheckResponse(
            assessment_id="asm_test", event_id="evt_test", user_id="U001",
            final_score=10, risk_level="低",
            decision="通过", rule_count=0, triggered_rules=[],
            features={}, create_time="2026-01-01",
        )
        assert resp.ml_score is None
        assert resp.ml_decision is None


# ============================================================
# 3. 前端 risk_check.html 模板必须引用 blocked_by / message
# ============================================================

class TestRiskCheckPageBlacklistHint:
    """risk_check.html 必须能识别撞黑短路, 渲染警告 + 不渲染 ML 评分块."""

    @pytest.fixture
    def html(self):
        path = Path(__file__).resolve().parent.parent / "templates" / "risk_check.html"
        return path.read_text(encoding="utf-8")

    def test_risk_check_html_references_message(self, html):
        """模板必须渲染 result.message 字段."""
        assert "result.message" in html, (
            "risk_check.html 没引用 result.message, 用户看不到撞黑原因"
        )

    def test_risk_check_html_detects_blacklist_reject(self, html):
        """模板必须判断 assessment_id === 'blacklist_reject' 来走撞黑分支."""
        assert "blacklist_reject" in html, (
            "risk_check.html 没判断 blacklist_reject 短路, 会显示 '未加载模型' 误导用户"
        )

    def test_risk_check_html_skips_ml_score_on_blacklist(self, html):
        """撞黑分支不渲染 ML 评分块 (用 isBlacklistReject 三元表达式隔离)."""
        assert "isBlacklistReject" in html, (
            "risk_check.html 应该有 isBlacklistReject 变量控制撞黑分支"
        )


# ============================================================
# 4. 端到端: 撞黑请求的完整响应字段快照
# ============================================================

class TestBlacklistResponseShape:
    """锁住撞黑响应的字段快照, 防止以后改 _blacklist_reject 破坏前端 UI."""

    def test_response_keys_for_blacklist_reject(self):
        """撞黑响应必须包含的字段: decision / final_score / blocked_by / message / ml_score=null."""
        from app.schemas import RiskCheckRequest
        req = RiskCheckRequest(
            event_type="预订", source_id="ORD001", user_id="U001", order_id="ORD001",
        )
        resp = event_module._blacklist_reject(req, "用户")
        # 响应转 dict 看完整字段
        d = resp.model_dump()
        required = ["assessment_id", "event_id", "user_id", "final_score", "risk_level",
                    "decision", "rule_count", "triggered_rules", "features", "create_time",
                    "ml_score", "ml_decision", "blocked_by", "message"]
        for k in required:
            assert k in d, f"响应缺字段 {k}"
        # 关键值校验
        assert d["decision"] == "拒绝"
        assert d["final_score"] == 100
        assert d["risk_level"] == "极高"
        assert d["blocked_by"] == "用户"
        assert d["message"] == "撞黑名单: 用户"
        assert d["ml_score"] is None  # 前端用这个判断不渲染 ML 块
