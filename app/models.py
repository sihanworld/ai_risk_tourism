"""
旅游风控系统 - ORM 模型总入口 (re-export hub)
包含 17 张业务表 + 7 张风控表的 SQLAlchemy 2.x 映射


"""

# 业务表 (17 个)
from app.models_business import (
    Logistics,
    LogisticsCompany,
    LogisticsComplaint,
    LogisticsComplaintsRecord,
    OrderDetail,
    OrderInfo,
    OrderLogistics,
    OrderStatus,
    Postsale,
    PostsaleLogistics,
    PostsaleReason,
    PostsaleStatus,
    ProductCategory,
    ReceiveInfo,
    Region,
    SkuInfo,
    UserInfo,
)

# 风控表 (7 个)
from app.models_risk import (
    RiskActionLog,
    RiskAlert,
    RiskAssessment,
    RiskBlacklist,
    RiskCase,
    RiskEvent,
    RiskFeature,
    RiskRule,
    RiskUserProfile,
)


__all__ = [
    # 业务表 (17)
    "UserInfo", "Region", "ProductCategory", "SkuInfo",
    "OrderStatus", "OrderInfo", "OrderDetail",
    "Logistics", "OrderLogistics", "LogisticsCompany",
    "LogisticsComplaint", "LogisticsComplaintsRecord",
    "PostsaleStatus", "PostsaleReason", "Postsale", "PostsaleLogistics",
    "ReceiveInfo",
    # 风控表 (9 = 7 业务 + 2 系统管理, P4 新增)
    "RiskRule", "RiskEvent", "RiskFeature", "RiskAssessment",
    "RiskCase", "RiskBlacklist", "RiskUserProfile",
    "RiskActionLog", "RiskAlert",
]


# ============================================================
# Demo: 列出 26 张表的所有 ORM 类 + 字段 — 无需连 DB (纯反射)
# 跑法: python app/models.py
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("ORM 模型总览 — 26 张表 (17 业务 + 9 风控)")
    print("=" * 60)

    business_models = [
        "UserInfo", "Region", "ProductCategory", "OrderStatus",
        "LogisticsCompany", "PostsaleStatus", "PostsaleReason",
        "ReceiveInfo", "SkuInfo", "OrderInfo", "OrderDetail",
        "Logistics", "OrderLogistics", "LogisticsComplaint",
        "LogisticsComplaintsRecord", "Postsale", "PostsaleLogistics",
    ]
    risk_models = [
        "RiskRule", "RiskEvent", "RiskFeature", "RiskAssessment",
        "RiskCase", "RiskBlacklist", "RiskUserProfile",
        "RiskActionLog", "RiskAlert",   # P4-L1/L2 系统管理表
    ]
    print(f"\n[1] 业务表 ({len(business_models)} 张):")
    for i, name in enumerate(business_models, 1):
        cls = globals().get(name)
        if cls is None:
            print(f"  {i:>2}. {name:<30} [NOT FOUND]")
            continue
        cols = list(cls.__table__.columns)
        print(f"  {i:>2}. {name:<30} {len(cols)} 字段  PK={cls.__table__.primary_key.columns.keys()}")

    print(f"\n[2] 风控表 ({len(risk_models)} 张):")
    for i, name in enumerate(risk_models, 1):
        cls = globals().get(name)
        if cls is None:
            print(f"  {i:>2}. {name:<30} [NOT FOUND]")
            continue
        cols = list(cls.__table__.columns)
        print(f"  {i:>2}. {name:<30} {len(cols)} 字段  PK={cls.__table__.primary_key.columns.keys()}")

    # Base.metadata 验证
    from app.database import Base
    total_tables = len(Base.metadata.tables)
    print(f"\n[3] Base.metadata 已注册表数: {total_tables} 张")
    print(f"     (Base.metadata 是 SQLAlchemy 自动建表的源, init_db.py 用它 DDL)")

    print("\n" + "=" * 60)
    print("结论: 26 张表 1 个导入点 (app.models), service/router 只 from app.models import X")
