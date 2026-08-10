"""
【P4-L3 2026-08-08 第三轮】train_xgb_model.py 数据加载校验测试.

真实案例: 用户问"5000 条数据哪来的" → 实际 DB 5465 条全是从 init_db --reset 残留
或历史 gen_risk_data.py 累计, 但训练脚本只 logger.info 不校验, silent 接受了坏数据.

修法: 加 3 维度校验 (条数 / pos 比例 / 时间跨度), 触发 WARNING 提示用户.
测试用 mock pymysql cursor 验证 SQL 跟校验逻辑.
"""
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 把 train_xgb_model.py 当模块加载, 但要 mock pymysql 避免真连 DB
import importlib.util
spec = importlib.util.spec_from_file_location("train_xgb_model", ROOT / "scripts" / "train_xgb_model.py")
train_mod = importlib.util.module_from_spec(spec)


class FakeCursor:
    """最小 mock: 根据 SQL 关键字返回假数据."""
    def __init__(self, db_total, db_pos, min_time, max_time, assessments):
        self.db_total = db_total
        self.db_pos = db_pos
        self.min_time = min_time
        self.max_time = max_time
        self.assessments = assessments  # list of (aid, eid, dec)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql[:80])

    def fetchall(self):
        return self.assessments

    def fetchone(self):
        return None  # 用更精细的实现覆盖

    def close(self):
        pass

    # 【P4-L3 2026-08-08 第三轮测试修复】pymysql cursor 用 with 上下文管理
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _CursorForChecks(FakeCursor):
    """支持 COUNT(*) / MIN/MAX 返回值."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fetch_count = 0

    def fetchone(self):
        last_sql = self.executed[-1].lower() if self.executed else ""
        if "count(*) from risk_assessment where decision" in last_sql:
            return (self.db_pos,)
        if "count(*) from risk_assessment" in last_sql:
            return (self.db_total,)
        if "min(create_time)" in last_sql or "max(create_time)" in last_sql:
            return (self.min_time, self.max_time)
        return None


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
    def cursor(self):
        return self.cursor_obj
    def close(self):
        pass


class TestTrainDataValidation:
    """训练脚本加载数据时的 3 维度校验 (条数/pos 比例/时间跨度)."""

    def _make_train_call(self, db_total, db_pos, span_days, num_assessments=1000, caplog=None):
        """用 mock conn 跑 _load_data_from_mysql, 返回 (X, y) + 触发 log."""
        from app.config import settings
        import numpy as np
        # 准备假数据
        if span_days == 0:
            min_time = max_time = datetime.now()
        else:
            min_time = datetime.now() - timedelta(days=span_days)
            max_time = datetime.now()
        # 假评估: assessment_id, event_id, decision
        # 80% 通过 + 20% 拒绝 (控制 pos 比例)
        assessments = []
        for i in range(num_assessments):
            dec = "拒绝" if i < (num_assessments * db_pos // max(1, db_total)) else "通过"
            assessments.append((f"AID{i:05d}", f"EID{i:05d}", dec))
        # 假特征: event_id, feature_name, feature_value (25 维)
        from app.engine.ml_model import FEATURE_COLUMNS
        feat_rows = []
        for eid_dec in assessments:
            for col in FEATURE_COLUMNS:
                feat_rows.append((eid_dec[1], col, 1.0))
        cursor = _CursorForChecks(db_total, db_pos, min_time, max_time, assessments)

        # 加 fetchall 返回 features
        original_fetchall = cursor.fetchall
        def smart_fetchall():
            last_sql = cursor.executed[-1].lower() if cursor.executed else ""
            if "from risk_feature" in last_sql:
                return feat_rows
            return assessments
        cursor.fetchall = smart_fetchall
        conn = FakeConn(cursor)
        # patch pymysql.connect
        import scripts.train_xgb_model as train_mod_real
        original_connect = train_mod_real.pymysql.connect
        train_mod_real.pymysql.connect = lambda **kwargs: conn
        try:
            with caplog.at_level(logging.WARNING, logger="scripts.train_xgb_model"):
                X, y = train_mod_real._load_data_from_mysql()
            return X, y, caplog.text
        finally:
            train_mod_real.pymysql.connect = original_connect

    def test_warns_when_db_total_less_than_limit_80pct(self, caplog):
        """DB 实际加载条数 < LIMIT 80% 时警告 (说明 DB 总数不够)."""
        from app.config import settings
        # LIMIT 5000, DB 只 200 条, 加载 200 条
        X, y, log_text = self._make_train_call(
            db_total=200, db_pos=10, span_days=30, num_assessments=200, caplog=caplog,
        )
        # 应有警告
        assert any("DB 实际只加载" in r.message for r in caplog.records), (
            f"加载条数 < 80% LIMIT 应警告, 实际: {[r.message[:80] for r in caplog.records]}"
        )

    def test_warns_when_pos_ratio_below_15pct(self, caplog):
        """正例比例 < 15% 时警告 (说明正例太少, 模型假收敛)."""
        # 5000 条评估, 100 个正例 = 2%
        X, y, log_text = self._make_train_call(
            db_total=5000, db_pos=100, span_days=30, num_assessments=5000, caplog=caplog,
        )
        # 应有警告
        assert any("正例比例" in r.message for r in caplog.records), (
            f"正例比例 < 15% 应警告, 实际: {[r.message[:80] for r in caplog.records]}"
        )
        # 警告里应有 "init_db.py --reset" 或 "gen_risk_data_with_dates" 提示
        assert any("gen_risk_data_with_dates" in r.message for r in caplog.records), (
            "正例比例警告应给出修复建议 (gen_risk_data_with_dates.py)"
        )

    def test_warns_when_time_span_less_than_1_day_with_lots_of_data(self, caplog):
        """数据 create_time 跨度 < 1 天 + DB > 100 条 → 警告 (init_db reset 后没重造)."""
        # 5000 条数据, 跨度 0 天 (全是同一天), DB > 100
        X, y, log_text = self._make_train_call(
            db_total=5000, db_pos=500, span_days=0, num_assessments=5000, caplog=caplog,
        )
        # 应有时间跨度警告
        assert any("create_time 跨度" in r.message for r in caplog.records), (
            f"数据跨度 < 1 天应警告 (init_db reset 后没重造), 实际: {[r.message[:80] for r in caplog.records]}"
        )

    def test_no_warnings_when_data_is_healthy(self, caplog):
        """数据健康 (5000 条, 30% 正例, 30 天跨度) → 不应有警告."""
        X, y, log_text = self._make_train_call(
            db_total=5000, db_pos=1500, span_days=30, num_assessments=5000, caplog=caplog,
        )
        # 不应有 "DB 实际只加载" / "正例比例" / "create_time 跨度" 这 3 类警告
        bad_keywords = ["DB 实际只加载", "正例比例", "create_time 跨度"]
        for rec in caplog.records:
            for kw in bad_keywords:
                assert kw not in rec.message, (
                    f"健康数据不应有 '{kw}' 警告, 实际: {rec.message[:120]}"
                )


class TestTrainScriptConfigWiring:
    """训练脚本应该用 settings.XGB_TRAIN_DATA_LIMIT 而不是硬编码 5000."""

    def test_uses_config_limit_not_hardcoded_5000(self):
        """scripts/train_xgb_model.py 的 SQL 必含 LIMIT %s (参数化, 非硬编码)."""
        script = (ROOT / "scripts" / "train_xgb_model.py").read_text(encoding="utf-8")
        # 不应有 "LIMIT 5000" 硬编码
        assert "LIMIT 5000" not in script, "不应硬编码 LIMIT 5000 (改用 config)"
        # 应有 "LIMIT %s" 参数化
        assert "LIMIT %s" in script, "SQL 应有 LIMIT %s 参数化"
        # 应传 settings.XGB_TRAIN_DATA_LIMIT
        assert "settings.XGB_TRAIN_DATA_LIMIT" in script, "应传 settings.XGB_TRAIN_DATA_LIMIT"

    def test_config_has_train_data_limit_setting(self):
        """app/config.py 必含 XGB_TRAIN_DATA_LIMIT 字段 (值可由 .env 覆盖, 不强求 5000)."""
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "XGB_TRAIN_DATA_LIMIT"), "Settings 必含 XGB_TRAIN_DATA_LIMIT"
        # 不强求 5000 (用户 .env 里可能设了 2500/10000 等), 但必须是 int
        assert isinstance(s.XGB_TRAIN_DATA_LIMIT, int), (
            f"XGB_TRAIN_DATA_LIMIT 应是 int, 实际 {type(s.XGB_TRAIN_DATA_LIMIT).__name__}"
        )
        assert s.XGB_TRAIN_DATA_LIMIT > 0, f"XGB_TRAIN_DATA_LIMIT 应 > 0, 实际 {s.XGB_TRAIN_DATA_LIMIT}"
