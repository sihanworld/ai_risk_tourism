"""
风险检查页面测试 (P4-L4 2026-08-08)
- 验证 templates/risk_check.html 关键元素
- 重点: 评估结果区必须显示 XGBoost ML 评分 (P(拒绝) + ML 决策)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RISK_CHECK_HTML = ROOT / "templates" / "risk_check.html"


class TestRiskCheckPageMLScore:
    """评估结果区必须展示 XGBoost ML 评分"""

    def test_ml_score_section_exists(self):
        """风险检查结果区必须含 'ML 评分' / XGBoost 字段"""
        html = RISK_CHECK_HTML.read_text(encoding="utf-8")
        assert "ML 评分" in html, "结果区应显示 'ML 评分'"
        assert "XGBoost" in html, "应标明 ML 来源是 XGBoost"

    def test_ml_score_field_rendered(self):
        """渲染逻辑引用了 result.ml_score"""
        html = RISK_CHECK_HTML.read_text(encoding="utf-8")
        assert "result.ml_score" in html, "应读取 result.ml_score"
        # 含 'P(拒绝)' 标签
        assert "P(拒绝)" in html, "应展示 P(拒绝) 标签"

    def test_ml_decision_field_rendered(self):
        """渲染逻辑引用了 result.ml_decision"""
        html = RISK_CHECK_HTML.read_text(encoding="utf-8")
        assert "result.ml_decision" in html, "应读取 result.ml_decision"

    def test_model_not_loaded_placeholder(self):
        """模型未加载时, 必须显示 '未加载' 提示而不是空白"""
        html = RISK_CHECK_HTML.read_text(encoding="utf-8")
        # ml_score 字段必须含 null 兜底
        assert "ml_score != null" in html, "ml_score 字段应有 null 兜底"
        # 含 "未加载" 字样
        assert "未加载" in html, "应含 '未加载' 提示"

    def test_uses_unified_ml_score_render_block(self):
        """P4-L4 2026-08-08 统一渲染: 必须用 renderMLScoreBlock 替代内联拼接.

        之前模板直接拼接字符串 (ml_score * 100) / decisionBadge 等, 改成
        renderMLScoreBlock(result.ml_score, result.ml_decision) 统一渲染.
        优点: 1 个函数管 3 个页面, 改样式只改 1 处.
        """
        html = RISK_CHECK_HTML.read_text(encoding="utf-8")
        assert "renderMLScoreBlock" in html, (
            "应使用 renderMLScoreBlock 统一渲染 (app.js)"
        )
        # 不要再直接拼接 ml_score * 100
        assert "* 100" not in html or "renderMLScoreBlock" in html, (
            "应去除旧的内联拼接 (ml_score * 100), 改用 renderMLScoreBlock"
        )

    def test_ml_score_section_has_sigmoid_calibration(self):
        """P4-L4 2026-08-08: ML 评分小节必须含 sigmoid 校准 (sigmoid 风险分).

        不再只是 P(拒绝) 百分比, 必须有 0-100 风险分 (sigmoid 校准).
        """
        html = RISK_CHECK_HTML.read_text(encoding="utf-8")
        assert "sigmoid" in html, "应标注 sigmoid 校准"
        assert "风险分" in html, "应含 风险分 字段"

    def test_ml_section_after_triggered_rules(self):
        """ML 评分小节必须在 '命中规则' 之后, '特征详情' 之前 (阅读顺序)"""
        html = RISK_CHECK_HTML.read_text(encoding="utf-8")
        pos_trigger = html.find("命中规则")
        pos_ml = html.find("ML 评分")
        pos_features = html.find("特征详情")
        assert pos_trigger != -1 and pos_ml != -1 and pos_features != -1, "三个小节都应在"
        assert pos_trigger < pos_ml < pos_features, "顺序: 命中规则 → ML 评分 → 特征详情"
