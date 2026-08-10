"""
电商风控系统 - 风控表 ORM (7 张)
风控系统自建表, 跟业务表分开管理
- 规则配置 (RiskRule)
- 事件审计 (RiskEvent / RiskFeature / RiskAssessment)
- 案件管理 (RiskCase)
- 黑名单 (RiskBlacklist)
- 用户画像 (RiskUserProfile)
"""
import json
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ============================================================
# 规则配置
# ============================================================

class RiskRule(Base):
    __tablename__ = "risk_rule"

    rule_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="规则ID")
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="规则名称")
    rule_category: Mapped[str] = mapped_column(
        Enum("订单欺诈", "支付风险", "账户风险", "售后滥用", "地址风险", "物流风险",
             name="rule_category_enum"),
        nullable=False, comment="风险场景分类",
    )
    event_type: Mapped[str] = mapped_column(
        Enum("下单", "支付", "售后申请", "物流投诉", "通用", name="rule_event_type_enum"),
        nullable=False, server_default="通用", comment="适用事件类型",
    )
    rule_condition: Mapped[str] = mapped_column(Text, nullable=False, comment="条件表达式(JSON)")
    risk_level: Mapped[str] = mapped_column(
        Enum("低", "中", "高", "极高", name="risk_level_enum"),
        nullable=False, comment="风险等级",
    )
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="命中分值(0-100)")
    action: Mapped[str] = mapped_column(
        Enum("通过", "标记", "人工审核", "拒绝", name="rule_action_enum"),
        nullable=False, comment="触发动作",
    )
    is_enabled: Mapped[int] = mapped_column(Integer, default=1, comment="是否启用")
    priority: Mapped[int] = mapped_column(Integer, default=0, comment="优先级(越高越先执行)")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="规则描述")
    create_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, comment="创建时间",
    )
    update_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )
    # 【P3-M9 新增 2026-08-07】软删除: NULL=未删, 有值=删除时间
    # 配套 DDL: ALTER TABLE risk_rule ADD COLUMN deleted_at DATETIME NULL;
    # 所有 SELECT 加 WHERE deleted_at IS NULL, DELETE 改 UPDATE deleted_at = NOW()
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="软删除时间(NULL=未删)",
    )

    @property
    def condition_dict(self) -> dict:
        """将 JSON 字符串的 rule_condition 解析为字典"""
        if isinstance(self.rule_condition, str):
            return json.loads(self.rule_condition)
        return self.rule_condition


# ============================================================
# 事件审计
# ============================================================

class RiskEvent(Base):
    __tablename__ = "risk_event"

    event_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="事件ID")
    event_type: Mapped[str] = mapped_column(
        Enum("下单", "支付", "售后申请", "物流投诉", name="event_type_enum"),
        nullable=False, comment="事件类型",
    )
    event_source_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="关联业务ID")
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户ID")
    event_data: Mapped[Optional[str]] = mapped_column(Text, comment="事件快照(JSON)")
    create_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, comment="创建时间",
    )

    __table_args__ = (
        Index("idx_risk_event_user_id", "user_id"),
        Index("idx_risk_event_create_time", "create_time"),
    )


class RiskFeature(Base):
    __tablename__ = "risk_feature"

    feature_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="特征ID")
    event_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="关联事件ID")
    entity_type: Mapped[str] = mapped_column(
        Enum("用户", "订单", "地址", name="feature_entity_type_enum"),
        nullable=False, comment="实体类型",
    )
    entity_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="实体ID")
    feature_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="特征名称")
    feature_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4), comment="特征值")
    compute_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), comment="计算时间",
    )

    __table_args__ = (
        Index("idx_risk_feature_event_id", "event_id"),
        Index("idx_risk_feature_entity", "entity_type", "entity_id"),
    )


class RiskAssessment(Base):
    __tablename__ = "risk_assessment"

    assessment_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="评估ID")
    event_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="关联事件ID")
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户ID")
    rule_results: Mapped[Optional[str]] = mapped_column(Text, comment="规则结果(JSON)")
    rule_count: Mapped[int] = mapped_column(Integer, default=0, comment="命中规则数")
    final_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="最终评分(0-100)")
    risk_level: Mapped[str] = mapped_column(
        Enum("低", "中", "高", "极高", name="assessment_risk_level_enum"),
        nullable=False, comment="风险等级",
    )
    decision: Mapped[str] = mapped_column(
        Enum("通过", "标记", "人工审核", "拒绝", name="assessment_decision_enum"),
        nullable=False, comment="决策",
    )
    create_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, comment="创建时间",
    )
    # XGBoost 评分 (新增, 2026-08-07)
    # ml_score    : 拒绝概率 P(y=1) ∈ [0, 1], 浮点
    # ml_decision : ML 单维度给出的决策字符串 (跟 decision 同 4 档)
    ml_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4), nullable=True, comment="XGBoost 拒绝概率 [0,1]",
    )
    ml_decision: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, comment="ML 决策: 通过/标记/人工审核/拒绝",
    )

    __table_args__ = (
        Index("idx_risk_assessment_user_id", "user_id"),
        Index("idx_risk_assessment_decision", "decision"),
        Index("idx_risk_assessment_create_time", "create_time"),
    )


# ============================================================
# 案件管理
# ============================================================

class RiskCase(Base):
    __tablename__ = "risk_case"

    case_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="案件ID")
    assessment_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="关联评估ID")
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户ID")
    case_status: Mapped[str] = mapped_column(
        Enum("待审核", "审核中", "已通过", "已拒绝", "已关闭", name="case_status_enum"),
        default="待审核", comment="案件状态",
    )
    case_category: Mapped[Optional[str]] = mapped_column(String(50), comment="案件分类")
    risk_detail: Mapped[Optional[str]] = mapped_column(Text, comment="风险详情(JSON)")
    reviewer: Mapped[Optional[str]] = mapped_column(String(50), comment="审核人")
    review_comment: Mapped[Optional[str]] = mapped_column(Text, comment="审核意见")
    review_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="审核时间")
    # --- 业务回溯字段 (重做检查时使用) ---
    source_id: Mapped[Optional[str]] = mapped_column(String(50), comment="原始业务ID(订单/售后/投诉ID)")
    event_type: Mapped[Optional[str]] = mapped_column(
        Enum("下单", "支付", "售后申请", "物流投诉", name="case_event_type_enum"),
        comment="触发案件的事件类型",
    )
    create_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, comment="创建时间",
    )
    update_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )

    __table_args__ = (
        Index("idx_risk_case_status", "case_status"),
        Index("idx_risk_case_user_id", "user_id"),
    )


# ============================================================
# 黑名单 + 用户画像
# ============================================================

class RiskBlacklist(Base):
    __tablename__ = "risk_blacklist"

    blacklist_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="黑名单ID")
    blacklist_type: Mapped[str] = mapped_column(
        Enum("用户", "地址", "手机号", name="blacklist_type_enum"),
        nullable=False, comment="黑名单类型",
    )
    blacklist_value: Mapped[str] = mapped_column(String(200), nullable=False, comment="黑名单值")
    reason: Mapped[Optional[str]] = mapped_column(Text, comment="加入原因")
    expire_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="过期时间(NULL=永久)")
    create_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, comment="创建时间",
    )
    # 【P3-M9 新增 2026-08-07】软删除: NULL=未删, 有值=删除时间
    # 配套 DDL: ALTER TABLE risk_blacklist ADD COLUMN deleted_at DATETIME NULL;
    # 撞黑检查 / 列表查询 都加 WHERE deleted_at IS NULL
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="软删除时间(NULL=未删)",
    )

    __table_args__ = (
        UniqueConstraint("blacklist_type", "blacklist_value", name="idx_blacklist_type_value"),
    )


class RiskUserProfile(Base):
    __tablename__ = "risk_user_profile"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="用户ID")
    risk_score: Mapped[int] = mapped_column(Integer, default=0, comment="综合风险评分(0-100)")
    risk_level: Mapped[str] = mapped_column(
        Enum("低", "中", "高", "极高", name="profile_risk_level_enum"),
        default="低", comment="风险等级",
    )
    total_orders: Mapped[int] = mapped_column(Integer, default=0, comment="总订单数")
    total_refunds: Mapped[int] = mapped_column(Integer, default=0, comment="退款次数")
    refund_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0, comment="退款率")
    avg_order_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, comment="平均订单金额")
    address_count: Mapped[int] = mapped_column(Integer, default=0, comment="地址数量")
    complaint_count: Mapped[int] = mapped_column(Integer, default=0, comment="投诉次数")
    assessment_count: Mapped[int] = mapped_column(Integer, default=0, comment="评估次数")
    last_assessment_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="最近评估时间")
    profile_data: Mapped[Optional[str]] = mapped_column(Text, comment="扩展画像数据(JSON)")
    update_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, onupdate=datetime.now, comment="更新时间",
    )


# ============================================================
# 系统管理表 (P4-L1 / P4-L2 新增 2026-08-07)
# 教学项目只加"系统管理"类表, 不动数据/特征
# ============================================================

class RiskActionLog(Base):
    """
    操作审计日志表 (P4-L1, PRD §5.2.5 / §7.1.3)

    任何规则 / 案件 / 黑名单 / 画像的变更都写一行, 出事能追责.
    教学价值: 学员能讲"我设计的系统有完整审计日志" (合规 + 银保监要求).
    """
    __tablename__ = "risk_action_log"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="日志ID")
    operator: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作人(admin/system/ai_agent)")
    action_type: Mapped[str] = mapped_column(
        Enum(
            "CREATE_RULE", "UPDATE_RULE", "TOGGLE_RULE", "DELETE_RULE",
            "REVIEW_CASE", "AUTO_REJECT_CASE", "AUTO_CLOSE_CASE",
            "ADD_BLACKLIST", "REMOVE_BLACKLIST",
            name="action_type_enum",
        ),
        nullable=False, comment="操作类型",
    )
    target_type: Mapped[str] = mapped_column(
        Enum("rule", "case", "blacklist", name="action_target_type_enum"),
        nullable=False, comment="对象类型",
    )
    target_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="对象ID")
    before_value: Mapped[Optional[str]] = mapped_column(Text, comment="变更前 JSON (NULL=新增)")
    after_value: Mapped[Optional[str]] = mapped_column(Text, comment="变更后 JSON (NULL=删除)")
    ip: Mapped[Optional[str]] = mapped_column(String(50), comment="操作 IP")
    remark: Mapped[Optional[str]] = mapped_column(String(500), comment="备注")
    create_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, comment="操作时间",
    )

    __table_args__ = (
        Index("idx_action_log_operator", "operator"),
        Index("idx_action_log_target", "target_type", "target_id"),
        Index("idx_action_log_create_time", "create_time"),
    )


class RiskAlert(Base):
    """
    告警记录表 (P4-L2, PRD §6.3.3)

    风控系统自己发现异常的记录 (规则命中率突降 / 案件积压 / 撞黑失败率过高等).
    教学价值: 让学员理解"风控不是写完规则就完事, 要监控".
    """
    __tablename__ = "risk_alert"

    alert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="告警ID")
    alert_type: Mapped[str] = mapped_column(
        Enum("BUSINESS", "MODEL", "SYSTEM", "SECURITY", name="alert_type_enum"),
        nullable=False, comment="告警分类",
    )
    alert_level: Mapped[str] = mapped_column(
        Enum("P0", "P1", "P2", "P3", name="alert_level_enum"),
        nullable=False, comment="告警等级 (P0=致命, P3=提示)",
    )
    alert_title: Mapped[str] = mapped_column(String(200), nullable=False, comment="告警标题")
    alert_content: Mapped[Optional[str]] = mapped_column(Text, comment="告警详情")
    metric_name: Mapped[Optional[str]] = mapped_column(String(100), comment="指标名(规则命中率/案件积压数等)")
    metric_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), comment="触发值")
    threshold: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), comment="阈值")
    status: Mapped[str] = mapped_column(
        Enum("PENDING", "HANDLING", "RESOLVED", "IGNORED", name="alert_status_enum"),
        default="PENDING", comment="处理状态",
    )
    handler: Mapped[Optional[str]] = mapped_column(String(50), comment="处理人")
    resolve_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="解决时间")
    create_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), default=datetime.now, comment="告警时间",
    )

    __table_args__ = (
        Index("idx_alert_status", "status"),
        Index("idx_alert_level", "alert_level"),
        Index("idx_alert_create_time", "create_time"),
    )
