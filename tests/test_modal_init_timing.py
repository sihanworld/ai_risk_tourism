"""[P4-L5 2026-08-10] 锁住"rules.html modal 初始化时机"修复.

背景: 之前 showCreateModal() 在 bootstrap.Modal.show() 之前直接调
buildConditionUI, 第一次开 modal 时 buildConditionUI 内部 throw
(Bootstrap 5 focus trap / 样式重排时插入 <select>/<input> 干扰),
导致 #condBuilder 空白. 用户体验: 第一次开模态框空白, 关闭再开才看到内容.

修复: buildConditionUI 放到 shown.bs.modal 事件回调里, 等 Bootstrap
完全 show 完再渲染.

本测试:
1. 验证 rules.html 真的把 buildConditionUI 放到了 shown.bs.modal 事件回调里
2. 验证 showCreateModal() 内不再直接调 buildConditionUI (在 .show() 之前)
3. 验证 editRule() 同理
4. 验证 app.js 仍然导出 buildConditionUI / collectCondition / validateScoreLevel
"""
import re
import pytest
from pathlib import Path

PROJECT_ROOT = Path("D:/workroom/尚硅谷大模型项目之风控系统/3.代码/AI_Risk")
RULES_HTML = PROJECT_ROOT / "templates" / "rules.html"
APP_JS = PROJECT_ROOT / "static" / "app.js"


@pytest.fixture
def rules_html() -> str:
    return RULES_HTML.read_text(encoding="utf-8")


@pytest.fixture
def appjs() -> str:
    return APP_JS.read_text(encoding="utf-8")


class TestShowCreateModalTiming:
    """showCreateModal: buildConditionUI 必须放到 shown.bs.modal 之后."""

    def test_uses_shown_event_callback(self, rules_html):
        """shown.bs.modal 事件必须在 showCreateModal 里挂载."""
        m = re.search(
            r"function\s+showCreateModal\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        assert m, "showCreateModal not found in rules.html"
        body = m.group(1)
        # 必须 addEventListener('shown.bs.modal', ...)
        assert "shown.bs.modal" in body, (
            "buildConditionUI 必须在 shown.bs.modal 回调里调, "
            "避免 Bootstrap 5 首次 show 干扰 throw"
        )
        # 必须用 addEventListener
        assert "addEventListener" in body, "需要 addEventListener('shown.bs.modal', ...)"

    def test_buildConditionUI_called_inside_shown_callback(self, rules_html):
        """buildConditionUI 必须在事件回调函数体里调, 不能在 .show() 之前."""
        m = re.search(
            r"function\s+showCreateModal\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)

        # 找 buildConditionUI(...) 位置 + new bootstrap.Modal(...).show() 位置
        bcui_pos = body.find("buildConditionUI(")
        show_pos = body.find(".show()")
        assert bcui_pos > -1, "showCreateModal 必须调 buildConditionUI"
        assert show_pos > -1, "showCreateModal 必须 .show() modal"

        # buildConditionUI 的位置必须在 .show() 之后 (因为回调注册在 .show() 之前,
        # 但 buildConditionUI 实际执行在 .show() 触发的 shown.bs.modal 事件后).
        # 这里我们检查源代码: buildConditionUI 调用必须出现在 shown.bs.modal
        # 事件回调函数体内, 而不在 .show() 之前.
        #
        # 简化: 找 "function () {" 或 "() => {" + 包含 buildConditionUI,
        # 确认 buildConditionUI 在某个 callback 函数里.
        # 找 onShown = () => { ... buildConditionUI ... }
        on_shown_match = re.search(
            r"const\s+onShown\s*=\s*\(\s*\)\s*=>\s*\{[^}]*buildConditionUI",
            body, re.DOTALL,
        )
        assert on_shown_match, (
            "buildConditionUI 必须在 onShown 回调里调, 不在 .show() 之前直接调"
        )

    def test_removes_listener_after_first_show(self, rules_html):
        """挂的事件监听器必须在第一次 show 后移除, 避免重复挂载内存泄漏."""
        m = re.search(
            r"function\s+showCreateModal\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        assert "removeEventListener" in body, (
            "shown.bs.modal 监听器必须 removeEventListener, 否则每次开关都挂新回调"
        )


class TestEditRuleTiming:
    """editRule 同样必须把 buildConditionUI 放到 shown.bs.modal 之后."""

    def test_uses_shown_event_callback(self, rules_html):
        m = re.search(
            r"async\s+function\s+editRule\s*\([^)]*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        assert m, "editRule not found in rules.html"
        body = m.group(1)
        assert "shown.bs.modal" in body, (
            "editRule 也必须把 buildConditionUI 放到 shown.bs.modal 之后, "
            "避免第一次开 modal 空白 bug"
        )
        assert "removeEventListener" in body, "editRule 也必须清理监听器"

    def test_buildConditionUI_called_after_get_rule(self, rules_html):
        """editRule 流程: fetch → 填表单 → shown.bs.modal 回调里 buildConditionUI."""
        m = re.search(
            r"async\s+function\s+editRule\s*\([^)]*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        # 简化: onShown 回调里必须调 buildConditionUI(r.rule_condition, 'condBuilder')
        on_shown_match = re.search(
            r"const\s+onShown\s*=\s*\(\s*\)\s*=>\s*\{[^}]*buildConditionUI",
            body, re.DOTALL,
        )
        assert on_shown_match, "editRule 内 onShown 回调必须调 buildConditionUI"


class TestAppJsExports:
    """app.js 仍然导出 buildConditionUI / collectCondition / validateScoreLevel."""

    def test_buildConditionUI_defined(self, appjs):
        assert "function buildConditionUI" in appjs

    def test_collectCondition_defined(self, appjs):
        assert "function collectCondition" in appjs

    def test_validateScoreLevel_defined(self, appjs):
        assert "function validateScoreLevel" in appjs

    def test_renderCondNode_defined(self, appjs):
        assert "function renderCondNode" in appjs

    def test_updateValueInput_defined(self, appjs):
        assert "function updateValueInput" in appjs

    def test_FEATURE_LABELS_has_25_keys(self, appjs):
        """25 个特征 key ↔ 中文标签: 用户画像 14 + 订单画像 8 + 地址画像 3."""
        m = re.search(r"FEATURE_LABELS\s*=\s*\{(.*?)\};", appjs, re.DOTALL)
        assert m
        # 匹配 "key": "label" 数量 (key 允许数字, 如 user_orders_30d)
        keys = re.findall(r'"[a-z_0-9]+"\s*:\s*"', m.group(1))
        assert len(keys) == 25, f"FEATURE_LABELS 应有 25 个 key, 实际 {len(keys)}"

    def test_OPERATORS_has_10_entries(self, appjs):
        """10 种 op: > >= < <= == != in not_in between ""."""
        m = re.search(r"OPERATORS\s*=\s*\[(.*?)\];", appjs, re.DOTALL)
        assert m
        # value: 计数
        values = re.findall(r'value:\s*"([^"]*)"', m.group(1))
        assert len(values) == 10, f"OPERATORS 应有 10 个, 实际 {len(values)}: {values}"


class TestBuildConditionUIRobustness:
    """buildConditionUI 自身应有 try-catch 兜底, 防止后续 throw 把整个 UI 卡死."""

    def test_try_catch_wrapper_exists(self, appjs):
        """[P4-L5 2026-08-10] buildConditionUI 用 try-catch 包 renderCondNode,
        失败时把异常显示在容器里 (红色 <pre>), 而不是无声失败让用户看到空白."""
        m = re.search(
            r"function\s+buildConditionUI\s*\([^)]*\)\s*\{(.*?)\n\}",
            appjs, re.DOTALL,
        )
        assert m
        body = m.group(1)
        assert "try" in body, "buildConditionUI 必须 try 包住 renderCondNode"
        assert "catch" in body, "buildConditionUI 必须 catch 错误兜底"
        assert "console.error" in body, "catch 内必须 console.error 调试"
        # 错误显示到容器里, 至少要有 innerHTML
        assert "innerHTML" in body, "catch 内必须把错误显示到容器"
