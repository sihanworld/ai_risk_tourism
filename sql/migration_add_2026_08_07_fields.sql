-- ============================================
-- 增量更新 (2026-08-07): 6 个字段补齐
--   1. risk_rule.deleted_at           (P3-M9 软删)
--   2. risk_assessment.ml_score       (V2 双轨融合)
--   3. risk_assessment.ml_decision     (V2 双轨融合)
--   4. risk_blacklist.deleted_at      (P3-M9 软删)
--   5. risk_case.source_id           (P1-S6 业务回溯, 之前漏在 DDL 里, 导致 1054 报错)
--   6. risk_case.event_type          (P1-S6 业务回溯, 同上)
--
-- 本脚本是幂等的: 重复执行不会报错
--   - 第一次跑: 新增字段
--   - 第二次跑: 字段已存在, 静默跳过
--
-- 新装环境 (2026-08-07 之后): 直接用 init_risk_tables.sql 即可, 字段已含
-- 老环境升级: 跑这个 migration 一次
-- 注: 原 migration_add_case_source_id.sql 已合并到本脚本 (5/6 项), 不再单独调用
-- ============================================

USE ecs;

-- 1. risk_rule.deleted_at
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_rule' AND COLUMN_NAME = 'deleted_at') = 0,
    'ALTER TABLE risk_rule ADD COLUMN deleted_at DATETIME DEFAULT NULL COMMENT "软删除时间(NULL=未删, P3-M9)" AFTER update_time',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2. risk_assessment.ml_score
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_assessment' AND COLUMN_NAME = 'ml_score') = 0,
    'ALTER TABLE risk_assessment ADD COLUMN ml_score DECIMAL(5,4) DEFAULT NULL COMMENT "XGBoost 拒绝概率 [0,1] (V2)" AFTER decision',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3. risk_assessment.ml_decision
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_assessment' AND COLUMN_NAME = 'ml_decision') = 0,
    'ALTER TABLE risk_assessment ADD COLUMN ml_decision VARCHAR(10) DEFAULT NULL COMMENT "ML 维度决策 (V2)" AFTER ml_score',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4. risk_blacklist.deleted_at
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_blacklist' AND COLUMN_NAME = 'deleted_at') = 0,
    'ALTER TABLE risk_blacklist ADD COLUMN deleted_at DATETIME DEFAULT NULL COMMENT "软删除时间(NULL=未删, P3-M9)" AFTER create_time',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 5. risk_case.source_id (合并自原 migration_add_case_source_id.sql)
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_case' AND COLUMN_NAME = 'source_id') = 0,
    'ALTER TABLE risk_case ADD COLUMN source_id VARCHAR(50) DEFAULT NULL COMMENT "原始业务ID(订单/售后/投诉ID), 重做检查时用" AFTER risk_detail',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 6. risk_case.event_type (合并自原 migration_add_case_source_id.sql)
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_case' AND COLUMN_NAME = 'event_type') = 0,
    'ALTER TABLE risk_case ADD COLUMN event_type ENUM("下单", "支付", "售后申请", "物流投诉") DEFAULT NULL COMMENT "触发案件的事件类型" AFTER source_id',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 7. risk_case.source_id 索引 (合并自原 migration_add_case_source_id.sql)
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_case' AND INDEX_NAME = 'idx_risk_case_source_id') = 0,
    'ALTER TABLE risk_case ADD INDEX idx_risk_case_source_id (source_id)',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 8. risk_action_log.action_type 加 2 个 ENUM 值 (P4-L3 2026-08-08 修生产 bug)
-- AUTO_REJECT_CASE: P2-S8 自动拒绝案件时记, AUTO_CLOSE_CASE: 案件超时自动关闭时记
-- MODIFY COLUMN 改 ENUM 大小, 不会丢数据 (旧值都在新 ENUM 集合里)
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_action_log' AND COLUMN_NAME = 'action_type'
       AND COLUMN_TYPE LIKE '%AUTO_CLOSE_CASE%') = 0,
    "ALTER TABLE risk_action_log MODIFY COLUMN action_type ENUM('CREATE_RULE','UPDATE_RULE','TOGGLE_RULE','DELETE_RULE','REVIEW_CASE','AUTO_REJECT_CASE','AUTO_CLOSE_CASE','ADD_BLACKLIST','REMOVE_BLACKLIST') NOT NULL COMMENT '操作类型'",
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 验证: 列出本次新增的 6 个字段
SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_COMMENT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'ecs'
  AND ((TABLE_NAME = 'risk_rule' AND COLUMN_NAME = 'deleted_at')
    OR (TABLE_NAME = 'risk_assessment' AND COLUMN_NAME IN ('ml_score', 'ml_decision'))
    OR (TABLE_NAME = 'risk_blacklist' AND COLUMN_NAME = 'deleted_at')
    OR (TABLE_NAME = 'risk_case' AND COLUMN_NAME IN ('source_id', 'event_type')))
ORDER BY TABLE_NAME, ORDINAL_POSITION;
