"""
测试 - 案件状态机流转校验
【P1-S7 修复 2026-08-07】原代码无条件 update case.case_status,
"已通过" 的 case 还能被改回"待审核"是 bug. 修复后:
  待审核 → 审核中 / 已通过 / 已拒绝 / 已关闭
  审核中 → 已通过 / 已拒绝 / 已关闭
  已通过 / 已拒绝 / 已关闭 → 终态, 不能再改
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.service import case as case_module
from app.schemas import CaseReviewRequest


def _make_request(decision: str) -> CaseReviewRequest:
    """CaseReviewRequest 的 decision 字段只允许 3 个终态值."""
    return CaseReviewRequest(decision=decision, reviewer="admin")


def _make_case(case_status: str) -> SimpleNamespace:
    """构造一个 mock RiskCase 对象, status 是 case_status."""
    return SimpleNamespace(
        case_id="cas_test_001",
        case_status=case_status,
        user_id="1001",
    )


async def _async_noop():
    """空 async 函数, 给 mock db.commit 用."""
    return None


class TestAllowedTransitions:
    """白名单本身: 每个状态允许的目标状态."""

    def test_pending_can_go_4_targets(self):
        """待审核 → 4 个状态 (审核中 + 3 个终态)"""
        allowed = case_module._ALLOWED_CASE_TRANSITIONS["待审核"]
        assert allowed == {"审核中", "已通过", "已拒绝", "已关闭"}

    def test_reviewing_can_close_pass_reject(self):
        """审核中 → 3 个结束状态都行 (防御性)"""
        allowed = case_module._ALLOWED_CASE_TRANSITIONS["审核中"]
        assert allowed == {"已通过", "已拒绝", "已关闭"}

    def test_final_states_have_no_transitions(self):
        """3 个终态没有出边"""
        for s in ("已通过", "已拒绝", "已关闭"):
            assert case_module._ALLOWED_CASE_TRANSITIONS[s] == set()


class TestReviewCaseStateMachine:
    """review_case 的状态机校验."""

    def _db_with_case(self, case):
        """构造 mock db, execute 返回给定的 case."""
        async def fake_execute(_stmt):
            class _R:
                def scalar_one_or_none(self_inner):
                    return case
            return _R()
        # 【P4-L1】mock db 需要有 add() (review_case 现在会调 record_action → db.add)
        from unittest.mock import MagicMock
        return SimpleNamespace(
            execute=fake_execute, commit=_async_noop, add=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_pending_to_passed_ok(self, monkeypatch):
        """待审核 → 已通过: 合法"""
        case = _make_case("待审核")
        db = self._db_with_case(case)

        async def fake_get_detail(_db, _cid):
            return SimpleNamespace(case_id="cas_test_001", case_status="已通过")
        monkeypatch.setattr(case_module, "get_case_detail", fake_get_detail)

        result = await case_module.review_case(db, "cas_test_001", _make_request("已通过"))
        assert result.case_status == "已通过"

    @pytest.mark.asyncio
    async def test_pending_to_rejected_ok(self):
        """待审核 → 已拒绝: 合法"""
        case = _make_case("待审核")
        db = self._db_with_case(case)

        async def fake_get_detail(_db, _cid):
            return SimpleNamespace(case_id="cas_test_001", case_status="已拒绝")
        import app.service.case as cm
        cm.get_case_detail = fake_get_detail

        result = await case_module.review_case(db, "cas_test_001", _make_request("已拒绝"))
        assert result.case_status == "已拒绝"

    @pytest.mark.asyncio
    async def test_passed_terminal_state_rejected(self):
        """已通过(终态) → 已通过: 非法, 应抛 400"""
        case = _make_case("已通过")
        db = self._db_with_case(case)
        with pytest.raises(HTTPException) as exc_info:
            await case_module.review_case(db, "cas_test_001", _make_request("已通过"))
        assert exc_info.value.status_code == 400
        assert "已通过" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_rejected_terminal_state_rejected(self):
        """已拒绝(终态) → 已关闭: 非法"""
        case = _make_case("已拒绝")
        db = self._db_with_case(case)
        with pytest.raises(HTTPException) as exc_info:
            await case_module.review_case(db, "cas_test_001", _make_request("已关闭"))
        assert exc_info.value.status_code == 400
        assert "已拒绝" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_closed_terminal_state_rejected(self):
        """已关闭(终态) → 已通过: 非法"""
        case = _make_case("已关闭")
        db = self._db_with_case(case)
        with pytest.raises(HTTPException) as exc_info:
            await case_module.review_case(db, "cas_test_001", _make_request("已通过"))
        assert exc_info.value.status_code == 400
        assert "已关闭" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_nonexistent_case_returns_none(self):
        """案件不存在 → 返回 None (跟原行为一致)"""
        db = self._db_with_case(None)
        result = await case_module.review_case(db, "cas_not_exist", _make_request("已通过"))
        assert result is None
