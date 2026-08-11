-- ============================================
-- 旅游风控系统 - 预置规则数据初始化
-- 30 条规则覆盖 6 大旅游风险场景 (R001-R030)
-- 行业: 旅游 OTA 平台 (酒店/门票预订)
-- ============================================================
-- R001-R007  预订欺诈  (7 条)  event_type=预订
-- R008-R010  支付风险  (3 条)  event_type=支付
-- R011-R016  账户风险  (6 条)  event_type=通用/预订
-- R017-R020  退改滥用  (4 条)  event_type=退改签
-- R021-R023  行程风险  (3 条)  event_type=行程开始/通用
-- R024-R030  票务风险  (7 条)  event_type=预订/通用
-- ============================================================

USE ecs;

-- 关外键约束 (允许 TRUNCATE 被外键引用的表; risk_action_log.target_id 引用 risk_rule.rule_id)
SET FOREIGN_KEY_CHECKS = 0;

-- 清空已有规则 (方便重复执行, 包括关联表 risk_action_log 的历史记录)
TRUNCATE TABLE risk_rule;
TRUNCATE TABLE risk_action_log;  -- 审计日志表, 也清空避免外键指向已删 rule_id

-- 恢复外键约束
SET FOREIGN_KEY_CHECKS = 1;

-- ============================
-- 场景一: 预订欺诈 (7条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R001', '大额旅游预订', '预订欺诈', '预订',
 '{"field": "order_total_amount", "op": ">=", "value": 8000}',
 '中', 40, '标记', 1, 50,
 '单笔预订金额≥8000元(高端酒店/长线跟团), 标记关注');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R002', '超高额预订拦截', '预订欺诈', '预订',
 '{"field": "order_total_amount", "op": ">=", "value": 20000}',
 '极高', 90, '拒绝', 1, 100,
 '单笔预订金额≥20000元, 疑似盗刷或代订黑产, 一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R003', '高频预订', '预订欺诈', '预订',
 '{"field": "user_orders_7d", "op": ">=", "value": 8}',
 '高', 70, '人工审核', 1, 80,
 '7天内预订≥8次, 疑似代订黑产或脚本占库存');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R004', '极端预订频率', '预订欺诈', '预订',
 '{"and": [{"field": "user_orders_7d", "op": ">=", "value": 15}, {"field": "user_orders_30d", "op": ">=", "value": 30}]}',
 '极高', 85, '拒绝', 1, 95,
 '7天预订≥15次且30天≥30次, 严重机器预订, 一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R005', '深夜连续预订', '预订欺诈', '预订',
 '{"and": [{"field": "order_is_night", "op": "==", "value": 1}, {"field": "user_orders_7d", "op": ">=", "value": 5}]}',
 '高', 65, '人工审核', 1, 70,
 '凌晨0-6点预订且近7天≥5单, 疑似脚本批量订房');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R006', '预订提前期异常(临期大额)', '预订欺诈', '预订',
 '{"and": [{"field": "order_lead_days", "op": "<=", "value": 1}, {"field": "order_total_amount", "op": ">=", "value": 5000}]}',
 '高', 70, '人工审核', 1, 75,
 '出行日期≤1天且金额≥5000元, 疑似黄牛临期代订高价房/票');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R007', '多出行人高额订单', '预订欺诈', '预订',
 '{"and": [{"field": "trip_traveler_count", "op": ">=", "value": 6}, {"field": "order_total_amount", "op": ">=", "value": 10000}]}',
 '高', 65, '人工审核', 1, 72,
 '单订单出行人数≥6且金额≥10000元, 疑似代订黑产批量预订');

-- ============================
-- 场景二: 支付风险 (3条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R008', '极速支付', '支付风险', '支付',
 '{"and": [{"field": "order_pay_interval_sec", "op": "between", "value": [0, 3]}, {"field": "order_total_amount", "op": ">=", "value": 3000}]}',
 '中', 45, '标记', 1, 55,
 '预订到支付≤3秒且金额≥3000元, 疑似脚本支付');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R009', '高频未支付占库存', '支付风险', '支付',
 '{"and": [{"field": "user_orders_7d", "op": ">=", "value": 10}, {"field": "order_pay_interval_sec", "op": "==", "value": -1}]}',
 '中', 50, '标记', 1, 60,
 '7天预订≥10次且本单未支付, 疑似恶意占用房源/票源');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R010', '深夜高额支付', '支付风险', '支付',
 '{"and": [{"field": "order_is_night", "op": "==", "value": 1}, {"field": "order_total_amount", "op": ">=", "value": 8000}]}',
 '高', 60, '人工审核', 1, 65,
 '凌晨0-6点支付且金额≥8000元, 疑似盗卡支付');

-- ============================
-- 场景三: 账户风险 (6条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R011', '高退改率账户', '账户风险', '通用',
 '{"and": [{"field": "user_postsale_rate", "op": ">=", "value": 0.3}, {"field": "user_total_orders", "op": ">=", "value": 5}]}',
 '高', 60, '人工审核', 1, 70,
 '退改率≥30%且预订≥5单, 退改行为异常');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R012', '极高退改率账户', '账户风险', '通用',
 '{"and": [{"field": "user_postsale_rate", "op": ">=", "value": 0.8}, {"field": "user_total_orders", "op": ">=", "value": 3}]}',
 '极高', 85, '拒绝', 1, 98,
 '退改率≥80%且预订≥3单, 疑似恶意退改/薅羊毛, 一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R013', '高退款取消率', '账户风险', '通用',
 '{"and": [{"field": "user_refund_rate", "op": ">=", "value": 0.5}, {"field": "user_total_orders", "op": ">=", "value": 4}]}',
 '高', 65, '人工审核', 1, 75,
 '退款/退订率≥50%且预订≥4单, 疑似恶意退款');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R014', '高频取消预订', '账户风险', '通用',
 '{"field": "user_cancel_count", "op": ">=", "value": 5}',
 '中', 50, '标记', 1, 55,
 '取消预订≥5次, 疑似恶意占用库存');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R015', '新账户大额预订', '账户风险', '预订',
 '{"and": [{"field": "user_total_orders", "op": "<=", "value": 2}, {"field": "order_total_amount", "op": ">=", "value": 6000}]}',
 '高', 65, '人工审核', 1, 85,
 '历史预订≤2单且当前金额≥6000元, 新账户大额消费风险');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R016', '短期多目的地账户', '账户风险', '通用',
 '{"and": [{"field": "user_trip_city_count", "op": ">=", "value": 8}, {"field": "user_orders_30d", "op": ">=", "value": 10}]}',
 '高', 70, '人工审核', 1, 78,
 '出行目的地≥8个城市且30天预订≥10单, 疑似全国代订倒卖');

-- ============================
-- 场景四: 退改滥用 (4条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R017', '退款次数过多', '退改滥用', '退改签',
 '{"field": "user_refund_count", "op": ">=", "value": 5}',
 '高', 60, '人工审核', 1, 70,
 '退款/退订≥5次, 退改行为需人工复核');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R018', '退改次数过多', '退改滥用', '退改签',
 '{"field": "user_postsale_count", "op": ">=", "value": 8}',
 '高', 70, '人工审核', 1, 80,
 '退改签≥8次, 疑似职业退改');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R019', '退款金额过大', '退改滥用', '退改签',
 '{"field": "user_refund_amount", "op": ">=", "value": 10000}',
 '极高', 85, '拒绝', 1, 95,
 '累计退款≥10000元, 疑似骗退套现, 一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R020', '频繁改期模式', '退改滥用', '退改签',
 '{"and": [{"field": "user_postsale_count", "op": ">=", "value": 6}, {"field": "user_postsale_rate", "op": ">=", "value": 0.5}]}',
 '高', 70, '人工审核', 1, 75,
 '退改≥6次且退改率≥50%, 频繁改期锁资源异常模式');

-- ============================
-- 场景五: 行程风险 (3条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R021', '行程投诉用户', '行程风险', '行程开始',
 '{"field": "user_complaint_count", "op": ">=", "value": 2}',
 '中', 50, '标记', 1, 50,
 '行程投诉≥2次, 行程开始事件标记关注');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R022', '行程投诉过多', '行程风险', '行程开始',
 '{"field": "user_complaint_count", "op": ">=", "value": 5}',
 '高', 75, '人工审核', 1, 70,
 '行程投诉≥5次, 疑似恶意投诉或服务质量需核查');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R023', '投诉叠加高退款率', '行程风险', '通用',
 '{"and": [{"field": "user_complaint_count", "op": ">=", "value": 2}, {"field": "user_refund_rate", "op": ">=", "value": 0.3}]}',
 '高', 70, '人工审核', 1, 72,
 '投诉≥2次且退款率≥30%, 疑似投诉骗退黑产');

-- ============================
-- 场景六: 票务风险 (7条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R024', '大批量购票', '票务风险', '预订',
 '{"and": [{"field": "order_sku_count", "op": ">=", "value": 10}, {"field": "order_total_amount", "op": ">=", "value": 3000}]}',
 '高', 70, '人工审核', 1, 80,
 '单订单购票/间夜≥10且金额≥3000元, 疑似黄牛囤票');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R025', '超大量购票拦截', '票务风险', '预订',
 '{"field": "order_sku_count", "op": ">=", "value": 20}',
 '极高', 90, '拒绝', 1, 96,
 '单订单购票/间夜≥20, 严重囤票倒卖嫌疑, 一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R026', '深折扣订单', '票务风险', '预订',
 '{"and": [{"field": "order_discount_rate", "op": ">=", "value": 0.5}, {"field": "order_total_amount", "op": ">=", "value": 2000}]}',
 '中', 45, '标记', 1, 55,
 '折扣率≥50%且金额≥2000元, 疑似利用优惠券漏洞');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R027', '优惠叠加高频预订', '票务风险', '预订',
 '{"and": [{"field": "order_discount_rate", "op": ">=", "value": 0.3}, {"field": "user_orders_7d", "op": ">=", "value": 6}]}',
 '高', 60, '人工审核', 1, 65,
 '折扣率≥30%且7天预订≥6次, 疑似职业薅旅游优惠');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R028', '多品类混合大额订单', '票务风险', '预订',
 '{"and": [{"field": "order_item_count", "op": ">=", "value": 5}, {"field": "order_total_amount", "op": ">=", "value": 8000}]}',
 '中', 50, '标记', 1, 45,
 '单订单≥5个明细且金额≥8000元, 混合代订订单标记');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R029', '新出行人高额行程', '票务风险', '预订',
 '{"and": [{"field": "trip_is_new_traveler", "op": "==", "value": 1}, {"field": "order_total_amount", "op": ">=", "value": 8000}]}',
 '中', 45, '标记', 1, 40,
 '首次使用的出行人且金额≥8000元, 低风险标记关注');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R030', '高频高额代订账户', '票务风险', '通用',
 '{"and": [{"field": "user_orders_30d", "op": ">=", "value": 20}, {"field": "user_avg_order_amount", "op": ">=", "value": 5000}]}',
 '极高', 85, '拒绝', 1, 90,
 '30天预订≥20单且平均金额≥5000元, 代订黑产账户一票否决');

-- ============================
-- 旅游行业黑名单种子 (risk_blacklist)
-- ============================
INSERT INTO risk_blacklist (blacklist_type, blacklist_value, reason) VALUES
('手机号', '13900009999', '代订黑产常用手机号'),
('手机号', '13711112222', '黄牛倒卖门票手机号'),
('手机号', '13633334444', '投诉骗退黑产手机号'),
('用户', 'U_BLACK_001', '高风险代订账户'),
('用户', 'U_BLACK_002', '恶意退改账户');
