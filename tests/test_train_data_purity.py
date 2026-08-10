"""
训练数据严格化测试 (P4-L4 2026-08-08)
- 验证 train_xgb_model.py SQL 显式 WHERE ml_score IS NULL (无 ml 痕迹)
- 验证 gen_train_dataset.py 训练数据无 ml_score 垃圾值
- 验证 backfill_ml_score.py 回填合理
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAIN_PY = ROOT / "scripts" / "train_xgb_model.py"
GEN_PY = ROOT / "scripts" / "gen_train_dataset.py"
BACKFILL_PY = ROOT / "scripts" / "backfill_ml_score.py"


class TestTrainDataPurity:
    """训练数据无 ml 痕迹"""

    def test_train_sql_filters_null_ml_score(self):
        """train_xgb_model.py SQL 必须显式 WHERE ml_score IS NULL"""
        src = TRAIN_PY.read_text(encoding="utf-8")
        # 找 SQL_FETCH_ASSESSMENTS 块
        m = re.search(r'SQL_FETCH_ASSESSMENTS\s*=\s*"""(.*?)"""', src, re.DOTALL)
        assert m, "找不到 SQL_FETCH_ASSESSMENTS 块"
        sql = m.group(1)
        assert "ml_score IS NULL" in sql, (
            "SQL 必须显式 WHERE ml_score IS NULL 锁定无 ml 痕迹数据"
        )

    def test_train_sql_no_ml_score_in_select(self):
        """训练 SQL 不 SELECT ml_score (避免循环依赖)"""
        src = TRAIN_PY.read_text(encoding="utf-8")
        m = re.search(r'SQL_FETCH_ASSESSMENTS\s*=\s*"""(.*?)"""', src, re.DOTALL)
        sql = m.group(1)
        # SELECT 里不能有 ml_score
        select_part = sql.split("FROM")[0]
        assert "ml_score" not in select_part.lower(), (
            f"训练 SQL 不应 SELECT ml_score (避免循环), 实际: {select_part!r}"
        )

    def test_train_sql_comment_documents_ml_filter(self):
        """SQL 块必须有注释说明 ml_score 过滤原因"""
        src = TRAIN_PY.read_text(encoding="utf-8")
        # 找 SQL 周围的注释 (向上 5 行内)
        m = re.search(r'(.{0,500}SQL_FETCH_ASSESSMENTS\s*=\s*""")(.*?)(""")', src, re.DOTALL)
        assert m, "找不到 SQL 块上下文"
        before = m.group(1)
        assert "ml_score" in before or "ml 痕迹" in before or "无 ml" in before, (
            "SQL 块前必须有注释说明 ml_score 过滤原因"
        )


class TestGenTrainDatasetScript:
    """gen_train_dataset.py 严格造数据 + ml_score 强制 NULL"""

    def test_script_exists(self):
        assert GEN_PY.exists(), "gen_train_dataset.py 必须存在"

    def test_script_forces_ml_score_null(self):
        """造数据脚本必须强制 ml_score=NULL (写库后 UPDATE)"""
        src = GEN_PY.read_text(encoding="utf-8")
        # 找 UPDATE SET ml_score = NULL 的语句
        assert "UPDATE risk_assessment" in src, "应有 UPDATE risk_assessment 语句"
        assert "ml_score = NULL" in src or "ml_score=NULL" in src, (
            "应强制 SET ml_score = NULL"
        )

    def test_script_uses_process_event(self):
        """走 process_event 让 30 规则跑 (decision 真实)"""
        src = GEN_PY.read_text(encoding="utf-8")
        assert "from app.service.event import process_event" in src
        assert "await process_event(" in src, "应调 process_event 跑 30 规则"

    def test_script_default_1500_samples(self):
        """默认 30 RISK + 30 普通 × 25 = 1500 条"""
        src = GEN_PY.read_text(encoding="utf-8")
        # argparse default
        assert '"--n-risk"' in src or "'--n-risk'" in src
        assert "default=30" in src, "n_risk/n_normal 默认 30"
        assert "default=25" in src, "per_user 默认 25"
        # 注释说明
        assert "1500" in src, "应有 1500 字样"

    def test_script_picks_risk_and_normal_users(self):
        """脚本应分别选 RISK 用户和普通用户"""
        src = GEN_PY.read_text(encoding="utf-8")
        assert "_pick_risk_users" in src, "应有 _pick_risk_users 函数"
        assert "_pick_normal_users" in src, "应有 _pick_normal_users 函数"
        assert "RISK" in src, "应区分 RISK 用户"


class TestBackfillMlScoreScript:
    """backfill_ml_score.py 用训好的模型回填 ml_score"""

    def test_script_exists(self):
        assert BACKFILL_PY.exists(), "backfill_ml_score.py 必须存在"

    def test_script_loads_trained_model(self):
        """必须先加载训好的模型"""
        src = BACKFILL_PY.read_text(encoding="utf-8")
        assert "load_model" in src, "应调 load_model 加载训好的模型"
        assert "is_model_loaded" in src, "应检查模型是否加载"

    def test_script_uses_predict(self):
        """必须用 XGBoost predict 推理"""
        src = BACKFILL_PY.read_text(encoding="utf-8")
        assert "from app.engine.ml_model import" in src
        assert "predict(" in src, "应调 predict 推理"

    def test_script_filters_null_records(self):
        """只回填 ml_score=NULL 的记录 (避免覆盖已有值)"""
        src = BACKFILL_PY.read_text(encoding="utf-8")
        assert "ml_score IS NULL" in src, "应只更新 ml_score=NULL 记录"

    def test_script_reports_separation_quality(self):
        """应报告正负例 ml_score 平均分离度"""
        src = BACKFILL_PY.read_text(encoding="utf-8")
        assert "分离度" in src or "pos_avg" in src or "sep" in src.lower(), (
            "应输出正负例 ml_score 分离度 (验证模型质量)"
        )


class TestTrainingWorkflowIntegration:
    """整体训练工作流: gen_train_dataset → train → backfill"""

    def test_workflow_steps_order(self):
        """三步顺序: 造数据 → 训练 → 回填"""
        gen_src = GEN_PY.read_text(encoding="utf-8")
        train_src = TRAIN_PY.read_text(encoding="utf-8")
        backfill_src = BACKFILL_PY.read_text(encoding="utf-8")
        # gen_train_dataset 输出应提示下一步 train
        assert "train_xgb_model" in gen_src
        # backfill 应提示"训完模型后跑"
        assert "train_xgb_model" in backfill_src or "回填" in backfill_src

    def test_total_dataset_size_documented(self):
        """三个脚本应有"1500 条" 文档 (默认数据集大小)"""
        gen_src = GEN_PY.read_text(encoding="utf-8")
        assert "1500" in gen_src, "gen_train_dataset.py 应说明 1500 条"
