"""
全局配置: 从 .env 文件加载, 支持环境变量覆盖.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置, 自动从 .env 文件和环境变量加载"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ---- 数据库配置 ----
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "123321"
    DB_NAME: str = "ecs"
    TEST_DB_NAME: str = "ecs_test"

    def get_database_url_async(self, db_name: str | None = None) -> str:
        """构建异步 MySQL 连接 URL (用于 aiomysql 驱动)"""
        name = db_name or self.DB_NAME
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{name}?charset=utf8mb4"
        )

    def get_test_database_url_async(self) -> str:
        """测试库异步 URL (用于 conftest.py 初始化测试库)"""
        return self.get_database_url_async(self.TEST_DB_NAME)

    # ---- 风控决策阈值 (按 event_type 拆, 不同场景严苛度不同) ----
    # 全局默认阈值 (向下兼容, RISK_PASS_THRESHOLD 等保留)
    # 评分 < PASS → 通过, < MARK → 标记, < REVIEW → 人工审核, >= REVIEW → 拒绝
    RISK_PASS_THRESHOLD: int = 30
    RISK_MARK_THRESHOLD: int = 60
    RISK_REVIEW_THRESHOLD: int = 80
    RISK_MULTI_RULE_BONUS: int = 3     # 多规则命中时, 每条额外规则加的分
    RISK_VETO_MIN_SCORE: int = 90      # 一票否决时强制的最低分

    # 按 event_type 拆的阈值 (P4-L5 2026-08-10):
    # 售后/物流比下单/支付严 (售后容易薅羊毛, 物流容易虚假签收)
    # 找不到 event_type 时 fallback 到全局阈值
    RISK_EVENT_THRESHOLDS: dict[str, dict[str, int]] = {
        "下单":     {"pass": 30, "mark": 60, "review": 80},   # 标准
        "支付":     {"pass": 25, "mark": 55, "review": 75},   # 支付更严 (钱的事)
        "售后申请":  {"pass": 40, "mark": 70, "review": 85},   # 售后更严 (薅羊毛)
        "物流投诉":  {"pass": 35, "mark": 65, "review": 80},   # 物流偏严
        "通用":     {"pass": 30, "mark": 60, "review": 80},   # = 全局默认
    }

    # ---- 风险等级 ↔ 分数 映射 (P4-L5 2026-08-10) ----
    # 教学场景: 4 档等级 (低/中/高/极高) 对应 4 段分数区间
    # 业务方调阈值不用动 schema, 改 config.py 即可
    # 区间左闭右闭, 边界值属于上面那个等级 (高+1 算下一档)
    # 一票否决 (极高) 区间独立, 防止 89 分跟 90 分的边界争议
    RISK_LEVEL_SCORE_MAP: dict[str, tuple[int, int]] = {
        "低":   (0, 29),     # 0-29 分
        "中":   (30, 59),    # 30-59 分
        "高":   (60, 84),    # 60-84 分
        "极高": (85, 100),   # 85-100 分
    }

    def get_risk_level_by_score(self, score: int) -> str:
        """根据分数反查风险等级 (前端下拉 + 后端校验)."""
        for level, (low, high) in self.RISK_LEVEL_SCORE_MAP.items():
            if low <= score <= high:
                return level
        # 越界兜底 (理论上不应发生, 因为分数范围 0-100)
        return "极高" if score > 100 else "低"

    def get_event_thresholds(self, event_type: str) -> dict[str, int]:
        """按 event_type 查阈值, 找不到 fallback 到全局."""
        return self.RISK_EVENT_THRESHOLDS.get(
            event_type,
            {"pass": self.RISK_PASS_THRESHOLD, "mark": self.RISK_MARK_THRESHOLD, "review": self.RISK_REVIEW_THRESHOLD},
        )

    # ---- LLM 配置 (阿里云百炼) ----
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL_NAME: str = "qwen-plus"

    # ---- features 脱敏 (P3-M6) ----
    # True: 响应里 features 返回全量 25 维 (教学/内部 admin 用)
    # False: 响应里 features={} (前端不展示, 防敏感数据外泄)
    # 真生产要按角色判断 (admin 看全量, 普通前端看空), 留 TODO
    RISK_FEATURES_FULL_RETURN: bool = True

    # ---- AI Agent chat 超时 (P3-M8) ----
    AI_AGENT_CHAT_TIMEOUT_SEC: float = 60.0

    # ---- 案件超时自动关闭 (P4-L3 2026-08-08) ----
    # "待审核" 案件超过 N 小时没人审, 自动关案 (避免积压). 0 = 关闭此功能.
    CASE_TIMEOUT_HOURS: int = 24

    # ---- 告警自动调度 (P4-L3 2026-08-08) ----
    # 告警检查的间隔 (分钟). 0 = 关闭自动调度, 只能手动 POST /api/alerts/check
    ALERT_SCHEDULER_INTERVAL_MIN: int = 15

    # ---- 风控告警阈值 (P4-L2) ----
    ALERT_PENDING_CASE_THRESHOLD: int = 50          # 场景 1: 待审核案件积压数
    ALERT_RULE_HIT_RATE_MIN: float = 5.0            # 场景 2: 最近窗口规则命中率下限 (%)
    ALERT_BLACKLIST_HIT_RATE_MAX: float = 30.0      # 场景 3: 最近窗口撞黑比例上限 (%)
    ALERT_CHECK_WINDOW_HOURS: int = 1               # 告警检查的时间窗口 (小时)

    # ---- XGBoost 双轨融合配置 ----
    XGB_MODEL_PATH: str = "app/engine/xgb_model.json"   # 相对路径, ml_model.py resolve 成绝对
    XGB_ENABLED: bool = True                              # False = 纯规则, 兜底
    # 评分融合权重 (规则占比 + XGBoost 占比 = 1.0), 当前 0.5/0.5 等权
    ML_WEIGHT_RULE: float = 0.5
    ML_WEIGHT_XGB: float = 0.5
    # ML 单维度的决策阈值 (P(拒绝) 概率 → 4 档)
    ML_PASS_THRESHOLD: float = 0.30
    ML_MARK_THRESHOLD: float = 0.60
    ML_REVIEW_THRESHOLD: float = 0.80
    # 【P4-L3 2026-08-08 第二轮】训练数据加载: 硬编码 SQL LIMIT 5000 → 配置化
    XGB_TRAIN_DATA_LIMIT: int = 2500  # 训练时从 risk_assessment 取最近 N 条 (按 create_time DESC)
    # 训练参数 (P4-L3 2026-08-08 优化正负样本比 + 早停)
    XGB_TEST_SIZE: float = 0.2                # 验证集比例 (stratify 拆分, 保持正负比)
    XGB_EARLY_STOPPING_ROUNDS: int = 10      # 早停: 验证集指标连续 N 轮不升就停 (监控指标见下)
    XGB_MIN_SAMPLES: int = 1250              # 最小样本数 = 25 维 × 50 倍 (教学经验值)
    XGB_MAX_SCALE_POS_WEIGHT: float = 10.0   # scale_pos_weight 上限, 防过拟合 (不平衡太严重时)
    # 【P4-L3 2026-08-08 第二轮优化】训练超参 (防假收敛)
    XGB_MAX_DEPTH: int = 6                   # 树最大深度 (6=中等复杂度, 防过拟合)
    XGB_LEARNING_RATE: float = 0.1           # 学习率 (0.1=平衡, 越低越稳但要更多树)
    XGB_MIN_CHILD_WEIGHT: int = 3            # 子节点最小权重, 防止对噪声过拟合
    XGB_REG_ALPHA: float = 0.1               # L1 正则 (稀疏化, 特征选择)
    XGB_REG_LAMBDA: float = 1.0              # L2 正则 (平滑化, 防过拟合)
    XGB_GAMMA: float = 0.0                   # 分裂最小损失下降 (0=无限制)
    XGB_SUBSAMPLE: float = 0.8               # 训练样本采样比例 (随机森林式抗过拟合)
    XGB_COLSAMPLE_BYTREE: float = 0.8        # 特征采样比例 (跟 subsample 配合)
    XGB_WARMUP_ROUNDS: int = 50              # 早停 warmup: 前 N 轮强制不早停 (给模型充分训练时间)
    XGB_EARLY_STOP_METRIC: str = "auc"       # 早停监控指标 (auc 对不平衡比 logloss 敏感)
    # 【P4-L3 2026-08-08 第二轮优化】质量验收 (假收敛检测)
    XGB_MIN_BEST_ITER: int = 30              # 真正收敛 best_iter 应 >= 30, 否则可能假收敛
    XGB_MIN_VAL_AUC: float = 0.70            # val_auc < 0.70 警告模型无效
    XGB_MIN_VAL_F1: float = 0.50             # val_f1 < 0.50 警告模型无效 (不平衡下 f1 更敏感)
    XGB_MIN_POS_RATIO: float = 0.15          # 正例比例 < 15% 警告用 --balance-pos 重造数据
    XGB_MAX_POS_RATIO: float = 0.60          # 正例比例 > 60% 警告可能标签噪声


settings = Settings()


# ============================================================
# Demo: 看一眼项目所有关键配置 (无需 DB / 启动服务, 纯 print)
# 跑法: python app/config.py
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("AI_Risk 全局配置 (从 .env 加载, 缺省值兜底)")
    print("=" * 60)

    sections = [
        ("数据库", ["DB_HOST", "DB_PORT", "DB_USER", "DB_NAME", "TEST_DB_NAME"]),
        ("风控决策阈值", ["RISK_PASS_THRESHOLD", "RISK_MARK_THRESHOLD",
                       "RISK_REVIEW_THRESHOLD", "RISK_MULTI_RULE_BONUS", "RISK_VETO_MIN_SCORE"]),
        ("LLM (阿里云百炼)", ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_NAME"]),
        ("XGBoost 双轨融合", ["XGB_ENABLED", "XGB_MODEL_PATH",
                          "ML_WEIGHT_RULE", "ML_WEIGHT_XGB",
                          "ML_PASS_THRESHOLD", "ML_MARK_THRESHOLD", "ML_REVIEW_THRESHOLD"]),
        ("告警 (P4-L2)", ["ALERT_PENDING_CASE_THRESHOLD", "ALERT_RULE_HIT_RATE_MIN",
                       "ALERT_BLACKLIST_HIT_RATE_MAX", "ALERT_CHECK_WINDOW_HOURS"]),
        ("其他", ["AI_AGENT_CHAT_TIMEOUT_SEC", "RISK_FEATURES_FULL_RETURN"]),
    ]
    for sec_name, keys in sections:
        print(f"\n【{sec_name}】")
        for k in keys:
            v = getattr(settings, k, None)
            if v and "API_KEY" in k and isinstance(v, str) and len(v) > 8:
                v = v[:4] + "***" + v[-4:]   # 脱敏
            print(f"  {k:<30} = {v}")
