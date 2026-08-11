"""
【P4-L3 2026-08-08 第三轮】gen_risk_data_with_dates.py --balance-pos / --target-pos-ratio 测试.

真实场景: 用户问"python scripts/gen_risk_data_with_dates.py --days 30 --per-day 200
生成的数据正负例比例确定了吗?" — 答案是: 完全 NOT 确定 (默认正例 ≈ 2%).

修法: 给 gen_risk_data_with_dates.py 加 --balance-pos / --target-pos-ratio 参数,
跟 gen_risk_data.py 行为一致, 强制控制正例比例.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "gen_risk_data_with_dates.py"


class TestGenRiskDataWithDatesCLI:
    """scripts/gen_risk_data_with_dates.py 的 CLI 参数."""

    def test_script_accepts_balance_pos_argument(self):
        """必须接受 --balance-pos 参数 (跟 gen_risk_data.py 对齐)."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True, timeout=10,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        assert "--balance-pos" in stdout, f"--help 应含 --balance-pos, 实际: {stdout[:500]}"
        import re
        assert re.search(r"--balance-pos\s+\S", stdout), "--balance-pos 应有描述"

    def test_script_accepts_target_pos_ratio_argument(self):
        """必须接受 --target-pos-ratio 参数 (跟 gen_risk_data.py 对齐)."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True, timeout=10,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        assert "--target-pos-ratio" in stdout, f"--help 应含 --target-pos-ratio, 实际: {stdout[:500]}"
        import re
        assert re.search(r"--target-pos-ratio\s+\S", stdout), "--target-pos-ratio 应有描述"

    def test_existing_arguments_still_present(self):
        """原有参数 (--days / --per-day / --clean 等) 仍然存在, 没破坏向后兼容."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True, timeout=10,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        for arg in ["--days", "--per-day", "--max-per-day", "--clean", "--start", "--end"]:
            assert arg in stdout, f"--help 应保留 {arg} 参数, 实际: {stdout[:500]}"

    def test_script_accepts_live_argument(self):
        """必须接受 --live 参数 (不回写 create_time, 适合 demo 仪表盘)."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True, timeout=10,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        assert "--live" in stdout, f"--help 应含 --live, 实际: {stdout[:500]}"
        import re
        assert re.search(r"--live\s+\S", stdout), "--live 应有描述"

    def test_script_accepts_force_pos_ratio_argument(self):
        """必须接受 --force-pos-ratio 参数 (强制正例比例, retry 机制保证精度)."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--help"],
            capture_output=True, timeout=10,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        assert "--force-pos-ratio" in stdout, f"--help 应含 --force-pos-ratio, 实际: {stdout[:500]}"
        import re
        assert re.search(r"--force-pos-ratio\s+\S", stdout), "--force-pos-ratio 应有描述"


class TestGenRiskDataForcedPosLogic:
    """--force-pos-ratio 配套函数 + 逻辑验证."""

    def test_force_pos_pickers_defined(self):
        """3 个高风险 picker 必须存在: 退改签 / 行程投诉 / 高额订单."""
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # 3 个 _pick_forced_* 函数
        assert "_pick_forced_postsale" in script, "必须有 _pick_forced_postsale (RISK 退改签)"
        assert "_pick_forced_logistics_complaint" in script, "必须有 _pick_forced_logistics_complaint (行程投诉)"
        assert "_pick_forced_order_for_high_amount" in script, "必须有 _pick_forced_order_for_high_amount (高额订单)"

    def test_force_pos_retry_logic(self):
        """--force-pos-ratio 必须有 retry 机制 (max_tries > 1, 决策没触发就换 picker)."""
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # max_tries 变量
        assert "max_tries" in script, "必须用 max_tries 控制 retry 次数"
        # max_tries = 3 if use_force_pos else 1
        assert "3 if use_force_pos else 1" in script, "force 模式 max_tries=3, 普通模式 max_tries=1"
        # pickers 列表 3 个高风险
        assert "_pick_forced_postsale" in script and "_pick_forced_logistics_complaint" in script, (
            "force 模式 picker 列表应包含 3 个高风险 picker"
        )

    def test_stdout_reconfigure_for_emoji(self):
        """【P4-L3 2026-08-08 修复】Windows GBK 终端不能编码 emoji, 必须 reconfigure UTF-8.

        真实 bug: 之前脚本用 🎯🎯 等 emoji 提示, Windows GBK 终端报
        UnicodeEncodeError: 'gbk' codec can't encode character '\\U0001f3af'.
        修法: 脚本开头调用 sys.stdout.reconfigure(encoding="utf-8").
        """
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # 必须有 sys.stdout.reconfigure(encoding="utf-8")
        assert "sys.stdout.reconfigure(encoding=\"utf-8\")" in script, (
            "必须 sys.stdout.reconfigure(encoding='utf-8') 防 Windows GBK 编码 emoji 报错"
        )

    def test_no_decision_hit_reference_after_retry_removal(self):
        """【P4-L3 2026-08-08 修复回归】删除 retry 兜底代码里残留的 decision_hit 引用.

        真实 bug: 之前删除 decision_hit 变量时, 兜底 if 块里还有
        `if use_force_pos and not decision_hit and not success_done:`
        导致 NameError. 修法: 删掉残留引用 + 留注释说明.
        """
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # 去掉注释
        import re
        code_lines = [l for l in script.splitlines() if not l.strip().startswith("#")]
        code = "\n".join(code_lines)
        assert "decision_hit" not in code, (
            "代码里还有 'decision_hit' 引用 (变量已删), 会报 NameError"
        )


class TestGenRiskDataWithDatesLogic:
    """--balance-pos 跟 --target-pos-ratio 函数行为."""

    def test_balance_pos_uses_risky_user_prefix(self):
        """--balance-pos 模式必须用 RISK 前缀查 RISK 高风险用户."""
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # 必须定义 RISKY_USER_PREFIX = "RISK" 常量
        assert 'RISKY_USER_PREFIX = "RISK"' in script or "RISKY_USER_PREFIX='RISK'" in script, (
            "必须定义 RISKY_USER_PREFIX 常量 (跟 gen_risk_data.py 对齐)"
        )
        # _pick_order_for_balance / _pick_postsale_for_balance 函数必须存在
        assert "_pick_order_for_balance" in script, "必须有 _pick_order_for_balance 函数"
        assert "_pick_postsale_for_balance" in script, "必须有 _pick_postsale_for_balance 函数"
        # 必须用 LIKE 'RISK%' 查 RISK 用户
        assert "user_id LIKE :prefix" in script, "必须用 LIKE :prefix 查 RISK 用户"

    def test_positive_counting_logic(self):
        """正例统计: 决策是'拒绝'或'人工审核' = 正例, 必须用 grand_positive 累加."""
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # 必须有 grand_positive 计数器
        assert "grand_positive" in script, "必须有 grand_positive 正例累加器"
        # 决策判断
        assert '"拒绝"' in script or "'拒绝'" in script, "必须判断'拒绝'决策"
        assert '"人工审核"' in script or "'人工审核'" in script, "必须判断'人工审核'决策"

    def test_target_pos_ratio_warning(self):
        """--target-pos-ratio 模式: 跑完必须提示用户正例比例, 低于 15% 警告."""
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # 必须有整体正例比例计算
        assert "overall_pos" in script or "grand_positive" in script, (
            "必须计算整体正例比例, 提示用户"
        )
        # 完成时如果 < 15% 警告
        assert "正例比例" in script, "完成时必须显示正例比例"

    def test_no_early_break_in_day_loop(self):
        """【P4-L3 2026-08-08 第四轮 修复回归】for day_offset 循环不能在单轮模式 (target_pos_ratio=None) 时 break.

        真实 bug: 之前在 for day_offset in range(total_days) 里有个
        `if target_pos_ratio is None: break`, 导致单轮模式跑 1 天就退出,
        --per-day 200 只造 1 条. 现在已删, 验证回归.
        """
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        # 去掉注释 (避免匹配注释里的代码片段)
        import re
        # 删 # 开头的行
        code_lines = [l for l in script.splitlines() if not l.strip().startswith("#")]
        code = "\n".join(code_lines)
        # 找原 bug pattern: `if target_pos_ratio is None:` 后面 3 行内 break
        pattern = re.compile(
            r"if target_pos_ratio is None:.*?(?:\n\s+.*?){0,3}?break",
            re.DOTALL,
        )
        matches = pattern.findall(code)
        assert not matches, (
            f"原 bug pattern 还在! `if target_pos_ratio is None: ... break` 会导致单轮模式只造 1 条. "
            f"匹配: {matches[:200]}"
        )

