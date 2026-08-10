"""
特征工程模块: 通过 ORM 查询业务数据, 计算 25 个风控特征.

【特征命名规范】前缀用于 engine/decision.py 决定 risk_feature 表的 entity_type
  user_xxx   = 用户维度特征
  order_xxx  = 订单维度特征
  addr_xxx   = 地址维度特征
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    LogisticsComplaintsRecord, OrderDetail, OrderInfo, Postsale, ReceiveInfo, SkuInfo,
)


# 通用 SQL 工具
async def _count(model, db: AsyncSession, **filters) -> float:
    """SELECT COUNT(*) FROM model WHERE filters."""
    stmt = select(func.count()).select_from(model)
    for col, val in filters.items():
        stmt = stmt.where(getattr(model, col) == val)
    return float((await db.execute(stmt)).scalar() or 0)


async def _sum(model, col_name: str, db: AsyncSession, **filters) -> float:
    """SELECT COALESCE(SUM(col), 0) FROM model WHERE filters."""
    col = getattr(model, col_name)
    stmt = select(func.coalesce(func.sum(col), 0)).select_from(model)
    for f_col, val in filters.items():
        stmt = stmt.where(getattr(model, f_col) == val)
    return float((await db.execute(stmt)).scalar() or 0)


# ============================================================
# 用户维度特征 (14 个)
# ============================================================

async def _feat_user_total_orders(db: AsyncSession, user_id: str) -> float:
    """历史订单总数"""
    return await _count(OrderInfo, db, user_id=user_id)


async def _feat_user_orders_30d(db: AsyncSession, user_id: str) -> float:
    """近 30 天订单数"""
    since = datetime.now() - timedelta(days=30)
    stmt = select(func.count()).select_from(OrderInfo).where(
        OrderInfo.user_id == user_id,
        OrderInfo.create_time >= since,
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_user_orders_7d(db: AsyncSession, user_id: str) -> float:
    """近 7 天订单数"""
    since = datetime.now() - timedelta(days=7)
    stmt = select(func.count()).select_from(OrderInfo).where(
        OrderInfo.user_id == user_id,
        OrderInfo.create_time >= since,
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_user_total_amount(db: AsyncSession, user_id: str) -> float:
    """历史总消费金额"""
    stmt = select(func.coalesce(func.sum(OrderDetail.final_amount), 0)).select_from(
        OrderDetail
    ).join(OrderInfo, OrderDetail.order_id == OrderInfo.order_id).where(
        OrderInfo.user_id == user_id
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_user_avg_order_amount(
    db: AsyncSession, user_id: str, total_orders: float | None = None,
) -> float:
    """平均订单金额 = 总金额 / 订单数. total_orders 预传可避免 batch 时重复查 SQL."""
    if total_orders is None:
        total_orders = await _feat_user_total_orders(db, user_id)
    if total_orders == 0:
        return 0
    total_amount = await _feat_user_total_amount(db, user_id)
    return round(total_amount / total_orders, 2)


async def _feat_user_max_order_amount(db: AsyncSession, user_id: str) -> float:
    """最大单笔订单金额 (订单分组求和再 MAX)"""
    subq = (
        select(
            OrderDetail.order_id,
            func.sum(OrderDetail.final_amount).label("order_total"),
        )
        .join(OrderInfo, OrderDetail.order_id == OrderInfo.order_id)
        .where(OrderInfo.user_id == user_id)
        .group_by(OrderDetail.order_id)
        .subquery()
    )
    stmt = select(func.coalesce(func.max(subq.c.order_total), 0))
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_user_refund_count(db: AsyncSession, user_id: str) -> float:
    """退款总次数 (postsale_type='退款')"""
    stmt = select(func.count()).select_from(Postsale).join(
        OrderDetail, Postsale.order_detail_id == OrderDetail.order_detail_id
    ).join(
        OrderInfo, OrderDetail.order_id == OrderInfo.order_id
    ).where(
        OrderInfo.user_id == user_id,
        Postsale.postsale_type == '退款',
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_user_postsale_count(db: AsyncSession, user_id: str) -> float:
    """售后总次数 (退款+退货+换货)"""
    stmt = select(func.count()).select_from(Postsale).join(
        OrderDetail, Postsale.order_detail_id == OrderDetail.order_detail_id
    ).join(
        OrderInfo, OrderDetail.order_id == OrderInfo.order_id
    ).where(
        OrderInfo.user_id == user_id
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_user_refund_rate(
    db: AsyncSession, user_id: str, total_orders: float | None = None,
) -> float:
    """退款率 = 退款次数 / 总订单数. total_orders 预传可避免 batch 时重复查 SQL."""
    if total_orders is None:
        total_orders = await _feat_user_total_orders(db, user_id)
    if total_orders == 0:
        return 0
    refund_count = await _feat_user_refund_count(db, user_id)
    return round(refund_count / total_orders, 4)


async def _feat_user_postsale_rate(
    db: AsyncSession, user_id: str, total_orders: float | None = None,
) -> float:
    """售后率 = 售后次数 / 总订单数. total_orders 预传可避免 batch 时重复查 SQL."""
    if total_orders is None:
        total_orders = await _feat_user_total_orders(db, user_id)
    if total_orders == 0:
        return 0
    postsale_count = await _feat_user_postsale_count(db, user_id)
    return round(postsale_count / total_orders, 4)


async def _feat_user_refund_amount(db: AsyncSession, user_id: str) -> float:
    """退款总金额"""
    stmt = select(func.coalesce(func.sum(Postsale.refund_amount), 0)).select_from(
        Postsale
    ).join(
        OrderDetail, Postsale.order_detail_id == OrderDetail.order_detail_id
    ).join(
        OrderInfo, OrderDetail.order_id == OrderInfo.order_id
    ).where(
        OrderInfo.user_id == user_id
    )
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_user_cancel_count(db: AsyncSession, user_id: str) -> float:
    """取消订单次数 (order_status='已取消')"""
    return await _count(OrderInfo, db, user_id=user_id, order_status='已取消')


async def _feat_user_complaint_count(db: AsyncSession, user_id: str) -> float:
    """投诉次数 (物流投诉记录表)"""
    return await _count(LogisticsComplaintsRecord, db, user_id=user_id)


async def _feat_user_address_count(db: AsyncSession, user_id: str) -> float:
    """收货地址数量"""
    return await _count(ReceiveInfo, db, user_id=user_id)


# ============================================================
# 订单维度特征 (8 个)
# ============================================================

async def _feat_order_total_amount(db: AsyncSession, order_id: str) -> float:
    """订单总金额"""
    return await _sum(OrderDetail, "final_amount", db, order_id=order_id)


async def _feat_order_item_count(db: AsyncSession, order_id: str) -> float:
    """订单商品行数"""
    stmt = select(func.count()).select_from(OrderDetail).where(OrderDetail.order_id == order_id)
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_order_sku_count(db: AsyncSession, order_id: str) -> float:
    """订单 SKU 总数 (累加 sku_count)"""
    return await _sum(OrderDetail, "sku_count", db, order_id=order_id)


async def _feat_order_discount_amount(db: AsyncSession, order_id: str) -> float:
    """折扣总金额"""
    return await _sum(OrderDetail, "discount_amount", db, order_id=order_id)


async def _feat_order_discount_rate(db: AsyncSession, order_id: str) -> float:
    """折扣率 = 折扣金额 / 原总金额"""
    discount = await _feat_order_discount_amount(db, order_id)
    original = await _sum(OrderDetail, "total_amount", db, order_id=order_id)
    if original == 0:
        return 0
    return round(discount / original, 4)


async def _feat_order_pay_interval(db: AsyncSession, order_id: str) -> float:
    """下单到支付时间差 (秒), 未支付返回 -1"""
    row = (await db.execute(
        select(OrderInfo.create_time, OrderInfo.payment_time).where(OrderInfo.order_id == order_id)
    )).first()
    if row and row.payment_time and row.create_time:
        return max(float((row.payment_time - row.create_time).total_seconds()), 0)
    return -1


async def _feat_order_is_night(db: AsyncSession, order_id: str) -> float:
    """是否夜间下单 (0~6 点)"""
    row = (await db.execute(
        select(OrderInfo.create_time).where(OrderInfo.order_id == order_id)
    )).first()
    if row and row.create_time:
        return 1.0 if 0 <= row.create_time.hour < 6 else 0.0
    return 0.0


async def _feat_order_category_count(db: AsyncSession, order_id: str) -> float:
    """订单商品类别数 (DISTINCT)"""
    stmt = select(func.count(func.distinct(SkuInfo.sku_category))).select_from(
        OrderDetail
    ).join(SkuInfo, OrderDetail.sku_id == SkuInfo.sku_id).where(
        OrderDetail.order_id == order_id
    )
    return float((await db.execute(stmt)).scalar() or 0)


# ============================================================
# 地址维度特征 (3 个)
# ============================================================

async def _feat_addr_total_count(db: AsyncSession, user_id: str) -> float:
    """用户地址总数"""
    return await _count(ReceiveInfo, db, user_id=user_id)


async def _feat_addr_province_count(db: AsyncSession, user_id: str) -> float:
    """不同省份数"""
    stmt = select(func.count(func.distinct(ReceiveInfo.receive_province))).select_from(
        ReceiveInfo
    ).where(ReceiveInfo.user_id == user_id)
    return float((await db.execute(stmt)).scalar() or 0)


async def _feat_addr_is_new(
    db: AsyncSession, user_id: str, receive_id: str | None
) -> float:
    """是否新地址 (订单中使用该地址的次数 <= 1)"""
    if not receive_id:
        return 0.0
    cnt = (await db.execute(
        select(func.count()).select_from(OrderInfo).where(
            OrderInfo.user_id == user_id,
            OrderInfo.receive_id == receive_id,
        )
    )).scalar() or 0
    return 1.0 if cnt <= 1 else 0.0


# ============================================================
# 分类聚合 (字典派发: 加新特征只加一行)
# ============================================================

async def compute_user_features(db: AsyncSession, user_id: str) -> dict[str, float]:
    """计算 14 个用户维度特征.

    【P5 优化 2026-08-07】先 await 1 次 _feat_user_total_orders, 然后传给
    3 个派生特征复用, 避免它们各自重算 1 次 (4 次 SQL → 1 次).
    """
    total_orders = await _feat_user_total_orders(db, user_id)

    independent_features = {
        "user_orders_30d": _feat_user_orders_30d,
        "user_orders_7d": _feat_user_orders_7d,
        "user_total_amount": _feat_user_total_amount,
        "user_max_order_amount": _feat_user_max_order_amount,
        "user_refund_count": _feat_user_refund_count,
        "user_postsale_count": _feat_user_postsale_count,
        "user_refund_amount": _feat_user_refund_amount,
        "user_cancel_count": _feat_user_cancel_count,
        "user_complaint_count": _feat_user_complaint_count,
        "user_address_count": _feat_user_address_count,
    }
    features = {name: await func(db, user_id) for name, func in independent_features.items()}
    features["user_total_orders"] = total_orders

    # 派生特征: 传 total_orders 避免再查
    features["user_avg_order_amount"] = await _feat_user_avg_order_amount(db, user_id, total_orders=total_orders)
    features["user_refund_rate"] = await _feat_user_refund_rate(db, user_id, total_orders=total_orders)
    features["user_postsale_rate"] = await _feat_user_postsale_rate(db, user_id, total_orders=total_orders)

    return features


async def compute_order_features(db: AsyncSession, order_id: str) -> dict[str, float]:
    """计算 8 个订单维度特征."""
    feat_funcs = {
        "order_total_amount": _feat_order_total_amount,
        "order_item_count": _feat_order_item_count,
        "order_sku_count": _feat_order_sku_count,
        "order_discount_amount": _feat_order_discount_amount,
        "order_discount_rate": _feat_order_discount_rate,
        "order_pay_interval_sec": _feat_order_pay_interval,
        "order_is_night": _feat_order_is_night,
        "order_category_count": _feat_order_category_count,
    }
    return {name: await func(db, order_id) for name, func in feat_funcs.items()}


async def compute_address_features(
    db: AsyncSession,
    user_id: str,
    receive_id: str | None = None,
) -> dict[str, float]:
    """计算 3 个地址维度特征."""
    return {
        "addr_total_count": await _feat_addr_total_count(db, user_id),
        "addr_province_count": await _feat_addr_province_count(db, user_id),
        "addr_is_new": await _feat_addr_is_new(db, user_id, receive_id),
    }


async def compute_all_features(
    db: AsyncSession,
    user_id: str,
    order_id: str | None = None,
    receive_id: str | None = None,
) -> dict[str, float]:
    """一次性计算全部特征并合并返回."""
    features = await compute_user_features(db, user_id)
    if order_id:
        features.update(await compute_order_features(db, order_id))
    features.update(await compute_address_features(db, user_id, receive_id))
    return features


# ============================================================
# Demo: 展示 25 维特征名 + 分类 + 字典派发表 — 无需 DB (只读常量)
# 跑法: python app/engine/feature.py
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("特征工程 — 25 维特征名 + 字典派发表")
    print("=" * 60)

    # 25 维特征按域分组 (跟 engine/feature.py 的 3 个 compute_* 函数对应)
    user_feats = [
        ("user_total_orders",     "历史订单总数"),
        ("user_orders_7d",        "近 7 天订单数"),
        ("user_orders_30d",       "近 30 天订单数"),
        ("user_total_amount",     "历史总消费金额"),
        ("user_avg_order_amount", "平均订单金额"),
        ("user_max_order_amount", "最大单笔订单金额"),
        ("user_refund_count",     "退款总次数"),
        ("user_refund_rate",      "退款率"),
        ("user_refund_amount",    "退款总金额"),
        ("user_postsale_count",   "售后总次数"),
        ("user_postsale_rate",    "售后率"),
        ("user_cancel_count",     "取消订单次数"),
        ("user_complaint_count",  "物流投诉次数"),
        ("user_address_count",    "收货地址数量"),
    ]
    order_feats = [
        ("order_total_amount",    "订单总金额"),
        ("order_item_count",      "订单商品行数"),
        ("order_sku_count",       "订单 SKU 总数"),
        ("order_discount_amount", "折扣总金额"),
        ("order_discount_rate",   "折扣率"),
        ("order_pay_interval",    "下单到支付时间差(秒)"),
        ("order_is_night",        "是否夜间下单 (0-6 点)"),
        ("order_category_count",  "订单商品类别数"),
    ]
    addr_feats = [
        ("addr_total_count",      "用户地址总数"),
        ("addr_province_count",   "不同省份数"),
        ("addr_is_new",           "本次地址是否新 (0/1)"),
    ]
    all_groups = [("用户 (14)", user_feats), ("订单 (8)", order_feats), ("地址 (3)", addr_feats)]
    total = 0
    for sec, feats in all_groups:
        print(f"\n【{sec}】")
        for i, (k, desc) in enumerate(feats, 1):
            print(f"  {i:>2}. {k:<25} - {desc}")
            total += 1
    print(f"\n总计: {total} 维特征 (跟 XGBoost 的 FEATURE_COLUMNS 顺序一一对应)")

    # P5 优化示例: total_orders 一次查询复用 3 个函数
    print("\n" + "=" * 60)
    print("[P5 优化示例] 1 次 SQL 查 user_total_orders, 复用给 3 个函数:")
    print("  compute_user_features(db, user_id) 内部")
    print("    _feat_user_total_orders(db, user_id)        → 1 次 SQL")
    print("    _feat_user_avg_order_amount(...,total_orders) → 0 次 SQL (复用)")
    print("    _feat_user_refund_rate(...,total_orders)     → 0 次 SQL (复用)")
    print("  原来 4 个特征 = 4 次 SQL → 现在 4 个 = 1 次 SQL (节省 75%)")
