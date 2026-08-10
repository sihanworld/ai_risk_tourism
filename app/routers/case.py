"""案件管理 API"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_async
from app.schemas import CaseDetailResponse, CaseListResponse, CaseReviewRequest, CaseStatistics
from app.service.case import get_case_detail, get_case_list, get_case_statistics, review_case


case_router = APIRouter(prefix="/api/cases", tags=["案件管理"])


# 注意路由顺序: "/statistics" 必须在 "/{case_id}" 之前注册,
# 否则 FastAPI 会把 "statistics" 误当成 case_id
@case_router.get("", response_model=CaseListResponse)
async def api_list_cases(
    status: str = Query(None, description="精确状态, 跟 active_only 互斥 (同传时 active_only 失效)"),
    category: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(False, description="只看未结案 (待审核+审核中), 案件工作台默认"),
    db: AsyncSession = Depends(get_db_async),
):
    return await get_case_list(
        db, status=status, category=category, page=page, page_size=page_size, active_only=active_only,
    )


@case_router.get("/statistics", response_model=CaseStatistics)
async def api_case_statistics(db: AsyncSession = Depends(get_db_async)):
    return await get_case_statistics(db)


@case_router.get("/{case_id}", response_model=CaseDetailResponse)
async def api_get_case(case_id: str, db: AsyncSession = Depends(get_db_async)):
    detail = await get_case_detail(db, case_id)
    if not detail:
        raise HTTPException(status_code=404, detail="案件不存在")
    return detail


@case_router.post("/{case_id}/review", response_model=CaseDetailResponse)
async def api_review_case(
    case_id: str,
    data: CaseReviewRequest,
    db: AsyncSession = Depends(get_db_async),
):
    result = await review_case(db, case_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="案件不存在")
    return result


# ============================================================
# Demo: 列出 case router 4 个端点 + P3-S9 active_only 参数演示
# 跑法: python app/routers/case.py
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Router Case — 4 个端点 (P3-S9 active_only)")
    print("=" * 60)

    # 列出所有端点
    print("\n[1] 注册的 4 个端点:")
    for route in case_router.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods = "|".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
            print(f"  {methods:<10} {route.path}")

    # 显示 P3-S9 active_only 参数
    print("\n[2] GET /api/cases 查询参数:")
    sig = api_list_cases.__annotations__
    for k, v in sig.items():
        if k != "return" and k != "db":
            print(f"  {k:<20}: {str(v).replace('typing.', '')}")

    print("\n[3] 真实调用示例 (curl / httpx):")
    print("  # 默认只看'待办' (P3-S9 active_only=True)")
    print('  curl "http://localhost:8000/api/cases?page=1&page_size=20"')
    print()
    print("  # 看全部 (active_only=False)")
    print('  curl "http://localhost:8000/api/cases?active_only=false"')
    print()
    print("  # 按状态精确筛选")
    print('  curl "http://localhost:8000/api/cases?status=%E5%B7%B2%E9%80%9A%E8%BF%87"')
    print()
    print("  # 审核案件 (P1-S7 状态机校验)")
    print('  curl -X POST "http://localhost:8000/api/cases/cas_xxx/review" \\')
    print('       -H "Content-Type: application/json" \\')
    print('       -d \'{"decision": "已通过", "reviewer": "admin"}\'')

    print("\n" + "=" * 60)
    print("总结: 4 端点 = 列表 + 统计 + 详情 + 审核, active_only 让工作台默认只看待办")
