"""
一条龙命令测试 (P4-L4 2026-08-08)
- 验证 scripts/one_command.py 结构 (6 步 + 3 个跳过选项)
- 不实际跑 (避免破坏 DB)
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "one_command.py"


class TestOneCommandStructure:
    """一条龙命令的 6 步结构必须保持完整"""

    def test_script_exists(self):
        assert SCRIPT.exists(), "one_command.py 必须存在"

    def test_has_6_steps(self):
        """6 个 step 函数: reset_db / risk_users / train_dataset / train_xgboost / backfill_ml_score / business_today"""
        src = SCRIPT.read_text(encoding="utf-8")
        for step in ["step_1_reset_db", "step_2_risk_users", "step_3_train_dataset",
                     "step_4_train_xgboost", "step_5_backfill_ml_score", "step_6_business_today"]:
            assert f"def {step}(" in src, f"缺步骤函数: {step}"

    def test_steps_call_real_scripts(self):
        """每个 step 必须调真实脚本 (不是 mock)"""
        src = SCRIPT.read_text(encoding="utf-8")
        # 6 个 step 各调一个真实脚本
        assert "init_db.py" in src, "step 1 调 init_db.py"
        assert "gen_risky_users.py" in src, "step 2 调 gen_risky_users.py"
        assert "gen_train_dataset.py" in src, "step 3 调 gen_train_dataset.py (新训练数据集)"
        assert "train_xgb_model.py" in src, "step 4 调 train_xgb_model.py"
        assert "backfill_ml_score.py" in src, "step 5 调 backfill_ml_score.py (新回填脚本)"
        assert "gen_risk_data_with_dates.py" in src, "step 6 调 gen_risk_data_with_dates.py (今日业务数据)"

    def test_step_3_uses_reset_flag(self):
        """步骤 3 必须用 --reset (清表后重造训练数据)"""
        src = SCRIPT.read_text(encoding="utf-8")
        # 找 step_3_train_dataset 函数
        m = re.search(r"def step_3_train_dataset.*?(?=\ndef )", src, re.DOTALL)
        assert m, "找不到 step_3_train_dataset"
        assert "--reset" in m.group(0), "步骤 3 必须加 --reset"

    def test_step_4_no_extra_args(self):
        """步骤 4 训练用默认参数 (脚本内部会读 config.py + 校验数据)"""
        src = SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"def step_4_train_xgboost.*?(?=\ndef )", src, re.DOTALL)
        assert m, "找不到 step_4_train_xgboost"
        # 训练不能随便传 --reset (没这个 flag)
        assert "--reset" not in m.group(0) or "不传" in m.group(0)

    def test_step_6_uses_live_for_dashboard(self):
        """步骤 6 用 --live (不回写 create_time, 仪表盘"今日"能看到)"""
        src = SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"def step_6_business_today.*?(?=\ndef )", src, re.DOTALL)
        assert m, "找不到 step_6_business_today"
        assert "--live" in m.group(0), "步骤 6 必须加 --live (仪表盘可见)"


class TestOneCommandSkipOptions:
    """3 个跳过选项: --skip-init / --skip-train / --only-start"""

    def test_has_skip_init_option(self):
        """--skip-init: 跳过 1+2"""
        src = SCRIPT.read_text(encoding="utf-8")
        assert '"--skip-init"' in src or "'--skip-init'" in src
        # 实际跳过 step 1+2
        assert "args.skip_init" in src
        m = re.search(r'if not args\.skip_init:(.*?)(?=\n\s+if not args\.skip_train)', src, re.DOTALL)
        assert m, "skip-init 必须跳过 1+2"
        skip_text = m.group(0)
        assert "step_1_reset_db" in skip_text
        assert "step_2_risk_users" in skip_text

    def test_has_skip_train_option(self):
        """--skip-train: 跳过 3+4+5"""
        src = SCRIPT.read_text(encoding="utf-8")
        assert '"--skip-train"' in src or "'--skip-train'" in src
        assert "args.skip_train" in src
        m = re.search(r'if not args\.skip_train:(.*?)(?=\n\s+step_6)', src, re.DOTALL)
        assert m, "skip-train 必须跳过 3+4+5"
        skip_text = m.group(0)
        assert "step_3_train_dataset" in skip_text
        assert "step_4_train_xgboost" in skip_text
        assert "step_5_backfill_ml_score" in skip_text

    def test_has_only_start_option(self):
        """--only-start: 只跑步骤 6"""
        src = SCRIPT.read_text(encoding="utf-8")
        assert '"--only-start"' in src or "'--only-start'" in src
        assert "args.only_start" in src
        # only-start 应该只调 step 6
        m = re.search(r'if args\.only_start:(.*?)(?=\s+else:)', src, re.DOTALL)
        assert m, "only-start 必须存在"
        assert "step_6_business_today" in m.group(0)


class TestOneCommandErrorHandling:
    """错误处理: 子进程失败要抛 RuntimeError 并打印排查建议"""

    def test_subprocess_failure_raises(self):
        """子进程 returncode != 0 抛 RuntimeError"""
        src = SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"def _run_subprocess.*?(?=\ndef )", src, re.DOTALL)
        assert m, "找不到 _run_subprocess"
        assert "RuntimeError" in m.group(0)

    def test_main_catches_runtime_error(self):
        """main() 必须 try/except RuntimeError 友好提示"""
        src = SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"def main.*?(?=\nif __name__)", src, re.DOTALL)
        assert m, "找不到 main"
        assert "except RuntimeError" in m.group(0)
        assert "排查建议" in m.group(0) or "MySQL" in m.group(0), "应有排查建议提示"

    def test_prints_next_step_after_success(self):
        """成功后打印"下一步: python run_app.py" 提示"""
        src = SCRIPT.read_text(encoding="utf-8")
        assert "python run_app.py" in src, "应提示下一步: python run_app.py"


class TestOneCommandDocumentation:
    """docstring 跟 6 步工作流一致"""

    def test_docstring_lists_all_six_steps(self):
        src = SCRIPT.read_text(encoding="utf-8")
        # docstring 里应提到 6 步
        m = re.search(r'"""(.*?)"""', src, re.DOTALL)
        assert m, "缺模块 docstring"
        doc = m.group(1)
        for step_num, step_name in [
            ("1", "重置"),
            ("2", "RISK"),
            ("3", "1500"),
            ("4", "训练"),
            ("5", "回填"),
            ("6", "业务"),
        ]:
            assert step_num in doc and step_name in doc, (
                f"docstring 应提到步骤 {step_num} ({step_name})"
            )
