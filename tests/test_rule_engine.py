"""
测试 - 规则引擎 (rule_engine.py)
"""

from app.engine.rule import evaluate_condition


class TestEvaluateCondition:
    """测试条件求值器"""

    def test_gt(self):
        assert evaluate_condition({"field": "x", "op": ">", "value": 5}, {"x": 10})
        assert not evaluate_condition({"field": "x", "op": ">", "value": 5}, {"x": 3})

    def test_gte(self):
        assert evaluate_condition({"field": "x", "op": ">=", "value": 5}, {"x": 5})
        assert not evaluate_condition({"field": "x", "op": ">=", "value": 5}, {"x": 4})

    def test_lt(self):
        assert evaluate_condition({"field": "x", "op": "<", "value": 5}, {"x": 3})
        assert not evaluate_condition({"field": "x", "op": "<", "value": 5}, {"x": 5})

    def test_lte(self):
        assert evaluate_condition({"field": "x", "op": "<=", "value": 5}, {"x": 5})
        assert not evaluate_condition({"field": "x", "op": "<=", "value": 5}, {"x": 6})

    def test_eq(self):
        assert evaluate_condition({"field": "x", "op": "==", "value": 1}, {"x": 1.0})
        assert not evaluate_condition({"field": "x", "op": "==", "value": 1}, {"x": 2})

    def test_ne(self):
        assert evaluate_condition({"field": "x", "op": "!=", "value": 1}, {"x": 2})

    def test_between(self):
        assert evaluate_condition({"field": "x", "op": "between", "value": [0, 5]}, {"x": 3})
        assert evaluate_condition({"field": "x", "op": "between", "value": [0, 5]}, {"x": 0})
        assert not evaluate_condition({"field": "x", "op": "between", "value": [0, 5]}, {"x": 6})

    def test_in(self):
        assert evaluate_condition({"field": "x", "op": "in", "value": [1, 2, 3]}, {"x": 2})
        assert not evaluate_condition({"field": "x", "op": "in", "value": [1, 2, 3]}, {"x": 5})

    def test_not_in(self):
        assert evaluate_condition({"field": "x", "op": "not_in", "value": [1, 2]}, {"x": 5})

    def test_and(self):
        cond = {
            "and": [
                {"field": "x", "op": ">", "value": 5},
                {"field": "y", "op": "<", "value": 10},
            ]
        }
        assert evaluate_condition(cond, {"x": 8, "y": 3})
        assert not evaluate_condition(cond, {"x": 3, "y": 3})  # x 不满足
        assert not evaluate_condition(cond, {"x": 8, "y": 15})  # y 不满足

    def test_or(self):
        cond = {
            "or": [
                {"field": "x", "op": ">", "value": 100},
                {"field": "y", "op": "==", "value": 1},
            ]
        }
        assert evaluate_condition(cond, {"x": 200, "y": 0})  # x 满足
        assert evaluate_condition(cond, {"x": 50, "y": 1})   # y 满足
        assert not evaluate_condition(cond, {"x": 50, "y": 0})

    def test_missing_field(self):
        """缺失特征 → 条件不命中"""
        assert not evaluate_condition({"field": "missing", "op": ">", "value": 5}, {"x": 10})

    def test_nested_and_or(self):
        """嵌套的 and + or"""
        cond = {
            "and": [
                {"field": "a", "op": ">=", "value": 50},
                {"or": [
                    {"field": "b", "op": "==", "value": 1},
                    {"field": "c", "op": ">", "value": 100},
                ]}
            ]
        }
        assert evaluate_condition(cond, {"a": 60, "b": 1, "c": 0})
        assert evaluate_condition(cond, {"a": 60, "b": 0, "c": 200})
        assert not evaluate_condition(cond, {"a": 40, "b": 1, "c": 200})  # a 不满足

    def test_unsupported_op(self):
        """不支持的运算符返回 False"""
        assert not evaluate_condition({"field": "x", "op": "magic", "value": 1}, {"x": 1})
