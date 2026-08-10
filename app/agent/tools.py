"""
AI Agent 工具集 (8 个 LangChain @tool).

  风控决策工具 (RISK_TOOLS, 4): 风险检查 / 案件查询 / 用户画像 / 黑名单管理
  数据分析工具 (DATA_TOOLS, 4): 仪表盘统计 / 趋势 / 规则效果 / 业务数据

架构: 业务实现是 _impl 函数, @tool 包装层只负责转 LLM 入参 → 调 _safe_call → _impl.
"""
import asyncio
import json
import logging
import ulid
from datetime import datetime, timedelta
from typing import Any, Literal

from langchain_core.tools import tool
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.engine.feature import compute_user_features
from app.models import (
    OrderDetail,
    OrderInfo,
    Postsale,
    ReceiveInfo,
    RiskAssessment,
    RiskBlacklist,
    RiskCase,
    RiskRule,
)
from app.schemas import BlacklistCreate, RiskCheckRequest
from app.service.case import (
    add_blacklist,
    check_blacklist,
    get_blacklist,
    get_case_list,
    get_case_statistics,
    get_user_profile,
    remove_blacklist,
)
from app.service.event import process_event

logger = logging.getLogger(__name__)


# ============================================================
# 公共 helper
# ============================================================

async def _safe_call(error_label: str, impl, **kwargs) -> str:
    """8 个 @tool 共享的执行模板: 开 session → 调 impl → 异常转字符串.
    """
    try:
        async with AsyncSessionLocal() as db:
            return await impl(db=db, **kwargs)
    except Exception as e:
        error_id = f"err_{ulid.new().str.lower()[:12]}"
        logger.exception(
            "%s 执行失败 [error_id=%s] args=%s",
            error_label, error_id, {k: v for k, v in kwargs.items() if k != "db"},
        )
        return f"{error_label}失败: {e} (error_id={error_id})"


# SQLAlchemy Row → dict (处理 datetime / Decimal 等不可 JSON 化的类型)
def _row_to_dict(row) -> dict:
    """SQLAlchemy 2.0 的 Row → dict.  datetime → ISO 字符串, Decimal/numpy 数值 → float."""
    item = {}
    for key, val in row._mapping.items():
        if isinstance(val, datetime):
            val = val.isoformat()
        elif hasattr(val, "__float__"):  # Decimal / numpy 数值
            val = float(val)
        item[key] = val
    return item


# ============================================================
# 风控决策工具 (4 个)
# ============================================================

async def _risk_check_impl(
    *, db: AsyncSession, user_id: str, event_type: str, source_id: str,
) -> str:
    """对用户和事件执行实时风控检查 (走 process_event 7 步)."""
    request = RiskCheckRequest(event_type=event_type, source_id=source_id, user_id=user_id)
    result = await process_event(db, request)
    return json.dumps({
        "assessment_id": result.assessment_id,
        "user_id": result.user_id,
        "final_score": result.final_score,
        "risk_level": result.risk_level,
        "decision": result.decision,
        "rule_count": result.rule_count,
        "triggered_rules": [r.model_dump() for r in result.triggered_rules],
    }, ensure_ascii=False, indent=2)


async def _query_cases_impl(
    *, db: AsyncSession, status: str, page: int,
) -> str:
    """查询风控案件列表 + 统计 (组合返回, 1 次调用拿全)."""
    case_list = await get_case_list(db, status=status or None, page=page)
    stats = await get_case_statistics(db)
    return json.dumps({
        "cases": [item.model_dump(mode="json") for item in case_list.items],
        "total": case_list.total,
        "page": case_list.page,
        "statistics": stats.model_dump(),
    }, ensure_ascii=False, indent=2)


async def _query_user_profile_impl(*, db: AsyncSession, user_id: str) -> str:
    """查询用户风险画像. 没画像时实时算 14 个 user 特征 (不写库)."""
    profile = await get_user_profile(db, user_id)
    if not profile:
        features = await compute_user_features(db, user_id)
        return json.dumps({
            "user_id": user_id,
            "has_profile": False,
            "computed_features": features,
        }, ensure_ascii=False, indent=2)
    return json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2)


# 黑名单 4 个 action handler
# 【P4-L5 2026-08-10 修复】blacklist_type 不是每个 action 都用:
#   - add / check: 必须 (DB 唯一约束是 (type, value))
#   - list: 不用 (查全表)
#   - remove: 必须 (工具层用 (type, value) 联合定位, 然后调 case.remove_blacklist 走软删 + 审计)
# _manage_blacklist_impl 按 action 动态传参, 避免 list 误传 blacklist_type 抛 TypeError.
async def _blacklist_add_impl(
    *, db: AsyncSession, blacklist_type: Literal["用户","手机号","地址"], value: str, reason: str,
) -> str:
    result = await add_blacklist(db, BlacklistCreate(
        blacklist_type=blacklist_type, blacklist_value=value, reason=reason,
    ))
    await db.commit()
    return f"已添加到黑名单: {result.model_dump(mode='json')}"


async def _blacklist_check_impl(
    *, db: AsyncSession, blacklist_type: str, value: str,
) -> str:
    is_blocked = await check_blacklist(db, blacklist_type, value)
    return f"{'在' if is_blocked else '不在'}黑名单中: {blacklist_type}={value}"


async def _blacklist_list_impl(*, db: AsyncSession) -> str:
    total, items = await get_blacklist(db)
    return json.dumps(
        {"total": total, "items": [b.model_dump(mode="json") for b in items]},
        ensure_ascii=False, indent=2,
    )


async def _blacklist_remove_impl(
    *, db: AsyncSession, blacklist_type: str, value: str,
) -> str:
    # 1. 先用 (type, value) 联合定位拿到 blacklist_id
    bl = (await db.execute(
        select(RiskBlacklist).where(
            RiskBlacklist.blacklist_type == blacklist_type,
            RiskBlacklist.blacklist_value == value,
            RiskBlacklist.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not bl:
        return f"未找到黑名单记录: {blacklist_type}={value}"
    # 2. 走 case.py::remove_blacklist (P3-M9 软删 + 审计日志 + 内部 commit)
    ok = await remove_blacklist(db, bl.blacklist_id)
    if not ok:
        return f"未找到黑名单记录: {blacklist_type}={value} (已被并发移除)"
    return f"已从黑名单移除: {blacklist_type}={value}"


# 黑名单 action dispatch table
# 标注: list 不需要 blacklist_type, 字典派发时跳过这个 kwargs
_BLACKLIST_ACTIONS = {
    "add": _blacklist_add_impl,
    "check": _blacklist_check_impl,
    "list": _blacklist_list_impl,
    "remove": _blacklist_remove_impl,
}
# 哪些 action 需要 blacklist_type (其余 action 不传, 避免 list 抛 TypeError)
_BLACKLIST_TYPE_REQUIRED = {"add", "check", "remove"}


async def _manage_blacklist_impl(
    *, db: AsyncSession, action: str, blacklist_type: Literal["用户","手机号","地址"], value: str, reason: str,
) -> str:
    """黑名单管理统一入口 (字典派发 4 个 action).

    按 action 动态构造 kwargs:
      - add:    {blacklist_type, value, reason}
      - check:  {blacklist_type, value}
      - list:   {} (不需要 blacklist_type)
      - remove: {blacklist_type, value}

    【P4-L5 2026-08-10 修复】之前无脑传 blacklist_type 给所有 action, list 报 TypeError.
    """
    impl = _BLACKLIST_ACTIONS.get(action)
    if not impl:
        return f"不支持的操作: {action}, 请使用 add/remove/check/list"
    # 按 action 动态构造 kwargs
    kwargs: dict = {"db": db}
    if action in _BLACKLIST_TYPE_REQUIRED:
        kwargs["blacklist_type"] = blacklist_type
    if action in ("add", "check", "remove"):
        kwargs["value"] = value
    if action == "add":
        kwargs["reason"] = reason
    return await impl(**kwargs)


# ============================================================
# 数据分析工具 (4 个)
# ============================================================

async def _stats_today(db: AsyncSession) -> dict:
    """今日统计: 评估总数 / 高风险数 / 通过数 / 通过率. 1 条 SQL 拿 3 聚合."""
    today = datetime.now().date()
    row = (await db.execute(
        select(
            func.count().label("total"),
            func.sum(case(
                (RiskAssessment.risk_level.in_(["高", "极高"]), 1), else_=0,
            )).label("high_risk"),
            func.sum(case(
                (RiskAssessment.decision == "通过", 1), else_=0,
            )).label("passed"),
        ).select_from(RiskAssessment).where(func.date(RiskAssessment.create_time) == today)
    )).first()
    # 0 行也是 None, 用 or 0 兜底, 防 TypeError
    total = int(row.total) if row and row.total else 0
    high_risk = int(row.high_risk) if row and row.high_risk else 0
    passed = int(row.passed) if row and row.passed else 0
    pass_rate = round(passed / total * 100, 1) if total > 0 else 0
    return {
        "today_assessments": total,
        "today_high_risk": high_risk,
        "pass_rate": pass_rate,
    }


async def _stats_pending_cases(db: AsyncSession) -> int:
    """待审核案件数."""
    return int((await db.execute(
        select(func.count()).select_from(RiskCase).where(RiskCase.case_status == "待审核")
    )).scalar() or 0)


async def _stats_trend_7d(db: AsyncSession) -> list[dict]:
    """近 7 天每日评估 + 高风险数. GROUP BY 表达式函数 MySQL 5.7+ 也支持."""
    seven_days_ago = datetime.now().date() - timedelta(days=7)
    rows = (await db.execute(
        select(
            func.date(RiskAssessment.create_time).label("dt"),
            func.count().label("cnt"),
            func.sum(case(
                (RiskAssessment.risk_level.in_(["高", "极高"]), 1), else_=0,
            )).label("high_cnt"),
        ).select_from(RiskAssessment)
        .where(func.date(RiskAssessment.create_time) >= seven_days_ago)
        .group_by(func.date(RiskAssessment.create_time))
        .order_by(func.date(RiskAssessment.create_time))
    )).all()
    return [
        {"date": str(r.dt), "count": int(r.cnt), "high_risk_count": int(r.high_cnt or 0)}
        for r in rows
    ]


# 解析最近 N 条评估的 rule_results JSON, 返回 {rule_id: hit_count}
# Python 端解析: MySQL 5.7 没 JSON_TABLE, 500 条足够反映近期规则热度
async def _count_rule_hits(db: AsyncSession, recent_limit: int = 500) -> dict[str, int]:
    rows = (await db.execute(
        select(RiskAssessment.rule_results)
        .order_by(RiskAssessment.create_time.desc())
        .limit(recent_limit)
    )).all()
    counter: dict[str, int] = {}
    for r in rows:
        if not r.rule_results:
            continue
        try:
            rules_data = json.loads(r.rule_results)
        except (json.JSONDecodeError, TypeError):
            continue
        for hit in rules_data:
            rid = hit.get("rule_id")
            if rid:
                counter[rid] = counter.get(rid, 0) + 1
    return counter


# 批量查 rule_name (避免 _parse_top_rules 内部 N+1)
async def _enrich_with_rule_names(db: AsyncSession, rule_ids: list[str]) -> dict[str, str]:
    if not rule_ids:
        return {}
    rows = (await db.execute(
        select(RiskRule.rule_id, RiskRule.rule_name).where(RiskRule.rule_id.in_(rule_ids))
    )).all()
    return {r.rule_id: r.rule_name for r in rows}


# TOP N 规则 + 命中次数 + 名称
async def _parse_top_rules(
    db: AsyncSession, recent_limit: int = 500, top_n: int = 5,
) -> list[dict]:
    counter = await _count_rule_hits(db, recent_limit)
    top = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:top_n]
    names = await _enrich_with_rule_names(db, [rid for rid, _ in top])
    return [
        {
            "rule_id": rid,
            # 找不到 rule_name 时用 rule_id 顶替 (前端至少能显示 ID)
            "rule_name": names.get(rid, rid),
            "hit_count": cnt,
        }
        for rid, cnt in top
    ]


async def _query_dashboard_stats_impl(*, db: AsyncSession) -> str:
    """仪表盘统计统一实现: 今日 + 待审 + 7 天趋势 + 规则 TOP5."""
    today = await _stats_today(db)
    pending = await _stats_pending_cases(db)
    trend = await _stats_trend_7d(db)
    top_rules = await _parse_top_rules(db)
    return json.dumps({
        **today,
        "pending_cases": pending,
        "trend_7d": trend,
        "top_rules": top_rules,
    }, ensure_ascii=False, indent=2)


async def _analyze_risk_trend_impl(*, db: AsyncSession, days: int) -> str:
    """指定天数内每日评估 + 风险等级分布 + 决策分布."""
    since = datetime.now().date() - timedelta(days=days)

    daily = (await db.execute(
        select(
            func.date(RiskAssessment.create_time).label("dt"),
            func.count().label("cnt"),
        ).select_from(RiskAssessment)
        .where(func.date(RiskAssessment.create_time) >= since)
        .group_by(func.date(RiskAssessment.create_time))
        .order_by(func.date(RiskAssessment.create_time))
    )).all()

    # dict([(level, count), ...]) 直接转字典 (键是 level)
    level_dist = dict((await db.execute(
        select(RiskAssessment.risk_level, func.count().label("cnt"))
        .select_from(RiskAssessment)
        .where(func.date(RiskAssessment.create_time) >= since)
        .group_by(RiskAssessment.risk_level)
    )).all())

    decision_dist = dict((await db.execute(
        select(RiskAssessment.decision, func.count().label("cnt"))
        .select_from(RiskAssessment)
        .where(func.date(RiskAssessment.create_time) >= since)
        .group_by(RiskAssessment.decision)
    )).all())

    return json.dumps({
        "period_days": days,
        "daily_counts": [{"date": str(r.dt), "count": r.cnt} for r in daily],
        "risk_level_distribution": level_dist,
        "decision_distribution": decision_dist,
    }, ensure_ascii=False, indent=2)


async def _analyze_rule_effectiveness_impl(*, db: AsyncSession) -> str:
    """所有启用规则的命中率 (用最近 500 条样本近似, 避免扫全表)."""
    total = (await db.execute(select(func.count()).select_from(RiskAssessment))).scalar() or 0
    enabled_rules = (await db.execute(
        select(RiskRule).where(RiskRule.is_enabled == 1).order_by(RiskRule.priority.desc())
    )).scalars().all()
    hit_counter = await _count_rule_hits(db, recent_limit=500)

    rules_stats = [
        {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "category": r.rule_category,
            "score": r.risk_score,
            "hit_count": hit_counter.get(r.rule_id, 0),
            "hit_rate_pct": round(hit_counter.get(r.rule_id, 0) / total * 100, 2) if total > 0 else 0,
        }
        for r in enabled_rules
    ]
    return json.dumps({
        "total_assessments": total,
        "rules": rules_stats,
    }, ensure_ascii=False, indent=2)


# ============================================================
# 业务数据查询 (字典派发 6 种 query_type)
# ============================================================

async def _biz_user_orders(db: AsyncSession, user_id: str, order_id: str, limit: int) -> list[Any]:
    """用户的所有订单 (含聚合总金额). LEFT JOIN 保没明细的订单 total_amount 显 0."""
    order_total_subq = (
        select(
            OrderDetail.order_id,
            func.coalesce(func.sum(OrderDetail.final_amount), 0).label("total_amount"),
        )
        .group_by(OrderDetail.order_id)
        .subquery()
    )
    stmt = (
        select(
            OrderInfo.order_id,
            OrderInfo.create_time,
            OrderInfo.order_status,
            func.coalesce(order_total_subq.c.total_amount, 0).label("total_amount"),
        )
        .select_from(OrderInfo)
        .outerjoin(order_total_subq, OrderInfo.order_id == order_total_subq.c.order_id)
        .where(OrderInfo.user_id == user_id)
        .order_by(OrderInfo.create_time.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def _biz_user_postsales(db: AsyncSession, user_id: str, order_id: str, limit: int) -> list[Any]:
    """用户的售后记录 (3 表 JOIN: postsale → order_detail → order_info)."""
    stmt = (
        select(
            Postsale.postsale_id,
            Postsale.create_time,
            Postsale.postsale_type,
            Postsale.postsale_reason,
            Postsale.postsale_status,
            Postsale.refund_amount,
        )
        .select_from(Postsale)
        .join(OrderDetail, Postsale.order_detail_id == OrderDetail.order_detail_id)
        .join(OrderInfo, OrderDetail.order_id == OrderInfo.order_id)
        .where(OrderInfo.user_id == user_id)
        .order_by(Postsale.create_time.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def _biz_user_addresses(db: AsyncSession, user_id: str, order_id: str, limit: int) -> list[Any]:
    """用户的收货地址."""
    stmt = (
        select(
            ReceiveInfo.receive_id,
            ReceiveInfo.receiver_name,
            ReceiveInfo.receiver_phone,
            ReceiveInfo.receive_province,
            ReceiveInfo.receive_city,
            ReceiveInfo.receive_district,
        )
        .where(ReceiveInfo.user_id == user_id)
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def _biz_order_detail(db: AsyncSession, user_id: str, order_id: str, limit: int) -> list[Any]:
    """订单的明细行."""
    stmt = (
        select(
            OrderDetail.order_detail_id,
            OrderDetail.sku_id,
            OrderDetail.sku_name,
            OrderDetail.sku_count,
            OrderDetail.total_amount,
            OrderDetail.discount_amount,
            OrderDetail.final_amount,
        )
        .where(OrderDetail.order_id == order_id)
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def _biz_recent_orders(db: AsyncSession, user_id: str, order_id: str, limit: int) -> list[Any]:
    """系统最近的订单 (不限 user, 管理员视角)."""
    order_total_subq = (
        select(
            OrderDetail.order_id,
            func.coalesce(func.sum(OrderDetail.final_amount), 0).label("total_amount"),
        )
        .group_by(OrderDetail.order_id)
        .subquery()
    )
    stmt = (
        select(
            OrderInfo.order_id,
            OrderInfo.user_id,
            OrderInfo.create_time,
            OrderInfo.order_status,
            func.coalesce(order_total_subq.c.total_amount, 0).label("total_amount"),
        )
        .select_from(OrderInfo)
        .outerjoin(order_total_subq, OrderInfo.order_id == order_total_subq.c.order_id)
        .order_by(OrderInfo.create_time.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


async def _biz_high_value_orders(db: AsyncSession, user_id: str, order_id: str, limit: int) -> list[Any]:
    """高价值订单 (单笔总价 >= 1000, GROUP BY + HAVING 筛选).

    HAVING 在 GROUP BY 之后筛选聚合结果, 区别于 WHERE (筛行).
    """
    stmt = (
        select(
            OrderInfo.order_id,
            OrderInfo.user_id,
            OrderInfo.create_time,
            func.sum(OrderDetail.final_amount).label("total_amount"),
        )
        .select_from(OrderInfo)
        .join(OrderDetail, OrderInfo.order_id == OrderDetail.order_id)
        .group_by(
            OrderInfo.order_id,
            OrderInfo.user_id,
            OrderInfo.create_time,
        )
        .having(func.sum(OrderDetail.final_amount) >= 1000)
        .order_by(func.sum(OrderDetail.final_amount).desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).all())


# 业务查询 dispatch table
_BIZ_QUERY_HANDLERS = {
    "user_orders": _biz_user_orders,
    "user_postsales": _biz_user_postsales,
    "user_addresses": _biz_user_addresses,
    "order_detail": _biz_order_detail,
    "recent_orders": _biz_recent_orders,
    "high_value_orders": _biz_high_value_orders,
}


async def _query_business_data_impl(
    *, db: AsyncSession, query_type: str, user_id: str, order_id: str, limit: int,
) -> str:
    """业务数据查询统一入口 (字典派发 6 种 query_type)."""
    handler = _BIZ_QUERY_HANDLERS.get(query_type)
    if not handler:
        return f"不支持的查询类型: {query_type}, 可选: {', '.join(_BIZ_QUERY_HANDLERS)}"
    rows = await handler(db, user_id, order_id, limit)
    return json.dumps(
        [_row_to_dict(r) for r in rows],
        ensure_ascii=False, indent=2,
    )


# ============================================================
# @tool 包装层 (8 个 LangChain 工具)
# ============================================================

@tool(
    description=(
        "对指定用户和事件执行实时风险检查。"
        "参数: user_id (用户ID, 如 '1001')、event_type (事件类型, 可选值: 下单/支付/售后申请/物流投诉)、source_id (关联业务ID, 如订单号)。"
        "返回: 风控评估结果字符串, 含评分、风险等级、决策和命中规则。"
        "内部: 走 process_event 7 步流水线 (校验→黑名单→补全→决策)。"
    )
)
async def risk_check(user_id: str, event_type: str, source_id: str) -> str:
    return await _safe_call("风险检查", _risk_check_impl,
                            user_id=user_id, event_type=event_type, source_id=source_id)


@tool(
    description=(
        "查询风控案件列表。"
        "参数: status (案件状态筛选, 可选值: 待审核/审核中/已通过/已拒绝/已关闭, 为空查全部)、page (页码, 默认1)。"
        "返回: 案件列表 + 统计信息 (JSON 字符串)。"
    )
)
async def query_cases(status: str = "", page: int = 1) -> str:
    return await _safe_call("案件查询", _query_cases_impl, status=status, page=page)


@tool(
    description=(
        "查询用户的风险画像信息。"
        "参数: user_id (用户ID, 如 '1001')。"
        "返回: 用户的风险评分、订单统计、退款率、地址数等画像数据; 没画像时实时算 14 个 user 特征。"
    )
)
async def query_user_profile(user_id: str) -> str:
    return await _safe_call("用户画像查询", _query_user_profile_impl, user_id=user_id)


@tool(
    description=(
        "管理风控黑名单。"
        "参数: action (操作类型: add/remove/check/list)、blacklist_type (黑名单类型: 用户/地址/手机号)、value (黑名单值, 添加/检查/移除时需要)、reason (加黑原因, 添加时需要)。"
        "返回: 操作结果 (文本或 JSON)。"
    )
)
async def manage_blacklist(
    action: str, blacklist_type: str = "用户", value: str = "", reason: str = "",
) -> str:
    return await _safe_call("黑名单操作", _manage_blacklist_impl,
                            action=action, blacklist_type=blacklist_type, value=value, reason=reason)


@tool(
    description=(
        "查询风控仪表盘统计数据, 包含今日评估数、高风险数、待审案件数、通过率、近7天趋势、规则TOP5。"
        "返回: JSON 字符串 (4 段数据)。"
    )
)
async def query_dashboard_stats() -> str:
    return await _safe_call("统计查询", _query_dashboard_stats_impl)


@tool(
    description=(
        "分析指定天数内的风控趋势, 包含每日评估量、风险分布、决策分布。"
        "参数: days (分析天数, 默认30天)。"
        "返回: JSON 字符串 (period_days / daily_counts / risk_level_distribution / decision_distribution)。"
    )
)
async def analyze_risk_trend(days: int = 30) -> str:
    return await _safe_call("趋势分析", _analyze_risk_trend_impl, days=days)


@tool(
    description=(
        "分析所有启用规则的命中效果, 包含命中次数、命中率和各规则覆盖情况。"
        "返回: JSON 字符串 (total_assessments / rules[...])。"
    )
)
async def analyze_rule_effectiveness() -> str:
    return await _safe_call("规则效果分析", _analyze_rule_effectiveness_impl)


@tool(
    description=(
        "查询业务数据, 用于数据分析和风控辅助判断。"
        "参数: query_type (查询类型, 可选值: user_orders/user_postsales/user_addresses/order_detail/recent_orders/high_value_orders)、user_id (部分需要)、order_id (部分需要)、limit (返回数量, 默认10)。"
        "返回: 业务数据 (JSON 字符串)。"
    )
)
async def query_business_data(
    query_type: str, user_id: str = "", order_id: str = "", limit: int = 10,
) -> str:
    return await _safe_call("业务数据查询", _query_business_data_impl,
                            query_type=query_type, user_id=user_id, order_id=order_id, limit=limit)


# ============================================================
# Demo: 列出 8 个 @tool + 演示 _safe_call + _row_to_dict 子函数
# 跑法: python app/agent/tools.py
# ============================================================
if __name__ == "__main__":
    from datetime import datetime
    from decimal import Decimal
    print("=" * 60)
    print("Agent Tools — 8 个 @tool + 3 大子函数")
    print("=" * 60)

    # 1. _row_to_dict 子函数: datetime/Decimal 等不可 JSON 化的类型转字符串
    print("\n[1] _row_to_dict 子函数 (Row → dict, 处理 datetime/Decimal):")

    # 用 SQLAlchemy 真实 Row 类型 (用 select 包一下)
    from sqlalchemy import select as _select
    from sqlalchemy.engine.row import Row as _Row
    from sqlalchemy.sql.selectable import Select as _Select

    # 构造一个真实的 Row 对象 (用 sqlalchemy 的 select() 配合 connection.execute 太重)
    # 简化: 直接给 _row_to_dict 喂一个含 _mapping 属性的对象
    class _FakeMapping:
        def __init__(self, data):
            self._mapping = data
    class _FakeRow:
        def __init__(self, data):
            self._mapping = data

    sample = _FakeRow({
        "user_id": "U001",
        "total": Decimal("1234.56"),
        "created": datetime(2026, 8, 8, 12, 30, 0),
    })
    d = _row_to_dict(sample)
    print(f"  Decimal('1234.56')   → {type(d['total']).__name__}  值={d['total']}")
    print(f"  datetime(...)        → {type(d['created']).__name__}  值={d['created']}")
    print(f"  普通字段              → {d['user_id']}")

    # 2. _safe_call 子函数: 异常包装 + error_id
    print("\n[2] _safe_call 子函数 (异常包装模板):")

    async def failing_impl(**kwargs):
        raise ValueError(f"模拟错误: {kwargs.get('uid', '?')}")

    async def success_impl(**kwargs):
        return json.dumps({"user_id": kwargs.get("uid"), "risk_score": 65})

    async def demo_safe_call():
        # 成功路径
        r1 = await _safe_call("测试", success_impl, uid="U001")
        print(f"  成功: {r1}")
        # 失败路径 (返回 JSON 含 error_id, 不抛异常)
        r2 = await _safe_call("测试", failing_impl, uid="U999")
        print(f"  失败: {r2}")

    asyncio.run(demo_safe_call())

    # 3. 8 个 @tool 列表
    print("\n[3] 8 个 @tool (LangChain 工具):")
    tools_list = [
        ("risk_check",            "对用户和事件执行实时风控检查"),
        ("query_cases",           "查询案件列表 (按 status)"),
        ("query_user_profile",    "查询用户风险画像"),
        ("manage_blacklist",      "黑名单管理 (4 action: add/check/list/remove)"),
        ("query_dashboard_stats", "仪表盘统计 (今日+待审+7天趋势+TOP5 规则)"),
        ("analyze_risk_trend",    "指定天数内风险趋势分析"),
        ("analyze_rule_effectiveness", "所有启用规则命中率分析"),
        ("query_business_data",   "业务数据查询 (6 query_type)"),
    ]
    for name, desc in tools_list:
        print(f"  {name:<30}  {desc}")

    # 4. dispatch table
    print("\n[4] 字典派发表 (代码内 lookup):")
    print(f"  _BLACKLIST_ACTIONS  = {list(_BLACKLIST_ACTIONS.keys())}  (4 个 action)")
    print(f"  _BIZ_QUERY_HANDLERS = {list(_BIZ_QUERY_HANDLERS.keys())}  (6 个 query_type)")

    # 5. 8 个 _impl 计数
    print("\n[5] _impl 子函数 (每个 @tool 对应 1 个):")
    impls = [
        _risk_check_impl, _query_cases_impl, _query_user_profile_impl,
        _blacklist_add_impl, _blacklist_check_impl, _blacklist_list_impl, _blacklist_remove_impl,
        _manage_blacklist_impl, _stats_today, _stats_pending_cases, _stats_trend_7d,
        _count_rule_hits, _enrich_with_rule_names, _parse_top_rules,
        _query_dashboard_stats_impl, _analyze_risk_trend_impl, _analyze_rule_effectiveness_impl,
        _biz_user_orders, _biz_user_postsales, _biz_user_addresses,
        _biz_order_detail, _biz_recent_orders, _biz_high_value_orders,
        _query_business_data_impl,
    ]
    print(f"  共 {len(impls)} 个 _impl (其中 4 个黑名单 + 6 个业务查询 + 4 个统计)")

    print("\n" + "=" * 60)
    print("总结: 8 个 tool 共用 1 个 _safe_call 模板 + 3 个字典派发表 (黑名单/业务查询/统计)")


# 工具列表导出: RISK_TOOLS (风控决策) + DATA_TOOLS (数据分析) = ALL_TOOLS (8)
RISK_TOOLS = [risk_check, query_cases, query_user_profile, manage_blacklist]
DATA_TOOLS = [query_dashboard_stats, analyze_risk_trend, analyze_rule_effectiveness, query_business_data]
ALL_TOOLS = RISK_TOOLS + DATA_TOOLS
