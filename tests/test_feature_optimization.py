"""
测试 - 特征工程冗余调用优化 (P5)
【P5 优化 2026-08-07】_feat_user_total_orders 在 compute_user_features 内被
3 个派生函数 (avg / refund_rate / postsale_rate) 各调 1 次, 冗余.
修复: 预计算 1 次 total_orders, 传给 3 个派生函数复用.
验证:
  1. SQL 次数: 1 次 (从 4 次 → 1 次)
  2. 派生特征结果与原版完全一致
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine import feature as feature_module
from app.engine.feature import (
    _feat_user_avg_order_amount,
    _feat_user_refund_rate,
    _feat_user_postsale_rate,
    _feat_user_total_orders,
    compute_user_features,
)


def _row(value):
    """构造 SQLAlchemy Row-like, 让 execute() 返回该值."""
    return SimpleNamespace(scalar=MagicMock(return_value=value))


class TestPreComputedTotalOrders:
    """3 个派生函数接受 pre-computed total_orders 时不再查 SQL."""

    @pytest.mark.asyncio
    async def test_avg_skips_total_orders_query_when_pre_computed(self):
        """传 total_orders=10 → 不该调 _feat_user_total_orders"""
        db = MagicMock()
        call_log = []

        async def fake_total_orders(*_args, **_kwargs):
            call_log.append("total_orders")
            return 0  # 不该被调

        async def fake_total_amount(*_args, **_kwargs):
            call_log.append("total_amount")
            return 100.0

        # patch 让 _feat_user_total_orders / _feat_user_total_amount 走 fake
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(feature_module, "_feat_user_total_orders", fake_total_orders)
            mp.setattr(feature_module, "_feat_user_total_amount", fake_total_amount)
            result = await _feat_user_avg_order_amount(db, "u1", total_orders=10)
        assert result == 10.0  # 100 / 10
        assert "total_orders" not in call_log, "传 total_orders 时不该再查 _feat_user_total_orders"
        assert "total_amount" in call_log

    @pytest.mark.asyncio
    async def test_refund_rate_skips_query_when_pre_computed(self):
        db = MagicMock()
        call_log = []

        async def fake_total_orders(*_args, **_kwargs):
            call_log.append("total_orders")
            return 0

        async def fake_refund_count(*_args, **_kwargs):
            call_log.append("refund_count")
            return 5

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(feature_module, "_feat_user_total_orders", fake_total_orders)
            mp.setattr(feature_module, "_feat_user_refund_count", fake_refund_count)
            result = await _feat_user_refund_rate(db, "u1", total_orders=10)
        assert result == 0.5  # 5 / 10
        assert "total_orders" not in call_log

    @pytest.mark.asyncio
    async def test_postsale_rate_skips_query_when_pre_computed(self):
        db = MagicMock()
        call_log = []

        async def fake_total_orders(*_args, **_kwargs):
            call_log.append("total_orders")
            return 0

        async def fake_postsale_count(*_args, **_kwargs):
            call_log.append("postsale_count")
            return 3

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(feature_module, "_feat_user_total_orders", fake_total_orders)
            mp.setattr(feature_module, "_feat_user_postsale_count", fake_postsale_count)
            result = await _feat_user_postsale_rate(db, "u1", total_orders=10)
        assert result == 0.3  # 3 / 10
        assert "total_orders" not in call_log

    @pytest.mark.asyncio
    async def test_avg_falls_back_to_query_when_not_provided(self):
        """不传 total_orders → 正常调 _feat_user_total_orders (向后兼容)"""
        db = MagicMock()
        call_log = []

        async def fake_total_orders(*_args, **_kwargs):
            call_log.append("total_orders")
            return 5

        async def fake_total_amount(*_args, **_kwargs):
            call_log.append("total_amount")
            return 200.0

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(feature_module, "_feat_user_total_orders", fake_total_orders)
            mp.setattr(feature_module, "_feat_user_total_amount", fake_total_amount)
            result = await _feat_user_avg_order_amount(db, "u1")
        assert result == 40.0  # 200 / 5
        assert "total_orders" in call_log  # 向后兼容, 没传就调

    @pytest.mark.asyncio
    async def test_zero_total_orders_returns_zero(self):
        """total_orders=0 时, 3 个派生特征都返回 0, 不再查更多 SQL"""
        db = MagicMock()
        call_log = []

        async def fake_should_not_call(*_args, **_kwargs):
            call_log.append("should_not_call")
            return 99

        with pytest.MonkeyPatch.context() as mp:
            # total_amount / refund_count / postsale_count 都不该被调
            mp.setattr(feature_module, "_feat_user_total_amount", fake_should_not_call)
            mp.setattr(feature_module, "_feat_user_refund_count", fake_should_not_call)
            mp.setattr(feature_module, "_feat_user_postsale_count", fake_should_not_call)
            assert await _feat_user_avg_order_amount(db, "u1", total_orders=0) == 0
            assert await _feat_user_refund_rate(db, "u1", total_orders=0) == 0
            assert await _feat_user_postsale_rate(db, "u1", total_orders=0) == 0
        assert call_log == [], f"total_orders=0 时不该查更多, 实际调了 {call_log}"


class TestComputeUserFeaturesOptimization:
    """compute_user_features 内部: total_orders 只算 1 次."""

    @pytest.mark.asyncio
    async def test_total_orders_called_only_once(self):
        """_feat_user_total_orders 整个 compute_user_features 流程里只被调 1 次"""
        call_log = []
        call_counts = {"_feat_user_total_orders": 0}

        async def counting_total_orders(*_args, **_kwargs):
            call_counts["_feat_user_total_orders"] += 1
            return 100  # 假设有 100 单

        # 模拟其他 11 个特征函数 (不依赖 total_orders)
        async def fake_independent(*_args, **_kwargs):
            return 0.0

        with pytest.MonkeyPatch.context() as mp:
            # 把 _feat_user_total_orders 替换成计数版本
            mp.setattr(feature_module, "_feat_user_total_orders", counting_total_orders)
            # 把其他特征都换成 fake
            for fn_name in [
                "_feat_user_orders_30d", "_feat_user_orders_7d",
                "_feat_user_total_amount", "_feat_user_max_order_amount",
                "_feat_user_refund_count", "_feat_user_postsale_count",
                "_feat_user_refund_amount", "_feat_user_cancel_count",
                "_feat_user_complaint_count", "_feat_user_address_count",
            ]:
                mp.setattr(feature_module, fn_name, fake_independent)
            # refund_rate / postsale_rate 内部还会调 _feat_user_total_orders / _feat_user_refund_count 等
            # 但因 total_orders=0 (本测试返回 0) 走 early return, 不调其他
            mp.setattr(feature_module, "_feat_user_refund_count", fake_independent)
            mp.setattr(feature_module, "_feat_user_postsale_count", fake_independent)

            db = MagicMock()
            features = await compute_user_features(db, "u1")

        # 关键断言: _feat_user_total_orders 只被调 1 次
        assert call_counts["_feat_user_total_orders"] == 1, (
            f"_feat_user_total_orders 应该是 1 次, 实际 {call_counts['_feat_user_total_orders']} 次, "
            f"优化失败 (3 个派生特征各自重算了)"
        )
        # 14 个特征都返回了
        assert len(features) == 14
        # user_total_orders = 100 (用预计算值)
        assert features["user_total_orders"] == 100
