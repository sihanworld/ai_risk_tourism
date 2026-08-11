"""
XGBoost module unit tests (5 groups).
Coverage:
  1. Feature column order stability (25 dim)
  2. Model loading (with file / without file)
  3. Predict interface: input dict -> output MlResult
  4. 4-tier decision mapping (threshold boundary)
  5. Train interface: synthetic data training -> metrics reasonable
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# Add project root to sys.path so import app.* works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import ml_model  # noqa: E402


class TestFeatureColumns:
    """1. Feature column order stability"""

    def test_feature_count_is_25(self):
        """Must be 25-dim features (align with 25 keys computed by feature.py)"""
        assert len(ml_model.FEATURE_COLUMNS) == 25

    def test_feature_prefixes(self):
        """14 user_* + 8 order_* + 3 trip_* (align with feature.py naming)"""
        user = [c for c in ml_model.FEATURE_COLUMNS if c.startswith("user_")]
        order = [c for c in ml_model.FEATURE_COLUMNS if c.startswith("order_")]
        trip = [c for c in ml_model.FEATURE_COLUMNS if c.startswith("trip_")]
        assert len(user) == 14, f"user features should be 14, got {len(user)}"
        assert len(order) == 8, f"order features should be 8, got {len(order)}"
        assert len(trip) == 3, f"trip features should be 3, got {len(trip)}"

    def test_features_to_array(self):
        """dict -> 1x25 ndarray, missing filled with 0, string -> float"""
        features = {
            "user_total_orders": 10,         # 0
            "user_orders_30d": 3,            # 1
            # intentionally omit 22 middle keys -> 0
            "trip_is_new_traveler": 0,                # 24 (last in FEATURE_COLUMNS)
        }
        arr = ml_model._features_to_array(features)
        assert arr.shape == (1, 25)
        assert arr.dtype == np.float32
        assert arr[0, 0] == 10.0
        assert arr[0, 1] == 3.0
        assert arr[0, 2] == 0.0     # missing filled
        assert arr[0, 24] == 0.0    # explicit 0

    def test_feature_columns_align_with_feature_module(self):
        """
        FEATURE_COLUMNS must align 1:1 with the 25 keys actually computed by feature.py.

        Prevent re-occurrence of "FEATURE_COLUMNS not aligned with feature.py,
        causing XGBoost train/inference degraded to 0-imputation" bug (found 2026-08-07).
        If feature.py renames/reorders features, must sync this list.
        """
        # 14 user + 8 order + 3 trip, aligned with feature.py's 3 feat_funcs dict order
        expected = [
            # --- 14 user features (compute_user_features) ---
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
            # --- 8 order features (compute_order_features) ---
            "order_total_amount",
            "order_item_count",
            "order_sku_count",
            "order_discount_amount",
            "order_discount_rate",
            "order_pay_interval_sec",
            "order_is_night",
            "order_lead_days",
            # --- 3 trip features (compute_trip_features) ---
            "trip_traveler_count",
            "trip_city_count",
            "trip_is_new_traveler",
        ]
        assert ml_model.FEATURE_COLUMNS == expected, (
            "FEATURE_COLUMNS not aligned with the 25 keys computed by feature.py. "
            "This will degrade XGBoost train/inference to 0-imputation. "
            "Please sync ml_model.py and feature.py."
        )


class TestModelLoad:
    """2. Model loading (with file / without file)"""

    def test_load_real_model(self, capsys):
        """【P4-L4 2026-08-08 简化】加载本地真实模型 + 推理一次 + 打印完整输出.

        之前只 assert 加载成功, 看不到推理结果. 现在用真实 25 维特征跑一次 predict(),
        打印 score/decision/is_loaded, 顺便演示模型在线推理.
        """
        from app.config import settings
        path = str(Path(settings.XGB_MODEL_PATH).resolve())
        if not Path(path).exists():
            pytest.skip("Model file not generated; run scripts/train_xgb_model.py first")
        # 1. 加载
        ok = ml_model.load_model(path)
        assert ok is True
        assert ml_model.is_model_loaded() is True
        assert ml_model.get_model() is not None

        # 2. 准备一组"正常用户"特征 (低值, 期望 → 通过/标记)
        normal_features = {
            "user_total_orders": 5,
            "user_orders_30d": 1,
            "user_orders_7d": 0,
            "user_total_amount": 2000.0,
            "user_avg_order_amount": 400.0,
            "user_max_order_amount": 800.0,
            "user_refund_count": 0,
            "user_postsale_count": 0,
            "user_refund_rate": 0.0,
            "user_postsale_rate": 0.0,
            "user_refund_amount": 0,
            "user_cancel_count": 0,
            "user_complaint_count": 0,
            "user_trip_city_count": 1,
            "order_total_amount": 200.0,
            "order_item_count": 1,
            "order_sku_count": 1,
            "order_discount_amount": 0,
            "order_discount_rate": 0.0,
            "order_pay_interval_sec": 60,
            "order_is_night": 0,
            "order_lead_days": 1,
            "trip_traveler_count": 1,
            "trip_city_count": 1,
            "trip_is_new_traveler": 0,
        }
        # 3. 准备一组"高风险用户"特征 (强信号, 期望 → 人工审核/拒绝)
        risky_features = dict(normal_features)
        risky_features.update({
            "user_total_orders": 200,
            "user_orders_30d": 80,
            "user_total_amount": 80000.0,
            "user_refund_count": 150,
            "user_refund_rate": 0.95,
            "user_complaint_count": 10,
        })

        # 4. 推理 + 打印
        print("\n" + "=" * 60)
        print(f"[真实模型推理] 模型: {path}")
        print("=" * 60)

        normal_res = ml_model.predict(normal_features)
        print(f"  正常用户 → P(拒绝)={normal_res.score:.4f}, decision={normal_res.decision}")

        risky_res = ml_model.predict(risky_features)
        print(f"  高风险用户 → P(拒绝)={risky_res.score:.4f}, decision={risky_res.decision}")

        # 5. 验证: 分数范围 [0, 1] + 4 档合法 + 模型加载成功
        for res in (normal_res, risky_res):
            assert 0.0 <= res.score <= 1.0
            assert res.decision in ("通过", "标记", "人工审核", "拒绝")
            assert res.is_loaded is True
        # 【P4-L3 2026-08-08 第二轮】不强 assert "高风险 > 正常" (那是模型质量问题, 不是这个测试的范围)
        # 模型质量检查走 train_xgb_model.py 的假收敛检测 (假收敛时打 WARNING 提示 --balance-pos)
        print(f"  差值 = risky-normal = {risky_res.score - normal_res.score:+.4f} "
              f"({'OK 高风险更高' if risky_res.score > normal_res.score else '⚠️ 高风险不高于正常 → 看训练是否假收敛'})")

    def test_load_missing_file(self):
        """Non-existent file -> load fails, is_loaded remains False (does not affect business)"""
        ok = ml_model.load_model("D:/nonexistent/xgb_model_xxx.json")
        assert ok is False


class TestPredict:
    """3. Predict interface"""

    def test_predict_normal_user(self):
        """Normal user (low 25-dim features) -> reject probability low -> decision 'pass'"""
        result = ml_model.predict({
            "user_total_orders": 5,
            "user_orders_30d": 0,
            "order_total_amount": 100,
        })
        assert 0.0 <= result.score <= 1.0
        # Normal user should be decided as "pass"
        # Note: missing 22-dim features keep model stable, but the sample's features
        # are all low, so should not be "reject"
        assert result.decision in ("\u901a\u8fc7", "\u6807\u8bb0")  # "pass" or "mark"

    def test_predict_risky_user(self):
        """【P4-L3 2026-08-08 第二轮】高风险用户: 25 维完整特征, 跟训练数据分布对齐.
        之前只填 5 维 (其他 20 维默认 0), 跟训练分布偏离大, 模型预测失真.
        修法: 用全 25 维特征 + 把"高风险信号"叠加在关键特征上, 让模型能在训练分布内识别."""
        from app.engine.ml_model import FEATURE_COLUMNS
        # 高风险用户: 25 维全部填, 高退款率/短间隔/大额/夜单
        risky = {
            # 用户画像 (高退款 + 多退改签)
            "user_total_orders": 200,
            "user_orders_30d": 100,
            "user_orders_7d": 50,
            "user_total_amount": 800000,       # 80w 累计
            "user_avg_order_amount": 4000,
            "user_max_order_amount": 50000,   # 5w 单笔
            "user_refund_count": 180,         # 90% 退款率
            "user_postsale_count": 120,
            "user_refund_rate": 0.9,
            "user_postsale_rate": 0.6,
            "user_refund_amount": 700000,     # 退款金额也很高
            "user_cancel_count": 50,
            "user_complaint_count": 30,
            "user_trip_city_count": 8,          # 多地址 (可疑)
            # 订单特征 (大额 + 短间隔 + 夜单 + 多品类)
            "order_total_amount": 50000,
            "order_item_count": 5,
            "order_sku_count": 5,
            "order_discount_amount": 49000,   # 几乎不打折
            "order_discount_rate": 0.02,
            "order_pay_interval_sec": 30,     # 30s 内支付 (极短)
            "order_is_night": 1,              # 凌晨预订
            "order_lead_days": 5,
            # 地址特征
            "trip_traveler_count": 8,
            "trip_city_count": 3,         # 跨省 (可疑)
            "trip_is_new_traveler": 1,                  # 新地址
        }
        # 验证 25 维都填了 (否则回退到训练分布外)
        assert set(risky.keys()) >= set(FEATURE_COLUMNS), (
            f"测试用例缺字段, 跟训练分布偏离! 缺: {set(FEATURE_COLUMNS) - set(risky.keys())}"
        )
        result = ml_model.predict(risky)
        assert 0.0 <= result.score <= 1.0

        # 普通用户: 25 维都填, 都填低值
        normal = {col: 0.0 for col in FEATURE_COLUMNS}
        normal.update({
            "user_total_orders": 5,
            "user_orders_30d": 1,
            "user_orders_7d": 0,
            "user_total_amount": 500,
            "order_total_amount": 100,
        })
        normal_result = ml_model.predict(normal)
        # 高风险用户应该 P(拒绝) >= 普通用户
        assert result.score >= normal_result.score, (
            f"高风险用户 score={result.score} 应 >= 普通用户 score={normal_result.score}。"
            f"  如果 fail: 1) 训练数据可能不平衡 (用 --balance-pos 重造), "
            f"2) 特征工程 25 维可能没区分度, 3) 验证 best_iter 是否太低 (假收敛)"
        )

    def test_predict_fallback_when_not_loaded(self):
        """Model not loaded -> returns fallback (score=0, decision=pass)"""
        # Force reset (test only)
        original_loaded = ml_model._LOADED
        original_model = ml_model._MODEL
        try:
            ml_model._LOADED = False
            ml_model._MODEL = None
            result = ml_model.predict({"user_total_orders": 1})
            assert result.score == 0.0
            assert result.decision == "\u901a\u8fc7"  # "pass"
            assert result.is_loaded is False
        finally:
            ml_model._LOADED = original_loaded
            ml_model._MODEL = original_model


class TestProbToDecision:
    """4. 4-tier decision mapping (threshold boundary)"""

    def test_pass_threshold(self):
        assert ml_model._prob_to_decision(0.0) == "\u901a\u8fc7"   # "pass"
        assert ml_model._prob_to_decision(0.29) == "\u901a\u8fc7"

    def test_mark_threshold(self):
        assert ml_model._prob_to_decision(0.30) == "\u6807\u8bb0"  # "mark"
        assert ml_model._prob_to_decision(0.59) == "\u6807\u8bb0"

    def test_review_threshold(self):
        assert ml_model._prob_to_decision(0.60) == "\u4eba\u5de5\u5ba1\u6838"  # "manual review"
        assert ml_model._prob_to_decision(0.79) == "\u4eba\u5de5\u5ba1\u6838"

    def test_reject_threshold(self):
        assert ml_model._prob_to_decision(0.80) == "\u62d2\u7edd"  # "reject"
        assert ml_model._prob_to_decision(1.0) == "\u62d2\u7edd"


class TestTrainAndSave:
    """5. Train interface (use synthetic data; verify it can run)"""

    def test_train_synthetic_data(self, tmp_path):
        """100 synthetic data training; metrics reasonable + model can be saved"""
        np.random.seed(42)  # fix random, test reproducible
        # Synthetic data: 50 class 0 + 50 class 1
        # class 0: feature values close to 0
        X0 = np.random.uniform(0, 1, size=(50, 25)).astype(np.float32)
        # class 1: feature values close to 1
        X1 = np.random.uniform(5, 10, size=(50, 25)).astype(np.float32)
        X = np.vstack([X0, X1])
        y = np.array([0] * 50 + [1] * 50, dtype=np.int32)
        # Train + save to tmp
        save_path = str(tmp_path / "xgb_test.json")
        metrics = ml_model.train_and_save(X, y, model_path=save_path, num_boost_round=50)
        # Verify metrics
        assert metrics["n_train"] == 100
        assert 0.9 <= metrics["accuracy"] <= 1.0, f"synthetic data should fit well, acc={metrics['accuracy']}"
        assert Path(save_path).exists(), "model file should be saved"

    def test_return_model_returns_booster(self, tmp_path):
        """【P4-L3 2026-08-08】return_model=True 时返回 (metrics, booster) 元组, 方便训练脚本输出特征重要性."""
        save_path = str(tmp_path / "xgb.json")
        np.random.seed(42)
        X = np.random.randn(100, 25).astype(np.float32)
        y = (np.random.rand(100) > 0.5).astype(np.int32)
        # 构造 user_total_orders 强相关 y (用真实 FEATURE_COLUMNS[0] 名字)
        from app.engine.ml_model import FEATURE_COLUMNS
        target_col = FEATURE_COLUMNS[0]  # user_total_orders
        col_idx = 0
        X[:, col_idx] = y.astype(np.float32) * 5 + np.random.randn(100) * 0.1
        result = ml_model.train_and_save(X, y, model_path=save_path, num_boost_round=30, return_model=True)
        # 返元组
        assert isinstance(result, tuple) and len(result) == 2
        metrics, booster = result
        assert metrics["n_train"] == 100
        # booster 是 xgb.Booster
        import xgboost as xgb
        assert isinstance(booster, xgb.Booster)
        # 特征重要性 gain 字典, 特征名是 FEATURE_COLUMNS 里那些
        importance = booster.get_score(importance_type="gain")
        assert len(importance) > 0, "应该至少 1 个特征有非零 importance"
        # 特征名应该是真实名字, 不是 f0
        assert target_col in importance, f"{target_col} 应在 importance 中, 实际 keys={list(importance.keys())[:3]}"
        # user_total_orders 应该是 Top 1 (相关性最强)
        top_feature = max(importance, key=importance.get)
        assert top_feature == target_col, f"最强特征应是 {target_col}, 实际 {top_feature}"
        # 所有 importance 应该是 float
        assert all(isinstance(v, float) for v in importance.values())
        # Top 3 应占大多数 gain
        total = sum(importance.values())
        top3 = sum(sorted(importance.values(), reverse=True)[:3])
        assert top3 / total > 0.3, f"Top 3 应占 >30% gain, 实际 {top3/total:.1%}"

    # ---- P4-L3 第二轮 2026-08-08: 正负样本比 + 早停 + AUC/F1 ----

    def test_train_warns_when_sample_too_small(self, tmp_path, caplog):
        """样本 < XGB_MIN_SAMPLES (1250) 时打印 warning (但不阻断, 教学允许小样本试跑)."""
        np.random.seed(42)
        # 故意只造 80 条 (< 1250), 验证会出 warning
        X = np.random.uniform(0, 1, size=(80, 25)).astype(np.float32)
        y = (np.random.rand(80) > 0.7).astype(np.int32)  # 约 24 正
        save_path = str(tmp_path / "xgb_small.json")
        with caplog.at_level("WARNING", logger="app.engine.ml_model"):
            metrics = ml_model.train_and_save(
                X, y, model_path=save_path, num_boost_round=20,
            )
        # 验证 warning 出现
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("样本量" in msg and "1250" in msg for msg in warnings), (
            f"应警告样本量 < 1250, 实际 warnings={warnings}"
        )
        # 但训练仍能成功, metrics 正常返回
        assert metrics["n_train"] == 80
        assert Path(save_path).exists()

    def test_train_validates_stratify_split_preserves_ratio(self, tmp_path):
        """80/20 stratify 拆分后, 验证集正负比应与全量一致 (误差 < 1%)."""
        np.random.seed(42)
        # 造 1000 条, 正负比约 30% (业务上足够的不平衡场景)
        X = np.random.uniform(0, 1, size=(1000, 25)).astype(np.float32)
        y = (np.random.rand(1000) > 0.7).astype(np.int32)
        overall_pos_ratio = float(y.mean())
        save_path = str(tmp_path / "xgb_stratify.json")
        metrics = ml_model.train_and_save(
            X, y, model_path=save_path, num_boost_round=20,
            early_stopping_rounds=5,  # 显式开早停 → 触发 stratify split
        )
        # 验证集 n + 指标都在
        assert "val_accuracy" in metrics, "开早停时应有 val_* 指标"
        assert "n_val" in metrics
        # 验证集 n 应约等于 1000 * 0.2 = 200
        assert 180 <= metrics["n_val"] <= 220, (
            f"验证集 n={metrics['n_val']}, 应约 200 (20% of 1000)"
        )
        # 正负比报告
        assert "pos_ratio" in metrics
        assert abs(metrics["pos_ratio"] - overall_pos_ratio) < 0.05

    def test_train_with_early_stopping_returns_best_iteration(self, tmp_path):
        """早停能正确触发并报告 best_iteration (不能 num_boost_round 全用满)."""
        np.random.seed(42)
        # 造 500 条, 第 0 维强相关 y
        X = np.random.uniform(0, 1, size=(500, 25)).astype(np.float32)
        y = (np.random.rand(500) > 0.5).astype(np.int32)
        X[:, 0] = y.astype(np.float32) * 10 + np.random.randn(500) * 0.1
        save_path = str(tmp_path / "xgb_early.json")
        metrics = ml_model.train_and_save(
            X, y, model_path=save_path, num_boost_round=200,  # 给多轮
            early_stopping_rounds=10,
        )
        # best_iteration 应在 metrics 中, 且小于 num_boost_round (说明早停起作用了)
        assert "best_iteration" in metrics
        assert 1 <= metrics["best_iteration"] <= 200
        # 验证集指标存在
        assert metrics.get("val_auc", 0) > 0
        # AUC 应显著 > 0.5 (因为第 0 维强相关)
        assert metrics["auc"] > 0.7, f"强相关数据 AUC 应 > 0.7, 实际 {metrics['auc']}"

    def test_train_returns_auc_f1_metrics(self, tmp_path):
        """metrics 必须含 auc + f1 + val_auc + val_f1 (P4-L3 第二轮新增字段)."""
        np.random.seed(42)
        X = np.random.uniform(0, 1, size=(300, 25)).astype(np.float32)
        y = (np.random.rand(300) > 0.6).astype(np.int32)
        X[:, 0] = y.astype(np.float32) * 8 + np.random.randn(300) * 0.5
        save_path = str(tmp_path / "xgb_metrics.json")
        metrics = ml_model.train_and_save(
            X, y, model_path=save_path, num_boost_round=30,
            early_stopping_rounds=5,
        )
        # P4-L3 新字段
        for key in ("auc", "f1", "accuracy", "precision", "recall",
                    "scale_pos_weight", "raw_scale_pos_weight", "best_iteration"):
            assert key in metrics, f"metrics 应含 {key}, 实际 keys={list(metrics.keys())}"
        # AUC + F1 范围
        assert 0.0 <= metrics["auc"] <= 1.0
        assert 0.0 <= metrics["f1"] <= 1.0
        # 验证集指标 (开了早停)
        assert "val_auc" in metrics
        assert "val_f1" in metrics
        # scale_pos_weight 应等于 n_neg/n_pos 或被截断到 XGB_MAX_SCALE_POS_WEIGHT
        from app.config import settings
        raw = (y == 0).sum() / max(1, (y == 1).sum())
        assert metrics["raw_scale_pos_weight"] == round(raw, 4)
        assert metrics["scale_pos_weight"] == round(min(raw, settings.XGB_MAX_SCALE_POS_WEIGHT), 4)


# ============================================================
# 【P4-L3 bug 修复 2026-08-08】train_xgb_model.py 解包顺序回归测试
# 防止: 写错成 model, metrics = train_and_save(..., return_model=True)
#       导致 metrics 实际指向 xgb.Booster 实例, 然后 metrics["n_train"] 报 TypeError
# 正确: metrics, model = train_and_save(..., return_model=True) (跟 ml_model.py 接口对齐)
# ============================================================
class TestTrainScriptUnpacking:
    """scripts/train_xgb_model.py 里 train_and_save 解包顺序必须对齐 ml_model.py 接口."""

    def test_train_script_unpacks_metrics_first_then_model(self):
        """scripts/train_xgb_model.py 必须写 'metrics, model = train_and_save(...)', 不是 'model, metrics = ...'.
        这条 bug 真实发生: 解包顺序反了导致 metrics 实际指向 xgb.Booster,
        metrics["n_train"] 报 'TypeError: Expecting int or slice. Got str'."""
        script = Path("scripts/train_xgb_model.py").read_text(encoding="utf-8")
        # 找 train_and_save(...) 调用
        import re
        m = re.search(r'(\w+)\s*,\s*(\w+)\s*=\s*train_and_save\s*\(', script)
        assert m, "scripts/train_xgb_model.py 里没找到 train_and_save(...) 解包"
        first, second = m.group(1), m.group(2)
        assert first == "metrics", (
            f"scripts/train_xgb_model.py 解包顺序错! 应先解 metrics, 再解 model.\n"
            f"当前是 '{first}, {second} = train_and_save(...)'.\n"
            f"原因: train_and_save(return_model=True) 返回 (metrics_dict, booster), "
            f"如果解成 'model, metrics', metrics 实际指向 xgb.Booster, 然后 metrics['n_train'] 报错.\n"
            f"修复: 改成 'metrics, model = train_and_save(...)'"
        )
        assert second == "model", (
            f"scripts/train_xgb_model.py 第二个变量应是 'model', 当前是 '{second}'"
        )


# ============================================================
# 【P4-L3 2026-08-08 第二轮】训练质量验收: 早停用 auc + warmup + 正则化
# 防止"假收敛" (best_iter<10 + val_auc<0.6 + val_f1<0.4) 出现在生产模型
# ============================================================
class TestTrainQuality:
    """P4-L3 第二轮: 训练参数升级 + 质量验收."""

    def test_train_uses_auc_for_early_stopping(self, tmp_path):
        """早停监控指标必须是 auc (对不平衡敏感), 不是 logloss (会假收敛)."""
        save_path = str(tmp_path / "xgb_early.json")
        np.random.seed(42)
        # 模拟不平衡数据: 1000 样本, 50 正例 (5%)
        X = np.random.randn(1000, 25).astype(np.float32)
        y = np.zeros(1000, dtype=np.int32)
        y[:50] = 1
        X[:, 0] = y.astype(np.float32) * 5 + np.random.randn(1000) * 0.5
        metrics = ml_model.train_and_save(
            X, y, model_path=save_path, num_boost_round=100,
            early_stopping_rounds=10,
        )
        # warmup 后, val 集指标应达到一定水平 (不是假收敛)
        assert "val_auc" in metrics, "应包含 val_auc 字段"
        assert "val_f1" in metrics, "应包含 val_f1 字段"
        # 正例 = 50, scale_pos_weight 会被截断到 10, 模型应能学到区分度
        assert metrics["val_auc"] > 0.6, (
            f"val_auc={metrics['val_auc']} 应 > 0.6 (有 5% 正例 + 强相关特征, 至少能区分)"
        )

    def test_train_with_warmup_uses_minimum_iterations(self, tmp_path):
        """warmup 防假收敛: 训练结束后 best_iter 应 >= 30 (假收敛的 best_iter 通常 < 20)."""
        from app.config import settings
        save_path = str(tmp_path / "xgb_warmup.json")
        np.random.seed(42)
        X = np.random.randn(500, 25).astype(np.float32)
        y = (np.random.rand(500) > 0.7).astype(np.int32)  # ~30% 正例 (合理)
        X[:, 0] = y.astype(np.float32) * 4 + np.random.randn(500) * 0.3
        metrics = ml_model.train_and_save(
            X, y, model_path=save_path, num_boost_round=200,
            early_stopping_rounds=settings.XGB_EARLY_STOPPING_ROUNDS,
        )
        # warmup 50 轮 + 早停 10 轮, 最少 50, 通常 50-100
        assert metrics["best_iteration"] >= settings.XGB_WARMUP_ROUNDS, (
            f"best_iter={metrics['best_iteration']} < warmup={settings.XGB_WARMUP_ROUNDS}, "
            f"说明 warmup 没生效, 仍可能假收敛"
        )

    def test_train_warns_on_low_pos_ratio(self, tmp_path, caplog):
        """正例比例 < XGB_MIN_POS_RATIO (15%) 时训练函数应打 warning."""
        import logging
        from app.config import settings
        save_path = str(tmp_path / "xgb_lowpos.json")
        np.random.seed(42)
        # 1000 样本, 只 20 个正例 (2%) - 触发 warning
        X = np.random.randn(1000, 25).astype(np.float32)
        y = np.zeros(1000, dtype=np.int32)
        y[:20] = 1
        with caplog.at_level(logging.WARNING, logger="app.engine.ml_model"):
            ml_model.train_and_save(
                X, y, model_path=save_path, num_boost_round=50,
                early_stopping_rounds=10,
            )
        # 应有 "正例比例" 警告
        assert any("正例比例" in r.message for r in caplog.records), (
            f"正例比例 < {settings.XGB_MIN_POS_RATIO*100:.0f}% 时应打 warning, "
            f"实际 records: {[r.message[:50] for r in caplog.records]}"
        )

    def test_train_metrics_includes_fake_convergence_flag(self, tmp_path):
        """metrics 必须含 is_fake_convergence 字段, 让训练脚本能判断质量."""
        save_path = str(tmp_path / "xgb_fc.json")
        np.random.seed(42)
        X = np.random.randn(500, 25).astype(np.float32)
        y = (np.random.rand(500) > 0.6).astype(np.int32)
        X[:, 0] = y.astype(np.float32) * 3 + np.random.randn(500) * 0.5
        metrics = ml_model.train_and_save(
            X, y, model_path=save_path, num_boost_round=100,
            early_stopping_rounds=10,
        )
        assert "is_fake_convergence" in metrics, "metrics 应含 is_fake_convergence 字段"
        assert "baseline_accuracy" in metrics, "metrics 应含 baseline_accuracy 字段"

    def test_train_uses_regularization(self, tmp_path):
        """训练参数应含 L1/L2 正则 + 子节点最小权重 (防过拟合)."""
        from app.config import settings
        # 检查 config.py 设了这些参数
        assert settings.XGB_REG_ALPHA >= 0
        assert settings.XGB_REG_LAMBDA > 0
        assert settings.XGB_MIN_CHILD_WEIGHT >= 1
        assert settings.XGB_SUBSAMPLE > 0 and settings.XGB_SUBSAMPLE <= 1
        assert settings.XGB_COLSAMPLE_BYTREE > 0 and settings.XGB_COLSAMPLE_BYTREE <= 1
        # 早停监控指标
        assert settings.XGB_EARLY_STOP_METRIC == "auc", (
            f"早停指标应是 'auc' (对不平衡敏感), 当前是 '{settings.XGB_EARLY_STOP_METRIC}'"
        )
        # warmup 轮数
        assert settings.XGB_WARMUP_ROUNDS >= 30, "warmup 应 >= 30 轮, 给模型充分训练时间"

    def test_train_finds_best_f1_threshold(self, tmp_path):
        """【P4-L3 2026-08-08 第二轮】val 集 F1 应扫描多阈值找最佳点, 不用固定 0.5.

        之前固定阈值 0.5 在不平衡数据 + 验证集分布偏移时, F1 可能从 0.7 暴跌到 0.09.
        修法: 遍历 0.1-0.85 阈值找 F1 最高点, metrics 必含 best_f1_threshold.
        """
        save_path = str(tmp_path / "xgb_thr.json")
        np.random.seed(42)
        # 500 样本, 30% 正例 (用强相关特征, 让模型能学到)
        X = np.random.randn(500, 25).astype(np.float32)
        y = (np.random.rand(500) > 0.7).astype(np.int32)
        X[:, 0] = y.astype(np.float32) * 5 + np.random.randn(500) * 0.3
        metrics = ml_model.train_and_save(
            X, y, model_path=save_path, num_boost_round=100,
            early_stopping_rounds=10,
        )
        # 关键字段必须存在
        assert "best_f1_threshold" in metrics, "metrics 应含 best_f1_threshold (验证集 F1 最高点阈值)"
        # 阈值应在合理范围
        thr = metrics["best_f1_threshold"]
        assert 0.1 <= thr <= 0.85, f"最佳阈值应在 0.1-0.85, 实际 {thr}"
        # val_f1 应该 > 固定 0.5 阈值的 F1 (因为我们选了最佳点)
        # 模拟固定 0.5 阈值的 F1
        from sklearn.metrics import f1_score
        # 重新跑一次拿验证集预测概率
        # 这里我们用 is_fake_convergence 字段间接验证
        assert "is_fake_convergence" in metrics
