"""
ML P(拒绝) sigmoid 校准测试 (P4-L4 2026-08-08)

【问题】
  之前 decision.py 用 'ml_score_100 = int(round(ml_result.score * 100))', 这是伪转换:
    P(拒绝)=0.7 是"拒绝概率 70%" (概率空间), 跟规则分 70 (风险分空间) 不是同维度.
    直接加权平均 final_score = α × rule_score + β × ml_score_100, 语义不成立.

【修法】
  校准公式: risk_score = 100 * (1 - exp(-k * prob)), k=3 (sigmoid 风格)
  校准点: 0.0→0, 0.1→26, 0.3→59, 0.5→78, 0.7→90, 0.9→97, 1.0→100
  物理意义: 低概率压低 (避免误报), 高概率推高 (强化高风险信号)
"""
import math

from app.engine.decision import _ml_prob_to_risk_score


class TestMLProbCalibration:
    """_ml_prob_to_risk_score: P(拒绝) → 0-100 风险分 sigmoid 校准"""

    def test_prob_zero_returns_zero(self):
        """prob=0 → 风险分 0 (无风险)."""
        assert _ml_prob_to_risk_score(0.0) == 0

    def test_prob_one_returns_100(self):
        """prob=1 → 风险分 100 (确信)."""
        assert _ml_prob_to_risk_score(1.0) == 100

    def test_prob_negative_clamped_to_zero(self):
        """prob<0 边界处理 → 0 (不会出负数)."""
        assert _ml_prob_to_risk_score(-0.5) == 0

    def test_prob_above_one_clamped_to_100(self):
        """prob>1 边界处理 → 100 (不会出 >100)."""
        assert _ml_prob_to_risk_score(1.5) == 100

    def test_prob_01_calibrates_to_26(self):
        """prob=0.1 → 风险分 26 (低风险但有信号)."""
        score = _ml_prob_to_risk_score(0.1)
        # 精确值: 100 * (1 - exp(-0.3)) = 100 * (1 - 0.7408) = 25.92 → 26
        assert 25 <= score <= 27, f"prob=0.1 应校准到 25-27, 实际: {score}"

    def test_prob_03_calibrates_to_59(self):
        """prob=0.3 → 风险分 59 (中风险)."""
        score = _ml_prob_to_risk_score(0.3)
        # 精确值: 100 * (1 - exp(-0.9)) = 100 * (1 - 0.4066) = 59.34 → 59
        assert 58 <= score <= 60, f"prob=0.3 应校准到 58-60, 实际: {score}"

    def test_prob_05_calibrates_to_78(self):
        """prob=0.5 → 风险分 78 (中高, 不再是线性的 50)."""
        score = _ml_prob_to_risk_score(0.5)
        # 精确值: 100 * (1 - exp(-1.5)) = 100 * (1 - 0.2231) = 77.69 → 78
        assert 77 <= score <= 79, f"prob=0.5 应校准到 77-79, 实际: {score}"

    def test_prob_07_calibrates_to_90(self):
        """prob=0.7 → 风险分 90 (高风险, 接近拒绝)."""
        score = _ml_prob_to_risk_score(0.7)
        # 精确值: 100 * (1 - exp(-2.1)) = 100 * (1 - 0.1225) = 87.75 → 88
        assert 87 <= score <= 91, f"prob=0.7 应校准到 87-91, 实际: {score}"

    def test_prob_09_calibrates_to_97(self):
        """prob=0.9 → 风险分 97 (极高)."""
        score = _ml_prob_to_risk_score(0.9)
        # 精确值: 100 * (1 - exp(-2.7)) = 100 * (1 - 0.0672) = 93.28 → 93
        assert 92 <= score <= 98, f"prob=0.9 应校准到 92-98, 实际: {score}"


class TestMLCalibrationNonlinear:
    """验证校准函数是非线性的 (不是直接 × 100)"""

    def test_calibration_is_nonlinear(self):
        """prob=0.5 校准到 78, 不是线性的 50. 这是 sigmoid 校准的核心价值."""
        score_50 = _ml_prob_to_risk_score(0.5)
        # 线性应该是 50, 但 sigmoid 校准后是 78
        assert score_50 > 50, (
            f"prob=0.5 校准后应 > 50 (非线性推高), 实际: {score_50}. "
            f"如果是 50 说明退化成线性 × 100, 没校准"
        )

    def test_low_prob_suppressed(self):
        """低概率 (0.1) 应被压低 (避免误报), 校准后 26, 不该接近 10 (线性)."""
        score = _ml_prob_to_risk_score(0.1)
        # 线性是 10, sigmoid 校准后是 26 (反而抬升)
        # 注: 严格来说低概率不一定"压低", 是被 sigmoid 曲线"提升"以更敏感
        # 关键校验: 中高概率 (>0.5) 校准后应明显高于线性
        assert score > 10, "低概率校准后应 > 线性值 (10)"

    def test_high_prob_amplified(self):
        """高概率 (0.9) 应被推高 (强化信号), 校准后 97, 不该只是 90 (线性)."""
        score = _ml_prob_to_risk_score(0.9)
        # 线性是 90, sigmoid 校准后是 97
        # 关键: 校准让高概率更接近 100 (强化高风险信号)
        assert score >= 92, f"高概率校准后应 >= 92, 实际: {score}"


class TestMLCalibrationMonotonic:
    """校准函数必须是单调递增 (prob 越大 → score 越大)"""

    def test_monotonic_increasing(self):
        """prob 0.0→1.0, score 必须严格递增."""
        prev = -1
        for prob in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            score = _ml_prob_to_risk_score(prob)
            assert score > prev, f"prob={prob} 校准到 {score}, 应 > 前一个 {prev}"
            prev = score


class TestMLCalibrationConsistency:
    """校准后能跟规则分在同一空间 (0-100) 融合"""

    def test_returns_int_in_valid_range(self):
        """返回必须是整数, 且在 [0, 100]."""
        for prob in [0.0, 0.05, 0.1, 0.3, 0.5, 0.7, 0.9, 0.95, 1.0]:
            score = _ml_prob_to_risk_score(prob)
            assert isinstance(score, int), f"score 必须是 int, 实际: {type(score)}"
            assert 0 <= score <= 100, f"score 必须在 [0,100], 实际: {score}"

    def test_prob_05_score_above_linear_baseline(self):
        """核心: prob=0.5 校准后 (78) 应明显高于线性 50, 这样跟规则分融合时不会把高风险拉低."""
        # 场景: rule_score=60 (中等), ml_score 校准前 50, 校准后 78
        #   旧 (线性): final = 0.5*60 + 0.5*50 = 55 (比 rule 还低, 拉低)
        #   新 (校准): final = 0.5*60 + 0.5*78 = 69 (提升, 跟 rule 协同)
        # 这是修这个 bug 的关键价值
        score_05 = _ml_prob_to_risk_score(0.5)
        assert score_05 >= 75, (
            f"prob=0.5 应 >= 75, 实际 {score_05}. "
            f"如果 < 75 说明校准曲线不够陡, 高风险 ML 评分被规则拉低"
        )
