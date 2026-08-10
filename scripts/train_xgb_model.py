"""
电商风控系统 - XGBoost 训练脚本 (一次性, 跑完即可)
数据源: MySQL risk_event + risk_feature + risk_assessment
步骤:
  1. 拉历史评估 (decision 不为空的, 排除掉 None)
  2. 每个 event_id JOIN 出 25 个特征 (宽表: pivot risk_feature)
  3. 标签二分类: 0=通过/标记, 1=人工审核/拒绝
  4. 80/20 stratify 拆分 (验证集保持正负比)
  5. 训练 + 早停 (验证集 logloss 连续 10 轮不降就停) + AUC + F1
  6. 评估 + 保存到 app/engine/xgb_model.json + 输出特征重要性
跑法: python -u scripts/train_xgb_model.py
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pymysql

# 把项目根目录加到 sys.path, 这样能 import app.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.engine.ml_model import FEATURE_COLUMNS, train_and_save  # noqa: E402

# 日志配置: 输出到 stdout, 不写文件 (一次性脚本, 跑完即结束)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# 数据查询 SQL (2 步: 1 拉评估, 2 拉特征宽表)
# 【P4-L3 2026-08-08 第二轮】5000 改用配置 settings.XGB_TRAIN_DATA_LIMIT
# 【P4-L4 2026-08-08 训练数据严格化】显式 WHERE ml_score IS NULL: 训练只取"无 ml 痕迹"数据
#   原因: gen_train_dataset.py 造训练数据时强制 ml_score=NULL (避免"未训练模型"垃圾值),
#         backfill_ml_score.py 训完回填 ml_score. 显式过滤保证训练数据 100% 干净.
SQL_FETCH_ASSESSMENTS = """
SELECT assessment_id, event_id, decision
FROM risk_assessment
WHERE decision IN ('通过', '标记', '人工审核', '拒绝')
  AND ml_score IS NULL
ORDER BY create_time DESC
LIMIT %s
"""

SQL_FETCH_FEATURES_WIDE = """
SELECT event_id, feature_name, feature_value
FROM risk_feature
WHERE event_id IN ({event_ids})
"""


def _decision_to_label(decision: str) -> int:
    """
    业务 4 档 → 机器学习 2 分类
        通过/标记     → 0 (低风险, 模型放行)
        人工审核/拒绝 → 1 (高风险, 模型拦截)
    """
    return 1 if decision in ("人工审核", "拒绝") else 0


def _load_data_from_mysql() -> tuple[np.ndarray, np.ndarray]:
    """
    从 MySQL 拉数据, 返回 (X, y).
    X: (N, 25) float32
    y: (N,) int (0/1)
    """
    # 1. 连 MySQL (用 settings 的字段, 跟 ORM 一致)
    conn = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            # 1.1 拉评估 (【P4-L3 第二轮】LIMIT 用 settings.XGB_TRAIN_DATA_LIMIT 配置)
            cur.execute(SQL_FETCH_ASSESSMENTS, (settings.XGB_TRAIN_DATA_LIMIT,))
            rows = cur.fetchall()
            logger.info("拉取评估: %d 条 (LIMIT=%d)", len(rows), settings.XGB_TRAIN_DATA_LIMIT)
            # 【P4-L3 2026-08-08 第三轮】DB 总条数 + 正例 + 时间跨度校验
            cur.execute("SELECT COUNT(*) FROM risk_assessment")
            db_total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM risk_assessment WHERE decision IN ('人工审核', '拒绝')")
            db_total_pos = cur.fetchone()[0]
            # 时间跨度 (create_time 跨度, 防止 init_db reset 后残留)
            cur.execute("SELECT MIN(create_time), MAX(create_time) FROM risk_assessment")
            time_range = cur.fetchone()
            db_min_time, db_max_time = time_range if time_range else (None, None)
            # 跨度天数
            span_days = None
            if db_min_time and db_max_time:
                from datetime import datetime as _dt
                if isinstance(db_min_time, _dt):
                    span_days = (db_max_time - db_min_time).days
                else:
                    # pymysql 可能返回 str
                    try:
                        span_days = (_dt.now() - _dt.strptime(str(db_min_time)[:19], "%Y-%m-%d %H:%M:%S")).days
                    except Exception:
                        span_days = None
            # 校验 1: 实际加载 < LIMIT 80% (DB 总数不够)
            if len(rows) < settings.XGB_TRAIN_DATA_LIMIT * 0.8:
                logger.warning(
                    "⚠️  DB 实际只加载 %d 条 (< LIMIT %d 的 80%%), DB 总 %d 条. "
                    "建议先 init_db.py --reset --yes 清空, 再 gen_risky_users.py + gen_risk_data_with_dates.py 重新造",
                    len(rows), settings.XGB_TRAIN_DATA_LIMIT, db_total,
                )
            # 校验 2: DB 时间跨度 < 1 天 (说明数据全是同一天造的, 极可能 reset 后没重造)
            if span_days is not None and span_days < 1 and db_total > 100:
                logger.warning(
                    "⚠️  DB 评估数据 create_time 跨度 < 1 天 (%s ~ %s, %d 条). "
                    "说明数据全是同一天造的, 极可能 init_db.py --reset 后没重造. "
                    "建议: gen_risk_data_with_dates.py --days 30 --per-day 200 --clean",
                    db_min_time, db_max_time, db_total,
                )
            if not rows:
                raise RuntimeError("没有评估数据, 先跑几次 /api/risk/check")
            # event_id → label 映射
            event_to_label: dict[str, int] = {}
            for _aid, eid, dec in rows:
                event_to_label[eid] = _decision_to_label(dec)
            # 1.2 拉这些 event 的 25 维特征
            # 拼 IN (...) 列表 (注意: 必须防注入, 这里都是内部 ULID, 放心拼)
            ids = list(event_to_label.keys())
            # MySQL IN 列表太长会爆, 分批拉
            BATCH = 500
            # event_id → {feature_name: feature_value}
            event_to_features: dict[str, dict[str, float]] = {}
            for i in range(0, len(ids), BATCH):
                batch_ids = ids[i:i + BATCH]
                placeholders = ",".join(["%s"] * len(batch_ids))
                sql = SQL_FETCH_FEATURES_WIDE.format(event_ids=placeholders)
                cur.execute(sql, batch_ids)
                feat_rows = cur.fetchall()
                for eid, fname, fval in feat_rows:
                    if eid not in event_to_features:
                        event_to_features[eid] = {}
                    # 尝试转 float; 转不动当 0
                    try:
                        event_to_features[eid][fname] = float(fval)
                    except (TypeError, ValueError):
                        event_to_features[eid][fname] = 0.0
            logger.info("拉取特征: %d 个 event 各 25 维", len(event_to_features))
            # 2. 拼训练矩阵 (只保留 25 维特征齐全的样本)
            X_list, y_list = [], []
            missing = 0
            for eid, label in event_to_label.items():
                feats = event_to_features.get(eid)
                if not feats or len(feats) < 25:
                    missing += 1
                    continue
                row = [feats.get(col, 0.0) for col in FEATURE_COLUMNS]
                X_list.append(row)
                y_list.append(label)
            if missing:
                logger.warning("跳过 %d 条特征不全的样本", missing)
            X = np.array(X_list, dtype=np.float32)
            y = np.array(y_list, dtype=np.int32)
            pos_count = int(y.sum()) if len(y) else 0
            pos_ratio = pos_count / len(y) if len(y) else 0.0
            logger.info("训练矩阵: X.shape=%s, y 正例=%d (%.2f%%)",
                        X.shape, pos_count, 100 * pos_ratio)

            # 【P4-L3 2026-08-08 第三轮】数据质量校验 — 防止"看起来很多但全是噪声"
            # 真实案例 (2026-08-08): 5465 条评估里只有 103 个正例 (1.9%), 模型 pos 比例永远 < 3%
            if len(y) > 0 and pos_ratio < 0.15:
                logger.warning(
                    "⚠️  正例比例仅 %.1f%% < 推荐 15%% (DB 总正例: %d / %d = %.1f%%). "
                    "模型学不到 '正例模式', 会假收敛. "
                    "建议: gen_risky_users.py --count 30 + gen_risk_data_with_dates.py --days 30 --per-day 200",
                    100 * pos_ratio, db_total_pos, db_total, 100 * db_total_pos / max(1, db_total),
                )
            elif len(y) > 0 and pos_ratio < 0.25:
                logger.warning(
                    "⚠️  正例比例 %.1f%% 偏低 (< 25%% 推荐). 建议 --target-pos-ratio 0.30 重造",
                    100 * pos_ratio,
                )
            return X, y
    finally:
        conn.close()


def main() -> None:
    """主函数: 拉数据 → 训练 → 评估 → 保存 → 输出特征重要性"""
    logger.info("=" * 60)
    logger.info("XGBoost 训练开始")
    logger.info("=" * 60)
    # 1. 拉数据
    X, y = _load_data_from_mysql()
    n = len(X)
    if n < 50:
        logger.error("样本不足 50 条 (当前 %d), 无法训练, 请先跑风控检查积累数据", n)
        sys.exit(1)
    # 2. 训练 + 早停 + 保存 (XGB_MIN_SAMPLES 1250 推荐值, < 1250 训练函数会打印 warning)
    logger.info(
        "训练参数: num_boost_round=200, early_stopping_rounds=%d, test_size=%.2f",
        settings.XGB_EARLY_STOPPING_ROUNDS, settings.XGB_TEST_SIZE,
    )
    metrics, model = train_and_save(
        X, y,
        num_boost_round=200,
        early_stopping_rounds=settings.XGB_EARLY_STOPPING_ROUNDS,
        return_model=True,
    )
    # 3. 打评估结果
    logger.info("=" * 60)
    logger.info("训练完成: n=%d, pos=%d (%.1f%%), neg=%d",
                metrics["n_train"], metrics["n_pos"],
                100 * metrics["pos_ratio"], metrics["n_neg"])
    logger.info("  scale_pos_weight: %.2f (raw=%.2f)",
                metrics["scale_pos_weight"], metrics["raw_scale_pos_weight"])
    logger.info("  best_iteration:   %d (早停监控 %s, 连续 %d 轮不升就停 + warmup %d 轮防假收敛)",
                metrics["best_iteration"], settings.XGB_EARLY_STOP_METRIC,
                settings.XGB_EARLY_STOPPING_ROUNDS, settings.XGB_WARMUP_ROUNDS)
    logger.info("  AUC=%.4f, F1=%.4f, Acc=%.4f (baseline 全预测负例=%.4f), P=%.4f, R=%.4f",
                metrics["auc"], metrics["f1"], metrics["accuracy"],
                metrics.get("baseline_accuracy", 0.0),
                metrics["precision"], metrics["recall"])
    if "val_accuracy" in metrics:
        logger.info("  [验证集]  n=%d, AUC=%.4f, F1=%.4f (阈值=%.2f), Acc=%.4f",
                    metrics["n_val"], metrics["val_auc"],
                    metrics["val_f1"], metrics.get("best_f1_threshold", 0.5),
                    metrics["val_accuracy"])
        # 假收敛嫌疑总览
        warnings = []
        if metrics["best_iteration"] < settings.XGB_MIN_BEST_ITER:
            warnings.append(f"best_iter={metrics['best_iteration']} < {settings.XGB_MIN_BEST_ITER}")
        if metrics["val_auc"] < settings.XGB_MIN_VAL_AUC:
            warnings.append(f"val_auc={metrics['val_auc']:.3f} < {settings.XGB_MIN_VAL_AUC}")
        if metrics["val_f1"] < settings.XGB_MIN_VAL_F1:
            warnings.append(f"val_f1={metrics['val_f1']:.3f} < {settings.XGB_MIN_VAL_F1} (但 best_f1_threshold=%.2f 已优化)"
                            % metrics.get("best_f1_threshold", 0.5))
        if warnings:
            logger.warning("  [假收敛嫌疑] %s", " | ".join(warnings))
            logger.warning("  建议: 1) python scripts/gen_risk_data.py --balance-pos --target-pos-ratio 0.30 重造数据")
            logger.warning("        2) 检查 feature.py 25 维是否真的有区分度 (y=1 跟 y=0 特征分布差多少)")
            logger.warning("        3) 调高 XGB_WARMUP_ROUNDS / 调低 XGB_LEARNING_RATE 让模型有更多训练空间")
    else:
        logger.warning("  [验证集]  未拆分 (样本 < 10 或早停已关闭)")
    logger.info("  模型保存: %s", metrics["model_path"])
    logger.info("=" * 60)
    # 4. 【P4-L3 2026-08-08】输出特征重要性 TOP 10
    # 用 gain (默认) — 表示该特征对减少损失的总贡献, 越大越重要
    # 也可改 'weight' (被选作分裂点的次数) 或 'cover' (平均覆盖样本数)
    if model is not None:
        importance = model.get_score(importance_type="gain")
        # 按重要性降序
        top = sorted(importance.items(), key=lambda x: -x[1])
        logger.info("")
        logger.info("=" * 60)
        logger.info("[特征重要性 TOP %d] (XGBoost gain)", min(10, len(top)))
        logger.info("=" * 60)
        logger.info("  %-30s %-12s %s", "特征名", "重要性", "占比")
        total_gain = sum(v for _, v in top) or 1
        for rank, (feat, score) in enumerate(top[:10], 1):
            bar = "#" * min(40, int(40 * score / top[0][1]))
            logger.info("  %2d. %-27s %10.1f  %5.1f%%  %s",
                        rank, feat, score, 100 * score / total_gain, bar)
        logger.info("=" * 60)
        logger.info("Top 3 特征解释了 %.1f%% 的模型决策", 100 * sum(v for _, v in top[:3]) / total_gain)
        logger.info("→ 业务含义: 重点优化 TOP 5 特征的计算准确性 (P5 优化方向)")


if __name__ == "__main__":
    main()
