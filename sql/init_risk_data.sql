-- ============================================
-- 电商风控系统 - 预置规则数据初始化
-- 30 条规则覆盖 6 大风险场景 (R001-R030)
-- ============================================================
-- R001-R005  订单欺诈  (5 条)
-- R006-R009  支付风险  (4 条)
-- R010-R013  账户风险  (4 条, 含 R025/R029 新增)
-- R014-R017  售后滥用  (4 条, 含 R027 新增)
-- R018-R021  地址风险  (4 条)
-- R022-R024  物流风险  (3 条, 含 R028 新增)
-- R025-R026  新增支付/账户风险  (2 条, 极小金额/批量注册)
-- R027       新增售后滥用     (1 条, 多次换货模式)
-- R028       新增物流风险     (1 条, 订单+换地址)
-- R029-R030  新增账户/综合   (2 条, 首单大额 + 多条件 AND)
-- ============================================================

USE ecs;

-- 关外键约束 (允许 TRUNCATE 被外键引用的表; P4-L1 risk_action_log.target_id 引用 risk_rule.rule_id)
SET FOREIGN_KEY_CHECKS = 0;

-- 清空已有规则 (方便重复执行, 包括关联表 risk_action_log 的历史记录)
TRUNCATE TABLE risk_rule;
TRUNCATE TABLE risk_action_log;  -- P4-L1 审计日志表, 也清空避免外键指向已删 rule_id

-- 恢复外键约束
SET FOREIGN_KEY_CHECKS = 1;

-- ============================
-- 场景一: 订单欺诈 (5条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R001', '单笔超高金额订单', '订单欺诈', '下单',
 '{"field": "order_total_amount", "op": ">=", "value": 5000}',
 '高', 70, '人工审核', 1, 90,
 '单笔订单实付金额≥5000元，可能存在欺诈风险');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R002', '单笔极端高额订单', '订单欺诈', '下单',
 '{"field": "order_total_amount", "op": ">=", "value": 10000}',
 '极高', 95, '拒绝', 1, 100,
 '单笔订单实付金额≥10000元，一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R003', '深夜下单', '订单欺诈', '下单',
 '{"field": "order_is_night", "op": "==", "value": 1}',
 '中', 30, '标记', 1, 40,
 '凌晨0-6点下单，标记关注');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R004', '极速支付', '订单欺诈', '下单',
 '{"field": "order_pay_interval_sec", "op": "between", "value": [0, 5]}',
 '高', 60, '人工审核', 1, 70,
 '下单到支付间隔≤5秒，疑似机器下单');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R005', '高折扣率订单', '订单欺诈', '下单',
 '{"field": "order_discount_rate", "op": ">=", "value": 0.7}',
 '高', 65, '人工审核', 1, 60,
 '订单折扣率≥70%，疑似利用优惠漏洞');

-- ============================
-- 场景二: 支付风险 (4条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R006', '用户7天内高频下单', '支付风险', '支付',
 '{"field": "user_orders_7d", "op": ">=", "value": 10}',
 '高', 70, '人工审核', 1, 80,
 '7天内下单≥10次，疑似刷单');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R007', '用户30天内大量下单', '支付风险', '支付',
 '{"field": "user_orders_30d", "op": ">=", "value": 30}',
 '极高', 90, '拒绝', 1, 95,
 '30天内下单≥30次，严重刷单嫌疑，一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R008', '订单金额远超用户平均', '支付风险', '支付',
 '{"and": [{"field": "order_total_amount", "op": ">=", "value": 2000}, {"field": "user_avg_order_amount", "op": "<", "value": 500}]}',
 '高', 65, '人工审核', 1, 75,
 '当前订单金额≥2000且用户历史平均<500，消费行为异常');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R009', '用户累计消费异常', '支付风险', '支付',
 '{"field": "user_total_amount", "op": ">=", "value": 50000}',
 '中', 40, '标记', 1, 50,
 '用户累计消费≥5万元，标记为高消费用户');

-- ============================
-- 场景三: 账户风险 (4条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R010', '高取消率用户', '账户风险', '通用',
 '{"and": [{"field": "user_cancel_count", "op": ">=", "value": 5}, {"field": "user_total_orders", "op": ">=", "value": 5}]}',
 '中', 45, '标记', 1, 55,
 '取消订单≥5次且总订单≥5，取消行为异常');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R011', '新用户大额订单', '账户风险', '下单',
 '{"and": [{"field": "user_total_orders", "op": "<=", "value": 2}, {"field": "order_total_amount", "op": ">=", "value": 3000}]}',
 '高', 75, '人工审核', 1, 85,
 '历史订单≤2且当前订单≥3000元，新用户大额消费风险');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R012', '用户有大量投诉记录', '账户风险', '通用',
 '{"field": "user_complaint_count", "op": ">=", "value": 3}',
 '高', 60, '人工审核', 1, 65,
 '投诉次数≥3，账户存在风险');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R013', '多地址用户', '账户风险', '通用',
 '{"field": "user_address_count", "op": ">=", "value": 5}',
 '中', 35, '标记', 1, 45,
 '用户收货地址≥5个，关注账户共享可能');

-- ============================
-- 场景四: 售后滥用 (4条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R014', '高退款率用户', '售后滥用', '售后申请',
 '{"and": [{"field": "user_refund_rate", "op": ">=", "value": 0.5}, {"field": "user_total_orders", "op": ">=", "value": 5}]}',
 '高', 70, '人工审核', 1, 80,
 '退款率≥50%且订单≥5单，疑似恶意退款');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R015', '极端退款率用户', '售后滥用', '售后申请',
 '{"and": [{"field": "user_refund_rate", "op": ">=", "value": 0.8}, {"field": "user_total_orders", "op": ">=", "value": 3}]}',
 '极高', 92, '拒绝', 1, 98,
 '退款率≥80%且订单≥3单，严重售后滥用，一票否决');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R016', '高售后率用户', '售后滥用', '售后申请',
 '{"and": [{"field": "user_postsale_rate", "op": ">=", "value": 0.4}, {"field": "user_total_orders", "op": ">=", "value": 5}]}',
 '中', 50, '标记', 1, 60,
 '售后率≥40%且订单≥5，售后行为需关注');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R017', '高退款金额用户', '售后滥用', '售后申请',
 '{"field": "user_refund_amount", "op": ">=", "value": 5000}',
 '高', 55, '人工审核', 1, 55,
 '累计退款金额≥5000元，退款金额异常');

-- ============================
-- 场景五: 地址风险 (4条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R018', '新收货地址下单', '地址风险', '下单',
 '{"field": "addr_is_new", "op": "==", "value": 1}',
 '低', 15, '通过', 1, 20,
 '使用新收货地址下单，低风险标记');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R019', '新地址+大额订单', '地址风险', '下单',
 '{"and": [{"field": "addr_is_new", "op": "==", "value": 1}, {"field": "order_total_amount", "op": ">=", "value": 2000}]}',
 '高', 70, '人工审核', 1, 82,
 '新地址且订单金额≥2000元，地址欺诈风险');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R020', '多省份地址用户', '地址风险', '通用',
 '{"field": "addr_province_count", "op": ">=", "value": 3}',
 '中', 40, '标记', 1, 50,
 '用户地址覆盖≥3个省份，地址分散异常');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R021', '大量地址用户+高金额', '地址风险', '下单',
 '{"and": [{"field": "addr_total_count", "op": ">=", "value": 4}, {"field": "order_total_amount", "op": ">=", "value": 1500}]}',
 '高', 65, '人工审核', 1, 70,
 '地址≥4个且订单金额≥1500元，疑似代收/转单');

-- ============================
-- 场景六: 物流风险 (3条)
-- ============================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R022', '投诉用户下单', '物流风险', '下单',
 '{"field": "user_complaint_count", "op": ">=", "value": 1}',
 '低', 20, '通过', 1, 30,
 '有物流投诉记录的用户下单，低风险标记');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R023', '高频投诉用户', '物流风险', '物流投诉',
 '{"field": "user_complaint_count", "op": ">=", "value": 5}',
 '高', 60, '人工审核', 1, 70,
 '投诉次数≥5次，疑似恶意投诉');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R024', '大量商品类别订单', '物流风险', '下单',
 '{"field": "order_category_count", "op": ">=", "value": 5}',
 '中', 35, '标记', 1, 40,
 '单笔订单包含≥5个商品类别，购买行为异常');


-- ============================================================
-- 新增规则 (R025-R030) - 2026-08-07
-- 覆盖 4 个新场景: 极小金额/批量注册/换货模式/订单换地址/首单大额/AND 组合
-- ============================================================

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R025', '极小金额订单 (疑似刷单测试)', '支付风险', '下单',
 '{"field": "order_total_amount", "op": "<=", "value": 1}',
 '高', 50, '人工审核', 1, 85,
 '订单金额≤1元，疑似刷单测试或恶意占库存');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R026', '收货地址数过多 (>10)', '账户风险', '通用',
 '{"field": "user_address_count", "op": ">", "value": 10}',
 '高', 55, '人工审核', 1, 60,
 '用户收货地址超过10个，疑似批量小号注册');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R027', '高换货率用户 (非退款)', '售后滥用', '售后申请',
 '{"and": [{"field": "user_postsale_count", "op": ">=", "value": 5}, {"field": "user_refund_count", "op": "<", "value": 2}]}',
 '中', 40, '标记', 1, 50,
 '售后≥5次但退款<2次，频繁换货异常模式 (白嫖商品嫌疑)');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R028', '新地址 + 多次换地址', '物流风险', '下单',
 '{"and": [{"field": "addr_is_new", "op": "==", "value": 1}, {"field": "user_address_count", "op": ">=", "value": 4}]}',
 '高', 55, '人工审核', 1, 65,
 '首次用新地址下单 + 用户地址≥4个, 疑似恶意换地址');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R029', '新用户首单大额 (零评估历史)', '账户风险', '下单',
 '{"and": [{"field": "assessment_count", "op": "==", "value": 0}, {"field": "order_total_amount", "op": ">=", "value": 5000}]}',
 '高', 70, '人工审核', 1, 75,
 '新注册用户 (无评估历史) 首单≥5000, 高风险信号');

INSERT INTO risk_rule (rule_id, rule_name, rule_category, event_type, rule_condition, risk_level, risk_score, action, is_enabled, priority, description) VALUES
('R030', '综合高风险 (退款+大额+多地址)', '账户风险', '通用',
 '{"and": [
   {"field": "user_refund_rate", "op": ">=", "value": 0.5},
   {"field": "user_avg_order_amount", "op": ">=", "value": 2000},
   {"field": "user_address_count", "op": ">=", "value": 3}
 ]}',
 '极高', 90, '拒绝', 1, 95,
 '退款率≥50% 且 平均订单≥2000元 且 地址≥3个, 3 个高危条件 AND 触发一票否决');
