"""
电商风控系统 - XGBoost ml_score 字段回填脚本 (P4-L4 2026-08-08)

【目的】
  gen_train_dataset.py 造训练数据时强制 ml_score=NULL (避免"未训练模型"推理垃圾值).
  训完基础模型后, 用本脚本回填 ml_score 字段:
    - 用训好的 XGBoost 推理 1500 条 risk_assessment
    - 写回 ml_score (P(拒绝) ∈ [0,1]) + ml_decision (4 档决策)
  这样:
    1. 训练数据 ml_score 字段**真实合理** (来自训好的模型, 不是垃圾)
    2. 前端评估历史/详情能看到合理 ml_score
    3. 未来可作为 meta-feature (stacking) 二次训练

【注意】
  - 必须在 train_xgb_model.py 跑完后, xgb_model.json 存在
  - 只回填 ml_score=NULL 的记录 (避免覆盖)
  - 回填不影响训练 (训练 SQL 显式 WHERE ml_score IS NULL, 回填后这些记录被排除)

【用法】
  python scripts/backfill_ml_score.py                    # 回填所有 ml_score=NULL 的评估
  python scripts/backfill_ml_score.py --limit 1500       # 限制回填条数
  python scripts/backfill_ml_score.py --dry-run          # 只统计不写库
"""
import argparse
import asyncio
import os
import sys

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql

from app.config import settings
from app.engine.feature import compute_all_features
from app.engine.ml_model import FEATURE_COLUMNS, is_model_loaded, load_model, predict
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import RiskAssessment


async def backfill_ml_score(limit: int | None = None, dry_run: bool = False):
    """用训好的 XGBoost 推理回填 risk_assessment.ml_score/ml_decision."""
    # 1. 加载模型
    if not is_model_loaded():
        print("[1] 加载 XGBoost 模型...")
        ok = load_model()
        if not ok:
            print("  [FAIL] 模型加载失败, 先跑: python scripts/train_xgb_model.py")
            return
    print(f"  模型已加载, is_loaded={is_model_loaded()}")

    # 2. 拉 ml_score=NULL 的评估
    print(f"\n[2] 拉 ml_score=NULL 的评估 (limit={limit})...")
    conn = pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT,
        user=settings.DB_USER, password=settings.DB_PASSWORD,
        database=settings.DB_NAME, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT assessment_id, event_id, user_id, decision
                FROM risk_assessment
                WHERE ml_score IS NULL
            """
            if limit:
                sql += f" LIMIT {int(limit)}"
            cur.execute(sql)
            rows = cur.fetchall()
            print(f"  拉取 {len(rows)} 条 ml_score=NULL 记录")
            if not rows:
                print("  没有需要回填的记录, 退出")
                return
    finally:
        conn.close()

    # 3. 逐条推理回填
    print(f"\n[3] 推理 + 回填...")
    engine = create_async_engine(settings.DB_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    try:
        updated = 0
        pos_score_sum = 0.0  # 正例 (拒绝/审核) ml_score 累计
        neg_score_sum = 0.0  # 负例 (通过/标记) ml_score 累计
        pos_count = 0
        neg_count = 0
        for i, (aid, eid, uid, dec) in enumerate(rows, 1):
            try:
                async with SessionLocal() as db:
                    # 找该 event 的 order_id 和 receive_id
                    ev_row = (await db.execute(
                        __import__("sqlalchemy").text("""
                            SELECT order_id, receive_id, source_id, event_type
                            FROM risk_event
                            WHERE event_id = :eid
                        """),
                        {"eid": eid},
                    )).first()
                    if not ev_row:
                        continue
                    # 算 25 维特征
                    features = await compute_all_features(
                        db, uid, order_id=ev_row.order_id, receive_id=ev_row.receive_id,
                    )
                    # 推理
                    ml = predict(features)
                    if ml is None:
                        continue
                    # 回写 ml_score / ml_decision
                    if not dry_run:
                        from sqlalchemy import update
                        await db.execute(
                            update(RiskAssessment)
                            .where(RiskAssessment.assessment_id == aid)
                            .values(ml_score=ml.score, ml_decision=ml.decision)
                        )
                        await db.commit()
                    updated += 1
                    if dec in ("拒绝", "人工审核"):
                        pos_score_sum += ml.score
                        pos_count += 1
                    else:
                        neg_score_sum += ml.score
                        neg_count += 1
                if i % 100 == 0 or i == len(rows):
                    pos_avg = pos_score_sum / pos_count if pos_count else 0
                    neg_avg = neg_score_sum / neg_count if neg_count else 0
                    print(f"  进度 {i}/{len(rows)}: 回填 {updated}, 正例平均 ml_score={pos_avg:.4f}, 负例平均 ml_score={neg_avg:.4f}")
            except Exception as e:
                if i <= 3:
                    print(f"  [失败 #{i}] aid={aid}: {e}")

        # 4. 汇总
        print("\n" + "=" * 60)
        print(f"回填完成: 共回填 {updated} 条 ({'DRY-RUN' if dry_run else '已写库'})")
        if pos_count:
            print(f"  正例 ({pos_count} 条) 平均 ml_score = {pos_score_sum/pos_count:.4f}")
        if neg_count:
            print(f"  负例 ({neg_count} 条) 平均 ml_score = {neg_score_sum/neg_count:.4f}")
        # 合理性检查
        if pos_count and neg_count:
            pos_avg = pos_score_sum / pos_count
            neg_avg = neg_score_sum / neg_count
            sep = pos_avg - neg_avg
            print(f"  正负分离度: {sep:.4f} (越大越好, < 0.1 说明模型学不到东西)")
            if sep < 0.1:
                print("  [WARN] 正负分离度 < 0.1, 模型区分度低, 建议重训")
            elif sep > 0.3:
                print("  [OK] 正负分离度 > 0.3, 模型区分度好")
        print("=" * 60)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="用训好的 XGBoost 推理回填 risk_assessment.ml_score 字段 (无垃圾值)"
    )
    parser.add_argument("--limit", type=int, default=None, help="限制回填条数 (默认全部 NULL 记录)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()
    asyncio.run(backfill_ml_score(limit=args.limit, dry_run=args.dry_run))
