"""
base.html 布局单测 (P4-L4 2026-08-08)
- 验证关键 CSS 规则存在 (左侧 fixed + 右侧独立滚动)
- 防止以后改 base.html 误删布局相关 CSS
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASE_HTML = ROOT / "templates" / "base.html"


@pytest.fixture(scope="module")
def base_html() -> str:
    return BASE_HTML.read_text(encoding="utf-8")


class TestBaseLayout:
    """P4-L4 2026-08-08: 左侧 fixed + 右侧独立滚动"""

    def test_body_height_and_overflow_hidden(self, base_html):
        """body 必为 100% + overflow: hidden (body 不滚)"""
        assert re.search(r"body\s*\{[^}]*height:\s*100%", base_html), "body 高度应 100%"
        assert re.search(r"body\s*\{[^}]*overflow:\s*hidden", base_html), "body 应 overflow:hidden"

    def test_sidebar_position_fixed(self, base_html):
        """sidebar 必为 position: fixed (脱离文档流)"""
        assert re.search(
            r"\.sidebar\s*\{[^}]*position:\s*fixed", base_html
        ), "sidebar 应 position:fixed"
        # 关键: width 16.66667% (col-md-2 等宽) + top:0/left:0/bottom:0
        assert "left: 0" in base_html or "left:0" in base_html
        assert "top: 0" in base_html or "top:0" in base_html
        assert "bottom: 0" in base_html or "bottom:0" in base_html
        assert "16.66667%" in base_html, "sidebar 宽度应 16.66667% (col-md-2)"

    def test_sidebar_overflow_auto(self, base_html):
        """sidebar 自身 overflow-y: auto (内容多时自己滚, 不影响 body)"""
        assert re.search(
            r"\.sidebar\s*\{[^}]*overflow-y:\s*auto", base_html
        ), "sidebar 应 overflow-y:auto"

    def test_main_content_height_100vh_and_overflow(self, base_html):
        """main-content 必为 height: 100vh + overflow-y: auto (右侧独立滚动)"""
        m = re.search(r"\.main-content\s*\{([^}]*)\}", base_html)
        assert m, "找不到 .main-content CSS 块"
        css = m.group(1)
        assert "height: 100vh" in css, "main-content 应 height:100vh"
        assert "overflow-y: auto" in css, "main-content 应 overflow-y:auto (独立滚动)"
        # 【P4-L4 第二轮修复 2026-08-08】必须 margin-left 避开 fixed sidebar, 否则内容被盖住
        assert "margin-left: 16.66667%" in css, (
            "main-content 必须 margin-left:16.66667% 避开 fixed sidebar, "
            "否则内容会被左侧 16.67% 区域盖住"
        )

    def test_responsive_mobile_layout(self, base_html):
        """响应式: 窄屏 (md 以下) 恢复流式布局, 左侧不再 fixed"""
        # 找 @media 块
        m = re.search(
            r"@media\s*\(\s*max-width:\s*767\.98px\s*\)\s*\{(.+?)\}\s*</style>",
            base_html, re.DOTALL,
        )
        assert m, "找不到 @media 响应式块 (max-width: 767.98px)"
        css = m.group(1)
        # 响应式里 sidebar 应 position: relative (不再 fixed)
        assert re.search(r"\.sidebar\s*\{[^}]*position:\s*relative", css), \
            "响应式内 sidebar 应 position:relative"
        # main-content 应 margin-left: 0
        assert re.search(r"\.main-content\s*\{[^}]*margin-left:\s*0", css), \
            "响应式内 main-content 应 margin-left:0"

    def test_pagination_bottom_sticky(self, base_html):
        """【P4-L4 2026-08-08 修复】分页栏必须 sticky 粘在底部, 滚动时一直可见.

        之前问题: .main-content { height: 100vh; overflow-y: auto } 把分页栏
        推到滚动到底才看得到, 用户没滚到底就以为没分页. 现在 .pagination-bottom
        用 position: sticky 粘在底部.
        """
        # 找 .pagination-bottom 块
        m = re.search(r"\.pagination-bottom\s*\{([^}]*)\}", base_html)
        assert m, "找不到 .pagination-bottom CSS 块 (分页栏粘底样式)"
        css = m.group(1)
        assert "position: sticky" in css, ".pagination-bottom 应 position:sticky (粘在底部)"
        assert "bottom: 0" in css, ".pagination-bottom 应 bottom:0 (贴在底部)"

    def test_pagination_button_text_visible(self, base_html):
        """【P4-L4 2026-08-08 修复】分页按钮文字必须可见 (颜色 + display + 高度).

        之前问题: 用户只看到"一个窗口"但没有数字 - 因为某种原因数字被压成 0
        高度或颜色被覆盖. 现在显式设置:
          - .pagination: display: flex (让 li 排成行)
          - .page-link: 显式 color + background + font-size + min-width
          - .page-item.active: 高亮当前页
        """
        # 1. .pagination 块必须有 display: flex
        m = re.search(r"\.pagination-bottom\s+\.pagination\s*\{([^}]*)\}", base_html)
        assert m, "找不到 .pagination-bottom .pagination CSS 块"
        css = m.group(1)
        assert "display: flex" in css, ".pagination-bottom .pagination 应 display:flex (li 排成行)"

        # 2. .page-link 块必须有显式 color
        m = re.search(r"\.pagination-bottom\s+\.page-item\s+\.page-link\s*\{([^}]*)\}", base_html)
        assert m, "找不到 .pagination-bottom .page-item .page-link CSS 块"
        css = m.group(1)
        assert "color:" in css, ".page-link 应有显式 color (防白色字白底)"
        assert "background:" in css, ".page-link 应有显式 background"
        assert "min-width" in css, ".page-link 应有 min-width (数字按钮宽度)"

        # 3. .page-item.active 块必须有高亮色
        m = re.search(r"\.pagination-bottom\s+\.page-item\.active\s+\.page-link\s*\{([^}]*)\}", base_html)
        assert m, "找不到 .page-item.active 块 (高亮当前页)"

    def test_cases_and_assessments_use_pagination_bottom_class(self):
        """cases.html / assessments.html 必须用 .pagination-bottom class (分页栏粘底)."""
        cases_html = (ROOT / "templates" / "cases.html").read_text(encoding="utf-8")
        assess_html = (ROOT / "templates" / "assessments.html").read_text(encoding="utf-8")
        assert 'class="pagination-bottom"' in cases_html, (
            "cases.html 必须用 class='pagination-bottom' 让分页栏粘在底部"
        )
        assert 'class="pagination-bottom"' in assess_html, (
            "assessments.html 必须用 class='pagination-bottom' 让分页栏粘在底部"
        )

    def test_cases_and_assessments_use_shared_pagination_component(self):
        """【P4-L4 2026-08-08】cases / assessments 必须共用 buildPaginationHtml 通用分页组件.

        锁住一致性: 两边都用 ul#pagination + buildPaginationHtml(currentPage,totalPages,pageSize,loadFn).
        以后改一边忘改另一边会被这个测试拦下.
        """
        cases_html = (ROOT / "templates" / "cases.html").read_text(encoding="utf-8")
        assess_html = (ROOT / "templates" / "assessments.html").read_text(encoding="utf-8")

        for name, html, load_fn in [
            ("cases", cases_html, "loadCases"),
            ("assessments", assess_html, "loadAssessments"),
        ]:
            assert 'id="pagination"' in html, f"{name}.html 必须有 ul#pagination 容器"
            # 必须调用 buildPaginationHtml, 不能自己手写页码 HTML
            assert "buildPaginationHtml(" in html, (
                f"{name}.html 必须调 buildPaginationHtml 通用分页组件 (禁止内联手写)"
            )
            # 必须传入 loadFnName 作为字符串参数 (loadCases / loadAssessments)
            # 注: buildPaginationHtml 是多行调用, 直接匹配字面字符串
            assert f"'{load_fn}'" in html, (
                f"{name}.html 必须把 '{load_fn}' 作为 loadFnName 传给 buildPaginationHtml"
            )

    def test_all_list_pages_use_shared_pagination(self):
        """【P4-L4 2026-08-08v2】4 个列表页 (cases/assessments/rules/blacklist) 必须都用 buildPaginationHtml.

        用户反馈: "案件管理/规则管理/黑名单的分页栏还是没有显示".
        根因: 不是代码问题, 是浏览器缓存. 4 页面代码层面已统一, 用这个测试锁住.
        """
        pages = [
            ("cases", "cases.html", "loadCases"),
            ("assessments", "assessments.html", "loadAssessments"),
            ("rules", "rules.html", "loadRules"),
            ("blacklist", "blacklist.html", "loadList"),
        ]
        for name, fname, load_fn in pages:
            html = (ROOT / "templates" / fname).read_text(encoding="utf-8")
            # 1. 必须用 .pagination-bottom 容器 (CSS 粘底 + 紧凑样式)
            assert 'class="pagination-bottom"' in html, (
                f"{fname} 必须用 class='pagination-bottom' (CSS 粘底 + 紧凑分页栏)"
            )
            # 2. 必须有 ul#pagination
            assert 'id="pagination"' in html, f"{fname} 必须有 ul#pagination 容器"
            # 3. 必须调 buildPaginationHtml 通用组件
            assert "buildPaginationHtml(" in html, (
                f"{fname} 必须调 buildPaginationHtml 通用组件"
            )
            # 4. 必须传正确的 loadFnName
            assert f"'{load_fn}'" in html, (
                f"{fname} 必须传 '{load_fn}' 作为 loadFnName"
            )

    def test_sidebar_html_structure(self, base_html):
        """侧边栏 HTML 必含 7 个 nav-link (仪表盘/规则/案件/评估/风险检查/AI/黑名单)"""
        nav_block = re.search(
            r'<nav class="nav flex-column[^"]*">(.*?)</nav>', base_html, re.DOTALL,
        )
        assert nav_block, "找不到侧边栏 <nav>"
        nav_html = nav_block.group(1)
        # 7 个 nav-link
        assert nav_html.count('class="nav-link') == 7, \
            f"侧边栏应有 7 个 nav-link, 实际 {nav_html.count('class=\"nav-link')}"
        # 关键页面
        for path in ["/", "/rules", "/cases", "/assessments", "/risk-check", "/chat", "/blacklist"]:
            assert f'href="{path}"' in nav_html, f"侧边栏应含 {path} 链接"

    def test_main_content_html_structure(self, base_html):
        """主内容区 HTML 用 col-md-10 + main-content class (兼容 Bootstrap grid)"""
        assert re.search(
            r'<div\s+class="col-md-10\s+main-content">', base_html
        ), "主内容区应是 <div class=\"col-md-10 main-content\">"
