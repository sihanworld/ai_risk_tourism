-- ============================================
-- ⚠ DEPRECATED 2026-08-07
-- 内容已合并到 migration_add_2026_08_07_fields.sql (项 5/6/7)
-- 老用户跑这个脚本依然有效 (幂等), 但建议改跑 migration_add_2026_08_07_fields.sql
-- 保留此文件仅为兼容历史文档引用, 不再被 init_db.py 调用
-- ============================================
--
-- 原内容 (为兼容老用户, 保留):
--   为 risk_case 增加 source_id / event_type 字段
--   用于支持"从案件重做风控检查"功能
--   老案件这两个字段为 NULL (前端会显示"无 source_id", 不影响现有功能)
--   新案件写入时由 decision.py 自动填充
-- ============================================

USE ecs;

-- 1. 加 source_id 字段
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_case' AND COLUMN_NAME = 'source_id') = 0,
    'ALTER TABLE risk_case ADD COLUMN source_id VARCHAR(50) DEFAULT NULL COMMENT "原始业务ID(订单/退改签/投诉ID)" AFTER risk_detail',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2. 加 event_type 字段
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_case' AND COLUMN_NAME = 'event_type') = 0,
    'ALTER TABLE risk_case ADD COLUMN event_type ENUM("预订", "支付", "退改签", "行程开始") DEFAULT NULL COMMENT "触发案件的事件类型" AFTER source_id',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3. 加索引 (MySQL 不支持 CREATE INDEX IF NOT EXISTS, 用存储过程判断)
SET @sql = (SELECT IF(
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
     WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_case' AND INDEX_NAME = 'idx_risk_case_source_id') = 0,
    'ALTER TABLE risk_case ADD INDEX idx_risk_case_source_id (source_id)',
    'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4. 验证
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_COMMENT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'ecs' AND TABLE_NAME = 'risk_case'
  AND COLUMN_NAME IN ('source_id', 'event_type');
