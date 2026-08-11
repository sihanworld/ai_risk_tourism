"""
旅游风控系统 - 训练数据集生成 (P4-L4 2026-08-08)

【目的】
  造一份**严格标注**的 XGBoost 训练数据集 (1500 条), 满足:
    1. 数量: 1500 条 (30 RISK 用户 × 25 高风险 + 30 普通用户 × 25 正常)
    2. 标签: 真实由 30 规则跑出 (decision 字段), 不是随机
    3. 特征: 25 维真实从 DB 查 (feature.py), 不是捏造
    4. ml_score 字段: 强制 NULL (写库后 UPDATE), 不存"未训练的垃圾模型"推理值
       → 训完基础模型后, 用 scripts/backfill_ml_score.py 回填合理值

【为什么需要这个脚本】
  之前 gen_risk_data.py 随机挑订单 → 跑规则 → 写到 risk_assessment:
    - 数据随机, 标签跟用户身份弱相关
    - 正例比例 < 3% (RISK 用户少), 模型假收敛
    - ml_score 字段是 XGBoost 推理结果, 但当时模型未训 → 0.00141 这种垃圾值
  现在严格控制:
    - 30 RISK 用户 → 25 条高风险事件 (退改签) → 99% 拒绝/审核
    - 30 普通用户 → 25 条正常事件 (普通预订) → 99% 通过
    - 正例比例 ≈ 45-50%
    - ml_score 字段 = NULL (干净, 训练 SQL 显式 WHERE ml_score IS NULL)

【用法】
  python scripts/gen_train_dataset.py                  # 默认 30 RISK + 30 普通, 每用户 25 条
  python scripts/gen_train_dataset.py --n-risk 50      # 50 RISK 用户
  python scripts/gen_train_dataset.py --n-normal 50   # 50 普通用户
  python scripts/gen_train_dataset.py --per-user 50   # 每个用户 50 条
  python scripts/gen_train_dataset.py --reset         # 先清空 risk_event/feature/assessment 再造
  python scripts/gen_train_dataset.py --dry-run       # 只统计不写入 (验证数据够不够)
"""
import argparse
import asyncio
import os
import random
import sys

# UTF-8 stdout (Windows GBK 兼容)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.schemas import RiskCheckRequest
from app.service.event import process_event

# 用户前缀 (跟 gen_risky_users.py 一致)
RISKY_USER_PREFIX = "RISK"


# ============================================================
# 选用户
# ============================================================

async def _pick_risk_users(db, n: int) -> list[str]:
    """从 RISK00X 高风险用户里选 N 个 (按 user_id 排序稳定)."""
    r = await db.execute(text("""
        SELECT user_id FROM user_info
        WHERE user_id LIKE :prefix
        ORDER BY user_id
        LIMIT :n
    """), {"prefix": f"{RISKY_USER_PREFIX}%", "n": n})
    users = [row.user_id for row in r.fetchall()]
    return users


async def _pick_normal_users(db, n: int) -> list[str]:
    """从普通用户里选 N 个 (排除 RISK 预置用户与黑名单用户)."""
    r = await db.execute(text("""
        SELECT user_id
        FROM user_info
        WHERE user_id NOT LIKE :prefix
        AND user_id NOT LIKE 'U_BLACK%'
        ORDER BY user_id
        LIMIT :n
    """), {"prefix": f"{RISKY_USER_PREFIX}%", "n": n})
    users = [row.user_id for row in r.fetchall()]
    return users


# ============================================================
# 造事件
# ============================================================

async def _pick_postsale_for_user(db, user_id: str) -> tuple | None:
    """挑该用户的一条退改签记录 (postsale_id, user_id)."""
    r = await db.execute(text("""
        SELECT p.postsale_id, oi.user_id
        FROM postsale p
        JOIN order_detail od ON p.order_detail_id = od.order_detail_id
        JOIN order_info oi ON od.order_id = oi.order_id
        WHERE oi.user_id = :uid
        ORDER BY RAND() LIMIT 1
    """), {"uid": user_id})
    row = r.first()
    return (row.postsale_id, row.user_id) if row else None


async def _pick_order_for_user(db, user_id: str) -> tuple | None:
    """挑该用户的一条订单 (order_id, user_id, receive_id)."""
    r = await db.execute(text("""
        SELECT order_id, user_id, receive_id
        FROM order_info
        WHERE user_id = :uid
        ORDER BY RAND() LIMIT 1
    """), {"uid": user_id})
    row = r.first()
    return (row.order_id, row.user_id, row.receive_id) if row else None


# ============================================================
# 主流程
# ============================================================

async def gen_train_dataset(
    n_risk: int = 30,
    n_normal: int = 30,
    per_user: int = 25,
    reset: bool = False,
    dry_run: bool = False,
):
    """造训练数据集: n_risk × per_user 高风险 + n_normal × per_user 正常."""
    if dry_run:
        print("=" * 60)
        print("[DRY-RUN] 训练数据集预演 (不写库)")
    else:
        print("=" * 60)
        print("训练数据集生成 (1500 条强标注, ml_score=NULL)")

    total_target = (n_risk + n_normal) * per_user
    print(f"目标: {n_risk} RISK × {per_user} + {n_normal} 普通 × {per_user} = {total_target} 条")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        # 0. (可选) 清空训练用表
        if reset and not dry_run:
            print("\n[0] 清空训练用表 (risk_event / risk_feature / risk_assessment / risk_case)...")
            await db.execute(text("DELETE FROM risk_case"))
            await db.execute(text("DELETE FROM risk_assessment"))
            await db.execute(text("DELETE FROM risk_feature"))
            await db.execute(text("DELETE FROM risk_event"))
            await db.execute(text("DELETE FROM risk_user_profile"))
            await db.commit()
            print("  清空完成")

        # 1. 选用户
        print(f"\n[1] 选 {n_risk} RISK + {n_normal} 普通用户...")
        risk_users = await _pick_risk_users(db, n_risk)
        normal_users = await _pick_normal_users(db, n_normal)
        if not risk_users:
            print(f"  [FAIL] 没找到 RISK 用户, 先跑: python scripts/gen_risky_users.py --count {n_risk}")
            return
        if not normal_users:
            print("  [FAIL] 没找到普通用户, 先跑 init_business_data.sql 初始化业务数据")
            return
        if len(risk_users) < n_risk:
            print(f"  [WARN] RISK 用户只 {len(risk_users)} 个 < 目标 {n_risk}, 用现有数量")
            n_risk = len(risk_users)
        if len(normal_users) < n_normal:
            print(f"  [WARN] 普通用户只 {len(normal_users)} 个 < 目标 {n_normal}, 用现有数量")
            n_normal = len(normal_users)
        print(f"  RISK: {len(risk_users)} 个 ({risk_users[0]} ~ {risk_users[-1]})")
        print(f"  普通: {len(normal_users)} 个 ({normal_users[0]} ~ {normal_users[-1]})")

        if dry_run:
            print(f"\n[DRY-RUN] 预演完成. 真跑去掉 --dry-run")
            return

        # 2. 造事件
        success = 0
        pos_count = 0
        neg_count = 0
        failed = 0
        plan = []
        # RISK 用户 → 退改签 (99% 触发 R004 高退款率等)
        for uid in risk_users:
            for _ in range(per_user):
                plan.append((uid, "退改签"))
        # 普通用户 → 普通预订 (99% 不触规则)
        for uid in normal_users:
            for _ in range(per_user):
                plan.append((uid, "预订"))

        random.shuffle(plan)  # 乱序, 避免时间戳聚集
        print(f"\n[2] 造 {len(plan)} 条事件 (乱序)...")
        risk_pos = 0
        normal_pos = 0
        for idx, (uid, event_type) in enumerate(plan, 1):
            try:
                if event_type == "退改签":
                    picked = await _pick_postsale_for_user(db, uid)
                    if not picked:
                        # 退改签不够, fallback 到预订
                        picked = await _pick_order_for_user(db, uid)
                        if not picked:
                            failed += 1
                            continue
                        order_id, user_id, receive_id = picked
                        request = RiskCheckRequest(
                            event_type="预订", source_id=order_id, user_id=user_id,
                            order_id=order_id, receive_id=receive_id,
                        )
                    else:
                        ps_id, user_id = picked
                        request = RiskCheckRequest(
                            event_type="退改签", source_id=ps_id, user_id=user_id,
                        )
                else:  # 预订
                    picked = await _pick_order_for_user(db, uid)
                    if not picked:
                        failed += 1
                        continue
                    order_id, user_id, receive_id = picked
                    request = RiskCheckRequest(
                        event_type="预订", source_id=order_id, user_id=user_id,
                        order_id=order_id, receive_id=receive_id,
                    )

                result = await process_event(db, request)
                success += 1
                if result.decision in ("拒绝", "人工审核"):
                    pos_count += 1
                    if uid.startswith(RISKY_USER_PREFIX):
                        risk_pos += 1
                    else:
                        normal_pos += 1
                else:
                    neg_count += 1

                if idx % 100 == 0 or idx == len(plan):
                    print(f"  进度 {idx}/{len(plan)}: 成功 {success}, 正例 {pos_count} ({100*pos_count/max(success,1):.1f}%)")
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"  [失败 #{failed}] 用户={uid}, 事件={event_type}: {e}")

        # 3. 强制 ml_score = NULL (训练数据无 ml 痕迹)
        print(f"\n[3] 强制 ml_score = NULL (训练数据无 ml 痕迹)...")
        await db.execute(text("""
            UPDATE risk_assessment
            SET ml_score = NULL, ml_decision = NULL
            WHERE ml_score IS NOT NULL
        """))
        null_count = (await db.execute(text("""
            SELECT COUNT(*) FROM risk_assessment WHERE ml_score IS NULL
        """))).scalar()
        non_null = (await db.execute(text("""
            SELECT COUNT(*) FROM risk_assessment WHERE ml_score IS NOT NULL
        """))).scalar()
        await db.commit()
        print(f"  risk_assessment 总 {null_count + non_null} 条, ml_score=NULL: {null_count}, 非 NULL: {non_null}")

    # 4. 汇总
    print("\n" + "=" * 60)
    print("训练数据集生成完成!")
    print(f"  目标:       {total_target} 条 ({n_risk} RISK × {per_user} + {n_normal} 普通 × {per_user})")
    print(f"  实际成功:   {success} 条")
    print(f"  正例:       {pos_count} 条 ({100*pos_count/max(success,1):.1f}%)")
    print(f"  负例:       {neg_count} 条 ({100*neg_count/max(success,1):.1f}%)")
    print(f"  失败:       {failed} 条")
    print(f"  标签分布:   RISK 正例 {risk_pos} / RISK 总 {n_risk*per_user} = {100*risk_pos/max(n_risk*per_user,1):.1f}%")
    print(f"              普通 正例 {normal_pos} / 普通 总 {n_normal*per_user} = {100*normal_pos/max(n_normal*per_user,1):.1f}%")
    print(f"  ml_score:   全部 NULL (无未训练模型垃圾值)")
    print("=" * 60)
    if pos_count / max(success, 1) < 0.25:
        print(f"[WARN] 正例比例 {100*pos_count/max(success,1):.1f}% < 25% 推荐值, 模型可能假收敛")
    if pos_count / max(success, 1) > 0.65:
        print(f"[WARN] 正例比例 {100*pos_count/max(success,1):.1f}% > 65% 上限, 业务上不正常")
    print("\n下一步: python scripts/train_xgb_model.py")


async def _runner():
    """包装函数: 业务跑完后显式 dispose engine, 避免 Event loop is closed 警告"""
    from app.database import async_engine
    try:
        await gen_train_dataset(
            n_risk=args.n_risk,
            n_normal=args.n_normal,
            per_user=args.per_user,
            reset=args.reset,
            dry_run=args.dry_run,
        )
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="造训练数据集 (1500 条强标注, ml_score=NULL, 训练 SQL 显式 WHERE ml_score IS NULL)"
    )
    parser.add_argument("--n-risk", type=int, default=30, help="RISK 高风险用户数 (默认 30)")
    parser.add_argument("--n-normal", type=int, default=30, help="普通用户数 (默认 30)")
    parser.add_argument("--per-user", type=int, default=25, help="每个用户造几条 (默认 25, 总 1500)")
    parser.add_argument("--reset", action="store_true", help="先清空训练用表 (risk_event/feature/assessment/case)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()
    asyncio.run(_runner())
