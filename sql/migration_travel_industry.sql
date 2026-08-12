-- ============================================================
-- 旅游行业迁移脚本 (场景 A: 旅游 OTA 风控)
-- 将现有电商风控库迁移为旅游风控库
-- 适用: 已存在电商数据/表结构的 ecs 数据库 (MySQL 8.x)
-- 执行: mysql -uroot -p123456 ecs < sql/migration_travel_industry.sql
--       然后执行 sql/init_business_data.sql 和 sql/init_risk_data.sql 导入旅游字典与规则
-- 说明: 本脚本可重复执行 (幂等); 会清空全部业务与风控数据!
-- ============================================================

USE ecs;
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- 第一步: 清空电商时代的业务数据与风控数据
-- (旧枚举值无法保留, 必须清空后按旅游语义重建)
-- ----------------------------
TRUNCATE TABLE postsale_logistics;
TRUNCATE TABLE postsale;
TRUNCATE TABLE logistics_complaints_record;
TRUNCATE TABLE logistics_complaint;
TRUNCATE TABLE order_logistics;
TRUNCATE TABLE order_detail;
TRUNCATE TABLE logistics;
TRUNCATE TABLE order_info;
TRUNCATE TABLE receive_info;
TRUNCATE TABLE sku_info;
TRUNCATE TABLE postsale_reason;
TRUNCATE TABLE postsale_status;
TRUNCATE TABLE order_status;
TRUNCATE TABLE logistics_company;
TRUNCATE TABLE product_category;
TRUNCATE TABLE region;
TRUNCATE TABLE user_info;

TRUNCATE TABLE risk_feature;
TRUNCATE TABLE risk_rule;
TRUNCATE TABLE risk_assessment;
TRUNCATE TABLE risk_case;
TRUNCATE TABLE risk_event;
TRUNCATE TABLE risk_user_profile;
TRUNCATE TABLE risk_blacklist;
TRUNCATE TABLE risk_action_log;
TRUNCATE TABLE risk_alert;

-- ----------------------------
-- 第二步: 表结构迁移
-- ----------------------------

-- 2.1 order_info 增加旅游字段 (出行日期/出行人数) -- 幂等
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='order_info' AND COLUMN_NAME='travel_date');
SET @s := IF(@c=0, 'ALTER TABLE order_info ADD COLUMN travel_date DATE DEFAULT NULL COMMENT ''出行日期'' AFTER order_status', 'SELECT 1');
PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='order_info' AND COLUMN_NAME='travel_persons');
SET @s := IF(@c=0, 'ALTER TABLE order_info ADD COLUMN travel_persons INT DEFAULT 1 COMMENT ''出行人数'' AFTER travel_date', 'SELECT 1');
PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2.2 risk_rule: 规则类别/事件类型 改为旅游行业枚举
ALTER TABLE risk_rule
    MODIFY COLUMN rule_category ENUM('预订欺诈','支付风险','账户风险','退改滥用','行程风险','票务风险')
        NOT NULL COMMENT '风险场景分类';
ALTER TABLE risk_rule
    MODIFY COLUMN event_type ENUM('预订','支付','退改签','行程开始','通用')
        NOT NULL DEFAULT '通用' COMMENT '适用事件类型';

-- 2.3 risk_event: 事件类型改为旅游行业枚举
ALTER TABLE risk_event
    MODIFY COLUMN event_type ENUM('预订','支付','退改签','行程开始')
        NOT NULL COMMENT '事件类型';

-- 2.4 risk_case: 事件类型改为旅游行业枚举 (决策引擎写案件时引用)
ALTER TABLE risk_case
    MODIFY COLUMN event_type ENUM('预订','支付','退改签','行程开始')
        DEFAULT NULL COMMENT '触发案件的事件类型';

-- 2.5 risk_feature: 实体类型改为旅游行业枚举 (用户/订单/行程/票券)
ALTER TABLE risk_feature
    MODIFY COLUMN entity_type ENUM('用户','订单','行程','票券')
        NOT NULL COMMENT '实体类型';

-- 2.6 risk_user_profile: address_count → trip_city_count (出行目的地城市数) -- 幂等
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='risk_user_profile' AND COLUMN_NAME='address_count');
SET @s := IF(@c>0, 'ALTER TABLE risk_user_profile CHANGE COLUMN address_count trip_city_count INT DEFAULT 0 COMMENT ''出行目的地城市数量''', 'SELECT 1');
PREPARE stmt FROM @s; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2.7 postsale: 售后类型 → 退改签类型 (退款/改期/退订)
ALTER TABLE postsale
    MODIFY COLUMN postsale_type ENUM('退款','改期','退订') DEFAULT NULL COMMENT '退改签类型';

-- 2.8 logistics: 物流类别 → 出行方式 (自由行/跟团游/定制游)
ALTER TABLE logistics
    MODIFY COLUMN logistics_category ENUM('自由行','跟团游','定制游') DEFAULT NULL COMMENT '出行方式';

SET FOREIGN_KEY_CHECKS = 1;

SELECT '旅游行业迁移完成: 请继续执行 init_business_data.sql 与 init_risk_data.sql' AS migration_result;
