"""backfill_ml_score.py — 批量回填 risk_assessment.ml_score 字段

【P4-L4 2026-08-08】
【旅游行业迁移 2026-08-11】risk_event 无 order_id/receive_id 列, 改为从
    risk_feature 特征快照 (每事件 25 行) 聚合后推理回填.

场景: 训练完 XGBoost 后, 给所有历史 assessment (ml_score IS NULL) 回填 ML 分.
回填完成后输出正/负样本 ml_score 均值与分离度 (sep), 验证模型区分质量.

用法:
    python scripts/backfill_ml_score.py
"""
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine.ml_model import (
    load_model, is_model_loaded, get_model,
    _prob_to_decision, FEATURE_COLUMNS,
)

# 加载训练好的模型 (load_model 读 app/engine/xgb_model.json 到全局 _MODEL)
if not load_model():
    print("ERROR: XGBoost 模型未训练, 先运行: python scripts/train_xgb_model.py")
    sys.exit(1)
assert is_model_loaded(), "模型加载状态异常"
model = get_model()

print(f"XGBoost 模型已加载 (features={model.num_features()})")


async def backfill_ml_score():
    """回填所有 risk_assessment.ml_score IS NULL 的记录 (从 risk_feature 快照读特征)."""
    from sqlalchemy import text, bindparam
    import numpy as np
    import xgboost as xgb
    from app.database import AsyncSessionLocal

    # 1. 找到所有还没 ML 分的 assessment
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT assessment_id, event_id, user_id
            FROM risk_assessment
            WHERE ml_score IS NULL
        """))).fetchall()

    if not rows:
        print("没有需要回填的 assessment (ml_score 全部已填)")
        return

    print(f"需要回填 {len(rows)} 条 assessment")

    # 2. 批量加载特征快照 (risk_feature: 每事件 25 行 feature_name/feature_value)
    event_ids = list({r.event_id for r in rows})
    feat_by_event: dict[str, dict] = {}
    async with AsyncSessionLocal() as session:
        BATCH = 500
        for start in range(0, len(event_ids), BATCH):
            batch = event_ids[start:start + BATCH]
            stmt = text("""
                SELECT event_id, feature_name, feature_value
                FROM risk_feature
                WHERE event_id IN :ids
            """).bindparams(bindparam("ids", expanding=True))
            feat_rows = (await session.execute(stmt, {"ids": batch})).fetchall()
            for fr in feat_rows:
                feat_by_event.setdefault(fr.event_id, {})[fr.feature_name] = float(fr.feature_value or 0)

    # 3. 批量推理
    valid = [(r, feat_by_event[r.event_id]) for r in rows if r.event_id in feat_by_event]
    if not valid:
        print("WARNING: 没有可用的特征快照, 无法回填")
        return
    X = np.asarray(
        [[feats.get(col, 0.0) for col in FEATURE_COLUMNS] for _, feats in valid],
        dtype=np.float64,
    )
    probas = model.predict(xgb.DMatrix(X, feature_names=FEATURE_COLUMNS))

    # 4. 写回 risk_assessment.ml_score + ml_decision
    updated = 0
    BATCH = 500
    for start in range(0, len(valid), BATCH):
        batch = valid[start:start + BATCH]
        batch_probas = probas[start:start + BATCH]
        async with AsyncSessionLocal() as session:
            for (row, _feats), proba in zip(batch, batch_probas):
                proba = float(proba)
                await session.execute(text("""
                    UPDATE risk_assessment
                    SET ml_score = :s, ml_decision = :d
                    WHERE assessment_id = :aid
                """), {"s": round(proba, 4), "d": _prob_to_decision(proba), "aid": row.assessment_id})
                updated += 1
            await session.commit()

    print(f"已回填 {updated} 条 assessment")
    skipped = len(rows) - len(valid)
    if skipped:
        print(f"WARNING: {skipped} 条 assessment 无特征快照, 已跳过")

    # 5. 分离度报告: 正样本 (RISK 用户) vs 负样本 的 ml_score 均值差
    pos = [float(p) for (row, _f), p in zip(valid, probas) if str(row.user_id).startswith("RISK")]
    neg = [float(p) for (row, _f), p in zip(valid, probas) if not str(row.user_id).startswith("RISK")]
    pos_avg = sum(pos) / len(pos) if pos else 0.0
    neg_avg = sum(neg) / len(neg) if neg else 0.0
    sep = pos_avg - neg_avg
    print(f"分离度报告: 正样本均值 pos_avg={pos_avg:.4f} (n={len(pos)}), "
          f"负样本均值 neg_avg={neg_avg:.4f} (n={len(neg)}), 分离度 sep={sep:.4f}")
    if pos and neg and sep < 0.2:
        print("WARNING: 分离度偏低, 建议重训模型 (python scripts/train_xgb_model.py)")


if __name__ == "__main__":
    asyncio.run(backfill_ml_score())
