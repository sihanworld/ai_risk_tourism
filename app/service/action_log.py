"""
操作审计日志 (P4-L1).
任何规则/案件/黑名单的变更都调 record_action() 写一行.
教学价值: 学员能讲"我设计的系统有完整审计日志" (合规 + 银保监要求).

注意: 函数不 commit, 跟调用方合并成 1 个事务 (跟 add_blacklist 一样的设计).
"""
import asyncio
import json
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RiskActionLog

logger = logging.getLogger(__name__)


async def record_action(
    db: AsyncSession,
    operator: str,
    action_type: str,
    target_type: str,
    target_id: str,
    *,
    before_value: Optional[dict] = None,
    after_value: Optional[dict] = None,
    ip: Optional[str] = None,
    remark: Optional[str] = None,
) -> None:
    """写 1 行操作审计日志 (不 commit, 由调用方 commit).

    action_type: CREATE_RULE / UPDATE_RULE / TOGGLE_RULE / DELETE_RULE /
                 REVIEW_CASE / AUTO_REJECT_CASE / ADD_BLACKLIST / REMOVE_BLACKLIST
    target_type: rule / case / blacklist
    """
    log = RiskActionLog(
        operator=operator,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        # JSON 字符串存库, ensure_ascii=False 保留中文
        before_value=json.dumps(before_value, ensure_ascii=False) if before_value else None,
        after_value=json.dumps(after_value, ensure_ascii=False) if after_value else None,
        ip=ip,
        remark=remark,
    )
    db.add(log)
    logger.info(
        "action_log: %s by %s on %s(%s)",
        action_type, operator, target_type, target_id,
    )


def orm_to_dict(obj: Any, fields: list[str]) -> dict:
    """ORM 对象 → dict (只取 fields 指定字段).

    比 obj.__dict__ 安全: 不会暴露 SQLAlchemy 内部状态 (_sa_instance_state 等).
    """
    return {f: getattr(obj, f, None) for f in fields}


# ============================================================
# Demo: 演练 record_action 写审计 + orm_to_dict 安全取字段 — 用 mock DB
# 跑法: python app/service/action_log.py
# ============================================================
if __name__ == "__main__":
    from types import SimpleNamespace
    import json as _json

    print("=" * 60)
    print("Service ActionLog — 2 个核心子函数 (P4-L1 审计)")
    print("=" * 60)

    # 1. orm_to_dict 子函数演示 — 跟 obj.__dict__ 对比
    print("\n[1] orm_to_dict(obj, fields) — 安全取字段:")

    class _FakeRule:
        """模拟 SQLAlchemy ORM 对象, 含 _sa_instance_state 内部状态"""
        def __init__(self):
            self.rule_id = "R001"
            self.rule_name = "单笔极端高额订单"
            self.risk_score = 95
            self._sa_instance_state = "<SQLAlchemy 内部状态, 不应暴露>"

    rule = _FakeRule()

    # 安全方式 (用 orm_to_dict)
    safe = orm_to_dict(rule, ["rule_id", "rule_name", "risk_score"])
    print(f"  orm_to_dict 4 字段: {safe}")

    # 不安全方式 (直接 __dict__) — 会暴露 SQLAlchemy 内部状态
    unsafe = dict(rule.__dict__)
    print(f"  __dict__ 全字段:   {sorted(unsafe.keys())}  ({len(unsafe)} 字段, 含 SQLAlchemy 内部)")
    print(f"  → orm_to_dict 避免序列化 _sa_instance_state 等无关字段")

    # 字段不存在时, getattr 兜底 None
    miss = orm_to_dict(rule, ["rule_id", "not_exists"])
    print(f"  不存在的字段:       {miss}  (getattr 兜底 None)")

    # 2. record_action 演示 — 模拟 3 种典型操作
    print("\n[2] record_action(db, ...) 写 3 条审计 (mock DB):")

    class _FakeDB:
        """Mock DB: 捕获 db.add() 调用的对象"""
        def __init__(self):
            self.added = []
        def add(self, obj):
            self.added.append(obj)

    async def demo_record_action():
        db = _FakeDB()
        # 3 个典型操作: 创建规则 / 审核案件 / 自动拒绝
        await record_action(
            db, operator="admin", action_type="CREATE_RULE",
            target_type="rule", target_id="R025",
            before_value=None,
            after_value={"rule_name": "极小金额订单", "risk_score": 50},
            remark="新增 R025",
        )
        await record_action(
            db, operator="auditor1", action_type="REVIEW_CASE",
            target_type="case", target_id="cas_xxx",
            before_value={"case_status": "待审核"},
            after_value={"case_status": "已通过", "review_comment": "客户已提供发票"},
            remark="审核通过 + 备注",
        )
        await record_action(
            db, operator="system", action_type="AUTO_REJECT_CASE",
            target_type="case", target_id="cas_yyy",
            before_value=None,
            after_value={"case_status": "已拒绝", "final_score": 95},
            remark="系统自动拒绝, source_id=ORD001",
        )
        for log in db.added:
            print(f"  [{log.action_type}] {log.operator} → {log.target_type}({log.target_id})")
            print(f"    before = {log.before_value}")
            print(f"    after  = {log.after_value}")
            print(f"    remark = {log.remark}")
            print()

    asyncio.run(demo_record_action())

    # 3. action_type 文档说明
    print("[3] action_type 完整列表 (P4-L1 文档化):")
    valid_types = [
        "CREATE_RULE", "UPDATE_RULE", "TOGGLE_RULE", "DELETE_RULE",
        "REVIEW_CASE", "AUTO_REJECT_CASE",
        "ADD_BLACKLIST", "REMOVE_BLACKLIST",
    ]
    for t in valid_types:
        print(f"  - {t}")

    print("\n" + "=" * 60)
    print("总结: P4-L1 审计层 100% 覆盖 8 种 admin 操作, 任何变更可追溯 (合规 + 风控要求)")
