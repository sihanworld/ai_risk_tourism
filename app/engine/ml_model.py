"""
XGBoost 模型管理: 加载 / 推理 / 训练 / 兜底.

【重要约定】
  - 特征顺序固定 (FEATURE_COLUMNS), 跟 feature.py 算出的 25 个 key 一一对应
  - 标签二分类: 0=通过/标记, 1=人工审核/拒绝
  - 概率输出: predict_proba[:, 1] 即 P(拒绝)
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import xgboost as xgb
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

from app.config import settings

logger = logging.getLogger(__name__)


# 固定 25 维特征顺序 (训练和推理都用这个顺序, 防 dict 顺序不一致导致特征错位)
# 改这个列表前必须同步: feature.py::compute_user_features / compute_order_features
# / compute_trip_features / tests/test_xgboost.py::test_feature_columns_align
# 对不齐会让 XGBoost 训练/推理退化成 0 填充, 业务上相当于模型没工作
FEATURE_COLUMNS: list[str] = [
    "user_total_orders",
    "user_orders_30d",
    "user_orders_7d",
    "user_total_amount",
    "user_avg_order_amount",
    "user_max_order_amount",
    "user_refund_count",
    "user_postsale_count",
    "user_refund_rate",
    "user_postsale_rate",
    "user_refund_amount",
    "user_cancel_count",
    "user_complaint_count",
    "user_trip_city_count",
    "order_total_amount",
    "order_item_count",
    "order_sku_count",
    "order_discount_amount",
    "order_discount_rate",
    "order_pay_interval_sec",
    "order_is_night",
    "order_lead_days",
    "trip_traveler_count",
    "trip_city_count",
    "trip_is_new_traveler",
]

assert len(FEATURE_COLUMNS) == 25, f"特征数量必须是 25, 当前 {len(FEATURE_COLUMNS)}"


@dataclass
class MlResult:
    """XGBoost 单次推理结果"""
    score: float           # P(拒绝) ∈ [0, 1]
    decision: str          # 4 档: 通过/标记/人工审核/拒绝
    is_loaded: bool        # 模型是否加载成功 (False 表示走兜底)


# 训练/推理全局单例 (启动时初始化一次)
_MODEL: Optional[xgb.Booster] = None
_LOADED: bool = False


def get_model() -> Optional[xgb.Booster]:
    """获取加载好的 XGBoost 模型 (None = 没启用/加载失败)"""
    return _MODEL


def is_model_loaded() -> bool:
    """模型是否加载成功 (供 decision.py 判定要不要走 XGBoost 分支)"""
    return _LOADED


def load_model(model_path: Optional[str] = None) -> bool:
    """启动时加载 XGBoost 模型. 兜底: 文件不存在/加载失败 → 业务仍可运行."""
    global _MODEL, _LOADED
    if not settings.XGB_ENABLED:
        logger.info("XGBoost 已关闭 (XGB_ENABLED=False), 决策走纯规则模式")
        return False

    if model_path:
        path = model_path
    else:
        # 项目根 = ml_model.py 所在目录的父级 (app/engine/ml_model.py → 项目根)
        project_root = Path(__file__).resolve().parent.parent.parent
        path = str(project_root / settings.XGB_MODEL_PATH)
    if not os.path.exists(path):
        logger.warning("XGBoost 模型文件不存在: %s, 决策走纯规则模式", path)
        return False

    try:
        _MODEL = xgb.Booster()
        _MODEL.load_model(path)
        _LOADED = True
        logger.info("XGBoost 模型加载成功: %s, features=%d", path, _MODEL.num_features())
        return True
    except Exception as e:
        logger.exception("XGBoost 模型加载失败: %s, 错误: %s", path, e)
        _MODEL = None
        _LOADED = False
        return False


def _features_to_array(features: dict) -> np.ndarray:
    """25 维 dict → numpy 数组 (1×25). 缺失用 0.0 兜底; None/字符串统一 float."""
    row = []
    for col in FEATURE_COLUMNS:
        v = features.get(col, 0.0)
        try:
            row.append(float(v))
        except (TypeError, ValueError):
            row.append(0.0)
    return np.array([row], dtype=np.float32)


def predict(features: dict) -> MlResult:
    """推理入口: 25 维特征 → P(拒绝) + ML 维度决策. 模型没加载 → 兜底 score=0 通过."""
    if not _LOADED or _MODEL is None:
        return MlResult(score=0.0, decision="通过", is_loaded=False)
    try:
        x = _features_to_array(features)
        # XGBoost 2.x 要求 Booster.predict 必须传 DMatrix (跟训练时一致)
        dmat = xgb.DMatrix(x, feature_names=FEATURE_COLUMNS)
        prob = float(_MODEL.predict(dmat)[0])
    except Exception as e:
        logger.exception("XGBoost 推理失败, 走兜底: %s", e)
        return MlResult(score=0.0, decision="通过", is_loaded=True)
    return MlResult(score=round(prob, 4), decision=_prob_to_decision(prob), is_loaded=True)


def _prob_to_decision(prob: float) -> str:
    """XGBoost 概率 P(拒绝) ∈ [0,1] → 4 档决策 (用 .env 里 ML_*_THRESHOLD).

    跟 decision._score_to_decision() 同名结构但语义不同 (本函数接 float 概率, 接 int 评分),
    故意区分命名, 防止混淆.
    """
    if prob < settings.ML_PASS_THRESHOLD:
        return "通过"
    elif prob < settings.ML_MARK_THRESHOLD:
        return "标记"
    elif prob < settings.ML_REVIEW_THRESHOLD:
        return "人工审核"
    else:
        return "拒绝"


def train_and_save(
    X: np.ndarray,
    y: np.ndarray,
    model_path: Optional[str] = None,
    num_boost_round: int = 200,
    return_model: bool = False,
    early_stopping_rounds: Optional[int] = None,
) -> dict | tuple[dict, xgb.Booster]:
    """训练 XGBoost 二分类器 + 评估 + 保存.

    【P3-M3 修复 2026-08-07】业务场景"通过"远多于"拒绝" (95% vs 5% 是常态).
    XGBoost 默认会偏多数类, 加 scale_pos_weight=neg/pos 自动平衡权重,
    但取 XGB_MAX_SCALE_POS_WEIGHT 上限, 防极端不平衡时过拟合.

    【P4-L3 2026-08-08】return_model=True 时返回 (metrics_dict, booster) 元组,
    方便训练脚本输出特征重要性. 默认 False 保持向后兼容.

    【P4-L3 2026-08-08 第二轮】业务场景每天新评估 < 100 条, 样本 < XGB_MIN_SAMPLES (1250)
    时打印 warning, 不阻断训练 (教学场景允许小样本试跑). 早停用 sklearn 拆 80/20 (stratify
    保持正负比) + XGBoost early_stopping_rounds=N (验证集 logloss 连续 N 轮不降就停).
    """
    n = len(y)
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    pos_ratio = n_pos / n if n else 0.0

    # 1. 样本量预警: 经验值 25 维 × 50 倍 = 1250 才是稳的最小训练集
    if n < settings.XGB_MIN_SAMPLES:
        logger.warning(
            "样本量 %d < 推荐最小 %d (25 维 × 50 倍经验值), 模型可能欠拟合/过拟合, "
            "建议继续积累评估数据后重训", n, settings.XGB_MIN_SAMPLES,
        )

    # 2. 极不平衡时限制 scale_pos_weight 上限, 防过拟合
    raw_scale = n_neg / n_pos if n_pos > 0 else 1.0
    scale_pos_weight = min(raw_scale, settings.XGB_MAX_SCALE_POS_WEIGHT)
    if raw_scale > settings.XGB_MAX_SCALE_POS_WEIGHT:
        logger.warning(
            "scale_pos_weight %.2f 超过上限 %.2f, 已截断到 %.2f (防止过拟合)",
            raw_scale, settings.XGB_MAX_SCALE_POS_WEIGHT, scale_pos_weight,
        )

    # 【P4-L3 2026-08-08 第二轮】正例比例质量检查: 业务 5% 太低, 训练会假收敛
    if pos_ratio < settings.XGB_MIN_POS_RATIO:
        logger.warning(
            "正例比例 %.1f%% < 推荐最小 %.0f%%, 模型可能假收敛 (logloss 早停但 val_auc 不高).\n"
            "  建议: python scripts/gen_risk_data.py --balance-pos 重造数据",
            100 * pos_ratio, 100 * settings.XGB_MIN_POS_RATIO,
        )
    if pos_ratio > settings.XGB_MAX_POS_RATIO:
        logger.warning(
            "正例比例 %.1f%% > 推荐最大 %.0f%%, 可能标签有噪声 (正常业务高风险 < 30%%)",
            100 * pos_ratio, 100 * settings.XGB_MAX_POS_RATIO,
        )

    # 3. 80/20 stratify 拆分 (验证集保持正负比, 跟训练集一致)
    #    没传 early_stopping_rounds 时 (离线批训练) 跳过 split, 用全量训练
    esr = early_stopping_rounds if early_stopping_rounds is not None else settings.XGB_EARLY_STOPPING_ROUNDS
    if esr and n >= 10:
        X_tr, X_val, y_tr, y_val = train_test_split(
            X, y, test_size=settings.XGB_TEST_SIZE, stratify=y, random_state=42,
        )
        dtrain = xgb.DMatrix(X_tr, label=y_tr, feature_names=FEATURE_COLUMNS)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLUMNS)
        eval_set = [(dtrain, "train"), (dval, "val")]
    else:
        # 小样本或显式关早停 → 用全量训练
        dtrain = xgb.DMatrix(X, label=y, feature_names=FEATURE_COLUMNS)
        eval_set = [(dtrain, "train")]

    # 【P4-L3 2026-08-08 第二轮】训练超参: 加 L1/L2 正则 + 子节点最小权重 + 采样
    # 目的: 防过拟合到噪声, 跟 scale_pos_weight 配合保证模型稳健
    params = {
        "objective": "binary:logistic",         # 二分类, 输出概率
        "max_depth": settings.XGB_MAX_DEPTH,     # 树深度 (从 config, 默认 6)
        "eta": settings.XGB_LEARNING_RATE,      # 学习率 (从 config, 默认 0.1)
        "min_child_weight": settings.XGB_MIN_CHILD_WEIGHT,  # 防噪声
        "reg_alpha": settings.XGB_REG_ALPHA,    # L1
        "reg_lambda": settings.XGB_REG_LAMBDA,  # L2
        "gamma": settings.XGB_GAMMA,            # 分裂最小损失下降
        "subsample": settings.XGB_SUBSAMPLE,    # 样本采样
        "colsample_bytree": settings.XGB_COLSAMPLE_BYTREE,  # 特征采样
        "eval_metric": [settings.XGB_EARLY_STOP_METRIC, "logloss"],  # 早停用 auc, logloss 监控用
        "verbosity": 0,
        "scale_pos_weight": scale_pos_weight,   # P3-M3: 平衡样本
    }

    # 【P4-L3 2026-08-08 第二轮】warmup 防假收敛:
    # XGBoost 2.x early_stopping 监控最后一次提升, 10 轮不升就停.
    # 但如果监控的是 logloss, 不平衡数据下第 5 轮就 "稳定" 在 0.6x (实际模型没学到).
    # 解决: (1) 监控 auc 对不平衡敏感; (2) warmup 前 N 轮不让早停, 给模型充分训练时间.
    if esr and len(eval_set) > 1 and settings.XGB_WARMUP_ROUNDS > 0:
        # 阶段 1: warmup, 前 N 轮训完不评估早停
        warmup_params = {**params, "eval_metric": ["logloss"]}  # warmup 阶段只看 logloss
        warmup_booster = xgb.train(
            warmup_params,
            dtrain,
            num_boost_round=settings.XGB_WARMUP_ROUNDS,
            evals=eval_set,
            verbose_eval=False,
        )
        # 阶段 2: 从 warmup 末继续训, 开启早停监控 auc
        booster = xgb.train(
            params,
            dtrain,
            num_boost_round=num_boost_round,
            evals=eval_set,
            early_stopping_rounds=esr,
            xgb_model=warmup_booster,  # 从 warmup 末继续
            verbose_eval=False,
        )
    else:
        booster = xgb.train(
            params,
            dtrain,
            num_boost_round=num_boost_round,
            evals=eval_set,
            early_stopping_rounds=esr if len(eval_set) > 1 else None,
            verbose_eval=False,
        )

    # 4. 评估: 全量 + 验证集
    y_pred_prob = booster.predict(xgb.DMatrix(X, feature_names=FEATURE_COLUMNS))
    y_pred = (y_pred_prob >= 0.5).astype(int)
    tp = int(np.sum((y_pred == 1) & (y == 1)))
    fp = int(np.sum((y_pred == 1) & (y == 0)))
    fn = int(np.sum((y_pred == 0) & (y == 1)))
    tn = int(np.sum((y_pred == 0) & (y == 0)))
    accuracy = (tp + tn) / n if n else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = f1_score(y, y_pred, zero_division=0)
    auc = roc_auc_score(y, y_pred_prob) if n_pos > 0 and n_neg > 0 else 0.0

    val_metrics = {}
    if len(eval_set) > 1:
        y_val_pred_prob = booster.predict(dval)
        # 【P4-L3 2026-08-08 第二轮】最佳 F1 阈值扫描: 固定 0.5 阈值在不平衡数据上 F1 暴跌
        # (训练集能学, 验证集分布不同 → 预测概率错位). 解决: 遍历 0.1-0.9 找 F1 最高点
        best_f1, best_thr = 0.0, 0.5
        for thr in [round(x * 0.01, 2) for x in range(10, 90, 5)]:  # 0.10, 0.15, ..., 0.85
            y_val_pred_t = (y_val_pred_prob >= thr).astype(int)
            f1_t = f1_score(y_val, y_val_pred_t, zero_division=0)
            if f1_t > best_f1:
                best_f1 = f1_t
                best_thr = thr
        # 用最佳阈值算最终 val_f1 (替换原 0.5 固定阈值)
        y_val_pred = (y_val_pred_prob >= best_thr).astype(int)
        val_acc = float(np.mean(y_val_pred == y_val))
        val_f1 = float(best_f1)
        val_auc = roc_auc_score(y_val, y_val_pred_prob) if len(np.unique(y_val)) > 1 else 0.0
        val_metrics = {
            "n_val": int(len(y_val)),
            "val_accuracy": round(val_acc, 4),
            "val_f1": round(val_f1, 4),
            "val_auc": round(float(val_auc), 4),
            "best_f1_threshold": round(best_thr, 2),  # 验证集 F1 最高的概率阈值
        }

    # 5. 保存
    if model_path:
        save_path = model_path
    else:
        project_root = Path(__file__).resolve().parent.parent.parent
        save_path = str(project_root / settings.XGB_MODEL_PATH)
    booster.save_model(save_path)

    best_iter = booster.best_iteration if hasattr(booster, "best_iteration") and booster.best_iteration is not None else num_boost_round
    logger.info(
        "XGBoost 模型已保存: %s, n=%d, pos=%d (%.1f%%), neg=%d, scale_pos_weight=%.2f, "
        "best_iter=%d, acc=%.4f, auc=%.4f, f1=%.4f",
        save_path, n, n_pos, 100 * pos_ratio, n_neg, scale_pos_weight,
        best_iter, accuracy, auc, f1,
    )

    # 【P4-L3 2026-08-08 第二轮】假收敛检测: 训完不立刻退出, 检查质量是否达标
    # 假收敛 3 特征: (1) best_iter < 阈值 (2) val_auc 低 (3) val_f1 低
    is_fake_convergence = False
    if best_iter < settings.XGB_MIN_BEST_ITER:
        logger.warning(
            "[假收敛嫌疑] best_iter=%d < 推荐最小 %d, 模型可能早早停止, 没学到完整模式. "
            "原因可能是数据不平衡 / 特征没区分度. 建议: --balance-pos 重造数据, 或调高 XGB_WARMUP_ROUNDS",
            best_iter, settings.XGB_MIN_BEST_ITER,
        )
        is_fake_convergence = True
    if val_metrics and val_metrics.get("val_auc", 0) < settings.XGB_MIN_VAL_AUC:
        logger.warning(
            "[模型质量不达标] val_auc=%.4f < 最低 %.2f, 模型区分正负例能力不足. "
            "建议: --balance-pos 重造数据 / 检查 feature.py 25 维是否真的有区分度",
            val_metrics["val_auc"], settings.XGB_MIN_VAL_AUC,
        )
        is_fake_convergence = True
    if val_metrics and val_metrics.get("val_f1", 0) < settings.XGB_MIN_VAL_F1:
        logger.warning(
            "[模型质量不达标] val_f1=%.4f < 最低 %.2f, 召回正例能力不足. "
            "建议: 调高 scale_pos_weight 上限 (XGB_MAX_SCALE_POS_WEIGHT) 或 --balance-pos",
            val_metrics["val_f1"], settings.XGB_MIN_VAL_F1,
        )
    # baseline accuracy 对比 (全预测负例的准确率)
    baseline_acc = n_neg / n if n else 0.0
    if accuracy < baseline_acc + 0.02:
        logger.warning(
            "[模型不如 baseline] acc=%.4f 接近 baseline=%.4f (全预测负例), 模型没学到东西. "
            "建议: --balance-pos + 检查特征",
            accuracy, baseline_acc,
        )

    metrics = {
        "n_train": n,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "pos_ratio": round(pos_ratio, 4),
        "scale_pos_weight": round(scale_pos_weight, 4),
        "raw_scale_pos_weight": round(raw_scale, 4),
        "best_iteration": int(best_iter),
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(float(f1), 4),
        "auc": round(float(auc), 4),
        "model_path": save_path,
        "baseline_accuracy": round(baseline_acc, 4),  # 全预测负例的 acc, 跟实际 acc 对比
        "is_fake_convergence": is_fake_convergence,   # 假收敛嫌疑 (best_iter 低 + val 指标低)
    }
    metrics.update(val_metrics)
    if return_model:
        return metrics, booster
    return metrics


# 启动时自动加载 (其他模块 import 这个文件就触发). 失败不影响业务.
# 【P3-M1 修复 2026-08-07】原代码同步阻塞 import, 改成有 event loop 时用 to_thread 异步加载,
# 裸 import 场景同步加载 (兼容老行为)
def _schedule_load():
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(asyncio.to_thread(load_model))
    except RuntimeError:
        load_model()


_schedule_load()


# ============================================================
# Demo: XGBoost 模型生命周期 + 降级兜底 — 无需训练数据, 纯函数演示
# 跑法: python app/engine/ml_model.py
# ============================================================
if __name__ == "__main__":
    import os
    print("=" * 60)
    print("XGBoost 推理 — 模型生命周期 + 降级兜底")
    print("=" * 60)

    # 1. 模型加载状态
    print("\n[1] 模型状态检查:")
    print(f"  is_model_loaded() = {is_model_loaded()}")
    print(f"  模型路径         = {settings.XGB_MODEL_PATH}")
    print(f"  文件存在         = {os.path.exists(settings.XGB_MODEL_PATH)}")
    if not is_model_loaded():
        print("  (启动时 _schedule_load() 已尝试加载, 文件不在 → 兜底 None)")

    # 2. 特征向量化 (25 维 dict → numpy 数组)
    print("\n[2] 25 维特征 → numpy 数组 (_features_to_array):")
    print(f"  FEATURE_COLUMNS 长度 = {len(FEATURE_COLUMNS)}  (必须是 25, 跟 feature.py 对齐)")
    sample = {
        "user_total_orders": 3, "user_orders_30d": 1, "user_orders_7d": 0,
        "user_total_amount": 5000, "user_avg_order_amount": 1666.67,
        "user_max_order_amount": 3000,
        "user_refund_count": 0, "user_refund_rate": 0.0, "user_refund_amount": 0,
        "user_postsale_count": 0, "user_postsale_rate": 0.0,
        "user_cancel_count": 0, "user_complaint_count": 0, "user_trip_city_count": 1,
        "order_total_amount": 1500, "order_item_count": 1, "order_sku_count": 1,
        "order_discount_amount": 0, "order_discount_rate": 0.0,
        "order_pay_interval_sec": 30, "order_is_night": 0, "order_lead_days": 12,
        "trip_traveler_count": 1, "trip_city_count": 1, "trip_is_new_traveler": 0,
    }
    arr = _features_to_array(sample)
    print(f"  shape           = {arr.shape}  (期望 (1, 25))")
    print(f"  缺失字段数      = {sum(1 for c in FEATURE_COLUMNS if c not in sample)}")
    print(f"  缺失用 0 兜底, dtype = {arr.dtype}")

    # 3. predict 兜底行为 (模型没加载)
    print("\n[3] predict() 行为:")
    res = predict(sample)
    print(f"  模型未加载 → 兜底 score={res.score}, decision={res.decision}")
    print(f"  即: 业务照常运行, ML 分支贡献 0, 走纯规则路径")

    # 4. _prob_to_decision 概率阈值映射
    print("\n[4] P(拒绝) 概率 → 4 档决策:")
    print(f"  {'prob':<6} {'decision':<8}")
    for p in [0.05, 0.30, 0.50, 0.70, 0.85, 0.95]:
        print(f"  {p:<6} {_prob_to_decision(p):<8}")

    # 5. 训练接口存在性 + 现场小规模训练 (300 样本, 演示早停 + AUC + F1)
    print("\n[5] 训练接口 + 现场小训练 (300 样本, 验证早停 + AUC + F1 指标):")
    import inspect
    import tempfile
    sig = inspect.signature(train_and_save)
    print(f"  签名: {sig}")
    np.random.seed(42)
    # 造 300 条, 200 负 100 正 (不均衡, 触发 scale_pos_weight)
    X_demo = np.random.uniform(0, 1, size=(300, 25)).astype(np.float32)
    y_demo = (np.random.rand(300) > 0.66).astype(np.int32)  # 约 100 正
    # 让 user_total_orders (FEATURE_COLUMNS[0]) 强相关 y, 方便看特征重要性
    X_demo[:, 0] = y_demo.astype(np.float32) * 8 + np.random.randn(300) * 0.5
    print(f"  合成数据: n={len(y_demo)}, pos={int(y_demo.sum())} ({100*y_demo.mean():.1f}%)")
    # 用 tmp path 避免覆盖真实模型文件
    with tempfile.TemporaryDirectory() as td:
        demo_path = os.path.join(td, "demo_model.json")
        metrics, _ = train_and_save(
            X_demo, y_demo, model_path=demo_path, num_boost_round=50,
            early_stopping_rounds=10, return_model=True,
        )
    print(f"  训练指标: AUC={metrics['auc']:.4f}, F1={metrics['f1']:.4f}, Acc={metrics['accuracy']:.4f}")
    print(f"  scale_pos_weight={metrics['scale_pos_weight']:.2f} (raw={metrics['raw_scale_pos_weight']:.2f})")
    print(f"  best_iteration={metrics['best_iteration']}")
    if "val_accuracy" in metrics:
        print(f"  验证集: AUC={metrics['val_auc']:.4f}, F1={metrics['val_f1']:.4f}, Acc={metrics['val_accuracy']:.4f}")

    print("\n" + "=" * 60)
    print("总结: 25 维特征对齐 / 模型加载 / predict 兜底 / 概率阈值, 4 个核心能力演示完成")
    print("训练数据准备: python scripts/gen_risk_data_with_dates.py --days 30 --per-day 50")
    print("正式训练:     python scripts/train_xgb_model.py")
