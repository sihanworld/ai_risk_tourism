"""
旅游风控系统 - 教学场景 XGBoost 演示模型训练 (P4-L4 2026-08-08)

【目的】
  不依赖 DB, 纯 numpy 合成 2000 样本, 训练一个针对 30 规则 + 25 特征的合理 XGBoost 模型.
  训完保存到 app/engine/xgb_model.json, run_app.py 启动时直接加载.

【为什么需要这个脚本】
  用户的真实 DB 数据是教学造数据 (gen_risk_data_with_dates.py), 正例比例 < 3%, 训出 val_auc ≈ 0.5.
  这个脚本合成"已知能触发 30 规则"的样本 (高退款率/高投诉/大额/多地址/夜间预订 等),
  训出针对业务场景的合理模型 (val_auc > 0.85).

【6 种高风险模式】
  1. 高退款率 (refund_rate > 0.3, refund_count > 5)
  2. 高投诉 (complaint_count > 3)
  3. 大额订单 (max_order_amount > 15000)
  4. 多地址 (trip_city_count > 3)
  5. 夜间高频 (order_is_night=1 + orders_30d 高)
  6. 混合高风险 (上面多种特征都偏高)

【用法】
  python scripts/train_demo_model.py                    # 默认 2000 样本, 训 200 轮
  python scripts/train_demo_model.py --n 5000            # 5000 样本
  python scripts/train_demo_model.py --model-path ml_models/xgb_demo.json  # 自定义保存路径
"""
import argparse
import os
import random
import sys

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 把项目根目录加到 sys.path, 这样能 import app.*
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split

from app.config import settings
from app.engine.ml_model import FEATURE_COLUMNS, _features_to_array


# ============================================================
# 6 种高风险模式 + 1 种正常用户模式
# 跟 feature.py 25 维特征一一对应, 跟 30 条规则的触发条件对得上
# ============================================================

# 25 维特征顺序 (跟 FEATURE_COLUMNS 一致)
FEATURE_NAMES = FEATURE_COLUMNS
N_FEATURES = len(FEATURE_NAMES)
assert N_FEATURES == 25, f"必须是 25 维特征, 实际 {N_FEATURES}"


def _gen_high_refund_rate(rng: random.Random) -> np.ndarray:
    """模式 1: 高退款率 (触发 R004 '退款率 > 30%' / R006 '退款次数 > 5')"""
    return np.array([
        rng.uniform(5, 30),       # user_total_orders (有退款历史的用户通常订单多)
        rng.uniform(1, 8),        # user_orders_30d
        rng.uniform(0, 3),        # user_orders_7d
        rng.uniform(20000, 100000),  # user_total_amount
        rng.uniform(500, 3000),   # user_avg_order_amount
        rng.uniform(2000, 10000), # user_max_order_amount
        rng.uniform(5, 20),       # user_refund_count  ← 高
        rng.uniform(8, 25),       # user_postsale_count
        rng.uniform(0.3, 0.8),    # user_refund_rate   ← 高
        rng.uniform(0.4, 0.9),    # user_postsale_rate
        rng.uniform(5000, 50000), # user_refund_amount
        rng.uniform(0, 5),        # user_cancel_count
        rng.uniform(0, 2),        # user_complaint_count
        rng.uniform(2, 5),        # user_trip_city_count
        rng.uniform(200, 5000),   # order_total_amount
        rng.uniform(1, 5),        # order_item_count
        rng.uniform(1, 10),       # order_sku_count
        rng.uniform(0, 200),      # order_discount_amount
        rng.uniform(0, 0.1),      # order_discount_rate
        rng.uniform(60, 3600),    # order_pay_interval_sec
        0.0 if rng.random() < 0.7 else 1.0,  # order_is_night
        rng.uniform(1, 4),        # order_lead_days
        rng.uniform(2, 5),        # trip_traveler_count
        rng.uniform(1, 3),        # trip_city_count
        0.0 if rng.random() < 0.5 else 1.0,  # trip_is_new_traveler
    ], dtype=np.float32)


def _gen_high_complaint(rng: random.Random) -> np.ndarray:
    """模式 2: 高投诉 (触发 R013 '投诉次数 > 3' / R014 '投诉率高')"""
    return np.array([
        rng.uniform(10, 40),
        rng.uniform(2, 10),
        rng.uniform(1, 4),
        rng.uniform(30000, 150000),
        rng.uniform(800, 5000),
        rng.uniform(3000, 15000),
        rng.uniform(1, 5),
        rng.uniform(3, 10),
        rng.uniform(0.05, 0.2),
        rng.uniform(0.1, 0.3),
        rng.uniform(500, 5000),
        rng.uniform(0, 3),
        rng.uniform(3, 15),       # user_complaint_count  ← 高
        rng.uniform(2, 6),
        rng.uniform(300, 8000),
        rng.uniform(1, 6),
        rng.uniform(1, 12),
        rng.uniform(0, 300),
        rng.uniform(0, 0.1),
        rng.uniform(120, 7200),
        0.0 if rng.random() < 0.6 else 1.0,
        rng.uniform(1, 5),
        rng.uniform(2, 6),
        rng.uniform(1, 3),
        0.0 if rng.random() < 0.6 else 1.0,
    ], dtype=np.float32)


def _gen_high_amount(rng: random.Random) -> np.ndarray:
    """模式 3: 大额订单 (触发 R007 '单笔金额 > 10000' / R008 '高金额用户')"""
    return np.array([
        rng.uniform(1, 10),
        rng.uniform(0, 3),
        rng.uniform(0, 1),
        rng.uniform(50000, 200000),
        rng.uniform(2000, 10000),
        rng.uniform(15000, 50000),  # user_max_order_amount  ← 高
        rng.uniform(0, 2),
        rng.uniform(0, 3),
        rng.uniform(0, 0.1),
        rng.uniform(0, 0.1),
        rng.uniform(0, 2000),
        rng.uniform(0, 2),
        rng.uniform(0, 1),
        rng.uniform(1, 3),
        rng.uniform(10000, 50000),  # order_total_amount  ← 高
        rng.uniform(1, 4),
        rng.uniform(1, 8),
        rng.uniform(0, 500),
        rng.uniform(0, 0.05),
        rng.uniform(30, 1800),
        0.0 if rng.random() < 0.8 else 1.0,
        rng.uniform(1, 3),
        rng.uniform(1, 3),
        rng.uniform(1, 2),
        0.0 if rng.random() < 0.7 else 1.0,
    ], dtype=np.float32)


def _gen_multi_address(rng: random.Random) -> np.ndarray:
    """模式 4: 多地址 (触发 R011 '多省份地址 > 3')"""
    return np.array([
        rng.uniform(5, 20),
        rng.uniform(1, 6),
        rng.uniform(0, 3),
        rng.uniform(15000, 60000),
        rng.uniform(500, 3000),
        rng.uniform(2000, 8000),
        rng.uniform(0, 3),
        rng.uniform(1, 5),
        rng.uniform(0, 0.15),
        rng.uniform(0.05, 0.2),
        rng.uniform(0, 3000),
        rng.uniform(0, 3),
        rng.uniform(0, 2),
        rng.uniform(5, 10),       # user_trip_city_count  ← 高
        rng.uniform(300, 5000),
        rng.uniform(1, 4),
        rng.uniform(1, 8),
        rng.uniform(0, 200),
        rng.uniform(0, 0.1),
        rng.uniform(60, 3600),
        0.0 if rng.random() < 0.5 else 1.0,
        rng.uniform(2, 5),
        rng.uniform(5, 10),       # trip_traveler_count  ← 高
        rng.uniform(3, 7),        # trip_city_count  ← 高
        0.0 if rng.random() < 0.4 else 1.0,  # trip_is_new_traveler
    ], dtype=np.float32)


def _gen_night_high_freq(rng: random.Random) -> np.ndarray:
    """模式 5: 夜间高频 (触发 R012 '0-6点预订' / '近期订单激增')"""
    return np.array([
        rng.uniform(10, 40),
        rng.uniform(5, 15),       # user_orders_30d  ← 高
        rng.uniform(2, 6),        # user_orders_7d
        rng.uniform(20000, 80000),
        rng.uniform(300, 2000),
        rng.uniform(1500, 6000),
        rng.uniform(0, 3),
        rng.uniform(0, 4),
        rng.uniform(0, 0.1),
        rng.uniform(0, 0.15),
        rng.uniform(0, 2000),
        rng.uniform(0, 3),
        rng.uniform(0, 1),
        rng.uniform(1, 3),
        rng.uniform(200, 3000),
        rng.uniform(1, 4),
        rng.uniform(1, 6),
        rng.uniform(0, 150),
        rng.uniform(0, 0.1),
        rng.uniform(30, 1200),    # order_pay_interval_sec (快)
        1.0,                     # order_is_night  ← 必为 1
        rng.uniform(1, 3),
        rng.uniform(1, 3),
        rng.uniform(1, 2),
        0.0 if rng.random() < 0.5 else 1.0,
    ], dtype=np.float32)


def _gen_mixed_high_risk(rng: random.Random) -> np.ndarray:
    """模式 6: 混合高风险 (多种特征都偏高, 最难判但学习价值高)"""
    return np.array([
        rng.uniform(15, 50),
        rng.uniform(3, 12),
        rng.uniform(1, 5),
        rng.uniform(40000, 150000),
        rng.uniform(800, 4000),
        rng.uniform(8000, 30000),  # max_order_amount 高
        rng.uniform(3, 12),       # refund_count 中高
        rng.uniform(5, 20),
        rng.uniform(0.15, 0.5),   # refund_rate 中高
        rng.uniform(0.2, 0.6),
        rng.uniform(2000, 30000),
        rng.uniform(0, 4),
        rng.uniform(1, 6),        # complaint_count 中
        rng.uniform(3, 8),        # trip_city_count 高
        rng.uniform(2000, 20000), # order_total_amount 中高
        rng.uniform(1, 6),
        rng.uniform(2, 12),
        rng.uniform(0, 400),
        rng.uniform(0, 0.1),
        rng.uniform(30, 1800),    # 快支付
        0.4 if rng.random() < 0.6 else 1.0,  # is_night 中高概率
        rng.uniform(2, 5),
        rng.uniform(3, 8),        # addr_total 高
        rng.uniform(2, 5),        # addr_province 中高
        0.3 if rng.random() < 0.7 else 1.0,  # trip_is_new_traveler 中高
    ], dtype=np.float32)


def _gen_normal_user(rng: random.Random) -> np.ndarray:
    """正常用户 (低风险, 通过/标记)."""
    return np.array([
        rng.uniform(0, 5),        # user_total_orders 少
        rng.uniform(0, 2),        # user_orders_30d
        rng.uniform(0, 1),        # user_orders_7d
        rng.uniform(0, 10000),    # user_total_amount 少
        rng.uniform(0, 1000),     # user_avg_order_amount
        rng.uniform(0, 3000),     # user_max_order_amount  ← 低
        rng.uniform(0, 1),        # user_refund_count  ← 低
        rng.uniform(0, 2),        # user_postsale_count
        rng.uniform(0, 0.05),     # user_refund_rate  ← 低
        rng.uniform(0, 0.1),      # user_postsale_rate
        rng.uniform(0, 500),      # user_refund_amount
        rng.uniform(0, 1),        # user_cancel_count
        rng.uniform(0, 1),        # user_complaint_count  ← 低
        rng.uniform(1, 2),        # user_trip_city_count
        rng.uniform(0, 1500),     # order_total_amount
        rng.uniform(1, 3),        # order_item_count
        rng.uniform(1, 5),        # order_sku_count
        rng.uniform(0, 100),      # order_discount_amount
        rng.uniform(0, 0.1),      # order_discount_rate
        rng.uniform(120, 7200),   # order_pay_interval_sec (正常)
        0.0 if rng.random() < 0.85 else 1.0,  # order_is_night  ← 大概率白天
        rng.uniform(1, 3),        # order_lead_days
        rng.uniform(1, 2),        # trip_traveler_count
        1.0,                     # trip_city_count  ← 1 个省
        0.0 if rng.random() < 0.8 else 1.0,  # trip_is_new_traveler  ← 大概率老地址
    ], dtype=np.float32)


# 6 种正例模式 + 1 种负例
POSITIVE_PATTERNS = [
    _gen_high_refund_rate, _gen_high_complaint, _gen_high_amount,
    _gen_multi_address, _gen_night_high_freq, _gen_mixed_high_risk,
]
NEGATIVE_PATTERN = _gen_normal_user


def gen_synthetic_dataset(n: int = 2000, pos_ratio: float = 0.5, seed: int = 42):
    """生成合成训练数据集.

    Args:
        n: 总样本数
        pos_ratio: 正例比例 (默认 0.5)
        seed: 随机种子

    Returns:
        X: (N, 25) float32
        y: (N,) int (0/1)
    """
    rng = random.Random(seed)
    np.random.seed(seed)

    n_pos = int(n * pos_ratio)
    n_neg = n - n_pos

    # 正例: 6 种模式轮换
    X_pos = np.zeros((n_pos, N_FEATURES), dtype=np.float32)
    for i in range(n_pos):
        pattern = POSITIVE_PATTERNS[i % len(POSITIVE_PATTERNS)]
        X_pos[i] = pattern(rng)

    # 负例: 1 种模式
    X_neg = np.zeros((n_neg, N_FEATURES), dtype=np.float32)
    for i in range(n_neg):
        X_neg[i] = NEGATIVE_PATTERN(rng)

    X = np.vstack([X_pos, X_neg])
    y = np.concatenate([np.ones(n_pos, dtype=np.int32), np.zeros(n_neg, dtype=np.int32)])

    # 乱序
    idx = np.random.permutation(n)
    return X[idx], y[idx]


def train_xgboost(X: np.ndarray, y: np.ndarray, num_boost_round: int = 200):
    """训练 XGBoost (用 ml_model.py 的同款超参, 保持一致)."""
    # 80/20 stratify
    X_tr, X_val, y_tr, y_val = train_test_split(
        X, y, test_size=settings.XGB_TEST_SIZE, stratify=y, random_state=42,
    )

    # DMatrix (XGBoost 2.x 必须)
    dtrain = xgb.DMatrix(X_tr, label=y_tr, feature_names=FEATURE_NAMES)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_NAMES)

    # 训练参数 (跟 ml_model.py 一致, 但简化版)
    params = {
        "objective": "binary:logistic",
        "eval_metric": ["logloss", "auc"],
        "max_depth": 6,
        "learning_rate": 0.1,
        "min_child_weight": 3,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "seed": 42,
        "tree_method": "hist",
    }

    print(f"\n[训练] {len(y_tr)} 训练 / {len(y_val)} 验证 (80/20 stratify)")
    print(f"  正例比例: {y_tr.sum()/len(y_tr):.2%} (训练) / {y_val.sum()/len(y_val):.2%} (验证)")

    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=10,
        verbose_eval=20,
    )

    # 评估
    y_pred_prob = booster.predict(xval_dmatrix := xgb.DMatrix(X_val, feature_names=FEATURE_NAMES))
    y_pred = (y_pred_prob >= 0.5).astype(int)

    tp = int(np.sum((y_pred == 1) & (y_val == 1)))
    fp = int(np.sum((y_pred == 1) & (y_val == 0)))
    fn = int(np.sum((y_pred == 0) & (y_val == 1)))
    tn = int(np.sum((y_pred == 0) & (y_val == 0)))

    from sklearn.metrics import roc_auc_score, f1_score
    val_auc = roc_auc_score(y_val, y_pred_prob)
    val_f1 = f1_score(y_val, y_pred)
    val_acc = (tp + tn) / len(y_val)

    print(f"\n[验证集]")
    print(f"  AUC = {val_auc:.4f} {'OK' if val_auc > 0.85 else 'WARN (推荐 > 0.85)'}")
    print(f"  F1  = {val_f1:.4f} {'OK' if val_f1 > 0.6 else 'WARN (推荐 > 0.6)'}")
    print(f"  Acc = {val_acc:.4f}")
    print(f"  Confusion: TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  Best iter: {booster.best_iteration}")

    return booster, val_auc, val_f1


def main():
    parser = argparse.ArgumentParser(
        description="教学场景 XGBoost 演示模型训练 (不依赖 DB, 纯合成数据)"
    )
    parser.add_argument("--n", type=int, default=2000, help="合成样本数 (默认 2000)")
    parser.add_argument("--pos-ratio", type=float, default=0.5, help="正例比例 (默认 0.5)")
    parser.add_argument("--num-boost-round", type=int, default=200, help="XGBoost 迭代轮数 (默认 200)")
    parser.add_argument("--model-path", type=str,
                        default=os.path.join(PROJECT_ROOT, "app", "engine", "xgb_model.json"),
                        help="模型保存路径 (默认 app/engine/xgb_model.json)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子 (默认 42)")
    args = parser.parse_args()

    print("=" * 70)
    print("教学场景 XGBoost 演示模型训练")
    print("=" * 70)
    print(f"样本数: {args.n} (正例 {args.pos_ratio*100:.0f}% / 负例 {(1-args.pos_ratio)*100:.0f}%)")
    print(f"模型保存: {args.model_path}")
    print("=" * 70)

    # 1. 生成合成数据
    print(f"\n[1/3] 生成 {args.n} 合成样本 (6 种高风险模式 + 1 种正常模式)...")
    X, y = gen_synthetic_dataset(n=args.n, pos_ratio=args.pos_ratio, seed=args.seed)
    print(f"  X.shape={X.shape}, 正例={int(y.sum())} ({y.mean():.2%})")

    # 2. 训练
    print("\n[2/3] 训练 XGBoost...")
    booster, val_auc, val_f1 = train_xgboost(X, y, num_boost_round=args.num_boost_round)

    # 3. 保存
    print(f"\n[3/3] 保存模型到 {args.model_path}...")
    os.makedirs(os.path.dirname(args.model_path), exist_ok=True)
    booster.save_model(args.model_path)
    size_kb = os.path.getsize(args.model_path) / 1024
    print(f"  模型文件: {size_kb:.1f} KB")

    print("\n" + "=" * 70)
    print("训练完成!")
    print(f"  val_auc = {val_auc:.4f} {'OK' if val_auc > 0.85 else '< 0.85 警告'}")
    print(f"  val_f1  = {val_f1:.4f} {'OK' if val_f1 > 0.6 else '< 0.6 警告'}")
    print("=" * 70)
    print("下一步:")
    print("  python run_app.py                    # 启动 Web 服务, 自动加载此模型")
    print("  浏览器访问 http://localhost:8000       # 风险检查页能看到 XGBoost 评分")
    print("=" * 70)


if __name__ == "__main__":
    main()
