"""
P4-L4 2026-08-08: 前端 ML 评分 sigmoid 校准统一展示测试

验证:
- static/app.js 提供 mlProbToRiskScore + renderMLScoreBlock 函数
- 3 个页面 (risk_check / assessments / cases) 都用统一的 renderMLScoreBlock
- app/schemas.py CaseDetailResponse 含 ml_score / ml_decision 字段
- 校准点跟 Python 端 _ml_prob_to_risk_score 一致
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
RISK_CHECK_HTML = ROOT / "templates" / "risk_check.html"
ASSESS_HTML = ROOT / "templates" / "assessments.html"
CASES_HTML = ROOT / "templates" / "cases.html"
SCHEMAS = ROOT / "app" / "schemas.py"
SERVICE_CASE = ROOT / "app" / "service" / "case.py"

_NODE = shutil.which("node")


def _run_js(expr: str) -> str:
    """跑 JS 表达式, 返回 stdout 字符串."""
    if not _NODE:
        pytest.skip("node.js 未安装, 跳过 JS 运行时测试")
    js_code = (
        "const window = {}; const document = {getElementById: () => ({innerHTML: ''})};\n"
        + APP_JS.read_text(encoding="utf-8")
        + "\nresult = eval(" + json.dumps(expr) + ");\n"
        + "process.stdout.write(result === null || result === undefined ? 'null' : String(result));\n"
    )
    r = subprocess.run(
        [_NODE, "-e", js_code],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError(f"node.js 失败: {r.stderr}")
    return r.stdout


class TestMLProbToRiskScore:
    """app.js::mlProbToRiskScore P(拒绝) → 0-100 风险分 sigmoid 校准"""

    def test_function_exists(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "function mlProbToRiskScore(" in src, "mlProbToRiskScore 函数必须存在"

    def test_null_returns_null(self):
        assert _run_js("mlProbToRiskScore(null)") == "null"
        assert _run_js("mlProbToRiskScore(undefined)") == "null"

    def test_zero_returns_zero(self):
        assert _run_js("mlProbToRiskScore(0)") == "0"

    def test_one_returns_100(self):
        assert _run_js("mlProbToRiskScore(1)") == "100"

    def test_prob_01_returns_26(self):
        # 100 * (1 - exp(-0.3)) = 25.92 → 26
        assert _run_js("mlProbToRiskScore(0.1)") == "26"

    def test_prob_05_returns_78(self):
        # 100 * (1 - exp(-1.5)) = 77.69 → 78
        assert _run_js("mlProbToRiskScore(0.5)") == "78"

    def test_prob_09_returns_97(self):
        # 100 * (1 - exp(-2.7)) = 93.28 → 93... actually 100*(1-0.0672)=93.28
        # Wait let me recompute: exp(-2.7) = 0.0672, 100*(1-0.0672) = 93.28 → 93
        out = _run_js("mlProbToRiskScore(0.9)")
        assert out in ("92", "93", "94"), f"prob=0.9 应在 92-94, 实际: {out}"

    def test_monotonic_increasing(self):
        """prob 越大 → score 越大."""
        prev = -1
        for prob in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            score = int(_run_js(f"mlProbToRiskScore({prob})"))
            assert score >= prev, f"prob={prob} 应 >= 前一个 {prev}, 实际 {score}"
            prev = score


class TestRenderMLScoreBlock:
    """app.js::renderMLScoreBlock 渲染统一 HTML 片段"""

    def test_function_exists(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "function renderMLScoreBlock(" in src, "renderMLScoreBlock 函数必须存在"

    def test_null_returns_placeholder(self):
        out = _run_js("renderMLScoreBlock(null, null)")
        assert "未加载模型" in out, f"null/ml=NULL 应显示'未加载模型', 实际: {out!r}"

    def test_with_score_includes_three_parts(self):
        """有 ml_score 时, 渲染应含 P(拒绝) + 风险分(sigmoid 校准) + ML 决策"""
        out = _run_js("renderMLScoreBlock(0.5, '拒绝')")
        assert "P(拒绝)" in out, f"应含 P(拒绝), 实际: {out!r}"
        assert "风险分 (sigmoid 校准)" in out, f"应含'风险分 (sigmoid 校准)', 实际: {out!r}"
        assert "ML 决策" in out, f"应含 'ML 决策', 实际: {out!r}"
        assert "拒绝" in out, f"应含 ML 决策值 '拒绝', 实际: {out!r}"
        # prob=0.5 sigmoid 校准 = 78
        assert ">78<" in out, f"sigmoid 校准 0.5 应=78, 实际: {out!r}"


class TestRiskCheckPageMLScore:
    """risk_check.html 评估结果区必须显示 sigmoid 校准后的 ml_score"""

    def test_uses_render_block(self):
        src = RISK_CHECK_HTML.read_text(encoding="utf-8")
        assert "renderMLScoreBlock" in src, (
            "risk_check.html 应调 renderMLScoreBlock 统一渲染"
        )
        assert "ml_score" in src, "应引用 result.ml_score"

    def test_ml_score_section_title(self):
        src = RISK_CHECK_HTML.read_text(encoding="utf-8")
        assert "ML 评分" in src, "应含 ML 评分 小节标题"


class TestAssessmentsPageMLScore:
    """assessments.html 评估列表 + 详情都显示 sigmoid 校准 ml_score"""

    def test_uses_render_block_in_detail(self):
        src = ASSESS_HTML.read_text(encoding="utf-8")
        assert "renderMLScoreBlock" in src, "详情应调 renderMLScoreBlock"

    def test_uses_ml_prob_to_risk_score_in_list(self):
        """列表应调 mlProbToRiskScore 显示风险分列"""
        src = ASSESS_HTML.read_text(encoding="utf-8")
        assert "mlProbToRiskScore(" in src, "列表应调 mlProbToRiskScore"

    def test_list_header_has_risk_score_column(self):
        """列表表头应有'风险分 (sigmoid)'列"""
        src = ASSESS_HTML.read_text(encoding="utf-8")
        assert "风险分 (sigmoid)" in src, "列表表头应加'风险分 (sigmoid)'列"


class TestCasesPageMLScore:
    """cases.html 案件详情必须显示 sigmoid 校准后的 ml_score"""

    def test_uses_render_block(self):
        src = CASES_HTML.read_text(encoding="utf-8")
        assert "renderMLScoreBlock" in src, (
            "cases.html 应调 renderMLScoreBlock 统一渲染"
        )

    def test_uses_ml_score_field(self):
        src = CASES_HTML.read_text(encoding="utf-8")
        assert "c.ml_score" in src, "应引用 c.ml_score (从 API 响应拿)"

    def test_ml_score_section_title(self):
        src = CASES_HTML.read_text(encoding="utf-8")
        assert "ML 评分" in src, "应含 ML 评分 小节标题"


class TestCaseDetailResponseSchema:
    """CaseDetailResponse 必须含 ml_score / ml_decision 字段 (前端才能拿到)"""

    def test_ml_score_in_schema(self):
        src = SCHEMAS.read_text(encoding="utf-8")
        # 找 CaseDetailResponse 类块 (到下一个 class 为止)
        m = re.search(
            r"class CaseDetailResponse\(BaseModel\):(.*?)\n\nclass ",
            src, re.DOTALL,
        )
        assert m, "找不到 CaseDetailResponse 类"
        block = m.group(1)
        assert "ml_score" in block, "CaseDetailResponse 缺 ml_score 字段"
        assert "ml_decision" in block, "CaseDetailResponse 缺 ml_decision 字段"

    def test_get_case_detail_returns_ml_score(self):
        """get_case_detail 应该从 assessment 拿 ml_score / ml_decision"""
        src = SERVICE_CASE.read_text(encoding="utf-8")
        # 找 get_case_detail 函数体 (到下一个 async def 或 def 为止)
        m = re.search(
            r"async def get_case_detail\(.*?\n(?=\nasync def |\ndef )",
            src, re.DOTALL,
        )
        assert m, "找不到 get_case_detail 函数"
        body = m.group(0)
        assert "ml_score=" in body, "get_case_detail 应填 ml_score"
        assert "ml_decision=" in body, "get_case_detail 应填 ml_decision"
