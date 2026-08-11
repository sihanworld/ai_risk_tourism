"""
旅游风控系统 - FastAPI 路由总入口 (re-export hub)
30 个路由按业务域拆到 10 个 router 文件 (app/routers/):

  - page_router        7 个  页面 (Jinja2 模板, 含 P3-S9 评估历史)
  - risk_router        1 个  风控检查
  - rule_router        6 个  规则管理
  - case_router        4 个  案件管理
  - blacklist_router   3 个  黑名单
  - profile_router     1 个  用户画像
  - dashboard_router   1 个  仪表盘
  - agent_router       2 个  AI Agent
  - alert_router       3 个  告警 (P4-L2)
  - assessment_router  2 个  评估历史 (P3-S9 2026-08-08)
"""

# 10 个 router re-export
from app.routers.pages import page_router
from app.routers.risk import risk_router
from app.routers.rule import rule_router
from app.routers.case import case_router
from app.routers.blacklist import blacklist_router
from app.routers.profile import profile_router
from app.routers.dashboard import dashboard_router
from app.routers.agent import agent_router
from app.routers.alert import alert_router
# 【P3-S9 新增 2026-08-08】评估历史路由
from app.routers.assessment import assessment_router


__all__ = [
    "page_router",
    "risk_router",
    "rule_router",
    "case_router",
    "blacklist_router",
    "profile_router",
    "dashboard_router",
    "agent_router",
    "alert_router",
    "assessment_router",   # 【P3-S9】
]
