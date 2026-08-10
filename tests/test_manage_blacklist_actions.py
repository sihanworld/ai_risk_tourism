"""
黑名单管理 4 action 回归测试 (P4-L5 2026-08-10):
- _manage_blacklist_impl 按 action 动态传参, 避免 list 误传 blacklist_type 抛 TypeError
- 验证: list / check / add / remove 4 个 action 都能正常调用
- 验证: remove 走 case.py::remove_blacklist (P3-M9 软删 + 审计) 而不是硬删
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import tools as tools_module
from app.models_risk import RiskBlacklist


# ============================================================
# 公共 fixture: 4 个 action 都用到的 mock db
# ============================================================

def _make_db() -> MagicMock:
    """Mock AsyncSession: commit/refresh/flush 都得是 awaitable."""
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


# ============================================================
# 1. _manage_blacklist_impl 4 个 action 都能调通
# ============================================================

class TestManageBlacklistAllActions:
    """_manage_blacklist_impl 字典派发 4 个 action, 每个 action 都有合适 kwargs."""

    @pytest.mark.asyncio
    async def test_list_action_works_without_blacklist_type(self):
        """【P4-L5 修复核心】list 不需要 blacklist_type, 之前传了会抛 TypeError."""
        db = _make_db()
        with patch("app.agent.tools.get_blacklist", new=AsyncMock(return_value=(0, []))):
            # 即便 LLM 无脑传 blacklist_type="用户" 也不该报错
            result = await tools_module._manage_blacklist_impl(
                db=db, action="list", blacklist_type="用户", value="", reason="",
            )
        assert "items" in result, f"list 应返回 JSON, 实际 {result[:100]}"
        assert "total" in result, f"list 应包含 total 字段, 实际 {result[:100]}"

    @pytest.mark.asyncio
    async def test_list_action_works_with_empty_blacklist_type(self):
        """LLM 调用时 blacklist_type 可能传空字符串, list 也该能跑."""
        db = _make_db()
        with patch("app.agent.tools.get_blacklist", new=AsyncMock(return_value=(0, []))):
            result = await tools_module._manage_blacklist_impl(
                db=db, action="list", blacklist_type="", value="", reason="",
            )
        assert "items" in result

    @pytest.mark.asyncio
    async def test_check_action_uses_blacklist_type(self):
        """check 必须传 blacklist_type, 验证透传到 case.check_blacklist."""
        db = _make_db()
        with patch("app.agent.tools.check_blacklist", new=AsyncMock(return_value=True)) as mock_check:
            result = await tools_module._manage_blacklist_impl(
                db=db, action="check", blacklist_type="用户", value="U001", reason="",
            )
        # 验证透传参数
        mock_check.assert_called_once()
        call_args = mock_check.call_args
        assert call_args[0][1] == "用户", "blacklist_type 透传"
        assert call_args[0][2] == "U001", "value 透传"
        assert "在黑名单中" in result

    @pytest.mark.asyncio
    async def test_add_action_uses_blacklist_type_and_reason(self):
        """add 必须传 blacklist_type + reason."""
        from app.schemas import BlacklistResponse

        db = _make_db()
        fake_resp = BlacklistResponse(
            blacklist_id=1, blacklist_type="用户", blacklist_value="U001",
            reason="test_reason", expire_time=None, create_time="2026-01-01T00:00:00",
        )
        with patch("app.agent.tools.add_blacklist", new=AsyncMock(return_value=fake_resp)):
            result = await tools_module._manage_blacklist_impl(
                db=db, action="add", blacklist_type="用户", value="U001", reason="test_reason",
            )
        assert "已添加到黑名单" in result
        assert "test_reason" in result

    @pytest.mark.asyncio
    async def test_remove_action_uses_soft_delete_via_case_remove(self):
        """【P4-L5 修复】remove 走 case.remove_blacklist (软删 + 审计), 不用 db.delete()."""
        db = _make_db()
        # 1. 工具层 SELECT 拿到 blacklist_id
        fake_bl = RiskBlacklist(
            blacklist_id=42, blacklist_type="用户", blacklist_value="U001", reason="old"
        )
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=fake_bl)
        ))
        # 2. 验证 case.remove_blacklist 被调, 而不是 db.delete
        with patch("app.agent.tools.remove_blacklist", new=AsyncMock(return_value=True)) as mock_remove:
            result = await tools_module._manage_blacklist_impl(
                db=db, action="remove", blacklist_type="用户", value="U001", reason="",
            )
        # 走的是软删, 调的是 case.remove_blacklist
        mock_remove.assert_called_once()
        assert mock_remove.call_args[0][1] == 42, "传 blacklist_id=42 给 case.remove_blacklist"
        # 工具层不能自己 db.delete (硬删), 必须走 case.remove_blacklist
        assert "已从黑名单移除" in result

    @pytest.mark.asyncio
    async def test_remove_action_record_not_found(self):
        """没找到记录 → 友好提示, 不抛异常."""
        db = _make_db()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))
        result = await tools_module._manage_blacklist_impl(
            db=db, action="remove", blacklist_type="用户", value="NONEXIST", reason="",
        )
        assert "未找到黑名单记录" in result

    @pytest.mark.asyncio
    async def test_unknown_action_returns_friendly_error(self):
        """action 不在字典里 → 友好提示, 不抛 KeyError."""
        db = _make_db()
        result = await tools_module._manage_blacklist_impl(
            db=db, action="delete_all", blacklist_type="用户", value="", reason="",
        )
        assert "不支持的操作" in result
        assert "add/remove/check/list" in result


# ============================================================
# 2. 字典派发表配置正确
# ============================================================

class TestBlacklistActionsConfig:
    """_BLACKLIST_ACTIONS / _BLACKLIST_TYPE_REQUIRED 配置正确."""

    def test_all_four_actions_registered(self):
        assert set(tools_module._BLACKLIST_ACTIONS.keys()) == {"add", "check", "list", "remove"}

    def test_blacklist_type_required_actions(self):
        """blacklist_type 必传: add / check / remove; 不要传: list."""
        assert tools_module._BLACKLIST_TYPE_REQUIRED == {"add", "check", "remove"}

    def test_list_impl_does_not_accept_blacklist_type(self):
        """_blacklist_list_impl 签名只要 db, 不要 blacklist_type."""
        import inspect
        sig = inspect.signature(tools_module._blacklist_list_impl)
        params = list(sig.parameters.keys())
        assert params == ["db"], f"list_impl 签名应只有 [db], 实际 {params}"


# ============================================================
# 3. case.py 黑名单管理函数签名 (boundary 锁定)
# ============================================================

class TestCaseServiceBlacklistSignatures:
    """case.py 黑名单 4 个管理函数: blacklist_type 哪些要哪些不要."""

    def test_check_blacklist_signature(self):
        """check_blacklist 必须接受 (db, blacklist_type, value)."""
        from app.service.case import check_blacklist
        import inspect
        sig = inspect.signature(check_blacklist)
        params = list(sig.parameters.keys())
        assert params == ["db", "blacklist_type", "value"], (
            f"check_blacklist 应是 (db, blacklist_type, value), 实际 {params}"
        )

    def test_add_blacklist_takes_request_not_kwargs(self):
        """add_blacklist 接 BlacklistCreate 请求体, blacklist_type 在 request 里."""
        from app.service.case import add_blacklist
        import inspect
        sig = inspect.signature(add_blacklist)
        params = list(sig.parameters.keys())
        assert "request" in params, "add_blacklist 应该有 request 参数 (BlacklistCreate)"
        assert "blacklist_type" not in params, "add_blacklist 不该直接接 blacklist_type kwarg"

    def test_get_blacklist_no_blacklist_type(self):
        """get_blacklist 不接受 blacklist_type (查全表)."""
        from app.service.case import get_blacklist
        import inspect
        sig = inspect.signature(get_blacklist)
        params = list(sig.parameters.keys())
        assert "blacklist_type" not in params, "get_blacklist 不该有 blacklist_type 参数"

    def test_remove_blacklist_uses_id_not_type_value(self):
        """remove_blacklist 用 blacklist_id 定位, 不用 (type, value)."""
        from app.service.case import remove_blacklist
        import inspect
        sig = inspect.signature(remove_blacklist)
        params = list(sig.parameters.keys())
        assert "blacklist_id" in params
        assert "blacklist_type" not in params, (
            "remove_blacklist 应用 blacklist_id 定位, 不用 (type, value)"
        )
        assert "value" not in params, "remove_blacklist 不该有 value 参数"
