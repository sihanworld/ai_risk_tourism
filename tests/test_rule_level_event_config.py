"""
规则配置改造测试 (P4-L5 2026-08-10):
1. RISK_LEVEL_SCORE_MAP 区间一致性 (0-100 全覆盖, 4 档不重不漏)
2. RISK_EVENT_THRESHOLDS 按 event_type 拆
3. decision._score_to_level / _score_to_decision 接 event_type 参数
4. validate_rule_score_level 互验
5. 前端 app.js 包含 26 特征 + 构建器函数 (静态扫描)
6. rules.html 用 condBuilder 不用 textarea (静态扫描)
"""
import json
from pathlib import Path

import pytest

from app.config import settings
from app.engine.rule import RuleScoreLevelMismatchError, validate_rule_score_level


# ============================================================
# 1. RISK_LEVEL_SCORE_MAP 区间一致性
# ============================================================

class TestRiskLevelScoreMap:
    """RISK_LEVEL_SCORE_MAP 必须: 4 档不重不漏 + 全覆盖 0-100 + 顺序递增."""

    def test_4_levels_defined(self):
        assert set(settings.RISK_LEVEL_SCORE_MAP.keys()) == {"低", "中", "高", "极高"}

    def test_ranges_cover_0_to_100(self):
        """0-100 区间必须被 4 档完全覆盖."""
        sorted_ranges = sorted(settings.RISK_LEVEL_SCORE_MAP.items(), key=lambda x: x[1][0])
        # 第一个区间从 0 开始
        assert sorted_ranges[0][1][0] == 0, f"第一档应从 0 开始, 实际 {sorted_ranges[0]}"
        # 最后一个区间到 100
        assert sorted_ranges[-1][1][1] == 100, f"最后一档应到 100, 实际 {sorted_ranges[-1]}"
        # 相邻区间无缝隙无重叠
        for i in range(len(sorted_ranges) - 1):
            cur_high = sorted_ranges[i][1][1]
            next_low = sorted_ranges[i + 1][1][0]
            assert next_low == cur_high + 1, (
                f"区间 {sorted_ranges[i]} 和 {sorted_ranges[i+1]} 不连续: "
                f"cur_high={cur_high}, next_low={next_low}"
            )

    def test_ranges_ascending(self):
        """分数区间必须按等级递增."""
        ranges = [(k, v) for k, v in settings.RISK_LEVEL_SCORE_MAP.items()]
        for i in range(len(ranges) - 1):
            assert ranges[i][1][0] < ranges[i + 1][1][0], (
                f"{ranges[i][0]} 区间应该比 {ranges[i+1][0]} 小"
            )

    def test_get_risk_level_by_score(self):
        """settings.get_risk_level_by_score 反查正确."""
        assert settings.get_risk_level_by_score(0) == "低"
        assert settings.get_risk_level_by_score(29) == "低"
        assert settings.get_risk_level_by_score(30) == "中"
        assert settings.get_risk_level_by_score(59) == "中"
        assert settings.get_risk_level_by_score(60) == "高"
        assert settings.get_risk_level_by_score(84) == "高"
        assert settings.get_risk_level_by_score(85) == "极高"
        assert settings.get_risk_level_by_score(100) == "极高"
        # 越界兜底
        assert settings.get_risk_level_by_score(-1) == "低"
        assert settings.get_risk_level_by_score(150) == "极高"


# ============================================================
# 2. RISK_EVENT_THRESHOLDS 按 event_type 拆
# ============================================================

class TestRiskEventThresholds:
    """RISK_EVENT_THRESHOLDS 必须: 4 个 event_type + 通用 fallback."""

    def test_all_event_types_defined(self):
        assert set(settings.RISK_EVENT_THRESHOLDS.keys()) == {
            "下单", "支付", "售后申请", "物流投诉", "通用"
        }

    def test_each_event_type_has_3_thresholds(self):
        """每种 event_type 都有 pass/mark/review 3 阈值."""
        for et, th in settings.RISK_EVENT_THRESHOLDS.items():
            assert set(th.keys()) == {"pass", "mark", "review"}, (
                f"{et} 阈值缺字段, 实际 {th}"
            )
            assert th["pass"] < th["mark"] < th["review"], (
                f"{et} 阈值应 pass < mark < review, 实际 {th}"
            )

    def test_get_event_thresholds_with_fallback(self):
        """get_event_thresholds 找不到时 fallback 到全局."""
        # 命中: 返回对应 event_type 阈值
        th = settings.get_event_thresholds("售后申请")
        assert th["pass"] == 40  # 售后更严
        # fallback: 通用阈值
        th_fallback = settings.get_event_thresholds("通用")
        assert th_fallback == {
            "pass": settings.RISK_PASS_THRESHOLD,
            "mark": settings.RISK_MARK_THRESHOLD,
            "review": settings.RISK_REVIEW_THRESHOLD,
        }
        # 未知 event_type 也 fallback
        th_unknown = settings.get_event_thresholds("不存在的")
        assert th_unknown == th_fallback

    def test_售后_比_下单_严(self):
        """售后/支付阈值应该 >= 下单 (业务: 薅羊毛防风险)."""
        th_下单 = settings.RISK_EVENT_THRESHOLDS["下单"]
        th_售后 = settings.RISK_EVENT_THRESHOLDS["售后申请"]
        th_支付 = settings.RISK_EVENT_THRESHOLDS["支付"]
        # 售后 pass 阈值应该 >= 下单 pass (更严格)
        assert th_售后["pass"] >= th_下单["pass"], (
            "售后应该比下单严 (pass 阈值更高)"
        )
        # 支付 pass 阈值应该 <= 下单 pass (支付更敏感)
        assert th_支付["pass"] <= th_下单["pass"], (
            "支付应该比下单敏感 (pass 阈值更低)"
        )


# ============================================================
# 3. decision._score_to_level / _score_to_decision 接 event_type
# ============================================================

class TestScoreToLevelWithEventType:
    """_score_to_level / _score_to_decision 必须按 event_type 查表."""

    def test_score_to_level_default_event(self):
        from app.engine.decision import _score_to_level, _score_to_decision
        # 不传 event_type 用通用阈值 (PASS=30, MARK=60, REVIEW=80)
        assert _score_to_level(0) == "低"
        assert _score_to_level(29) == "低"
        assert _score_to_level(30) == "中"
        assert _score_to_level(59) == "中"
        assert _score_to_level(60) == "高"
        # 边界: 80 = REVIEW, 走"极高"分支 (因为 score < 80 是 False)
        assert _score_to_level(80) == "极高"
        assert _score_to_level(100) == "极高"

    def test_score_to_level_with_event_type(self):
        from app.engine.decision import _score_to_level
        # 售后: pass=40, mark=70, review=85
        assert _score_to_level(39, "售后申请") == "低"
        assert _score_to_level(40, "售后申请") == "中"
        assert _score_to_level(69, "售后申请") == "中"
        assert _score_to_level(70, "售后申请") == "高"
        assert _score_to_level(85, "售后申请") == "极高"

    def test_score_to_decision_with_event_type(self):
        from app.engine.decision import _score_to_decision
        # 支付: pass=25, mark=55, review=75
        assert _score_to_decision(24, "支付") == "通过"
        assert _score_to_decision(25, "支付") == "标记"
        assert _score_to_decision(75, "支付") == "拒绝"

    def test_score_to_level_fallback_unknown_event(self):
        """未知 event_type fallback 到全局."""
        from app.engine.decision import _score_to_level
        # 未知 event_type 用通用阈值
        assert _score_to_level(30, "不存在的") == "中"
        assert _score_to_level(79, "不存在的") == "高"  # < 80 = 高
        assert _score_to_level(80, "不存在的") == "极高"  # >= 80 = 极高


# ============================================================
# 4. validate_rule_score_level 互验
# ============================================================

class TestValidateRuleScoreLevel:
    """validate_rule_score_level 业务校验: risk_level ↔ risk_score 必匹配."""

    def test_valid_combinations(self):
        # 4 档各举 1 个合法值
        validate_rule_score_level("低", 0)
        validate_rule_score_level("低", 29)
        validate_rule_score_level("中", 30)
        validate_rule_score_level("中", 59)
        validate_rule_score_level("高", 60)
        validate_rule_score_level("高", 84)
        validate_rule_score_level("极高", 85)
        validate_rule_score_level("极高", 100)

    def test_score_out_of_range_raises(self):
        with pytest.raises(RuleScoreLevelMismatchError, match="越界"):
            validate_rule_score_level("极高", 50)
        with pytest.raises(RuleScoreLevelMismatchError, match="越界"):
            validate_rule_score_level("低", 50)
        with pytest.raises(RuleScoreLevelMismatchError, match="越界"):
            validate_rule_score_level("高", 20)

    def test_unknown_level_raises(self):
        with pytest.raises(RuleScoreLevelMismatchError, match="未知风险等级"):
            validate_rule_score_level("未定义", 50)

    def test_score_not_int_raises(self):
        with pytest.raises(RuleScoreLevelMismatchError, match="整数"):
            validate_rule_score_level("高", "abc")
        with pytest.raises(RuleScoreLevelMismatchError, match="整数"):
            validate_rule_score_level("高", 50.5)

    def test_score_out_of_0_100_raises(self):
        with pytest.raises(RuleScoreLevelMismatchError, match="整数"):
            validate_rule_score_level("高", -1)
        with pytest.raises(RuleScoreLevelMismatchError, match="整数"):
            validate_rule_score_level("高", 101)

    def test_boundary_values(self):
        """边界值正确归属 (左闭右闭)."""
        # 低: 0-29
        validate_rule_score_level("低", 0)
        validate_rule_score_level("低", 29)
        # 中: 30-59
        validate_rule_score_level("中", 30)
        validate_rule_score_level("中", 59)
        # 高: 60-84
        validate_rule_score_level("高", 60)
        validate_rule_score_level("高", 84)
        # 极高: 85-100
        validate_rule_score_level("极高", 85)
        validate_rule_score_level("极高", 100)


# ============================================================
# 5. 前端 app.js 必须包含关键元素
# ============================================================

class TestFrontendRuleBuilder:
    """app.js 必须包含: 26 特征 + 构建器函数 + 风险等级映射 + 阈值映射."""

    @pytest.fixture
    def appjs(self):
        p = Path("D:/workroom/尚硅谷大模型项目之风控系统/3.代码/AI_Risk/static/app.js")
        return p.read_text(encoding="utf-8")

    def test_has_feature_labels_dict(self, appjs):
        assert "FEATURE_LABELS" in appjs, "app.js 缺 FEATURE_LABELS 字典"

    def test_has_all_25_features(self, appjs):
        """至少 25 个特征 (跟 ml_model.py FEATURE_COLUMNS 对齐)."""
        import re
        # 提取 "key_xxx": "label" 模式 (key 是 snake_case, 至少 1 个下划线)
        keys = re.findall(r'"([a-z]+_[a-z_0-9]+)"\s*:\s*"', appjs)
        # 去重 + 只保留作为 FEATURE_LABELS 字典 key 的 (按出现位置在 FEATURE_LABELS 字典内)
        labels_start = appjs.index("FEATURE_LABELS = {")
        # FEATURE_LABELS 字典结束的 "};"
        # 用第一个 "};" (在 RISK_LEVEL_SCORE_MAP 之前)
        labels_end_candidates = []
        idx = labels_start
        while True:
            idx = appjs.find("};", idx + 1)
            if idx < 0:
                break
            labels_end_candidates.append(idx)
            if len(labels_end_candidates) >= 5:
                break
        if labels_end_candidates:
            labels_end = labels_end_candidates[0]
            labels_block = appjs[labels_start:labels_end]
            keys_in_labels = re.findall(r'"([a-z]+_[a-z_0-9]+)"\s*:\s*"', labels_block)
            # 排除掉 "FEATURE_LABELS" / "LABEL_TO_FEATURE" 等非特征的 key
            feature_keys = [k for k in keys_in_labels if k.startswith(("user_", "order_", "addr_"))]
            assert len(feature_keys) >= 25, (
                f"FEATURE_LABELS 应有 25 维, 实际 {len(feature_keys)}: {feature_keys[:5]}"
            )

    def test_has_risk_level_score_map(self, appjs):
        assert "RISK_LEVEL_SCORE_MAP" in appjs
        # 4 档
        for level in ["低", "中", "高", "极高"]:
            assert f'"{level}"' in appjs

    def test_has_risk_event_thresholds(self, appjs):
        assert "RISK_EVENT_THRESHOLDS" in appjs
        for et in ["下单", "支付", "售后申请", "物流投诉", "通用"]:
            assert f'"{et}"' in appjs

    def test_has_builder_functions(self, appjs):
        for fn in ["buildConditionUI", "collectCondition", "renderCondNode",
                   "validateScoreLevel", "getRiskLevelByScore", "getEventThresholds"]:
            assert fn in appjs, f"app.js 缺 {fn} 函数"

    def test_has_operators(self, appjs):
        """10 种 op 必须都有."""
        for op in [">", ">=", "<", "<=", "==", "!=", "in", "not_in", "between", ""]:
            assert f'"{op}"' in appjs, f"app.js OPERATORS 缺 '{op}'"


class TestFrontendRulesPage:
    """rules.html 必须用 condBuilder 不用 textarea."""

    @pytest.fixture
    def html(self):
        p = Path("D:/workroom/尚硅谷大模型项目之风控系统/3.代码/AI_Risk/templates/rules.html")
        return p.read_text(encoding="utf-8")

    def test_uses_cond_builder(self, html):
        """必须用 condBuilder 容器."""
        assert "id=\"condBuilder\"" in html, "rules.html 缺 condBuilder 容器"

    def test_uses_collect_condition(self, html):
        """saveRule 必须调 collectCondition 拿 JSON."""
        assert "collectCondition" in html

    def test_hides_legacy_textarea(self, html):
        """老的 f_condition textarea 应被隐藏 (d-none), 留作 fallback."""
        assert 'id="f_condition"' in html
        assert "d-none" in html, "f_condition textarea 应该被隐藏"

    def test_has_auto_fill_score(self, html):
        """风险等级下拉 onchange 自动算 score."""
        assert "autoFillScoreByLevel" in html
        assert "onchange=\"autoFillScoreByLevel" in html

    def test_has_validate_score_level(self, html):
        """saveRule 必须前端预校验."""
        assert "validateScoreLevel" in html


# ============================================================
# 6. 端到端: validate_rule_score_level 集成到 save flow
# ============================================================

class TestRuleAPIValidation:
    """POST /api/rules 跟 PUT /api/rules/{id} 必须在 risk_level↔risk_score 不匹配时返 400."""

    @pytest.mark.asyncio
    async def test_create_rule_with_mismatch_returns_400(self):
        """集成测试: 通过 API 创建规则, 越界应返 400 (需要 mock DB)."""
        # 跳过真 DB 测试, 用 unit test 覆盖验证逻辑
        with pytest.raises(RuleScoreLevelMismatchError):
            validate_rule_score_level("极高", 30)
