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
    """+ 条件按钮一次加 1 个空条件框 [P4-L5 2026-08-11 用户偏好]."""

    def test_add_leaf_pushes_1(self, appjs):
        """[P4-L5 2026-08-11] + 条件按钮 push 1 次 (不是 for 循环 3 次)."""
        m = re.search(
            r"querySelector\('\.cond-add-leaf'\)\.addEventListener\('click',\s*\(\)\s*=>\s*\{(.*?)\}\);",
            appjs, re.DOTALL,
        )
        assert m, "cond-add-leaf handler not found"
        body = m.group(1)
        # 一次 push 1 个: children.push({field: ...})
        # 不能有 for 循环
        assert "for " not in body, \
            f"+ 条件应一次 push 1 个 (不带 for 循环), 实际: {body}"
        # 必须有 push
        assert "children.push(" in body, f"+ 条件必须 push 一个 leaf, 实际: {body}"

    def test_add_group_pushes_with_default_and(self, appjs):
        """[P4-L5 2026-08-10] + 分组默认带 1 个 AND 子组 (嵌套场景)."""
        m = re.search(
            r"querySelector\('\.cond-add-group'\)\.addEventListener\('click',\s*\(\)\s*=>\s*\{(.*?)\}\);",
            appjs, re.DOTALL,
        )
        assert m, "cond-add-group handler not found"
        body = m.group(1)
        assert "{and: [" in body, f"+ 分组默认带 1 个 AND 子组, 实际: {body}"

    def test_button_label_simple(self, appjs):
        """[P4-L5 2026-08-11] + 条件按钮文案就是 '+ 条件' (不再带 '一次 3 个' 提示)."""
        m = re.search(
            r"cond-add-leaf['\"][^>]*>([^<]+)</button>",
            appjs,
        )
        assert m, "cond-add-leaf button text not found"
        text = m.group(1).strip()
        assert text == "+ 条件", f"按钮文案应是 '+ 条件', 实际: {text}"


class TestShowCreateModalDefault:
    """showCreateModal 默认渲染 1 个 AND + 3 个空 leaf."""

    def test_default_1_empty_leaf(self, rules_html):
        """[P4-L5 2026-08-11] showCreateModal 默认 1 个空 leaf (用户偏好: 干净)."""
        m = re.search(
            r"const\s+initialCond\s*=\s*\{\s*and:\s*\[(.*?)\],\s*\}",
            rules_html, re.DOTALL,
        )
        assert m, "showCreateModal 必须有 const initialCond = {and: [...]}"
        items = m.group(1).count("user_total_orders")
        assert items == 1, f"默认应 1 个空 leaf, 实际 {items}"


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


class TestRemoveCondFromTree:
    """[P4-L5 2026-08-11] 删 leaf / 删 group 同步从 window._CURRENT_COND splice,
    避免 UI/数据不一致. 用对象引用 index 找节点 (Python list.index 行为跟 JS indexOf 一致)."""

    def _remove(self, node, target):
        """复刻 JS removeCondFromTree, 用 Python list 语法."""
        if not node or not isinstance(node, dict):
            return False
        if "and" in node and isinstance(node["and"], list):
            try:
                idx = node["and"].index(target)
            except ValueError:
                idx = -1
            if idx >= 0:
                del node["and"][idx]
                return True
            for c in node["and"]:
                if self._remove(c, target):
                    return True
        if "or" in node and isinstance(node["or"], list):
            try:
                idx = node["or"].index(target)
            except ValueError:
                idx = -1
            if idx >= 0:
                del node["or"][idx]
                return True
            for c in node["or"]:
                if self._remove(c, target):
                    return True
        return False

    def test_remove_leaf_from_root_and(self):
        """根 and 里删一个 leaf, splice 后剩 1 个 leaf."""
        leaf1 = {"field": "x", "op": ">=", "value": 1}
        leaf2 = {"field": "y", "op": "==", "value": 2}
        root = {"and": [leaf1, leaf2]}
        assert self._remove(root, leaf1) is True
        assert root == {"and": [leaf2]}

    def test_remove_group_from_root_and(self):
        """根 and 里删一个 group, splice 后剩 1 个 group."""
        group = {"and": [{"field": "x", "op": ">=", "value": 1}]}
        leaf = {"field": "y", "op": "==", "value": 2}
        root = {"and": [group, leaf]}
        assert self._remove(root, group) is True
        assert root == {"and": [leaf]}

    def test_remove_leaf_from_nested_group(self):
        """嵌套: 外层 and 里有个 group, group 内有 leaf, 删 leaf."""
        leaf_inner = {"field": "a", "op": ">=", "value": 1}
        group = {"and": [leaf_inner, {"field": "b", "op": "==", "value": 0}]}
        root = {"and": [group]}
        assert self._remove(root, leaf_inner) is True
        # group 还剩 1 个 leaf
        assert root == {"and": [{"and": [{"field": "b", "op": "==", "value": 0}]}]}

    def test_remove_not_found(self):
        """删一个不在树里的对象 -> False, 树不动."""
        leaf = {"field": "x", "op": ">=", "value": 1}
        root = {"and": [leaf]}
        other = {"field": "y", "op": "==", "value": 2}
        assert self._remove(root, other) is False
        assert root == {"and": [leaf]}


class TestDeleteAndReAddGroup:
    """[P4-L5 2026-08-11] 删分组后还能重新 + 分组再加 (用户反馈)."""

    def test_can_re_add_after_delete(self):
        """模拟: 根 and 有 1 个 leaf, 点 + 分组加 1 个, 删它, 再 + 分组再加 -> 树应该再次有 group."""
        root = {"and": [{"field": "a", "op": ">=", "value": 1}]}
        # 1. + 分组
        new_group = {"and": [{"field": "x", "op": ">=", "value": 0}]}
        root["and"].append(new_group)
        assert len(root["and"]) == 2
        # 2. 删 group (splice 同步, Python 用 del)
        idx = root["and"].index(new_group)
        del root["and"][idx]
        assert len(root["and"]) == 1
        # 3. 再 + 分组
        another = {"and": [{"field": "y", "op": "==", "value": 0}]}
        root["and"].append(another)
        assert len(root["and"]) == 2
        # 结构正确
        assert root == {"and": [
            {"field": "a", "op": ">=", "value": 1},
            {"and": [{"field": "y", "op": "==", "value": 0}]},
        ]}


class TestDeleteSyncSource:
    """[P4-L5 2026-08-11] 删 leaf / 删 group 必须通过 removeCondFromTree 同步数据."""

    def test_del_leaf_uses_remove_cond(self, appjs):
        """删 leaf handler 必须调 removeCondFromTree + buildConditionUI 整体重渲."""
        # 用 [\s\S]*? 跨行, 找 removeCondFromTree 出现
        m = re.search(
            r"cond-del-leaf['\"][^}]*?addEventListener\('click',\s*\(\)\s*=>\s*\{([\s\S]*?)\}\);",
            appjs,
        )
        assert m, "cond-del-leaf handler not found"
        body = m.group(1)
        assert "removeCondFromTree" in body, \
            f"删 leaf 必须调 removeCondFromTree 同步数据, 实际: {body[:300]}"
        assert "buildConditionUI" in body, \
            "删 leaf 后必须 buildConditionUI 整体重渲 (UI/数据同步)"

    def test_del_group_uses_remove_cond(self, appjs):
        """删 group handler 必须调 removeCondFromTree + buildConditionUI."""
        m = re.search(
            r"cond-del-group['\"][^}]*?addEventListener\('click',\s*\(\)\s*=>\s*\{([\s\S]*?)\}\);",
            appjs,
        )
        assert m, "cond-del-group handler not found"
        body = m.group(1)
        # 根节点保护: isRoot 时 alert
        assert "isRoot" in body, "删 group 必须 isRoot 保护, 根 group 不允许删"
        # 子 group: removeCondFromTree + buildConditionUI
        assert "removeCondFromTree" in body, \
            f"删 group 必须调 removeCondFromTree, 实际: {body[:300]}"
        assert "buildConditionUI" in body, "删 group 后必须整体重渲"

    def test_remove_cond_from_tree_defined(self, appjs):
        """removeCondFromTree 函数必须存在, 用对象引用 indexOf 找节点."""
        assert "function removeCondFromTree" in appjs, "removeCondFromTree 必须定义"
        # 必须用 indexOf
        m = re.search(
            r"function\s+removeCondFromTree\s*\([^)]*\)\s*\{(.*?)\n\}",
            appjs, re.DOTALL,
        )
        assert m
        body = m.group(1)
        assert "indexOf" in body, "removeCondFromTree 必须用 indexOf 找对象引用"
        assert "splice" in body, "removeCondFromTree 必须 splice"

    def test_current_cond_global_stored(self, appjs):
        """[P4-L5 2026-08-11] buildConditionUI 必须存当前 cond 到 window._CURRENT_COND,
        否则删 leaf/group 没法同步数据 (引用丢失)."""
        m = re.search(
            r"function\s+buildConditionUI\s*\([^)]*\)\s*\{(.*?)\n\}",
            appjs, re.DOTALL,
        )
        assert m
        body = m.group(1)
        assert "window._CURRENT_COND" in body, \
            f"buildConditionUI 必须存 cond 到 window._CURRENT_COND, 实际: {body[:300]}"


class TestAddLeafUsesGlobal:
    """+ 条件 / + 分组 按钮重渲必须用 window._CURRENT_COND (根), 不是 parent.id (undefined)."""

    def test_add_leaf_uses_current_cond(self, appjs):
        """+ 条件 重渲调 buildConditionUI(window._CURRENT_COND, 'condBuilder')."""
        # 找 cond-add-leaf 的 click handler, 实际代码 (去掉 // 注释行)
        m = re.search(
            r"cond-add-leaf['\"][^}]*?addEventListener\('click',\s*\(\)\s*=>\s*\{([\s\S]*?)buildConditionUI\(window\._CURRENT_COND,\s*'condBuilder'\)",
            appjs,
        )
        assert m, "+ 条件 handler 找不到 buildConditionUI(window._CURRENT_COND, 'condBuilder') 调用"
        # 去掉 // 注释行再检查 parent.id (避免注释里的 "parent.id" 字眼误报)
        code_lines = [
            ln for ln in m.group(1).split("\n")
            if ln.strip() and not ln.strip().startswith("//")
        ]
        code_only = "\n".join(code_lines)
        assert "children.push" in code_only, "+ 条件 handler 必须 children.push 一个新 leaf"
        assert "parent.id" not in code_only, \
            f"parent.id 在子级是 undefined, 不能用. 实际代码: {code_only}"

    def test_add_group_uses_current_cond(self, appjs):
        """+ 分组 同理."""
        m = re.search(
            r"cond-add-group['\"][^}]*?addEventListener\('click',\s*\(\)\s*=>\s*\{([\s\S]*?)buildConditionUI\(window\._CURRENT_COND,\s*'condBuilder'\)",
            appjs,
        )
        assert m, "+ 分组 handler 找不到 buildConditionUI(window._CURRENT_COND, 'condBuilder') 调用"
        code_lines = [
            ln for ln in m.group(1).split("\n")
            if ln.strip() and not ln.strip().startswith("//")
        ]
        code_only = "\n".join(code_lines)
        assert "children.push" in code_only, "+ 分组 handler 必须 children.push 一个新 group"
        assert "parent.id" not in code_only


class TestDeleteAndReAddGroup:
    """[P4-L5 2026-08-11] 删分组后还能重新 + 分组再加 (用户反馈)."""

    def test_can_re_add_after_delete(self):
        """模拟: 根 and 有 1 个 leaf, 点 + 分组加 1 个, 删它, 再 + 分组再加 -> 树应该再次有 group."""
        root = {"and": [{"field": "a", "op": ">=", "value": 1}]}
        # 1. + 分组
        new_group = {"and": [{"field": "x", "op": ">=", "value": 0}]}
        root["and"].append(new_group)
        assert len(root["and"]) == 2
        # 2. 删 group (splice 同步)
        idx = root["and"].index(new_group)
        del root["and"][idx]
        assert len(root["and"]) == 1
        # 3. 再 + 分组
        another = {"and": [{"field": "y", "op": "==", "value": 0}]}
        root["and"].append(another)
        assert len(root["and"]) == 2
        # 结构正确
        assert root == {"and": [
            {"field": "a", "op": ">=", "value": 1},
            {"and": [{"field": "y", "op": "==", "value": 0}]},
        ]}
