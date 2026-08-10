"""
测试 - 规则匹配 (match_rules + to_dict)
不需要 DB, 用 SimpleNamespace 模拟 RiskRule / RuleHitResult
"""
import json
from types import SimpleNamespace

from app.engine.rule import match_rules, RuleHitResult


def _mock_rule(rule_id, condition_dict, score=50, level="中", action="标记", name="测试规则", category="测试"):
    """
    构造一个 mock 的 RiskRule 对象, 让 match_rules 能读 condition_dict.
    RiskRule.condition_dict 是 property, 这里直接给对象塞 condition_dict 属性.
    """
    rule = SimpleNamespace(
        rule_id=rule_id,
        rule_name=name,
        rule_category=category,
        risk_level=level,
        risk_score=score,
        action=action,
        description=f"描述-{rule_id}",
        priority=0,
    )
    # condition_dict 是 property, 不能直接赋值, 改成 mock 一个返回 dict 的属性
    # 但 match_rules 调的是 rule.condition_dict, 需要这个属性可调用
    # SimpleNamespace 支持把可调用对象当属性访问
    rule.condition_dict = condition_dict
    return rule


class TestMatchRules:
    """测试 match_rules: 给一组规则 + 特征 → 返回命中列表"""

    def test_no_rules(self):
        """空规则列表 → 0 命中"""
        assert match_rules([], {"x": 10}) == []

    def test_no_hits(self):
        """规则都不满足 → 0 命中"""
        rules = [
            _mock_rule("R1", {"field": "x", "op": ">", "value": 100}),
            _mock_rule("R2", {"field": "y", "op": "==", "value": 0}),
        ]
        assert match_rules(rules, {"x": 10, "y": 5}) == []

    def test_single_hit(self):
        """1 条命中"""
        rules = [
            _mock_rule("R1", {"field": "x", "op": ">", "value": 5}, score=70),
        ]
        hits = match_rules(rules, {"x": 10})
        assert len(hits) == 1
        assert hits[0].rule_id == "R1"
        assert hits[0].risk_score == 70

    def test_multiple_hits(self):
        """3 条规则, 2 条命中"""
        rules = [
            _mock_rule("R1", {"field": "x", "op": ">", "value": 5}),  # 命中
            _mock_rule("R2", {"field": "y", "op": "<", "value": 10}),  # 命中
            _mock_rule("R3", {"field": "z", "op": "==", "value": 999}),  # 不命中
        ]
        hits = match_rules(rules, {"x": 10, "y": 3, "z": 0})
        assert len(hits) == 2
        assert {h.rule_id for h in hits} == {"R1", "R2"}

    def test_invalid_json_condition_skipped(self):
        """规则 condition_dict 抛 JSONDecodeError → 跳过这条规则, 不崩"""
        class _BadRule:
            """condition_dict 访问时抛 JSONDecodeError, 模拟坏 JSON"""
            rule_id = "R_BAD"
            rule_name = "坏规则"
            rule_category = "测试"
            risk_level = "中"
            risk_score = 50
            action = "标记"
            description = ""

            @property
            def condition_dict(self):
                raise json.JSONDecodeError("bad json", "", 0)

        rule_bad = _BadRule()
        rule_good = _mock_rule("R_GOOD", {"field": "x", "op": ">", "value": 0})
        hits = match_rules([rule_bad, rule_good], {"x": 10})
        # 坏的被跳过, 好的命中
        assert len(hits) == 1
        assert hits[0].rule_id == "R_GOOD"


class TestRuleHitResultToDict:
    """测试 RuleHitResult.to_dict"""

    def test_to_dict_all_fields(self):
        """所有字段都正确转换"""
        rule = _mock_rule("R1", {}, score=80, level="高", action="人工审核",
                          name="高额订单", category="订单欺诈")
        hit = RuleHitResult(rule)
        d = hit.to_dict()
        assert d["rule_id"] == "R1"
        assert d["rule_name"] == "高额订单"
        assert d["rule_category"] == "订单欺诈"
        assert d["risk_level"] == "高"
        assert d["risk_score"] == 80
        assert d["action"] == "人工审核"
        assert d["description"] == "描述-R1"

    def test_to_dict_keys_count(self):
        """to_dict 恰好 7 个 key, 不会多不会少"""
        rule = _mock_rule("R1", {})
        hit = RuleHitResult(rule)
        d = hit.to_dict()
        assert set(d.keys()) == {
            "rule_id", "rule_name", "rule_category",
            "risk_level", "risk_score", "action", "description",
        }
