-- ============================================
-- 增量更新 (P4 2026-08-07): 加 2 张系统管理表
--   1. risk_action_log  (P4-L1 操作审计日志)
--   2. risk_alert       (P4-L2 告警记录)
--
-- 本脚本是幂等的: 重复执行不会报错
--   - 第一次跑: CREATE TABLE
--   - 第二次跑: CREATE TABLE IF NOT EXISTS 静默跳过
--
-- 新装环境 (2026-08-07 之后): 直接用 init_risk_tables.sql 即可, 表已含
-- 老环境升级: 跑这个 migration 一次
-- ============================================

USE ecs;

-- 1. risk_action_log (P4-L1)
-- 任何规则/案件/黑名单的变更都写一行, 出事能追责
CREATE TABLE IF NOT EXISTS `risk_action_log` (
    `log_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '日志ID',
    `operator` VARCHAR(50) NOT NULL COMMENT '操作人(admin/system/ai_agent)',
    `action_type` ENUM('CREATE_RULE','UPDATE_RULE','TOGGLE_RULE','DELETE_RULE','REVIEW_CASE','ADD_BLACKLIST','REMOVE_BLACKLIST') NOT NULL COMMENT '操作类型',
    `target_type` ENUM('rule','case','blacklist') NOT NULL COMMENT '对象类型',
    `target_id` VARCHAR(50) NOT NULL COMMENT '对象ID',
    `before_value` JSON COMMENT '变更前 (NULL=新增)',
    `after_value` JSON COMMENT '变更后 (NULL=删除)',
    `ip` VARCHAR(50) COMMENT '操作IP',
    `remark` VARCHAR(500) COMMENT '备注',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
    PRIMARY KEY (`log_id`),
    INDEX `idx_action_log_operator` (`operator`),
    INDEX `idx_action_log_target` (`target_type`, `target_id`),
    INDEX `idx_action_log_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='风控操作审计日志表 (P4-L1)';

-- 2. risk_alert (P4-L2)
-- 风控系统自己发现异常的记录 (规则命中率突降/案件积压/拒绝率过高等)
CREATE TABLE IF NOT EXISTS `risk_alert` (
    `alert_id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '告警ID',
    `alert_type` ENUM('BUSINESS','MODEL','SYSTEM','SECURITY') NOT NULL COMMENT '告警分类',
    `alert_level` ENUM('P0','P1','P2','P3') NOT NULL COMMENT '告警等级 (P0=致命, P3=提示)',
    `alert_title` VARCHAR(200) NOT NULL COMMENT '告警标题',
    `alert_content` TEXT COMMENT '告警详情',
    `metric_name` VARCHAR(100) COMMENT '指标名(规则命中率/案件积压数等)',
    `metric_value` DECIMAL(20,6) COMMENT '触发值',
    `threshold` DECIMAL(20,6) COMMENT '阈值',
    `status` ENUM('PENDING','HANDLING','RESOLVED','IGNORED') DEFAULT 'PENDING' COMMENT '处理状态',
    `handler` VARCHAR(50) COMMENT '处理人',
    `resolve_time` DATETIME DEFAULT NULL COMMENT '解决时间',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '告警时间',
    PRIMARY KEY (`alert_id`),
    INDEX `idx_alert_status` (`status`),
    INDEX `idx_alert_level` (`alert_level`),
    INDEX `idx_alert_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='风控告警记录表 (P4-L2)';

-- 验证: 列出 2 张 P4 新表
SELECT TABLE_NAME, TABLE_COMMENT
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME IN ('risk_action_log', 'risk_alert')
ORDER BY TABLE_NAME;
