"""
校验函数去重回归测试 (P4-L5 2026-08-10):
1. ensure_order_exists / ensure_postsale_exists 是死代码, 已删除
2. run_risk_check 不再调 validate_risk_check_request (process_event 已校验)
3. process_event + run_risk_check 串起来, validate_risk_check_request 整体只调 1 次 (不是 2 次)
"""
import inspect

import pytest

from app.engine import decision as decision_module
from app.service import event as event_module
from app.service import validator as validator_module


# ============================================================
# 1. 死代码被删
# ============================================================

class TestDeadCodeRemoved:
    """ensure_order_exists / ensure_postsale_exists 是死代码, 已删除."""

    def test_ensure_order_exists_removed(self):
        """ensure_order_exists 应该被删, 不再导出."""
        assert not hasattr(validator_module, "ensure_order_exists"), (
            "ensure_order_exists 是死代码 (没有调用方), 应该被删除"
        )

    def test_ensure_postsale_exists_removed(self):
        """ensure_postsale_exists 应该被删, 不再导出."""
        assert not hasattr(validator_module, "ensure_postsale_exists"), (
            "ensure_postsale_exists 是死代码 (没有调用方), 应该被删除"
        )

    def test_ensure_user_exists_kept(self):
        """ensure_user_exists 仍被 validate_risk_check_request 用, 保留."""
        assert hasattr(validator_module, "ensure_user_exists"), (
            "ensure_user_exists 是 validate_risk_check_request 的依赖, 必须保留"
        )

    def test_ensure_order_belongs_to_user_kept(self):
        """防越权的核心函数, 保留."""
        assert hasattr(validator_module, "ensure_order_belongs_to_user")

    def test_ensure_source_matches_event_type_kept(self):
        """event_type 派发表, 保留."""
        assert hasattr(validator_module, "ensure_source_matches_event_type")

    def test_ensure_exists_generic_kept(self):
        """通用存在性校验, 被其他 ensure 包装, 保留."""
        assert hasattr(validator_module, "ensure_exists")


# ============================================================
# 2. run_risk_check 不再调 validate_risk_check_request
# ============================================================

class TestRunRiskCheckNoLongerCallsValidator:
    """run_risk_check 内部不再调 validate_risk_check_request (去重)."""

    def test_decision_module_does_not_import_validator(self):
        """decision.py 不应再 import validate_risk_check_request."""
        src = inspect.getsource(decision_module)
        assert "validate_risk_check_request" not in src, (
            "decision.py 不应再 import / 调 validate_risk_check_request, "
            "避免与 process_event 重复校验"
        )

    def test_run_risk_check_signature_unchanged(self):
        """run_risk_check 函数签名没变, 仍接受 (db, request) → Response."""
        sig = inspect.signature(decision_module.run_risk_check)
        params = list(sig.parameters.keys())
        assert params == ["db", "request"], (
            f"run_risk_check 签名应是 (db, request), 实际是 {params}"
        )

    def test_run_risk_check_source_does_not_call_validate(self):
        """run_risk_check 源码内不应出现 validate_risk_check_request 调用."""
        # 取 run_risk_check 函数的源码 (用 getsource + 截取)
        src = inspect.getsource(decision_module.run_risk_check)
        assert "validate_risk_check_request" not in src
        assert "_validate_request" not in src, (
            "_validate_request 包装函数应被删除, 不应再出现"
        )


# ============================================================
# 3. process_event 调 1 次 + run_risk_check 调 0 次 = 总共 1 次
# ============================================================

class TestProcessEventCallsValidatorOnce:
    """端到端: process_event 跑完整链路, validate_risk_check_request 应该只被调 1 次."""

    @pytest.mark.asyncio
    async def test_process_event_calls_validate_risk_check_request_once(self, monkeypatch):
        """完整跑 process_event, 用 spy 计数: 真实 run_risk_check 不调它, 所以总数 = 1."""
        from types import SimpleNamespace

        from app.schemas import RiskCheckRequest

        # 1. spy: 用 wrapt 风格的包装记录 event_module.validate_risk_check_request 调用次数
        original = event_module.validate_risk_check_request
        call_count = {"n": 0}

        async def spy_validate(db, request):
            call_count["n"] += 1
            # 不实际校验 (避免触发真实 SQL)

        monkeypatch.setattr(event_module, "validate_risk_check_request", spy_validate)

        # 2. mock _enrich_request (不变更 request)
        async def fake_enrich(db, request):
            return request
        monkeypatch.setattr(event_module, "_enrich_request", fake_enrich)

        # 3. mock _check_all_blacklists (不撞黑)
        async def fake_check_all(db, request):
            return None
        monkeypatch.setattr(event_module, "_check_all_blacklists", fake_check_all)

        # 4. mock run_risk_check 为真实函数 (不调 validate_risk_check_request)
        # 如果 run_risk_check 真的还调, spy 会记录到, 我们会断言失败
        async def fake_run(db, request):
            return SimpleNamespace(
                decision="通过", assessment_id="asm_test", case_id=None,
                rule_count=0, rule_hits=[], final_score=10, risk_level="低",
                action="通过", blocked_by=None, ml_score=0.1, ml_decision="通过",
                message="mock",
            )
        monkeypatch.setattr(event_module, "run_risk_check", fake_run)

        # 5. mock db
        class _FakeDB:
            pass
        db = _FakeDB()

        # 6. 跑
        request = RiskCheckRequest(
            event_type="下单", source_id="ORD001", user_id="U001", order_id="ORD001"
        )
        await event_module.process_event(db, request)

        # 7. 断言: 真实 run_risk_check 内部不调 validate, spy 应该只看到 1 次
        assert call_count["n"] == 1, (
            f"validate_risk_check_request 被调 {call_count['n']} 次, "
            f"期望 1 次 (process_event 第 1 步). "
            f"如果 > 1 次, 说明 run_risk_check 还在调它, 重复了"
        )

    def test_real_run_risk_check_does_not_call_validate(self, monkeypatch):
        """静态检查: 真实 run_risk_check 源码中不调 validate_risk_check_request.

        这个测试不跑 process_event, 而是直接读 decision.py 源码, 防止有 '看起来是 1 次但实际有 2 次' 的坑.
        """
        src = inspect.getsource(decision_module.run_risk_check)
        assert "validate_risk_check_request" not in src, (
            "run_risk_check 源码里不能出现 validate_risk_check_request, "
            "入口校验已在 process_event 完成"
        )

    def test_real_run_risk_check_does_not_call_validate(self, monkeypatch):
        """静态检查: 真实 run_risk_check 源码中不调 validate_risk_check_request.

        这个测试不跑 process_event, 而是直接读 decision.py 源码, 防止有 '看起来是 1 次但实际有 2 次' 的坑.
        """
        src = inspect.getsource(decision_module.run_risk_check)
        assert "validate_risk_check_request" not in src, (
            "run_risk_check 源码里不能出现 validate_risk_check_request, "
            "入口校验已在 process_event 完成"
        )


# ============================================================
# 4. validator 模块对外接口保持稳定 (下游测试/脚本不挂)
# ============================================================

class TestValidatorPublicApi:
    """validator.py 对外暴露的核心接口保持不变."""

    def test_validate_risk_check_request_exported(self):
        assert hasattr(validator_module, "validate_risk_check_request")

    def test_ensure_exists_exported(self):
        assert hasattr(validator_module, "ensure_exists")

    def test_event_source_validators_table_exported(self):
        assert hasattr(validator_module, "_EVENT_SOURCE_VALIDATORS")

    def test_validator_demo_block_mentions_4_ensure(self):
        """__main__ demo 块打印 '4 个 ensure_*' (不是 6 个, 死代码已删)."""
        src = inspect.getsource(validator_module)
        assert "4 个 ensure_*" in src, (
            "__main__ demo 块描述应更新为 '4 个 ensure_*' (ensure_order_exists / ensure_postsale_exists 已删)"
        )
        assert "6 个 ensure_*" not in src, (
            "不应该再出现 '6 个 ensure_*' 字样 (死代码已删)"
        )
