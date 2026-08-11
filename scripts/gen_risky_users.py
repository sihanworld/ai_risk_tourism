"""
生成有风险行为的用户测试数据 (异步).
【P4-L3 2026-08-08 第二轮】支持 --count 指定生成用户数 (默认 5).
【2026-08-11 旅游行业迁移】风险模式改为旅游场景:
  模式 1: 高退改率 (10 单 + 9 退改签, 退改率 90%)
  模式 2: 高频预订 (35 单, 30 天内)
  模式 3: 高退款金额 (3 单 + 2 退改 6000)
  模式 4: 多目的地 (7 个出行人/行程信息跨 7 城, 代订黑产特征)
  模式 5: 有投诉 (2 订单 + 2 行程投诉)

例:
  python scripts/gen_risky_users.py                # 默认 5 个 (RISK001-005)
  python scripts/gen_risky_users.py --count 30     # 30 个 (RISK001-030, 6 套 × 5 模式)
  python scripts/gen_risky_users.py --count 1      # 只 1 个 (RISK001, 高退改率模式)
  python scripts/gen_risky_users.py --reset        # 先删旧 RISK 用户再生成

风险模式轮换逻辑: idx % 5, 所以 count=30 → 6 套各 5 个 = 30 个; count=7 → 模式 1-5 + 模式 1-2 = 7 个
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

# 5 种风险模式 (旅游行业)
RISK_MODES = ["高退改率", "高频预订", "高退款金额", "多目的地", "有投诉"]

async def _gen_high_refund_user(conn, user_id: str, rec_id: str):
    """模式 1: 高退改率用户 (10 单 + 9 退改签, 退改率 90%)"""
    # 出行人/行程信息
    await conn.execute(text("""
        INSERT IGNORE INTO receive_info (receive_id, user_id, receiver_name, receiver_phone,
        receive_province, receive_city, receive_district, receive_street_address)
        VALUES (:rec_id, :uid, '张三', '13800138000', '北京市', '北京市', '朝阳区', '亚龙湾度假酒店')
    """), {"rec_id": rec_id, "uid": user_id})
    # 10 个预订订单
    for i in range(1, 11):
        day_offset = max(1, 30 - i * 3)  # 30, 28, 25, 20, 15, 12, 10, 8, 5, 2 天前
        await conn.execute(text("""
            INSERT IGNORE INTO order_info (order_id, user_id, order_status, receive_id, create_time, payment_time, travel_date, travel_persons)
            VALUES (:oid, :uid, '已完成', :rec_id,
            DATE_SUB(NOW(), INTERVAL :d1 DAY), DATE_SUB(NOW(), INTERVAL :d2 DAY),
            DATE_ADD(NOW(), INTERVAL 7 DAY), 2)
        """), {"oid": f"ORD_{user_id[4:]}_{i:02d}", "uid": user_id, "rec_id": rec_id,
               "d1": day_offset, "d2": max(1, day_offset - 1)})
        await conn.execute(text("""
            INSERT IGNORE INTO order_detail (order_detail_id, order_id, sku_id, sku_name, sku_count, total_amount, discount_amount, final_amount)
            VALUES (:odid, :oid, 'RSKU001', '三亚亚龙湾度假酒店豪华海景房', 1, 1000, 0, 1000)
        """), {"odid": f"OD_{user_id[4:]}_{i:02d}", "oid": f"ORD_{user_id[4:]}_{i:02d}"})
    # 9 个退改签
    for i in range(1, 10):
        day_offset = max(1, 28 - i * 3)
        await conn.execute(text("""
            INSERT IGNORE INTO postsale (postsale_id, order_detail_id, postsale_type, refund_amount, postsale_status, postsale_reason, receive_id, create_time)
            VALUES (:pid, :odid, '退款', 1000, '已退款', '行程有变', :rec_id, DATE_SUB(NOW(), INTERVAL :d DAY))
        """), {"pid": f"PS_{user_id[4:]}_{i:02d}",
               "odid": f"OD_{user_id[4:]}_{i:02d}",
               "rec_id": rec_id, "d": day_offset})

async def _gen_high_freq_user(conn, user_id: str, rec_id: str):
    """模式 2: 高频预订用户 (35 单, 30 天内)"""
    await conn.execute(text("""
        INSERT IGNORE INTO receive_info (receive_id, user_id, receiver_name, receiver_phone,
        receive_province, receive_city, receive_district, receive_street_address)
        VALUES (:rec_id, :uid, '李四', '13800138002', '上海市', '上海市', '浦东新区', '迪士尼乐园酒店')
    """), {"rec_id": rec_id, "uid": user_id})
    base_date = datetime.now() - timedelta(days=25)
    for i in range(35):
        order_date = base_date + timedelta(days=i % 25)
        order_dt = order_date.strftime("%Y-%m-%d %H:%M:%S")
        pay_dt = (order_date + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        await conn.execute(text("""
            INSERT IGNORE INTO order_info (order_id, user_id, order_status, receive_id, create_time, payment_time, travel_date, travel_persons)
            VALUES (:oid, :uid, '已完成', :rec_id, :d1, :d2, DATE_ADD(NOW(), INTERVAL 10 DAY), 1)
        """), {"oid": f"ORD_{user_id[4:]}_{i:02d}", "uid": user_id, "rec_id": rec_id,
               "d1": order_dt, "d2": pay_dt})
        await conn.execute(text("""
            INSERT IGNORE INTO order_detail (order_detail_id, order_id, sku_id, sku_name, sku_count, total_amount, discount_amount, final_amount)
            VALUES (:odid, :oid, 'RSKU002', '上海迪士尼乐园一日门票', 1, 500, 0, 500)
        """), {"odid": f"OD_{user_id[4:]}_{i:02d}", "oid": f"ORD_{user_id[4:]}_{i:02d}"})

async def _gen_high_amount_user(conn, user_id: str, rec_id: str):
    """模式 3: 高退款金额用户 (3 单 + 2 退改 6000)"""
    await conn.execute(text("""
        INSERT IGNORE INTO receive_info (receive_id, user_id, receiver_name, receiver_phone,
        receive_province, receive_city, receive_district, receive_street_address)
        VALUES (:rec_id, :uid, '王五', '13800138003', '广东省', '广州市', '天河区', '长隆旅游度假区')
    """), {"rec_id": rec_id, "uid": user_id})
    # 3 个大额订单 (高端跟团游)
    for i, day in enumerate([15, 10, 5], 1):
        await conn.execute(text("""
            INSERT IGNORE INTO order_info (order_id, user_id, order_status, receive_id, create_time, payment_time, travel_date, travel_persons)
            VALUES (:oid, :uid, '已完成', :rec_id, DATE_SUB(NOW(), INTERVAL :d1 DAY), DATE_SUB(NOW(), INTERVAL :d2 DAY),
            DATE_ADD(NOW(), INTERVAL 15 DAY), 2)
        """), {"oid": f"ORD_{user_id[4:]}_{i:02d}", "uid": user_id, "rec_id": rec_id,
               "d1": day, "d2": day - 1})
        await conn.execute(text("""
            INSERT IGNORE INTO order_detail (order_detail_id, order_id, sku_id, sku_name, sku_count, total_amount, discount_amount, final_amount)
            VALUES (:odid, :oid, 'RSKU003', '新疆喀纳斯伊犁8日跟团游', 1, 3000, 0, 3000)
        """), {"odid": f"OD_{user_id[4:]}_{i:02d}", "oid": f"ORD_{user_id[4:]}_{i:02d}"})
    # 2 个 3000 退改签
    for i, day in enumerate([12, 7], 1):
        await conn.execute(text("""
            INSERT IGNORE INTO postsale (postsale_id, order_detail_id, postsale_type, refund_amount, postsale_status, postsale_reason, receive_id, create_time)
            VALUES (:pid, :odid, '退款', 3000, '已退款', '个人原因无法出行', :rec_id, DATE_SUB(NOW(), INTERVAL :d DAY))
        """), {"pid": f"PS_{user_id[4:]}_{i:02d}", "odid": f"OD_{user_id[4:]}_{i:02d}",
               "rec_id": rec_id, "d": day})

async def _gen_multi_addr_user(conn, user_id: str, rec_id: str):
    """模式 4: 多目的地用户 (7 个出行人/行程信息跨 7 城, 代订黑产特征)"""
    provinces = ['北京市', '上海市', '广东省', '浙江省', '江苏省', '四川省', '湖北省']
    cities = ['北京市', '上海市', '广州市', '杭州市', '南京市', '成都市', '武汉市']
    districts = ['朝阳区', '浦东新区', '天河区', '西湖区', '玄武区', '锦江区', '武昌区']
    spots = ['故宫景观酒店', '外滩酒店', '长隆度假村', '西湖湖畔精品酒店',
             '夫子庙客栈', '春熙路酒店', '黄鹤楼观景酒店']
    for i, prov in enumerate(provinces):
        await conn.execute(text("""
            INSERT IGNORE INTO receive_info (receive_id, user_id, receiver_name, receiver_phone,
            receive_province, receive_city, receive_district, receive_street_address)
            VALUES (:rec_id, :uid, :name, :phone, :prov, :city, :dist, :addr)
        """), {"rec_id": f"{rec_id}_{i}", "uid": user_id,
               "name": f"出行人{i}", "phone": f"1390013900{i}",
               "prov": prov, "city": cities[i], "dist": districts[i],
               "addr": spots[i]})

async def _gen_complaint_user(conn, user_id: str, rec_id: str):
    """模式 5: 有投诉用户 (2 订单 + 2 行程投诉)"""
    await conn.execute(text("""
        INSERT IGNORE INTO receive_info (receive_id, user_id, receiver_name, receiver_phone,
        receive_province, receive_city, receive_district, receive_street_address)
        VALUES (:rec_id, :uid, '赵六', '13800138005', '江苏省', '南京市', '玄武区', '夫子庙景区民宿')
    """), {"rec_id": rec_id, "uid": user_id})
    # 2 个预订订单
    for i, day in enumerate([10, 7], 1):
        await conn.execute(text("""
            INSERT IGNORE INTO order_info (order_id, user_id, order_status, receive_id, create_time, payment_time, travel_date, travel_persons)
            VALUES (:oid, :uid, '已完成', :rec_id, DATE_SUB(NOW(), INTERVAL :d1 DAY), DATE_SUB(NOW(), INTERVAL :d2 DAY),
            DATE_ADD(NOW(), INTERVAL 5 DAY), 2)
        """), {"oid": f"ORD_{user_id[4:]}_{i:02d}", "uid": user_id, "rec_id": rec_id,
               "d1": day, "d2": day - 1})
        await conn.execute(text("""
            INSERT IGNORE INTO order_detail (order_detail_id, order_id, sku_id, sku_name, sku_count, total_amount, discount_amount, final_amount)
            VALUES (:odid, :oid, 'RSKU004', '南京至上海高铁二等座', 2, 800, 0, 800)
        """), {"odid": f"OD_{user_id[4:]}_{i:02d}", "oid": f"ORD_{user_id[4:]}_{i:02d}"})
    # 2 个行程投诉
    for i, (log_id, status, complaint, day) in enumerate([
        ("LOG01", "行程中", "行程安排不合理", 5),
        ("LOG02", "行程已完成", "酒店与描述不符", 3),
    ], 1):
        await conn.execute(text("""
            INSERT IGNORE INTO logistics (logistics_id, create_time, logistics_tracking, logistics_category)
            VALUES (:lid, DATE_SUB(NOW(), INTERVAL :d1 DAY), :status, '跟团游')
        """), {"lid": f"{log_id}_{user_id}", "d1": day + 2, "status": status})
        await conn.execute(text("""
            INSERT IGNORE INTO order_logistics (order_id, logistics_id)
            VALUES (:oid, :lid)
        """), {"oid": f"ORD_{user_id[4:]}_{i:02d}", "lid": f"{log_id}_{user_id}"})
        await conn.execute(text("""
            INSERT IGNORE INTO logistics_complaint (logistics_status, logistics_complaint)
            VALUES (:status, :complaint)
        """), {"status": status, "complaint": complaint})
        await conn.execute(text("""
            INSERT IGNORE INTO logistics_complaints_record
            (logistics_id, logistics_complaint, complaint_time, user_id)
            VALUES (:lid, :complaint, DATE_SUB(NOW(), INTERVAL :d DAY), :uid)
        """), {"lid": f"{log_id}_{user_id}", "complaint": complaint, "d": day, "uid": user_id})

# 5 种模式生成器
MODE_GENERATORS = [
    _gen_high_refund_user,    # 模式 0: 高退改率
    _gen_high_freq_user,      # 模式 1: 高频预订
    _gen_high_amount_user,    # 模式 2: 高退款金额
    _gen_multi_addr_user,     # 模式 3: 多目的地
    _gen_complaint_user,      # 模式 4: 有投诉
]

async def gen_risky_users(count: int = 5, reset: bool = False):
    """生成 N 个 RISK 高风险用户 (5 种模式轮换).

    Args:
        count: 生成用户数 (默认 5). 例: count=30 → RISK001-RISK030 (6 套 × 5 模式).
        reset: 是否先删旧 RISK 用户 + 相关数据 (默认 False, 用 INSERT IGNORE 增量插入).
    """
    if count < 1:
        raise ValueError(f"--count 必须 >= 1, 当前 {count}")

    db_url = settings.get_database_url_async()
    engine = create_async_engine(db_url)

    async with engine.connect() as conn:
        if reset:
            print(f"[reset] 删旧 RISK 用户 + 关联数据...")
            # 先删从表 (子表), 再删主表, 避免外键约束
            for tbl in ("logistics_complaints_record", "order_logistics", "logistics",
                        "postsale", "order_detail", "order_info", "receive_info", "user_info"):
                await conn.execute(text(f"DELETE FROM {tbl} WHERE user_id LIKE 'RISK%' OR user_id LIKE 'RISK%'"))
            print(f"  清理完成")

        # 基础数据 (region / sku / 订单状态 / 供应商 / 退改签原因) 只插入一次
        print(f"[setup] 基础数据 (region/sku/order_status/logistics_company/postsale_reason)...")
        await conn.execute(text("""
            INSERT IGNORE INTO region (province, city, district) VALUES
            ('北京市', '北京市', '朝阳区'), ('上海市', '上海市', '浦东新区'),
            ('广东省', '广州市', '天河区'), ('浙江省', '杭州市', '西湖区'),
            ('江苏省', '南京市', '玄武区'), ('四川省', '成都市', '锦江区'),
            ('湖北省', '武汉市', '武昌区')
        """))
        await conn.execute(text("""
            INSERT IGNORE INTO product_category (product_category) VALUES ('酒店'), ('门票'), ('跟团游'), ('火车票')
        """))
        await conn.execute(text("""
            INSERT IGNORE INTO sku_info (sku_id, sku_name, sku_price, sku_category, sku_count) VALUES
            ('RSKU001', '三亚亚龙湾度假酒店豪华海景房', 1000.00, '酒店', 100),
            ('RSKU002', '上海迪士尼乐园一日门票', 500.00, '门票', 1000),
            ('RSKU003', '新疆喀纳斯伊犁8日跟团游', 3000.00, '跟团游', 50),
            ('RSKU004', '南京至上海高铁二等座', 400.00, '火车票', 2000)
        """))
        await conn.execute(text("""
            INSERT IGNORE INTO order_status (order_status, status_code) VALUES
            ('待支付', 0), ('已支付', 1), ('已确认', 2), ('行程中', 3),
            ('已完成', 4), ('已取消', 5), ('已退订', 6)
        """))
        await conn.execute(text("""
            INSERT IGNORE INTO logistics_company (company_name) VALUES ('携程直采'), ('中青旅')
        """))
        await conn.execute(text("""
            INSERT IGNORE INTO postsale_reason (postsale_reason) VALUES ('行程有变'), ('个人原因无法出行')
        """))
        await conn.execute(text("""
            INSERT IGNORE INTO postsale_status (postsale_status, is_refund, is_return, is_exchange, status_code) VALUES
            ('已退款', 1, 0, 0, 3), ('已改期', 0, 1, 0, 5), ('已退订', 0, 0, 1, 7)
        """))

        # 批量生成 N 个 RISK 用户 (5 种模式轮换)
        print(f"[generate] 生成 {count} 个 RISK 高风险用户 (5 模式轮换)...")
        user_ids = [f"RISK{i:03d}" for i in range(1, count + 1)]
        # 先批量插 user_info (用 executemany)
        from sqlalchemy.ext.asyncio import AsyncConnection
        await conn.execute(
            text("INSERT IGNORE INTO user_info (user_id) VALUES " + ",".join(f"('{u}')" for u in user_ids)))

        # 逐个用户按模式生成订单/退改签/投诉
        for idx, user_id in enumerate(user_ids):
            mode_idx = idx % 5  # 0-4 轮换
            rec_id = f"REC{user_id[4:]}"
            mode_name = RISK_MODES[mode_idx]
            print(f"  [{idx+1}/{count}] {user_id} (模式 {mode_idx+1}: {mode_name})")
            await MODE_GENERATORS[mode_idx](conn, user_id, rec_id)

        await conn.commit()

        # 统计
        from sqlalchemy import text as _text
        r = await conn.execute(_text("SELECT COUNT(*) FROM user_info WHERE user_id LIKE 'RISK%'"))
        total_users = r.scalar()
        r = await conn.execute(_text("SELECT COUNT(*) FROM order_info WHERE user_id LIKE 'RISK%'"))
        total_orders = r.scalar()
        r = await conn.execute(_text("""
            SELECT COUNT(*) FROM postsale p
            JOIN order_detail od ON p.order_detail_id = od.order_detail_id
            JOIN order_info oi ON od.order_id = oi.order_id
            WHERE oi.user_id LIKE 'RISK%'
        """))
        total_postsale = r.scalar()
        r = await conn.execute(_text("SELECT COUNT(*) FROM receive_info WHERE user_id LIKE 'RISK%'"))
        total_recv = r.scalar()

        print(f"\n[完成] 高风险用户数据生成完成!")
        print(f"  RISK 用户:             {total_users} 个")
        print(f"  RISK 预订订单:         {total_orders} 个")
        print(f"  RISK 退改签:           {total_postsale} 条")
        print(f"  RISK 出行人/行程信息:  {total_recv} 个")

    await engine.dispose()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="造 RISK 高风险用户 + 预订订单/退改签. 默认 5 个, --count 指定数量.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python scripts/gen_risky_users.py                # 5 个 (RISK001-005, 一套)
  python scripts/gen_risky_users.py --count 30     # 30 个 (RISK001-030, 6 套 × 5 模式)
  python scripts/gen_risky_users.py --count 1      # 1 个 (RISK001, 高退改率模式)
  python scripts/gen_risky_users.py --reset        # 先删旧 RISK 数据再生成
        """,
    )
    parser.add_argument("--count", type=int, default=5, help="生成 RISK 用户数 (默认 5)")
    parser.add_argument("--reset", action="store_true", help="先删旧 RISK 用户 + 关联数据")
    args = parser.parse_args()
    asyncio.run(gen_risky_users(count=args.count, reset=args.reset))
