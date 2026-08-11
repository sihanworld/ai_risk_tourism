"""
通用分页组件测试 (P4-L4 2026-08-08)
- 验证 app.js 里的 buildPaginationHtml 在各种场景下行为正确
- 用 node.js 在 sub-process 跑 JS (项目纯 Python 后端, 没有 JS 运行时)
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"

_NODE = shutil.which("node")


def _run_js(expr: str) -> str:
    """跑 JS 表达式, 返回 stdout 字符串.

    用 node.js 评估 buildPaginationHtml 函数.
    """
    if not _NODE:
        pytest.skip("node.js 未安装, 跳过 JS 运行时测试")
    # 包一层: 加载 app.js, 移除 module 包装, 然后 eval 表达式
    js_code = (
        "const window = {}; const document = {getElementById: () => ({innerHTML: ''})};\n"
        + APP_JS.read_text(encoding="utf-8")
        + "\nresult = eval(" + json.dumps(expr) + ");\n"
        + "process.stdout.write(result || '');\n"
    )
    r = subprocess.run(
        [_NODE, "-e", js_code],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError(f"node.js 失败: {r.stderr}")
    return r.stdout


class TestBuildPaginationHtml:
    """通用分页组件 - 各种场景"""

    def test_total_pages_1_renders_placeholder(self):
        """totalPages=1 也渲染占位 (上一页[1]下一页 3 个按钮), 防底栏空白错觉"""
        out = _run_js("buildPaginationHtml(1, 1, 20, 'loadX')")
        # 不应该是空字符串 (改前是 '', 改后必须有内容)
        assert out != "", f"1 页应渲染占位分页栏, 实际: {out!r}"
        # 包含页码 1 (激活状态)
        assert 'active' in out, f"应有 active 页码, 实际: {out!r}"
        assert 'loadX(1)' in out
        # 上一页 + 下一页 都 disabled
        assert out.count('disabled') >= 2, f"1 页时上下页都应 disabled, 实际: {out!r}"
        # 1 页时不应有省略号
        assert '...' not in out, f"1 页不应有省略号, 实际: {out!r}"
        # 1 页时不应有 »» 末页快捷跳
        assert '»»' not in out, f"1 页不应有末页快捷跳, 实际: {out!r}"

    def test_total_pages_0_renders_empty_placeholder(self):
        """【P4-L4 2026-08-08v2】totalPages=0 (无数据) 渲染"暂无数据"占位条, 不再空白"""
        out = _run_js("buildPaginationHtml(1, 0, 20, 'loadX')")
        # 不应该是空字符串 (改前是 '', 改后必须有"暂无数据"占位)
        assert out != "", f"0 页 (无数据) 应渲染'暂无数据'占位, 实际: {out!r}"
        # 必须含 "暂无数据" 字样
        assert "暂无数据" in out, f"应显示'暂无数据'占位, 实际: {out!r}"
        # 必须是 disabled (不可点击)
        assert "disabled" in out, f"占位条应 disabled, 实际: {out!r}"

    def test_total_pages_2_shows_all(self):
        """totalPages=2 直接显示所有 (无需省略号)"""
        out = _run_js("buildPaginationHtml(1, 2, 20, 'loadX')")
        assert "loadX(1)" in out, "应有上一页"
        assert "loadX(2)" in out, "应有下一页"
        # 总共 4 个 li (上/2 个页码/下), 不应包含 ...
        assert "..." not in out, "2 页不应有省略号"

    def test_pagination_uses_compact_single_char_buttons(self):
        """P4-L4 2026-08-08 第二轮: 按钮改单字符 «»›› (紧凑版)"""
        out_2 = _run_js("buildPaginationHtml(1, 2, 20, 'loadX')")
        out_50 = _run_js("buildPaginationHtml(20, 50, 20, 'loadX')")
        # 上一页 = « (单字符), 不再用 "« 上一页"
        assert "« 上一页" not in out_2 and "« 上一页" not in out_50, f"应改用单字符, 实际: {out_50!r}"
        # 下一页 = » (单字符)
        assert "下一页 »" not in out_2 and "下一页 »" not in out_50, f"应改用单字符, 实际: {out_50!r}"
        # 末页快捷跳 = ›› (单字符), 不再用 »»
        assert "»»" not in out_50, f"应改用单字符 ››, 实际: {out_50!r}"
        assert "››" in out_50, f"应有 ›› 末页快捷跳, 实际: {out_50!r}"

    def test_total_pages_7_shows_all_no_ellipsis(self):
        """totalPages=7 (临界值) 直接显示所有"""
        out = _run_js("buildPaginationHtml(4, 7, 20, 'loadX')")
        # 7 个页码都显示
        for i in range(1, 8):
            assert f"loadX({i})" in out, f"应有页码 {i}"
        # 没有 ...
        assert "..." not in out

    def test_total_pages_10_middle_shows_ellipsis_both_sides(self):
        """totalPages=10, currentPage=5, 左右都显示 ..."""
        out = _run_js("buildPaginationHtml(5, 10, 20, 'loadX')")
        # 始终显示首页 1 + 末页 10
        assert "loadX(1)" in out
        assert "loadX(10)" in out
        # 中间页 3 4 5 6 7 (currentPage ± 2)
        for i in [3, 4, 5, 6, 7]:
            assert f"loadX({i})" in out, f"应有中间页 {i}"
        # currentPage > 4, 左边有 ...
        # currentPage < 10-3=7, 右边有 ...
        assert out.count("...") >= 2, f"应有 2 个省略号, 实际: {out!r}"

    def test_total_pages_10_current_2_left_ellipsis_only(self):
        """totalPages=10, currentPage=2, 只有左边 ..."""
        out = _run_js("buildPaginationHtml(2, 10, 20, 'loadX')")
        # 首页 1 + 末页 10
        assert "loadX(1)" in out
        assert "loadX(10)" in out
        # currentPage=2, 中间页: max(2,0)=2 .. min(9,4)=4, 即 2 3 4
        for i in [2, 3, 4]:
            assert f"loadX({i})" in out
        # currentPage < 7, 右边有 ..., 共 1 个
        assert out.count("...") == 1, f"应有 1 个省略号, 实际: {out!r}"

    def test_total_pages_10_current_9_right_ellipsis_only(self):
        """totalPages=10, currentPage=9, 只有右边 ..."""
        out = _run_js("buildPaginationHtml(9, 10, 20, 'loadX')")
        # currentPage=9, 中间页: max(2,7)=7 .. min(9,11)=9, 即 7 8 9
        for i in [7, 8, 9]:
            assert f"loadX({i})" in out
        # currentPage > 4, 左边有 ..., 共 1 个
        assert out.count("...") == 1, f"应有 1 个省略号, 实际: {out!r}"

    def test_ellipsis_click_jumps_5_pages(self):
        """点击 ... 应该跳 ±3 页 (避免点击无意义, 但也别跳太远)"""
        # totalPages=50, currentPage=20
        # 左边 ... 跳到 currentPage-3=17
        # 右边 ... 跳到 currentPage+3=23
        out = _run_js("buildPaginationHtml(20, 50, 20, 'loadX')")
        # 提取所有 onclick 跳页码 (按出现顺序)
        import re
        # 用更宽松的正则: onclick="loadX(N);return false;..." 后面可能有其他属性
        onclick_pattern = re.compile(r'onclick="loadX\((\d+)\)[^"]*"')
        jumps = [int(m.group(1)) for m in onclick_pattern.finditer(out)]
        # 17 和 23 都在 jumps 里 (跳页数)
        assert 17 in jumps, f"左边 ... 应跳到 17, 实际 jumps={jumps}"
        assert 23 in jumps, f"右边 ... 应跳到 23, 实际 jumps={jumps}"

    def test_large_total_shows_end_jump_button(self):
        """totalPages > 10 时显示 ›› 末页快捷跳"""
        out = _run_js("buildPaginationHtml(1, 50, 20, 'loadX')")
        # ›› 跳到第 50 页
        assert "››" in out, f"应有 ›› 末页快捷跳, 实际: {out!r}"
        assert "loadX(50)" in out

    def test_uses_callable_name_in_onclick(self):
        """onclick 里的函数名应该是 loadFnName 参数 (默认 'loadX')"""
        out = _run_js("buildPaginationHtml(3, 20, 20, 'myLoadFn')")
        # 全部 onclick 应该用 myLoadFn
        assert "myLoadFn(" in out
        # 不应该用其他函数名
        assert "loadAssessments(" not in out
        assert "loadCases(" not in out
