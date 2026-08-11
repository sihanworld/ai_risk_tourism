"""
案件管理模块: 案件查询 / 详情 / 审核 / 统计, 黑名单管理, 用户画像查询.

Commit 策略:
  *atomic 后缀: 内部 self-commit, 调用方不要再 commit
  *tx 后缀:    故意不 commit, 留给调用方合并事务
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RiskAssessment, RiskBlacklist, RiskCase, RiskEvent, RiskUserProfile
from app.schemas import (
    AssessmentDetailResponse,
    AssessmentItem,
    AssessmentListResponse,
    BlacklistCreate,
    BlacklistResponse,
    CaseDetailResponse,
    CaseItem,
    CaseListResponse,
    CaseReviewRequest,
    CaseStatistics,
    RuleHitInfo,
    UserProfileResponse,
)
from app.service.action_log import record_action

logger = logging.getLogger(__name__)


# ============================================================
# 黑名单
# ============================================================

async def check_blacklist(db: AsyncSession, blacklist_type: str, value: str) -> bool:
    # 【P4-L5 2026-08-10 修复】P3-M9 软删规范: deleted_at 不为空 = 已删除, 不应判为撞黑.
    # 之前漏过滤导致用户删除黑名单后还能撞黑 (实际是已软删的记录被捞出来).
    # 跟 add_blacklist / get_blacklist / remove_blacklist 保持一致.
    bl = (await db.execute(
        select(RiskBlacklist).where(
            RiskBlacklist.blacklist_type == blacklist_type,
            RiskBlacklist.blacklist_value == value,
            RiskBlacklist.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not bl:
        return False
    if bl.expire_time and bl.expire_time < datetime.now():
        return False
    return True


async def add_blacklist(db: AsyncSession, request: BlacklistCreate) -> BlacklistResponse:
    # 已存在 (未软删) → 更新 reason/expire_time, 不插新行
    existing = (await db.execute(
        select(RiskBlacklist).where(
            RiskBlacklist.blacklist_type == request.blacklist_type,
            RiskBlacklist.blacklist_value == request.blacklist_value,
            RiskBlacklist.deleted_at.is_(None),
        )
    )).scalar_one_or_none()

    if existing:
        before_value = {
            "reason": existing.reason,
            "expire_time": str(existing.expire_time) if existing.expire_time else None,
        }
        existing.reason = request.reason
        existing.expire_time = request.expire_time
        await record_action(
            db, operator="admin", action_type="ADD_BLACKLIST",
            target_type="blacklist", target_id=existing.blacklist_id,
            before_value=before_value,
            after_value={"reason": request.reason, "expire_time": str(request.expire_time) if request.expire_time else None},
            remark=f"更新黑名单 {request.blacklist_type}={request.blacklist_value}",
        )
        return BlacklistResponse(
            blacklist_id=existing.blacklist_id,
            blacklist_type=existing.blacklist_type,
            blacklist_value=existing.blacklist_value,
            reason=existing.reason,
            expire_time=existing.expire_time,
            create_time=existing.create_time,
        )

    bl = RiskBlacklist(
        blacklist_type=request.blacklist_type,
        blacklist_value=request.blacklist_value,
        reason=request.reason,
        expire_time=request.expire_time,
    )
    db.add(bl)
    await db.flush()  # 先 flush 拿自增 ID
    await record_action(
        db, operator="admin", action_type="ADD_BLACKLIST",
        target_type="blacklist", target_id=bl.blacklist_id,
        before_value=None,
        after_value={
            "blacklist_type": bl.blacklist_type,
            "blacklist_value": bl.blacklist_value,
            "reason": bl.reason,
            "expire_time": str(bl.expire_time) if bl.expire_time else None,
        },
        remark=f"新增黑名单 {bl.blacklist_type}={bl.blacklist_value}",
    )
    return BlacklistResponse(
        blacklist_id=bl.blacklist_id,
        blacklist_type=bl.blacklist_type,
        blacklist_value=bl.blacklist_value,
        reason=bl.reason,
        expire_time=bl.expire_time,
        create_time=bl.create_time,
    )


async def get_blacklist(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[BlacklistResponse]]:
    """分页查询黑名单, 返回 (total, items).

    P4-L4 2026-08-08: 加 total 对齐 assessments/cases 的 {items, total} 模式,
    前端统一用 buildPaginationHtml 渲染分页栏.
    """
    # 1 次 COUNT (软删的不算)
    total = int((await db.execute(
        select(func.count())
        .select_from(RiskBlacklist)
        .where(RiskBlacklist.deleted_at.is_(None))
    )).scalar() or 0)

    # 1 次 paged SELECT
    items = (await db.execute(
        select(RiskBlacklist)
        .where(RiskBlacklist.deleted_at.is_(None))
        .order_by(RiskBlacklist.create_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()
    return total, [
        BlacklistResponse(
            blacklist_id=b.blacklist_id,
            blacklist_type=b.blacklist_type,
            blacklist_value=b.blacklist_value,
            reason=b.reason,
            expire_time=b.expire_time,
            create_time=b.create_time,
        )
        for b in items
    ]


# 软删 (P3-M9): UPDATE deleted_at = NOW() 而非硬删, 保留 audit
async def remove_blacklist(db: AsyncSession, blacklist_id: int) -> bool:
    bl = (await db.execute(
        select(RiskBlacklist).where(
            RiskBlacklist.blacklist_id == blacklist_id,
            RiskBlacklist.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not bl:
        return False

    await record_action(
        db, operator="admin", action_type="REMOVE_BLACKLIST",
        target_type="blacklist", target_id=bl.blacklist_id,
        before_value={
            "blacklist_type": bl.blacklist_type,
            "blacklist_value": bl.blacklist_value,
            "reason": bl.reason,
        },
        after_value=None,
        remark=f"移除黑名单 {bl.blacklist_type}={bl.blacklist_value}",
    )

    bl.deleted_at = datetime.now()
    await db.commit()
    return True


# ============================================================
# 案件
# ============================================================

# 【P1-S7】案件状态机: 待审核 → 审核中/已通过/已拒绝/已关闭;
#                          审核中 → 已通过/已拒绝/已关闭; 其余终态
_ALLOWED_CASE_TRANSITIONS: dict[str, set[str]] = {
    "待审核": {"审核中", "已通过", "已拒绝", "已关闭"},
    "审核中": {"已通过", "已拒绝", "已关闭"},
    "已通过": set(),
    "已拒绝": set(),
    "已关闭": set(),
}


# ============================================================


# 【P2-S8】1 次 LEFT JOIN 拿 final_score / risk_level, 避免 N+1 (20 条/页 = 21 次 SQL → 2 次)
async def get_case_list(
    db: AsyncSession,
    status: str | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
    active_only: bool = False,
) -> CaseListResponse:
    """案件列表查询.

    active_only=True: 只查未结案 (待审核 + 审核中), 用于前端案件工作台默认视图.
    已结案 (已通过/已拒绝/已关闭) 走 assessment 历史页查.
    统计 API 不受 active_only 影响, 永远全状态.
    """
    filters = []
    if status:
        filters.append(RiskCase.case_status == status)
    elif active_only:
        filters.append(RiskCase.case_status.in_(("待审核", "审核中")))
    if category:
        filters.append(RiskCase.case_category == category)

    count_stmt = select(func.count()).select_from(RiskCase)
    for f in filters:
        count_stmt = count_stmt.where(f)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    paged_stmt = (
        select(RiskCase, RiskAssessment.final_score, RiskAssessment.risk_level)
        .outerjoin(RiskAssessment, RiskCase.assessment_id == RiskAssessment.assessment_id)
        .where(*filters)
        .order_by(RiskCase.create_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(paged_stmt)).all()
    items = [
        CaseItem(
            case_id=r[0].case_id,
            assessment_id=r[0].assessment_id,
            user_id=r[0].user_id,
            case_status=r[0].case_status,
            case_category=r[0].case_category,
            # assessment 可能为 None (历史数据孤儿 / LEFT JOIN 没匹配上)
            final_score=r.final_score,
            risk_level=r.risk_level,
            create_time=r[0].create_time,
            # 业务回溯字段 (前端"重做检查"按钮用)
            source_id=r[0].source_id,
            event_type=r[0].event_type,
        )
        for r in rows
    ]
    return CaseListResponse(items=items, total=total, page=page, page_size=page_size)


# 案件详情: 4 张表数据合并 (案件 + 评估 + 命中规则 + 用户画像)
async def get_case_detail(db: AsyncSession, case_id: str) -> CaseDetailResponse | None:
    case = (await db.execute(
        select(RiskCase).where(RiskCase.case_id == case_id)
    )).scalar_one_or_none()
    if not case:
        return None

    assessment = (await db.execute(
        select(RiskAssessment).where(RiskAssessment.assessment_id == case.assessment_id)
    )).scalar_one_or_none()

    # rule_results 是 JSON 字符串, 存当时命中的所有规则
    triggered_rules = []
    if assessment and assessment.rule_results:
        try:
            triggered_rules = [RuleHitInfo(**r) for r in json.loads(assessment.rule_results)]
        except (json.JSONDecodeError, TypeError, ValidationError):
            # 【P3-M5】加 ValidationError 兜底: 历史脏数据 rule_results 缺字段不影响主流程
            logger.warning(
                "case %s 的 rule_results 解析失败, 兜底空 list: %s",
                case.case_id, str(assessment.rule_results)[:200],
            )

    profile = (await db.execute(
        select(RiskUserProfile).where(RiskUserProfile.user_id == case.user_id)
    )).scalar_one_or_none()
    user_profile = None
    if profile:
        user_profile = {
            "risk_score": profile.risk_score,
            "risk_level": profile.risk_level,
            "total_orders": profile.total_orders,
            "total_refunds": profile.total_refunds,
            # DECIMAL → float (JSON 不支持 Decimal 类型)
            "refund_rate": float(profile.refund_rate),
            "avg_order_amount": float(profile.avg_order_amount),
            "trip_city_count": profile.trip_city_count,
            "complaint_count": profile.complaint_count,
            "assessment_count": profile.assessment_count,
        }

    return CaseDetailResponse(
        case_id=case.case_id,
        assessment_id=case.assessment_id,
        user_id=case.user_id,
        case_status=case.case_status,
        case_category=case.case_category,
        risk_detail=json.loads(case.risk_detail) if case.risk_detail else None,
        reviewer=case.reviewer,
        review_comment=case.review_comment,
        review_time=case.review_time,
        create_time=case.create_time,
        final_score=assessment.final_score if assessment else None,
        risk_level=assessment.risk_level if assessment else None,
        decision=assessment.decision if assessment else None,
        triggered_rules=triggered_rules,
        user_profile=user_profile,
        # 【P4-L4 2026-08-08】ML 评分字段 (前端 sigmoid 校准成 0-100 风险分)
        ml_score=float(assessment.ml_score) if assessment and assessment.ml_score is not None else None,
        ml_decision=assessment.ml_decision if assessment else None,
        source_id=case.source_id,
        event_type=case.event_type,
    )


# 审核: 通过 / 拒绝 / 关闭 (3 选 1)
# 拒绝 + add_to_blacklist=True → 自动加用户到黑名单, 与案件同步 1 个 commit
async def review_case(
    db: AsyncSession,
    case_id: str,
    request: CaseReviewRequest,
) -> CaseDetailResponse | None:
    case = (await db.execute(
        select(RiskCase).where(RiskCase.case_id == case_id)
    )).scalar_one_or_none()
    if not case:
        return None

    # 【P1-S7】状态机校验: 拒绝非法流转
    current_status = case.case_status
    target_status = request.decision
    allowed_targets = _ALLOWED_CASE_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_targets:
        raise HTTPException(
            status_code=400,
            detail=f"案件状态不能从 '{current_status}' 流转到 '{target_status}', "
                   f"合法的目标状态: {sorted(allowed_targets) or '(终态, 不可再改)'}",
        )

    case.case_status = request.decision
    case.reviewer = request.reviewer
    case.review_comment = request.review_comment
    case.review_time = datetime.now()

    await record_action(
        db, operator=request.reviewer, action_type="REVIEW_CASE",
        target_type="case", target_id=case.case_id,
        before_value={"case_status": current_status},
        after_value={"case_status": request.decision, "review_comment": request.review_comment or ""},
        remark=f"审核 {request.decision}" + (" + 加黑名单" if request.decision == "已拒绝" and request.add_to_blacklist else ""),
    )

    # 联动加黑名单 (add_blacklist 内部 flush 不 commit, 合并到下面 1 个事务)
    if request.decision == "已拒绝" and request.add_to_blacklist:
        expire_time = None
        if request.blacklist_expire_hours and request.blacklist_expire_hours > 0:
            expire_time = datetime.now() + timedelta(hours=request.blacklist_expire_hours)
        await add_blacklist(db, BlacklistCreate(
            blacklist_type="用户",
            blacklist_value=case.user_id,
            reason=f"案件审核拒绝: {case.case_id}",
            expire_time=expire_time,
        ))

    # 1 个事务: 案件 + (可选)黑名单, 原子性
    await db.commit()
    return await get_case_detail(db, case_id)


# 3 条 GROUP BY 拿全部统计: 1 总数 + 5 状态数 + N 分类数
async def get_case_statistics(db: AsyncSession) -> CaseStatistics:
    total = (await db.execute(
        select(func.count(RiskCase.case_id))
    )).scalar() or 0

    status_rows = (await db.execute(
        select(RiskCase.case_status, func.count(RiskCase.case_id))
        .group_by(RiskCase.case_status)
    )).all()
    status_map = {row[0]: row[1] for row in status_rows}

    category_rows = (await db.execute(
        select(RiskCase.case_category, func.count(RiskCase.case_id))
        .group_by(RiskCase.case_category)
    )).all()
    by_category = {cat: cnt for cat, cnt in category_rows if cat}  # 过滤 None

    return CaseStatistics(
        total=int(total),
        pending=status_map.get("待审核", 0),
        reviewing=status_map.get("审核中", 0),
        approved=status_map.get("已通过", 0),
        rejected=status_map.get("已拒绝", 0),
        closed=status_map.get("已关闭", 0),
        by_category=by_category,
    )


# ============================================================
# 用户画像
# ============================================================

# 没画像时返回 None, 不做实时算的兜底 (留给 agent tools 那层做)
async def get_user_profile(db: AsyncSession, user_id: str) -> UserProfileResponse | None:
    profile = (await db.execute(
        select(RiskUserProfile).where(RiskUserProfile.user_id == user_id)
    )).scalar_one_or_none()
    if not profile:
        return None

    return UserProfileResponse(
        user_id=profile.user_id,
        risk_score=profile.risk_score,
        risk_level=profile.risk_level,
        total_orders=profile.total_orders,
        total_refunds=profile.total_refunds,
        # DECIMAL 字段要转 float 才能 JSON 序列化
        refund_rate=float(profile.refund_rate),
        avg_order_amount=float(profile.avg_order_amount),
        trip_city_count=profile.trip_city_count,
        complaint_count=profile.complaint_count,
        assessment_count=profile.assessment_count,
        last_assessment_time=profile.last_assessment_time,
        profile_data=json.loads(profile.profile_data) if profile.profile_data else None,
    )


# ============================================================
# 评估历史 (P3-S9 2026-08-08)
# 案件工作台只看待办, 评估历史页查全量 (含已结案 + 通过/标记)
# ============================================================

async def list_assessments(
    db: AsyncSession,
    decision: str | None = None,
    risk_level: str | None = None,
    event_type: str | None = None,
    user_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AssessmentListResponse:
    """全量评估列表 (含通过/标记/人工审核/拒绝 4 种 decision).

    筛选维度 (可选):
      - decision: 通过 / 标记 / 人工审核 / 拒绝
      - risk_level: 低 / 中 / 高 / 极高
      - event_type: 预订 / 支付 / 退改签 / 行程开始 (JOIN risk_event)
      - user_id: 精确匹配

    注: risk_assessment 表没有 event_type 字段, 要 JOIN risk_event 拿.
    """
    a_filters = []
    if decision:
        a_filters.append(RiskAssessment.decision == decision)
    if risk_level:
        a_filters.append(RiskAssessment.risk_level == risk_level)
    if user_id:
        a_filters.append(RiskAssessment.user_id == user_id)

    # 1 次 COUNT (LEFT JOIN risk_event 以便 event_type 筛选生效)
    count_stmt = (
        select(func.count())
        .select_from(RiskAssessment)
        .outerjoin(RiskEvent, RiskAssessment.event_id == RiskEvent.event_id)
    )
    if event_type:
        count_stmt = count_stmt.where(RiskEvent.event_type == event_type)
    for f in a_filters:
        count_stmt = count_stmt.where(f)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    # 1 次 paged SELECT (LEFT JOIN + 取 event_type 冗余到结果)
    paged_stmt = (
        select(RiskAssessment, RiskEvent.event_type)
        .outerjoin(RiskEvent, RiskAssessment.event_id == RiskEvent.event_id)
        .where(*a_filters)
    )
    if event_type:
        paged_stmt = paged_stmt.where(RiskEvent.event_type == event_type)
    paged_stmt = (
        paged_stmt.order_by(RiskAssessment.create_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(paged_stmt)).all()

    items = [
        AssessmentItem(
            assessment_id=r[0].assessment_id,
            event_id=r[0].event_id,
            user_id=r[0].user_id,
            event_type=r[1] or "未知",
            final_score=r[0].final_score,
            risk_level=r[0].risk_level,
            decision=r[0].decision,
            rule_count=r[0].rule_count,
            ml_score=float(r[0].ml_score) if r[0].ml_score is not None else None,
            ml_decision=r[0].ml_decision,
            create_time=r[0].create_time,
        )
        for r in rows
    ]
    return AssessmentListResponse(items=items, total=total, page=page, page_size=page_size)


async def get_assessment_detail(
    db: AsyncSession, assessment_id: str,
) -> AssessmentDetailResponse | None:
    """评估详情: 基础字段 + 命中规则 + ML 评分 + 关联 event 的 event_data.

    rule_results 是 JSON 字符串, 解析失败时降级空 list (P3-M5 兜底).
    """
    a = (await db.execute(
        select(RiskAssessment).where(RiskAssessment.assessment_id == assessment_id)
    )).scalar_one_or_none()
    if not a:
        return None

    # 拿关联的 event (含 event_type / event_source_id / event_data)
    ev = (await db.execute(
        select(RiskEvent).where(RiskEvent.event_id == a.event_id)
    )).scalar_one_or_none()

    try:
        triggered = json.loads(a.rule_results) if a.rule_results else []
        triggered_rules = [RuleHitInfo(**r) for r in triggered]
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        logger.warning(
            "assessment %s 的 rule_results 解析失败, 兜底空 list: %s",
            a.assessment_id, str(a.rule_results)[:200],
        )
        triggered_rules = []

    return AssessmentDetailResponse(
        assessment_id=a.assessment_id,
        event_id=a.event_id,
        user_id=a.user_id,
        event_type=ev.event_type if ev else "未知",
        event_source_id=ev.event_source_id if ev else "",
        final_score=a.final_score,
        risk_level=a.risk_level,
        decision=a.decision,
        rule_count=a.rule_count,
        triggered_rules=triggered_rules,
        ml_score=float(a.ml_score) if a.ml_score is not None else None,
        ml_decision=a.ml_decision,
        create_time=a.create_time,
        event_data=ev.event_data if ev else None,
    )


# ============================================================
# Demo: 案件状态机 + get_case_list (active_only) — 纯函数 + mock DB
# 跑法: python app/service/case.py
# ============================================================
if __name__ == "__main__":
    from types import SimpleNamespace

    print("=" * 60)
    print("Service Case — 状态机 + 列表 (P3-S9 active_only)")
    print("=" * 60)

    # 1. 状态机表
    print("\n[1] _ALLOWED_CASE_TRANSITIONS 状态机:")
    print(f"  {'当前状态':<8} → 可流转到")
    for cur, allowed in _ALLOWED_CASE_TRANSITIONS.items():
        arrow = " → ".join(sorted(allowed)) if allowed else "(终态, 不可再改)"
        print(f"  {cur:<8} → {arrow}")

    # 2. 合法 vs 非法流转
    print("\n[2] 状态流转合法性 (9 种):")
    test_cases = [
        ("待审核", "已通过",  True),
        ("待审核", "已拒绝",  True),
        ("待审核", "待审核",  False),
        ("待审核", "审核中",  True),
        ("审核中", "已通过",  True),
        ("审核中", "待审核",  False),
        ("已通过", "已拒绝",  False),
        ("已拒绝", "已通过",  False),
        ("已关闭", "审核中",  False),
    ]
    for src, dst, expected in test_cases:
        allowed = _ALLOWED_CASE_TRANSITIONS.get(src, set())
        got = dst in allowed
        mark = "OK" if got == expected else "FAIL"
        print(f"  [{mark}] {src} → {dst:<6} 期望={expected} 实际={got}")

    # 3. active_only=True 演示
    print("\n[3] get_case_list active_only=True (P3-S9):")

    class _FakeDB:
        def __init__(self):
            self.captured = []
            self.total = 0
        async def execute(self, stmt):
            from sqlalchemy.sql import Select as _Select
            where = str(stmt.whereclause) if isinstance(stmt, _Select) and stmt.whereclause is not None else "(no where)"
            self.captured.append(where)
            class _R:
                def __init__(self, n=0): self.n = n
                def scalar(self): return self.n
                def all(self): return []
            return _R(self.total)

    async def demo_active_only():
        db = _FakeDB()
        await get_case_list(db, active_only=True, page=1, page_size=20)
        db2 = _FakeDB()
        await get_case_list(db2, active_only=False, page=1, page_size=20)
        db3 = _FakeDB()
        await get_case_list(db3, status="已通过", page=1, page_size=20)
        for label, d in [("active_only=True ", db), ("active_only=False", db2), ("status=已通过  ", db3)]:
            where = d.captured[0] if d.captured else "(empty)"
            print(f"  {label}  WHERE: {where[:90]}...")

    asyncio.run(demo_active_only())

    # 4. get_case_statistics
    print("\n[4] get_case_statistics (5 状态 + N 分类):")

    class _StatDB:
        def __init__(self):
            self.call_count = 0
        async def execute(self, stmt):
            self.call_count += 1
            class _R:
                def __init__(self, data): self.data = data
                def scalar(self): return 25
                def all(self): return self.data
            if self.call_count == 1:
                return _R(25)
            elif self.call_count == 2:
                return _R([("待审核", 10), ("审核中", 5), ("已通过", 8), ("已拒绝", 1), ("已关闭", 1)])
            elif self.call_count == 3:
                return _R([("预订欺诈", 12), ("支付风险", 8), ("账户风险", 5)])
            else:
                return _R([])

    async def demo_stats():
        stats = await get_case_statistics(_StatDB())
        print(f"  total       = {stats.total}")
        print(f"  pending     = {stats.pending}  ({'待审核'})")
        print(f"  reviewing   = {stats.reviewing}  ({'审核中'})")
        print(f"  approved    = {stats.approved}  ({'已通过'})")
        print(f"  rejected    = {stats.rejected}  ({'已拒绝'})")
        print(f"  closed      = {stats.closed}  ({'已关闭'})")
        print(f"  by_category = {stats.by_category}")

    asyncio.run(demo_stats())

    print("\n" + "=" * 60)
    print("总结: 状态机 5 状态 + 合法流转 9 种; active_only 让案件工作台只看待办")


# ============================================================
# 【P4-L3 2026-08-08】案件超时自动关闭 — 配合 scheduler 定时调用
# ============================================================
async def auto_close_timeout_cases(db: AsyncSession, hours: int | None = None) -> int:
    """把超过 N 小时的"待审核"案件自动改为"已关闭", 写 audit.

    场景: 案件一直没人审会积压, 自动关案避免越积越多.
    由 app/scheduler.py 每小时调一次, 也可手动 await.

    Args:
        hours: 超时阈值 (小时), None=用 settings.CASE_TIMEOUT_HOURS (默认 24)
               设 0 关闭此功能 (脚本直接返回 0).

    Returns:
        关闭的案件数.

    Note:
        - 状态机已允许"待审核 → 已关闭", 状态机校验不破
        - 用 record_action 记 AUTO_CLOSE_CASE 审计 (operator="system")
        - 关闭后 7 步决策里的"建案"逻辑不会再次建同 source_id 的 case (因 P1-S6 查重)
    """
    from app.config import settings as _settings
    if hours is None:
        hours = _settings.CASE_TIMEOUT_HOURS
    if hours <= 0:
        return 0

    threshold = datetime.now() - timedelta(hours=hours)
    stmt = select(RiskCase).where(
        RiskCase.case_status == "待审核",
        RiskCase.create_time < threshold,
    )
    cases = (await db.execute(stmt)).scalars().all()

    for c in cases:
        c.case_status = "已关闭"
        c.reviewer = "system"
        c.review_time = datetime.now()
        c.review_comment = f"系统自动关闭: 待审核超过 {hours} 小时未处理"
        await record_action(
            db, operator="system", action_type="AUTO_CLOSE_CASE",
            target_type="case", target_id=c.case_id,
            before_value={"case_status": "待审核"},
            after_value={"case_status": "已关闭",
                         "review_comment": c.review_comment,
                         "auto_close_hours": hours},
            remark=f"超时自动关闭, create_time={c.create_time.isoformat()}",
        )

    if cases:
        await db.commit()
        logger.info("auto_close_timeout_cases: 关闭 %d 个超时案件 (阈值 %dh)", len(cases), hours)
    return len(cases)
