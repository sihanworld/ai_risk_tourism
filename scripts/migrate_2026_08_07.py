"""
一键给老数据库补 2026-08-07 的 6 个字段 (含 risk_case.source_id/event_type).
不重置数据, 只 ALTER, 幂等 (重复跑无副作用).
"""
import asyncio
import os
import sys
from pathlib import Path

import aiomysql

sys.path.insert(0, Path(__file__).resolve().parent.parent)
from app.config import settings


# 6 个 ALTER 任务: (库, 表, 字段, 类型/默认值/位置/注释)
# 跟 migration_add_2026_08_07_fields.sql 保持一致
ALTERS = [
    ("risk_rule", "deleted_at",
     "DATETIME DEFAULT NULL COMMENT '软删除时间(NULL=未删, P3-M9)' AFTER update_time"),
    ("risk_assessment", "ml_score",
     "DECIMAL(5,4) DEFAULT NULL COMMENT 'XGBoost 拒绝概率 [0,1] (V2)' AFTER decision"),
    ("risk_assessment", "ml_decision",
     "VARCHAR(10) DEFAULT NULL COMMENT 'ML 维度决策 (V2)' AFTER ml_score"),
    ("risk_blacklist", "deleted_at",
     "DATETIME DEFAULT NULL COMMENT '软删除时间(NULL=未删, P3-M9)' AFTER create_time"),
    ("risk_case", "source_id",
     "VARCHAR(50) DEFAULT NULL COMMENT '原始业务ID(订单/退改签/投诉ID), 重做检查时用' AFTER risk_detail"),
    ("risk_case", "event_type",
     "ENUM('预订', '支付', '退改签', '行程开始') DEFAULT NULL COMMENT '触发案件的事件类型' AFTER source_id"),
]

INDEX_ALTERS = [
    ("risk_case", "idx_risk_case_source_id", "(source_id)"),
]

# 【P4-L3 2026-08-08 修生产 bug】risk_action_log.action_type ENUM 加 2 个值
# ALTER TYPE 改 ENUM 不会丢数据 (旧值都在新 ENUM 里)
ENUM_ALTERS = [
    ("risk_action_log", "action_type",
     "ENUM('CREATE_RULE','UPDATE_RULE','TOGGLE_RULE','DELETE_RULE','REVIEW_CASE','AUTO_REJECT_CASE','AUTO_CLOSE_CASE','ADD_BLACKLIST','REMOVE_BLACKLIST') NOT NULL COMMENT '操作类型'"),
]


async def column_exists(cur, db, table, col):
    await cur.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (db, table, col),
    )
    return (await cur.fetchone())[0] > 0


async def index_exists(cur, db, table, idx):
    await cur.execute(
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s",
        (db, table, idx),
    )
    return (await cur.fetchone())[0] > 0


async def enum_has_value(cur, db, table, col, value):
    """检查 ENUM 列是否含指定值 (用 COLUMN_TYPE 字符串匹配, 简单可靠)"""
    await cur.execute(
        "SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (db, table, col),
    )
    row = await cur.fetchone()
    if not row:
        return False
    return value in row[0]


async def main():
    cfg = settings
    print("=" * 60)
    print(f"连接 {cfg.DB_USER}@{cfg.DB_HOST}:{cfg.DB_PORT}/{cfg.DB_NAME}")
    print("补 6 个字段 + 1 个索引 + 1 个 ENUM 扩展 (幂等, 重复跑无副作用)")
    print("=" * 60)

    conn = await aiomysql.connect(
        host=cfg.DB_HOST, port=cfg.DB_PORT,
        user=cfg.DB_USER, password=cfg.DB_PASSWORD,
        db=cfg.DB_NAME, charset="utf8mb4", autocommit=True,
    )
    try:
        added = 0
        skipped = 0
        async with conn.cursor() as cur:
            for tbl, col, col_def in ALTERS:
                if await column_exists(cur, cfg.DB_NAME, tbl, col):
                    print(f"  [SKIP] {tbl}.{col} 已存在")
                    skipped += 1
                else:
                    sql = f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}"
                    print(f"  [ADD]  {tbl}.{col}")
                    await cur.execute(sql)
                    added += 1

            for tbl, idx, cols in INDEX_ALTERS:
                if await index_exists(cur, cfg.DB_NAME, tbl, idx):
                    print(f"  [SKIP] {tbl}.{idx} 已存在")
                    skipped += 1
                else:
                    sql = f"ALTER TABLE {tbl} ADD INDEX {idx} {cols}"
                    print(f"  [ADD]  {tbl}.{idx}")
                    await cur.execute(sql)
                    added += 1

            # 【P4-L3】ENUM 扩展 (改 COLUMN_TYPE, 不会丢旧数据)
            for tbl, col, col_def in ENUM_ALTERS:
                # 检查新值是否已在 ENUM 中
                # ENUM_ALTERS 每一项加新值, 只要检查最后那个值即可
                new_value = "AUTO_CLOSE_CASE"   # 当前只加这一个
                if await enum_has_value(cur, cfg.DB_NAME, tbl, col, new_value):
                    print(f"  [SKIP] {tbl}.{col} 已含 {new_value}")
                    skipped += 1
                else:
                    sql = f"ALTER TABLE {tbl} MODIFY COLUMN {col} {col_def}"
                    print(f"  [MODIFY] {tbl}.{col} (加 AUTO_REJECT_CASE + AUTO_CLOSE_CASE)")
                    await cur.execute(sql)
                    added += 1

        print("\n" + "=" * 60)
        print(f"完成! 新增 {added} 项, 跳过 {skipped} 项")
        if added > 0:
            print("现在可以重跑 gen_risk_data_with_dates.py 验证")
        print("=" * 60)
    finally:
        await conn.ensure_closed()


if __name__ == "__main__":
    asyncio.run(main())
