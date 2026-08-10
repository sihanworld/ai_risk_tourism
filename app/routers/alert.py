"""
风控告警 API (P4-L2)
3 个端点:
  POST /api/alerts/check        手动触发 3 个告警检查
  GET  /api/alerts              告警列表 (按状态过滤)
  POST /api/alerts/{id}/resolve 标记告警已处理

教学价值: 学员能讲"我设计过风控告警系统 (dashboard + 处理流程)"
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_async
from app.models import RiskAlert
from app.service.alert import run_all_alert_checks


alert_router = APIRouter(prefix="/api/alerts", tags=["告警"])


@alert_router.post("/check")
async def api_check_alerts(db: AsyncSession = Depends(get_db_async)):
    """手动触发 3 个告警检查 (待审核积压 / 命中率突降 / 拒绝率过高)"""
    new_alerts = await run_all_alert_checks(db)
    await db.commit()
    return {
        "checked_at": "now",
        "triggered_count": len(new_alerts),
        "alerts": [_alert_to_dict(a) for a in new_alerts],
    }


@alert_router.get("")
async def api_list_alerts(
    status: Optional[str] = Query(None, description="状态过滤: PENDING/HANDLING/RESOLVED/IGNORED"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_async),
):
    stmt = select(RiskAlert).order_by(RiskAlert.create_time.desc()).limit(limit)
    if status:
        stmt = stmt.where(RiskAlert.status == status)
    alerts = (await db.execute(stmt)).scalars().all()
    return [_alert_to_dict(a, with_handler=True) for a in alerts]


@alert_router.post("/{alert_id}/resolve")
async def api_resolve_alert(
    alert_id: int,
    handler: str = Query(..., description="处理人"),
    db: AsyncSession = Depends(get_db_async),
):
    alert = (await db.execute(
        select(RiskAlert).where(RiskAlert.alert_id == alert_id)
    )).scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "告警不存在")
    if alert.status == "RESOLVED":
        raise HTTPException(400, "告警已处理, 无需重复")
    alert.status = "RESOLVED"
    alert.handler = handler
    alert.resolve_time = datetime.now()
    await db.commit()
    return {"alert_id": alert_id, "status": "RESOLVED", "handler": handler}


def _alert_to_dict(a: RiskAlert, with_handler: bool = False) -> dict:
    base = {
        "alert_id": a.alert_id,
        "alert_type": a.alert_type,
        "alert_level": a.alert_level,
        "alert_title": a.alert_title,
        "alert_content": a.alert_content,
        "metric_name": a.metric_name,
        "metric_value": float(a.metric_value) if a.metric_value is not None else None,
        "threshold": float(a.threshold) if a.threshold is not None else None,
        "status": a.status,
    }
    if with_handler:
        base["handler"] = a.handler
        base["create_time"] = a.create_time
        base["resolve_time"] = a.resolve_time
    return base
