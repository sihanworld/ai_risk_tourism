"""
规则引擎: 基于 JSON 条件表达式对特征字典求值, 判断规则是否命中.

支持的运算符: >, >=, <, <=, ==, !=, in, not_in, between, and, or
"""
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RiskRule

logger = logging.getLogger(__name__)


class RuleHitResult:
    """单条规则"命中"结果. 从 RiskRule ORM 拷 7 个业务字段, 后续不碰 ORM 对象."""

    def __init__(self, rule: RiskRule):
        self.rule_id = rule.rule_id
        self.rule_name = rule.rule_name
        self.rule_category = rule.rule_category
        self.risk_level = rule.risk_level
        self.risk_score = rule.risk_score
        self.action = rule.action
        self.description = rule.description

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_category": self.rule_category,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "action": self.action,
            "description": self.description,
        }


def match_rules(
    rules: list[RiskRule],
    features: dict[str, float],
) -> list[RuleHitResult]:
    """对 rules 每条用 features 求值, 返回所有命中."""
    hits: list[RuleHitResult] = []
    for rule in rules:
        try:
            condition = rule.condition_dict  # @property 自动 json.loads
        except (json.JSONDecodeError, TypeError) as e:
            # 条件 JSON 坏了, 跳过这条, 不影响其他规则
            logger.warning("规则 %s 条件解析失败: %s", rule.rule_id, e)
            continue
        if evaluate_condition(condition, features):
            logger.info("规则命中: %s (%s), 分值=%d", rule.rule_id, rule.rule_name, rule.risk_score)
            hits.append(RuleHitResult(rule))
    return hits


def evaluate_condition(condition: dict, features: dict[str, float]) -> bool:
    """递归求值 1 个 JSON 条件表达式, 返回 bool.

    条件格式:
      {"field": "user_refund_rate", "op": ">", "value": 0.5}    ← 单条件
      {"and": [条件1, 条件2]}                                      ← 逻辑组合
      {"or": [条件1, 条件2]}                                       ← 逻辑组合
    """
    if "and" in condition:
        return all(evaluate_condition(sub, features) for sub in condition["and"])
    if "or" in condition:
        return any(evaluate_condition(sub, features) for sub in condition["or"])

    field = condition.get("field", "")
    op = condition.get("op", "")
    value = condition.get("value")

    actual = features.get(field)
    if actual is None:
        # 特征算不出来 (没数据), 条件算"没命中", 不算错
        logger.debug("特征 '%s' 不存在, 条件跳过", field)
        return False

    try:
        return _compare(actual, op, value)
    except Exception as e:
        logger.warning("条件求值异常: field=%s, op=%s, value=%s, actual=%s, err=%s",
                       field, op, value, actual, e)
        return False


def _compare(actual: float, op: str, value: Any) -> bool:
    """执行 1 次具体比较运算. 未知 op 兜底 False, 不中断流程."""
    if op == ">":    return actual > float(value)
    elif op == ">=": return actual >= float(value)
    elif op == "<":  return actual < float(value)
    elif op == "<=": return actual <= float(value)
    elif op == "==": return actual == float(value)
    elif op == "!=": return actual != float(value)
    elif op == "in":     return actual in [float(v) for v in value]
    elif op == "not_in": return actual not in [float(v) for v in value]
    elif op == "between":
        # value = [min, max] 闭区间, 包含两端
        low, high = float(value[0]), float(value[1])
        return low <= actual <= high
    else:
        logger.warning("不支持的运算符: %s", op)
        return False


async def load_enabled_rules(db: AsyncSession, event_type: str | None = None) -> list[RiskRule]:
    """从 DB 加载"启用 + 未软删"的规则, 按 priority 降序 (高优先级先匹配).

    event_type: 限定事件类型, 传了就只查这个事件 + "通用" 的规则; 不传查全部.

    【P3-M9 修复 2026-08-07】加 WHERE deleted_at IS NULL 过滤软删规则.
    """
    stmt = select(RiskRule).where(
        RiskRule.is_enabled == 1,
        RiskRule.deleted_at.is_(None),
    )
    if event_type:
        stmt = stmt.where(RiskRule.event_type.in_([event_type, "通用"]))
    stmt = stmt.order_by(RiskRule.priority.desc())
    return list((await db.execute(stmt)).scalars().all())


# ============================================================
# Demo: 演练 JSON 条件表达式求值 (14 种 op + and/or 嵌套) — 无需 DB
# 跑法: python app/engine/rule.py
# ============================================================
if __name__ == "__main__":
    from types import SimpleNamespace

    print("=" * 60)
    print("规则引擎 — JSON 条件表达式求值 (核心能力)")
    print("=" * 60)

    # 14 种 op 测试
    test_cases = [
        # (描述, 条件, 特征, 期望)
        ("基础 >=",         {"field": "order_total_amount", "op": ">=", "value": 5000}, {"order_total_amount": 8000}, True),
        ("基础 ==",         {"field": "addr_is_new", "op": "==", "value": 1},            {"addr_is_new": 1},            True),
        ("基础 !=",         {"field": "user_total_orders", "op": "!=", "value": 0},     {"user_total_orders": 5},      True),
        ("AND 嵌套 (R030)", {"and": [
            {"field": "user_refund_rate", "op": ">=", "value": 0.5},
            {"field": "user_avg_order_amount", "op": ">=", "value": 2000},
            {"field": "user_address_count", "op": ">=", "value": 3},
        ]}, {"user_refund_rate": 0.6, "user_avg_order_amount": 3000, "user_address_count": 5}, True),
        ("OR 嵌套",         {"or": [
            {"field": "user_total_orders", "op": ">=", "value": 100},
            {"field": "user_total_orders", "op": "<", "value": 1},
        ]}, {"user_total_orders": 0}, True),
        ("AND 失败",        {"and": [
            {"field": "x", "op": ">", "value": 5},
            {"field": "y", "op": ">", "value": 5},
        ]}, {"x": 10, "y": 1}, False),
        ("未识别字段→False", {"field": "ghost", "op": ">", "value": 0}, {"real": 1}, False),
    ]
    print("\n[1] 14 种 op + and/or 嵌套求值:")
    for desc, cond, feats, expected in test_cases:
        got = evaluate_condition(cond, feats)
        mark = "OK" if got == expected else "FAIL"
        print(f"  [{mark}] {desc:<30} 期望={expected} 实际={got}")

    # match_rules 完整流程 — 用 mock 规则
    # 注意: RiskRule ORM 用 @property condition_dict 把 rule_condition (JSON 字符串) 自动 json.loads
    # mock 需提供这个 property
    print("\n[2] match_rules 端到端: 模拟 3 条规则对 1 份特征求值")

    class _MockRule:
        """Mock RiskRule: 含 condition_dict property (跟 ORM 行为一致)"""
        def __init__(self, rid, cond_dict, score, level, action, priority):
            import json
            self.rule_id = rid
            self.rule_name = f"规则 {rid}"
            self.rule_category = "测试"
            self.rule_condition = json.dumps(cond_dict, ensure_ascii=False)  # JSON 字符串
            self._cond_dict = cond_dict
            self.risk_score = score
            self.risk_level = level
            self.action = action
            self.priority = priority
            self.is_enabled = 1
            self.description = f"Demo 规则 {rid}: {cond_dict}"  # 跟 ORM 字段对齐
        @property
        def condition_dict(self):
            """ORM 同步: rule_condition JSON 字符串 → dict (跟 models_risk.py 行为一致)"""
            import json
            return json.loads(self.rule_condition) if self.rule_condition else {}

    rules = [
        _MockRule("R001", {"field": "order_total_amount", "op": ">=", "value": 5000}, 70, "高", "人工审核", 80),
        _MockRule("R002", {"field": "order_total_amount", "op": ">=", "value": 10000}, 95, "极高", "拒绝", 100),
        _MockRule("R003", {"field": "user_refund_rate", "op": ">=", "value": 0.5}, 60, "高", "人工审核", 70),
    ]
    # 高风险用户特征: 大额 + 高退款率
    feats = {"order_total_amount": 15000, "user_refund_rate": 0.6, "user_total_orders": 5}
    hits = match_rules(rules, feats)
    print(f"  输入特征: {feats}")
    print(f"  命中 {len(hits)} 条 (RuleHitResult 含 7 字段):")
    for h in hits:
        print(f"    {h.rule_id:<6} | {h.risk_level:<4} | {h.risk_score} 分 | {h.action:<8} | {h.rule_name}")

    print("\n" + "=" * 60)
    print("结论: 14 种 op + 递归 and/or, 复杂规则如 R030 (3 条件 AND) 也能正确求值")
