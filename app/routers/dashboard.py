"""仪表盘 API: 复用 agent/tools.py 的 query_dashboard_stats 拿数据"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools import query_dashboard_stats
from app.database import get_db_async


dashboard_router = APIRouter(prefix="/api/dashboard", tags=["仪表盘"])


@dashboard_router.get("/overview")
async def api_dashboard_overview(db: AsyncSession = Depends(get_db_async)):
    result = await query_dashboard_stats.ainvoke({})
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        # tool 内部异常: 把错误原文回传前端
        raise HTTPException(status_code=500, detail=result)
