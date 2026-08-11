"""
旅游风控系统 - 一条龙命令 (P4-L4 2026-08-08)
从零开始, 一键完成所有准备 + 训练, 最后启动 Web 服务.

【工作流 6 步】
  1. 重置数据库 (init_db.py --reset --yes, 含 30 条规则)
  2. 造 30 个 RISK 高风险用户 (gen_risky_users.py --count 30)
  3. 造 1500 条强标注训练数据 (gen_train_dataset.py --reset, ml_score=NULL)
  4. 训练 XGBoost 模型 (train_xgb_model.py)
  5. 回填 ml_score 字段 (backfill_ml_score.py, 用训好的模型推理)
  6. 造 50 条今日业务数据 (gen_risk_data_with_dates.py --days 1 --per-day 50 --live)

【用法】
  python scripts/one_command.py                # 跑全部 6 步
  python scripts/one_command.py --skip-init     # 跳过 1+2, 假设 DB 和 RISK 用户已就绪
  python scripts/one_command.py --skip-train    # 跳过 3+4+5, 假设训练数据 + 模型已就绪
  python scripts/one_command.py --only-start    # 只跑第 6 步 + 启动服务
"""
import argparse
import asyncio
import os
import subprocess
import sys

# UTF-8 stdout (Windows GBK 兼容)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 项目根目录 (one_command.py 所在目录的父目录)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


def _run_subprocess(label: str, cmd: list[str], cwd: str = None) -> int:
    """跑一个子进程, 实时打印 stdout/stderr, 失败抛 RuntimeError.

    Args:
        label: 步骤名 (打印用)
        cmd: 命令 list (跟 subprocess.run 一致)
        cwd: 工作目录

    Returns:
        returncode
    """
    print(f"\n{'=' * 70}")
    print(f"[{label}] {' '.join(cmd)}")
    print(f"{'=' * 70}")
    result = subprocess.run(cmd, cwd=cwd or ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"[{label}] 失败, returncode={result.returncode}")
    print(f"[{label}] OK")
    return result.returncode


def step_1_reset_db() -> None:
    """步骤 1: 重置数据库 (--reset --yes 自动确认)."""
    _run_subprocess(
        "1/6 重置数据库 (init_db.py --reset --yes)",
        [sys.executable, os.path.join(SCRIPTS, "init_db.py"), "--reset", "--yes"],
    )


def step_2_risk_users() -> None:
    """步骤 2: 造 30 个 RISK 高风险用户 (5 模式 × 6 套)."""
    _run_subprocess(
        "2/6 造 30 个 RISK 用户 (gen_risky_users.py --count 30)",
        [sys.executable, os.path.join(SCRIPTS, "gen_risky_users.py"), "--count", "30"],
    )


def step_3_train_dataset() -> None:
    """步骤 3: 造 1500 条强标注训练数据 (30 RISK + 30 普通 × 25, ml_score=NULL)."""
    _run_subprocess(
        "3/6 造 1500 条强标注训练数据 (gen_train_dataset.py --reset)",
        [sys.executable, os.path.join(SCRIPTS, "gen_train_dataset.py"), "--reset"],
    )


def step_4_train_xgboost() -> None:
    """步骤 4: 训练 XGBoost 模型 (val_auc / val_f1 / best_iter)."""
    _run_subprocess(
        "4/6 训练 XGBoost 模型 (train_xgb_model.py)",
        [sys.executable, os.path.join(SCRIPTS, "train_xgb_model.py")],
    )


def step_5_backfill_ml_score() -> None:
    """步骤 5: 用训好的 XGBoost 推理回填 risk_assessment.ml_score."""
    _run_subprocess(
        "5/6 回填 ml_score 字段 (backfill_ml_score.py)",
        [sys.executable, os.path.join(SCRIPTS, "backfill_ml_score.py")],
    )


def step_6_business_today() -> None:
    """步骤 6: 造 50 条今日业务数据 (仪表盘/案件/评估立刻能看)."""
    _run_subprocess(
        "6/6 造 50 条今日业务数据 (gen_risk_data_with_dates.py --live)",
        [sys.executable, os.path.join(SCRIPTS, "gen_risk_data_with_dates.py"),
         "--days", "1", "--per-day", "50", "--live"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="旅游风控系统 - 一条龙命令 (6 步: 重置 → RISK → 训练数据 → 训练 → 回填 → 启动)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/one_command.py                # 跑完全部 6 步
  python scripts/one_command.py --skip-init     # 跳过 1+2 (DB + RISK 用户已就绪)
  python scripts/one_command.py --skip-train   # 跳过 3+4+5 (训练数据 + 模型已就绪)
  python scripts/one_command.py --only-start   # 只跑步骤 6 (造今日业务数据)
        """,
    )
    parser.add_argument("--skip-init", action="store_true",
                        help="跳过步骤 1+2 (DB + RISK 用户已就绪)")
    parser.add_argument("--skip-train", action="store_true",
                        help="跳过步骤 3+4+5 (训练数据 + 模型已就绪)")
    parser.add_argument("--only-start", action="store_true",
                        help="只跑步骤 6 (造今日业务数据, 不重置/训练)")
    args = parser.parse_args()

    print("=" * 70)
    print("旅游风控系统 - 一条龙命令 (6 步全流程)")
    print("=" * 70)
    print(f"工作目录: {ROOT}")
    print(f"Python:    {sys.executable}")
    print()

    try:
        if args.only_start:
            # 只造今日业务数据
            step_6_business_today()
        else:
            # 步骤 1+2: 重置 DB + RISK 用户
            if not args.skip_init:
                step_1_reset_db()
                step_2_risk_users()
            else:
                print("[跳过] 1+2: DB 和 RISK 用户已就绪")

            # 步骤 3+4+5: 训练数据 + 训练 + 回填
            if not args.skip_train:
                step_3_train_dataset()
                step_4_train_xgboost()
                step_5_backfill_ml_score()
            else:
                print("[跳过] 3+4+5: 训练数据 + 模型已就绪")

            # 步骤 6: 今日业务数据
            step_6_business_today()

    except RuntimeError as e:
        print(f"\n[FAIL] 步骤失败, 中断: {e}")
        print("=" * 70)
        print("排查建议:")
        print("  1. 检查 MySQL 是否启动 (默认 localhost:3306, root/root)")
        print("  2. 检查 .env 配置 (DB_HOST/DB_USER/DB_PASSWORD/DB_NAME)")
        print("  3. 查看 scripts/logs/gen_risk_fail.log 失败日志")
        print("  4. 分步跑 (--skip-init / --skip-train 跳过已完成的)")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("一条龙完成!")
    print("=" * 70)
    print("下一步:")
    print("  python run_app.py                          # 启动 Web 服务")
    print("  浏览器访问 http://localhost:8000            # 仪表盘/案件/评估/规则/黑名单/风险检查")
    print()
    print("造数据脚本:")
    print("  python scripts/gen_risk_data.py --balance-pos --target-pos-ratio 0.30 --count 200")
    print("  python scripts/gen_risk_data_with_dates.py --days 1 --per-day 100 --live")
    print("=" * 70)


if __name__ == "__main__":
    main()
