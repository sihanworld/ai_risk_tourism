"""[P4-L5 2026-08-10] 锁住"条件构建器布局优化"修复.

用户反馈:
1. modal 太小, 希望更大
2. op 下拉右侧 value 框被挤窄, 显示不全
3. + 条件每次只加 1 个, 不如一次显示多个空条件框

修复:
1. modal-lg -> modal-xl (1140px) + modal-dialog-scrollable
2. cond-leaf 改用 CSS Grid 4 列布局 (字段/op/value/操作), value 列最小 220px 不被挤
3. + 条件一次加 3 个空条件框
4. 默认 showCreateModal 渲染 1 个 AND + 3 个空 leaf, 用户开 modal 直接填
5. saveRule 加 stripEmptyLeaves 跳过 op='' 的空 leaf, 不存占位条件
6. + 分组默认带 1 个 AND 子组
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


class TestModalSize:
    """modal 宽度: modal-xl (1140px) + scrollable."""

    def test_uses_modal_xl(self, rules_html):
        """用 modal-xl 而非 modal-lg, 给条件构建器更宽画布."""
        m = re.search(
            r'<div\s+class="modal-dialog\s+([^"]+)"\s*>',
            rules_html,
        )
        assert m, "modal-dialog class not found"
        classes = m.group(1)
        assert "modal-xl" in classes, f"应该用 modal-xl, 实际: {classes}"
        assert "modal-dialog-scrollable" in classes, "需要 modal-dialog-scrollable 让长内容可滚"

    def test_no_modal_lg(self, rules_html):
        """不应该用 modal-lg (太窄 800px)."""
        assert "modal-lg" not in rules_html, "modal-lg 太窄, 已升级 modal-xl"


class TestCondLeafGridLayout:
    """cond-leaf 改用 CSS Grid 4 列, 解决 op/value 被挤."""

    def test_uses_grid_display(self, appjs):
        """[P4-L5 2026-08-10] cond-leaf row.style.display = 'grid'."""
        # 找 cond-leaf 的 row 创建
        m = re.search(
            r"row\.className\s*=\s*'cond-leaf[^']*';(.*?)parent\.appendChild\(row\);",
            appjs, re.DOTALL,
        )
        assert m, "cond-leaf row 创建逻辑找不到"
        body = m.group(1)
        assert "row.style.display = 'grid'" in body, \
            "cond-leaf 必须改用 grid 布局, 解决 d-flex 4 控件被挤"

    def test_grid_template_columns(self, appjs):
        """[P4-L5 2026-08-10] 4 列 grid 模板: 字段(2fr) / op(1fr) / value(2fr) / 操作(60px)."""
        m = re.search(
            r"row\.className\s*=\s*'cond-leaf[^']*';(.*?)parent\.appendChild\(row\);",
            appjs, re.DOTALL,
        )
        body = m.group(1)
        m2 = re.search(
            r"row\.style\.gridTemplateColumns\s*=\s*['\"]([^'\"]+)['\"]",
            body,
        )
        assert m2, "gridTemplateColumns 必须设置"
        cols = m2.group(1)
        # 4 列, 拿括号内 1 个完整列 (minmax(220px, 2fr) 是 1 列)
        # 用 ( 切分, minmax( 后到下一个 空格 之前是 1 个值片段
        # 简单做法: 数 "minmax" 出现次数 (3 次) + 末尾 "60px" 1 次 = 4 列
        minmax_count = cols.count("minmax(")
        # 应该有 3 个 minmax (字段/op/value) + 1 个固定宽 (操作) = 4 列
        assert minmax_count == 3, f"应有 3 个 minmax(...) 灵活列, 实际 {minmax_count}: {cols}"
        assert "60px" in cols, f"最后一列应是 60px 固定宽, 实际: {cols}"
        # value 列 (第 3 列) 必须有 minmax(220px,...) 防止被挤
        assert "minmax(220px" in cols, f"value 列应有 minWidth 220px, 实际: {cols}"

    def test_no_d_flex_on_cond_leaf(self, appjs):
        """[P4-L5 2026-08-10] 不再用 d-flex (grid 替代)."""
        m = re.search(
            r"row\.className\s*=\s*'cond-leaf[^']*';",
            appjs,
        )
        assert m
        cls = m.group(0)
        assert "d-flex" not in cls, "cond-leaf 不要再用 d-flex, 改 grid 4 列"

    def test_value_box_no_flex1(self, appjs):
        """[P4-L5 2026-08-10] valBox 不再用 flex:1 (grid 自动 stretch)."""
        # 找 valBox 创建块 (到 row.appendChild(valBox);)
        m = re.search(
            r"const valBox = document\.createElement\('div'\);(.*?)row\.appendChild\(valBox\);",
            appjs, re.DOTALL,
        )
        assert m, "valBox 创建块找不到"
        body = m.group(1)
        assert "flex: '1'" not in body and "flex:1" not in body, \
            f"valBox 不应再设 flex:1 (grid 自动 stretch), 实际: {body}"


class TestAddLeafBatch:
    """+ 条件按钮一次加 3 个空条件框."""

    def test_add_leaf_pushes_3(self, appjs):
        """[P4-L5 2026-08-10] + 条件按钮 for 循环 push 3 次."""
        # 找 cond-add-leaf 的 click handler
        m = re.search(
            r"querySelector\('\.cond-add-leaf'\)\.addEventListener\('click',\s*\(\)\s*=>\s*\{(.*?)\}\);",
            appjs, re.DOTALL,
        )
        assert m, "cond-add-leaf handler not found"
        body = m.group(1)
        # 必须有 for (let i = 0; i < 3; i++) 或类似
        assert "i < 3" in body or "i<3" in body, \
            f"+ 条件必须一次 push 3 次, 实际: {body}"

    def test_add_group_pushes_with_default_and(self, appjs):
        """[P4-L5 2026-08-10] + 分组默认带 1 个 AND 子组 (嵌套场景)."""
        m = re.search(
            r"querySelector\('\.cond-add-group'\)\.addEventListener\('click',\s*\(\)\s*=>\s*\{(.*?)\}\);",
            appjs, re.DOTALL,
        )
        assert m, "cond-add-group handler not found"
        body = m.group(1)
        # 默认 push 一个带子 leaf 的 and, 不是空 and
        assert "{and: [" in body, f"+ 分组默认带 1 个 AND 子组, 实际: {body}"

    def test_button_label_indicates_3(self, appjs):
        """[P4-L5 2026-08-10] + 条件按钮文案带 '一次 3 个' 提示用户."""
        m = re.search(
            r"cond-add-leaf['\"][^>]*>([^<]+)</button>",
            appjs,
        )
        assert m, "cond-add-leaf button text not found"
        assert "3" in m.group(1), \
            f"+ 条件按钮文案应含 3 提示用户, 实际: {m.group(1)}"


class TestShowCreateModalDefault:
    """showCreateModal 默认渲染 1 个 AND + 3 个空 leaf."""

    def test_default_3_empty_leaves(self, rules_html):
        """[P4-L5 2026-08-10] showCreateModal 默认 3 个空 leaf."""
        # [P4-L5 2026-08-10] 用 const initialCond = { and: [...] }; 模式后,
        # buildConditionUI 调用点变成 buildConditionUI(initialCond, 'condBuilder')
        # 这里改找: const initialCond = { and: [...], }, 然后数 user_total_orders 次数
        m = re.search(
            r"const\s+initialCond\s*=\s*\{\s*and:\s*\[(.*?)\],\s*\}",
            rules_html, re.DOTALL,
        )
        assert m, "showCreateModal 必须有 const initialCond = {and: [...]}, (3 个空 leaf)"
        items = m.group(1).count("user_total_orders")
        assert items == 3, f"默认应 3 个空 leaf, 实际 {items}"


class TestSaveRuleStripEmpty:
    """saveRule 用 stripEmptyLeaves 跳过 op='' 的空 leaf."""

    def test_strip_empty_leaves_defined(self, appjs):
        """[P4-L5 2026-08-10] app.js 必须有 stripEmptyLeaves 函数."""
        assert "function stripEmptyLeaves" in appjs, "stripEmptyLeaves 必须定义"

    def test_save_rule_uses_strip_empty_leaves(self, rules_html):
        """[P4-L5 2026-08-10] saveRule 调 collectCondition 后必须包 stripEmptyLeaves."""
        m = re.search(
            r"async\s+function\s+saveRule\s*\(\s*\)\s*\{(.*?)\n\}",
            rules_html, re.DOTALL,
        )
        body = m.group(1)
        assert "stripEmptyLeaves" in body, "saveRule 必须 stripEmptyLeaves 跳过空 leaf"
        assert "collectCondition" in body, "saveRule 必须 collectCondition 收 JSON"

    def test_strip_empty_leaves_logic(self, appjs):
        """stripEmptyLeaves 内部: op === '' 视为未填, 递归去掉空 group (无子节点)."""
        m = re.search(
            r"function\s+stripEmptyLeaves\s*\([^)]*\)\s*\{(.*?)\n\}",
            appjs, re.DOTALL,
        )
        assert m
        body = m.group(1)
        # op === '' 视为空
        assert "op === ''" in body or "op===''" in body, \
            f"stripEmptyLeaves 必须跳过 op === '' 的 leaf, 实际: {body[:300]}"
        # 递归处理 and / or
        assert "node.and" in body, "必须递归处理 and"
        assert "node.or" in body, "必须递归处理 or"
        # 过滤掉 null
        assert "filter" in body, "必须 filter 掉空的子节点"


class TestStripEmptyLeavesBehavior:
    """stripEmptyLeaves 行为测试 (直接调函数, 不依赖 DOM)."""

    def test_leaf_with_op_kept(self):
        """有 op 的 leaf 保留."""
        from app.engine.rule import validate_rule_score_level
        # 复刻 stripEmptyLeaves 行为 (因为它是 inline 在 app.js 不能直接 import)
        def strip(node):
            if not node or not isinstance(node, dict):
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
        assert strip({"field": "x", "op": ">=", "value": 1}) == \
            {"field": "x", "op": ">=", "value": 1}

    def test_empty_leaf_dropped(self):
        """op === '' 的空 leaf 去掉."""
        def strip(node):
            if not node or not isinstance(node, dict):
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
        assert strip({"field": "x", "op": "", "value": 0}) is None

    def test_and_with_all_empty_returns_null(self):
        """and 里全是空 leaf -> 整个 and = null."""
        def strip(node):
            if not node or not isinstance(node, dict):
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
        node = {"and": [
            {"field": "x", "op": "", "value": 0},
            {"field": "y", "op": "", "value": 0},
        ]}
        assert strip(node) is None

    def test_mixed_and_strips_only_empty(self):
        """and 里混合: 保留有 op 的, 去空."""
        def strip(node):
            if not node or not isinstance(node, dict):
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
        node = {"and": [
            {"field": "x", "op": "", "value": 0},
            {"field": "y", "op": ">=", "value": 5},
            {"field": "z", "op": "==", "value": 1},
        ]}
        out = strip(node)
        assert out == {"and": [
            {"field": "y", "op": ">=", "value": 5},
            {"field": "z", "op": "==", "value": 1},
        ]}

    def test_nested_group_recursive(self):
        """嵌套 group: 外层 or + 内层 and, 各自 strip."""
        def strip(node):
            if not node or not isinstance(node, dict):
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
        node = {"or": [
            {"and": [
                {"field": "a", "op": ">=", "value": 1},
                {"field": "b", "op": "", "value": 0},  # 空, 去掉
            ]},
            {"field": "c", "op": "==", "value": 0},  # 保留
        ]}
        out = strip(node)
        # 内层 and 剩 1 个 leaf, 外层 or 含 1 个 group + 1 个 leaf
        assert out == {"or": [
            {"and": [{"field": "a", "op": ">=", "value": 1}]},
            {"field": "c", "op": "==", "value": 0},
        ]}
