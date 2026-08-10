"""
app.routers - API 路由子包
拆分 30 个路由到 10 个 router 文件, 按业务域分组:
  - pages.py        页面路由 (Jinja2 模板, 7 个, 含 P3-S9 评估历史)
  - risk.py         风控检查 (1 个)
  - rule.py         规则管理 (6 个)
  - case.py         案件管理 (4 个)
  - blacklist.py    黑名单管理 (3 个)
  - profile.py      用户画像 (1 个)
  - dashboard.py    仪表盘 (1 个)
  - agent.py        AI Agent 对话 (2 个)
  - alert.py        告警 (3 个, P4-L2 2026-08-07)
  - assessment.py   评估历史 (2 个, P3-S9 2026-08-08)

外部代码继续用 from app.api import xxx_router (见 app/api.py 的 re-export)
"""
