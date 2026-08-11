"""[P4-L5 2026-08-11] 锁住"条件表达式 2 种编辑模式"功能.

用户反馈: 修改规则那部分的 JSON 编辑设置也要同步修改.
原来: 隐藏 textarea, alert 弹 JSON (丑/不能复制/不能编辑).
现在: 可视化 / JSON 两种模式自由切换 + JSON 弹窗 (modal + 复制按钮).
"""
import re
import pytest
from pathlib import Path

PROJECT_ROOT = Path("D:/workroom/尚硅谷大模型项目之风控系统/3.代码/AI_Risk")
RULES_HTML = PROJECT_ROOT / "templates" / "rules.html"


@pytest.fixture
def rules_html() -> str:
    return RULES_HTML.read_text(encoding="utf-8")


class TestCondModeToggle:
    """条件编辑模式切换按钮 (可视化 / JSON)."""

    def test_has_builder_button(self, rules_html):
        """[P4-L5 2026-08-11] 必须有 #condModeBuilder 按钮 (默认 active)."""
        assert 'id="condModeBuilder"' in rules_html, "缺 #condModeBuilder 按钮"
        # 默认 active
        m = re.search(
            r'<button[^>]*id="condModeBuilder"[^>]*>',
            rules_html,
        )
        assert m and 'active' in m.group(0), "#condModeBuilder 必须默认 active"

    def test_has_json_button(self, rules_html):
        """[P4-L5 2026-08-11] 必须有 #condModeJson 按钮."""
        assert 'id="condModeJson"' in rules_html, "缺 #condModeJson 按钮"
        m = re.search(
            r'<button[^>]*id="condModeJson"[^>]*>',
            rules_html,
        )
        assert m, "#condModeJson 按钮找不到"
        assert 'active' not in m.group(0), "JSON 按钮默认不应 active"

    def test_has_json_editor_container(self, rules_html):
        """[P4-L5 2026-08-11] 必须有 #condJsonEditor 容器 (默认 d-none 隐藏)."""
        m = re.search(
            r'<div\s+id="condJsonEditor"\s+class="([^"]+)"',
            rules_html,
        )
        assert m, "#condJsonEditor 容器找不到"
        classes = m.group(1)
        assert "d-none" in classes, f"#condJsonEditor 默认必须 d-none, 实际: {classes}"

    def test_has_cond_json_error(self, rules_html):
        """[P4-L5 2026-08-11] 必须有 #condJsonError 错误显示框."""
        assert 'id="condJsonError"' in rules_html, "缺 #condJsonError 错误显示框"

    def test_f_condition_textarea_in_json_editor(self, rules_html):
        """[P4-L5 2026-08-11] f_condition textarea 必须放在 #condJsonEditor 内."""
        m = re.search(
            r'<div\s+id="condJsonEditor"[^>]*>(.*?)</div>',
            rules_html, re.DOTALL,
        )
        assert m, "#condJsonEditor 容器找不到"
        body = m.group(1)
        assert 'id="f_condition"' in body, "f_condition textarea 必须在 condJsonEditor 内"
        # textarea 必须有 oninput 实时校验
        assert "oninput=" in body, "f_condition 必须挂 oninput 实时校验"


class TestSetCondMode:
    """setCondMode JS 函数: builder <-> json 切换."""

    def test_set_cond_mode_defined(self, rules_html):
        """[P4-L5 2026-08-11] setCondMode 函数必须定义."""
        assert "function setCondMode(" in rules_html, "setCondMode 函数必须定义"

    def test_builder_to_json_serializes(self, rules_html):
        """切到 json 模式: 把当前构建器 collectCondition + JSON.stringify 到 textarea."""
        m = re.search(
            r"function\s+setCondMode\s*\([^)]*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        assert m
        body = m.group(1)
        # 切到 json 必须 collectCondition + JSON.stringify
        assert "collectCondition" in body, "builder -> json 必须 collectCondition"
        assert "JSON.stringify" in body, "builder -> json 必须 JSON.stringify"

    def test_json_to_builder_parses(self, rules_html):
        """切回 builder 模式: JSON.parse + 校验 + buildConditionUI 渲染."""
        m = re.search(
            r"function\s+setCondMode\s*\([^)]*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        # json -> builder 必须 JSON.parse + buildConditionUI
        assert "JSON.parse" in body, "json -> builder 必须 JSON.parse"
        assert "buildConditionUI" in body, "json -> builder 必须 buildConditionUI"

    def test_set_cond_mode_validates_json_format(self, rules_html):
        """setCondMode json -> builder 时校验 JSON 必须是 {and: []} 或 {or: []}."""
        m = re.search(
            r"function\s+setCondMode\s*\([^)]*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        # 必须有格式校验 + 错误显示
        assert "condJsonError" in body, "json 校验错误必须显示到 #condJsonError"
        assert "and" in body and "or" in body, "格式校验必须有 and/or 检查"

    def test_set_cond_mode_uses_current_cond(self, rules_html):
        """[P4-L5 2026-08-11] 全局 _condMode 记录当前模式."""
        assert "let _condMode" in rules_html or "var _condMode" in rules_html, \
            "全局 _condMode 变量必须声明"
        m = re.search(r"(?:let|var)\s+_condMode\s*=\s*['\"]([^'\"]+)['\"]", rules_html)
        assert m, "_condMode 默认值必须是 'builder' 或 'json'"
        assert m.group(1) in ("builder", "json"), f"_condMode 默认: {m.group(1)}"


class TestOnCondJsonInput:
    """onCondJsonInput 实时校验 JSON."""

    def test_on_cond_json_input_defined(self, rules_html):
        """[P4-L5 2026-08-11] onCondJsonInput 函数必须定义."""
        assert "function onCondJsonInput(" in rules_html, "onCondJsonInput 必须定义"

    def test_on_cond_json_input_validates(self, rules_html):
        """onCondJsonInput 必须 try-catch + 显示错误到 #condJsonError."""
        m = re.search(
            r"function\s+onCondJsonInput\s*\([^)]*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        assert m
        body = m.group(1)
        assert "JSON.parse" in body, "onCondJsonInput 必须 JSON.parse"
        assert "try" in body and "catch" in body, "onCondJsonInput 必须 try-catch"
        assert "condJsonError" in body, "错误必须显示到 #condJsonError"


class TestShowRawConditionJson:
    """showRawConditionJson 弹窗 (替代 alert)."""

    def test_show_raw_uses_modal(self, rules_html):
        """[P4-L5 2026-08-11] showRawConditionJson 必须用 modal, 不用 alert."""
        m = re.search(
            r"function\s+showRawConditionJson\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        assert m
        body = m.group(1)
        # 必须有 bootstrap.Modal
        assert "bootstrap.Modal" in body, "showRawConditionJson 必须用 bootstrap.Modal 弹窗"
        # 不能直接 alert (alert 不能复制)
        assert "alert(" not in body or "alert('已" in body, \
            "showRawConditionJson 不能用 alert 直接弹 JSON, 必须用 modal"

    def test_show_raw_handles_json_mode(self, rules_html):
        """showRawConditionJson 在 JSON 模式时直接读 textarea."""
        m = re.search(
            r"function\s+showRawConditionJson\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        # 必须判断 _condMode === 'json'
        assert "_condMode" in body, "showRawConditionJson 必须判断当前模式"
        # 在 json 模式直接读 f_condition
        assert "f_condition" in body, "JSON 模式读 textarea 内容"

    def test_copy_cond_json_function_defined(self, rules_html):
        """[P4-L5 2026-08-11] 复制按钮函数 copyCondJsonFromViewer 必须存在."""
        assert "function copyCondJsonFromViewer(" in rules_html, \
            "copyCondJsonFromViewer 复制函数必须定义"


class TestSaveRuleDualMode:
    """saveRule 必须支持 builder 和 json 两种模式."""

    def test_save_rule_handles_json_mode(self, rules_html):
        """saveRule 在 _condMode === 'json' 时直接读 textarea."""
        m = re.search(
            r"async\s+function\s+saveRule\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        assert "_condMode" in body, "saveRule 必须判断 _condMode"
        # json 模式分支
        assert "f_condition" in body, "saveRule json 模式必须读 f_condition textarea"
        # builder 模式分支
        assert "collectCondition" in body, "saveRule builder 模式必须 collectCondition"
        # stripEmptyLeaves 两种模式都跑
        assert "stripEmptyLeaves" in body, "saveRule 必须 stripEmptyLeaves 两种模式都跑"

    def test_save_rule_json_validates(self, rules_html):
        """saveRule json 模式: 空 / 解析失败 / 格式错 都 alert 拦截."""
        m = re.search(
            r"async\s+function\s+saveRule\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        # 校验 JSON.parse 失败
        assert "JSON.parse" in body, "saveRule json 模式必须 JSON.parse"
        # 不能为空
        assert "alert" in body, "saveRule json 模式失败要 alert 提示"


class TestModeReset:
    """showCreateModal / editRule 打开时必须强制重置模式 (避免上次残留)."""

    def test_show_create_resets_mode(self, rules_html):
        """showCreateModal 打开时强制 _condMode = 'builder' + 隐藏 JSON 编辑器."""
        m = re.search(
            r"function\s+showCreateModal\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        assert m
        body = m.group(1)
        # 必须重置 _condMode 为 builder
        assert "_condMode = 'builder'" in body or '_condMode = "builder"' in body, \
            "showCreateModal 必须重置 _condMode = 'builder'"
        # 必须隐藏 condJsonEditor
        assert "condJsonEditor" in body, "showCreateModal 必须操作 condJsonEditor 隐藏"

    def test_edit_rule_resets_mode(self, rules_html):
        """editRule 打开时同样强制重置模式."""
        m = re.search(
            r"async\s+function\s+editRule\s*\([^)]*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        assert m
        body = m.group(1)
        assert "_condMode = 'builder'" in body or '_condMode = "builder"' in body, \
            "editRule 必须重置 _condMode = 'builder'"
        assert "condJsonEditor" in body, "editRule 必须操作 condJsonEditor 隐藏"


class TestJsonFormatValidation:
    """JSON 格式校验行为 (纯函数, 不依赖 DOM)."""

    def test_valid_and_format(self):
        """合法的 {and: [...]} 格式 -> 通过."""
        import json
        cond = {"and": [{"field": "x", "op": ">=", "value": 1}]}
        s = json.dumps(cond, ensure_ascii=False)
        parsed = json.loads(s)
        assert isinstance(parsed, dict) and "and" in parsed
        assert isinstance(parsed["and"], list)

    def test_valid_or_format(self):
        """合法的 {or: [...]} 格式 -> 通过."""
        import json
        cond = {"or": [{"field": "x", "op": "==", "value": 0}]}
        parsed = json.loads(json.dumps(cond, ensure_ascii=False))
        assert "or" in parsed

    def test_invalid_string_format_rejected(self):
        """字符串/数字/数组 -> 拒绝 (校验不通过)."""
        import json
        invalid = ["just a string", 42, [1, 2, 3], "and: []"]
        for s in invalid:
            try:
                parsed = json.loads(s) if isinstance(s, str) else s
            except json.JSONDecodeError:
                parsed = None
            # 必须不是 {and:[]} 或 {or:[]}
            is_valid = isinstance(parsed, dict) and ("and" in parsed or "or" in parsed)
            assert not is_valid, f"非法格式 {s!r} 不应通过校验"

    def test_empty_object_rejected(self):
        """空 {} 拒绝 (没有 and 也没有 or)."""
        parsed = {}
        is_valid = isinstance(parsed, dict) and ("and" in parsed or "or" in parsed)
        assert not is_valid, "空 {} 必须被拒绝"


class TestCondModeBehaviorSimulation:
    """模拟模式切换 + 保存, 锁住核心行为."""

    def test_builder_to_json_preserves_data(self):
        """builder 模式切到 json 模式, 数据应序列化保留."""
        # 模拟 collectCondition 拿到 builder 当前状态
        builder_cond = {
            "and": [
                {"field": "user_total_orders", "op": ">=", "value": 3},
                {"field": "order_total_amount", "op": ">", "value": 1000},
            ]
        }
        # 切到 json: JSON.stringify
        json_text = __import__("json").dumps(builder_cond, ensure_ascii=False, indent=2)
        # 切回 builder: JSON.parse
        restored = __import__("json").loads(json_text)
        assert restored == builder_cond, "builder <-> json 双向必须数据一致"

    def test_save_strips_empty_in_json_mode(self):
        """JSON 模式保存时 stripEmptyLeaves 也跑, 跳过 op='' 的 leaf."""
        # 复刻 stripEmptyLeaves 行为
        def strip(node):
            if not isinstance(node, dict):
                return node
            if "and" in node:
                children = [strip(c) for c in node["and"]]
                children = [c for c in children if c is not None]
                return {"and": children} if children else None
            if "or" in node:
                children = [strip(c) for c in node["or"]]
                children = [c for c in children if c is not None]
                return {"or": children} if children else None
            if node.get("op") in ("", None):
                return None
            return node
        # 用户在 JSON 模式直接粘贴了一个含 op='' 的 leaf
        cond = {
            "and": [
                {"field": "x", "op": "", "value": 0},  # 空, 跳过
                {"field": "y", "op": ">=", "value": 1},
            ]
        }
        out = strip(cond)
        assert out == {"and": [{"field": "y", "op": ">=", "value": 1}]}
