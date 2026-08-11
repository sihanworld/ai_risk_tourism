"""
评估历史 API (P3-S9 2026-08-08):
- 案件工作台只看待办, 全量评估历史走这个 API
- 列表 + 详情, 详情含命中规则 + ML 评分
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_async
from app.schemas import AssessmentDetailResponse, AssessmentListResponse
from app.service.case import get_assessment_detail, list_assessments


assessment_router = APIRouter(prefix="/api/assessments", tags=["评估历史"])


@assessment_router.get("", response_model=AssessmentListResponse)
async def api_list_assessments(
    decision: str = Query(None, description="决策: 通过/标记/人工审核/拒绝"),
    risk_level: str = Query(None, description="等级: 低/中/高/极高"),
    event_type: str = Query(None, description="事件: 预订/支付/退改签/行程开始"),
    user_id: str = Query(None, description="精确匹配用户ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
):
    """全量评估历史列表 (含已结案 + 通过/标记)."""
    return await list_assessments(
        db, decision=decision, risk_level=risk_level, event_type=event_type,
        user_id=user_id, page=page, page_size=page_size,
    )


@assessment_router.get("/{assessment_id}", response_model=AssessmentDetailResponse)
async def api_get_assessment(
    assessment_id: str, db: AsyncSession = Depends(get_db_async),
):
    """评估详情: 基础字段 + 命中规则 + ML 评分 + 事件快照."""
    return await get_assessment_detail(db, assessment_id)


# ============================================================
# Demo: 列出 assessment router 2 个端点 (P3-S9 评估历史)
# 跑法: python app/routers/assessment.py
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Router Assessment — 2 个端点 (P3-S9 评估历史)")
    print("=" * 60)

    # 1. 列出 2 端点
    print("\n[1] 注册的 2 个端点:")
    for route in assessment_router.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods = "|".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
            print(f"  {methods:<10} {route.path}")

    # 2. 4 维筛选说明
    print("\n[2] GET /api/assessments 4 维筛选:")
    sig = api_list_assessments.__annotations__
    for k, v in sig.items():
        if k != "return" and k != "db":
            print(f"  {k:<20}: {str(v).replace('typing.', '')}")

    # 3. 设计理念
    print("\n[3] 跟 /api/cases 的区别:")
    print("  /api/cases       : 案件工作台, 默认只看'待办' (P3-S9 active_only=True)")
    print("  /api/assessments : 评估历史, 全量 (含已结案 + 通过/标记) 4 维筛选")
    print("  设计: 决策结果不管 '拒绝' 还是 '通过' 都进 risk_assessment 表")
    print("        案件只在 decision='人工审核/拒绝' 时建 (P2-S8 auto-reject 改 case_status='已拒绝')")
    print("        评估历史 = 完整审计 + 回溯复盘, 案件 = 待办工作台")

    # 4. 真实调用示例
    print("\n[4] curl 调用示例:")
    print('  # 看所有拒绝的评估')
    print('  curl "http://localhost:8000/api/assessments?decision=%E6%8B%92%E7%BB%9D"')
    print()
    print('  # 看极高风险评估')
    print('  curl "http://localhost:8000/api/assessments?risk_level=%E6%9E%81%E9%AB%98"')
    print()
    print('  # 看某用户的全部评估')
    print('  curl "http://localhost:8000/api/assessments?user_id=U0001&page=1&page_size=20"')
    print()
    print('  # 评估详情 (含命中规则 + ML 评分)')
    print('  curl "http://localhost:8000/api/assessments/ast_01HXXXXXXXX"')

    print("\n" + "=" * 60)
    print("总结: 2 端点 (列表 + 详情), 4 维筛选让回溯复盘从'猜'变'查'")
