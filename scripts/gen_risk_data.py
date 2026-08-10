"""
电商风控系统 - 模拟风控评估数据生成 (异步)
从现有业务数据中随机选取订单/售后/用户，调用风控引擎生成评估记录
用于填充仪表盘和案件管理页面的初始数据

P4-L3 2026-08-08 新增 --balance-pos:
    XGBoost 训练是 2 分类, 需要关注正负样本比. 业务上"高风险评估"只占 5%~10%,
    训练时正负样本比 1:20 太极端, scale_pos_weight 会截断到上限 10.
    想要好训练效果, 应保证正例 (拒绝/人工审核) 占比 >= 20%.
    --balance-pos 启用时: 优先挑 RISK00X 系列高风险用户, 把正例比例拉到 25%~35%.
"""
import argparse
import asyncio
import os
import random
import sys

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.schemas import RiskCheckRequest
from app.service.event import process_event

# P4-L3: --balance-pos 用 RISK 前缀的预置高风险用户 (gen_risky_users.py 造过)
RISKY_USER_PREFIX = "RISK"


async def _pick_order(db, balance_pos: bool) -> tuple | None:
    """挑一条订单; balance_pos=True 时优先从 RISK 高风险用户里选.

    返回: (order_id, user_id, receive_id) 元组或 None
    """
    if balance_pos:
        # 80% 概率从高风险用户里挑 (RISK001~RISK005), 触发更多高风险评估
        if random.random() < 0.8:
            r = await db.execute(text("""
                SELECT order_id, user_id, receive_id
                FROM order_info
                WHERE user_id LIKE :prefix
                ORDER BY RAND() LIMIT 1
            """), {"prefix": f"{RISKY_USER_PREFIX}%"})
            row = r.first()
            if row:
                return (row.order_id, row.user_id, row.receive_id)
    r = await db.execute(text("""
        SELECT order_id, user_id, receive_id
        FROM order_info
        ORDER BY RAND() LIMIT 1
    """))
    row = r.first()
    return (row.order_id, row.user_id, row.receive_id) if row else None


async def _pick_postsale(db, balance_pos: bool) -> tuple | None:
    """挑一条售后; balance_pos=True 时优先从 RISK 高风险用户里选."""
    if balance_pos:
        if random.random() < 0.8:
            r = await db.execute(text("""
                SELECT p.postsale_id, oi.user_id
                FROM postsale p
                JOIN order_detail od ON p.order_detail_id = od.order_detail_id
                JOIN order_info oi ON od.order_id = oi.order_id
                WHERE oi.user_id LIKE :prefix
                ORDER BY RAND() LIMIT 1
            """), {"prefix": f"{RISKY_USER_PREFIX}%"})
            row = r.first()
            if row:
                return (row.postsale_id, row.user_id)
    r = await db.execute(text("""
        SELECT p.postsale_id, oi.user_id
        FROM postsale p
        JOIN order_detail od ON p.order_detail_id = od.order_detail_id
        JOIN order_info oi ON od.order_id = oi.order_id
        ORDER BY RAND() LIMIT 1
    """))
    row = r.first()
    return (row.postsale_id, row.user_id) if row else None


async def generate_risk_data(count: int = 30, balance_pos: bool = False, target_pos_ratio: float | None = None):
    """
    随机从现有订单中选取, 对每条执行风控检查 (异步).

    Args:
        count: 评估条数
        balance_pos: True 时优先从 RISK 高风险用户挑样本, 拉高正例比例
        target_pos_ratio: 目标正例比例 (0.0-1.0), 设置后自动循环造数据直到达标
            解决 --balance-pos 后正例仍然 < 5% 的问题 (RISK 用户订单数有限)
    """
    # 【P4-L3 2026-08-08 第二轮】target_pos_ratio 模式: 循环造数据直到正例达标
    if target_pos_ratio is not None and not balance_pos:
        print(f"⚠️  --target-pos-ratio 必须配合 --balance-pos, 自动启用 --balance-pos")
        balance_pos = True
    if target_pos_ratio is not None:
        print(f"🎯 目标正例比例: {target_pos_ratio*100:.0f}%, 循环造数据直到达标")

    max_rounds = 10  # 最多循环 10 轮, 避免无限循环
    target_total = count
    for round_idx in range(max_rounds):
        async with AsyncSessionLocal() as db:
            if balance_pos and round_idx == 0:
                print(f"⚠️  --balance-pos 模式: 80% 概率挑 RISK 高风险用户, 拉高训练正例比例")
            success = 0
            pos_count = 0
            for i in range(count):
                # balance_pos 时更倾向用售后 (高退款率用户)
                ps_odds = 0.6 if balance_pos else 0.3
                use_postsale = random.random() < ps_odds
                if use_postsale:
                    picked = await _pick_postsale(db, balance_pos)
                    if not picked:
                        picked = await _pick_order(db, balance_pos)
                    if not picked:
                        # 【P4-L3 第二轮】target 模式下, 持续造数据直到达标
                        if target_pos_ratio is not None:
                            continue
                        print(f"  [{i+1}/{count}] 没有可用售后/订单, 跳过")
                        continue
                    ps_id, user_id = picked
                    request = RiskCheckRequest(
                        event_type="售后申请",
                        source_id=ps_id,
                        user_id=user_id,
                    )
                    tag = "售后"
                else:
                    picked = await _pick_order(db, balance_pos)
                    if not picked:
                        if target_pos_ratio is not None:
                            continue
                        print(f"  [{i+1}/{count}] 没有可用订单, 跳过")
                        continue
                    order_id, user_id, receive_id = picked
                    event_type = random.choice(["下单", "下单", "下单", "支付", "支付"])
                    request = RiskCheckRequest(
                        event_type=event_type,
                        source_id=order_id,
                        user_id=user_id,
                        order_id=order_id,
                        receive_id=receive_id,
                    )
                    tag = "订单"
                try:
                    result = await process_event(db, request)
                    success += 1
                    # 决策是"拒绝"或"人工审核"= 正例
                    if result.decision in ("拒绝", "人工审核"):
                        pos_count += 1
                    # target 模式下不打印每条详情, 减少噪音
                    if target_pos_ratio is None:
                        print(f"  [{i+1}/{count}] {tag} 用户={user_id}, "
                              f"评分={result.final_score}, 决策={result.decision}, "
                              f"命中={result.rule_count}条规则")
                except Exception as e:
                    if target_pos_ratio is None:
                        print(f"  [{i+1}/{count}] 失败: {e}")

        current_ratio = pos_count / success if success else 0.0
        print(f"\n[第 {round_idx+1}/{max_rounds} 轮] 成功 {success} 条, 正例 {pos_count} 条 ({current_ratio*100:.1f}%)")

        # target 模式: 检查正例比例是否达标
        if target_pos_ratio is not None:
            if current_ratio >= target_pos_ratio:
                print(f"✅ 正例比例 {current_ratio*100:.1f}% >= 目标 {target_pos_ratio*100:.0f}%, 达标!")
                break
            elif round_idx < max_rounds - 1:
                print(f"⚠️  正例比例 {current_ratio*100:.1f}% < 目标 {target_pos_ratio*100:.0f}%, 继续造数据...")
                # 下一轮: 只造高风险事件 (更激进)
                continue
            else:
                print(f"❌ 跑完 {max_rounds} 轮仍未达标, 最后比例 {current_ratio*100:.1f}%")
                print(f"   建议: 跑 scripts/gen_risky_users.py 扩大 RISK 用户规模 (默认只 5 个不够)")
                break
        else:
            # 非 target 模式: 跑完就退出
            break

    print(f"\n完成! 成功生成 {success} 条风控评估记录, 正例 {pos_count} 条 ({pos_count/success*100:.1f}%)")


async def _runner():
    """包装函数: 业务跑完后显式 dispose engine, 避免 Event loop is closed 警告"""
    from app.database import async_engine
    try:
        await generate_risk_data(
            count=args.count,
            balance_pos=args.balance_pos,
            target_pos_ratio=args.target_pos_ratio,
        )
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="造风控评估数据. --balance-pos 优先挑 RISK 高风险用户, 拉高训练正例比例."
    )
    parser.add_argument("--count", type=int, default=30, help="评估条数 (默认 30)")
    parser.add_argument(
        "--balance-pos", action="store_true",
        help="优先挑 RISK00X 高风险用户, 让训练时正例比例 >= 20% (XGBoost 推荐值)",
    )
    parser.add_argument(
        "--target-pos-ratio", type=float, default=None,
        help="目标正例比例 (0.0-1.0), 配合 --balance-pos 使用, 循环造数据直到达标. 例: --target-pos-ratio 0.30",
    )
    args = parser.parse_args()
    asyncio.run(_runner())
