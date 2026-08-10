"""
端到端 DDL 同步检查:
- 用 SQLAlchemy 反射 (reflect) ecs 数据库的所有表
- 对比 models_risk.py 里定义的字段, 看是否跟 SQL 100% 对齐

需要在本地有可用的 ecs 数据库才能跑; 测试用 pytest.skip 自动跳过.
"""
import os
import pytest
from sqlalchemy import create_engine, inspect


@pytest.mark.skipif(
    not os.getenv("DDL_CHECK_ENABLED"),
    reason="DDL sync check 需要真实数据库; 默认跳过 (设 DDL_CHECK_ENABLED=1 启用)",
)
def test_risk_ddl_sync():
    from app.config import settings
    eng = create_engine(settings.get_database_url_async().replace("+aiomysql", ""))
    insp = inspect(eng)

    expected = {
        "risk_rule": {
            "rule_id", "rule_name", "rule_category", "event_type",
            "rule_condition", "risk_level", "risk_score", "action",
            "is_enabled", "priority", "description", "create_time",
            "update_time", "deleted_at",
        },
        "risk_assessment": {
            "assessment_id", "event_id", "user_id", "rule_results",
            "rule_count", "final_score", "risk_level", "decision",
            "ml_score", "ml_decision", "create_time",
        },
        "risk_blacklist": {
            "blacklist_id", "blacklist_type", "blacklist_value",
            "reason", "expire_time", "create_time", "deleted_at",
        },
        "risk_action_log": {
            "log_id", "operator", "action_type", "target_type",
            "target_id", "before_value", "after_value", "ip",
            "remark", "create_time",
        },
        "risk_alert": {
            "alert_id", "alert_type", "alert_level", "alert_title",
            "alert_content", "metric_name", "metric_value", "threshold",
            "status", "handler", "resolve_time", "create_time",
        },
    }

    for table, cols in expected.items():
        assert insp.has_table(table), f"表 {table} 在数据库里不存在"
        actual = {c["name"] for c in insp.get_columns(table)}
        missing = cols - actual
        extra = actual - cols
        assert not missing, f"{table} 缺字段: {missing}"
        assert not extra, f"{table} 多余字段: {extra}"
