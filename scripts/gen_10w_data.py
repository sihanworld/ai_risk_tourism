"""
电商风控系统 - 10w 条随机业务数据生成 (异步, 一次性脚本)
================
生成规模 (默认 10w 条, 可调):
  - 用户 (user_info):          N_USER       (默认 10000)
  - 收货地址 (receive_info):    N_USER * 2   (平均 2 个/人, 默认 20000)
  - 订单 (order_info):          N_USER * 3   (平均 3 单/人, 默认 30000)
  - 订单明细 (order_detail):     N_ORDER * 1  (平均 1 明细/单, 默认 30000)
  - 售后 (postsale):            N_ORDER * 15% (默认 4500)
  - 物流投诉 (complaints):      N_ORDER * 3%  (默认 900)
  - 总条目:                    ≈ 10w

风险画像 (自动注入):
  - 80% 正常用户 (中等订单数, 低退款率)
  - 15% 中风险 (高退款率 30-50% / 多地址 4-5 个)
  - 5%  高风险 (大额订单 / 深夜下单 / 极高退款率 90%+)

性能: 默认 10w 条 ≈ 3-5 分钟 (aiomysql 批量 executemany)
数据源: faker 中文 + numpy 随机
幂等: 重复跑会因 UNIQUE 约束报错, 用 --drop 先清 (⚠ 危险, 清空业务数据)
"""
import argparse
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta

# 把项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


# ============================================================
# 配置
# ============================================================
CHINESE_PROVINCES = [
    "北京", "上海", "广东", "浙江", "江苏", "四川", "湖北", "福建", "山东", "河南",
    "河北", "湖南", "安徽", "江西", "陕西", "辽宁", "吉林", "黑龙江", "广西", "云南",
]
CHINESE_CITIES = {
    "北京": "北京市", "上海": "上海市", "广东": "广州市", "浙江": "杭州市",
    "江苏": "南京市", "四川": "成都市", "湖北": "武汉市", "福建": "厦门市",
    "山东": "济南市", "河南": "郑州市", "河北": "石家庄市", "湖南": "长沙市",
    "安徽": "合肥市", "江西": "南昌市", "陕西": "西安市", "辽宁": "沈阳市",
    "吉林": "长春市", "黑龙江": "哈尔滨市", "广西": "南宁市", "云南": "昆明市",
}
CHINESE_DISTRICTS = ["朝阳区", "海淀区", "浦东新区", "黄浦区", "天河区", "越秀区",
                     "西湖区", "拱墅区", "鼓楼区", "玄武区", "锦江区", "青羊区"]
# 必须是 product_category 表里真实存在的值 (init_business_data.sql 灌了 7 条)
# 不然 sku_info.sku_category 的 FK 约束会失败, INSERT IGNORE 静默吞掉
CHINESE_SKU_CATEGORIES = ["图书", "家具", "数码", "服装", "母婴", "美妆", "食品"]

# 必须是 order_status 表里真实存在的值 (7 条)
# 不然 order_info.order_status 的 FK 约束会失败
ORDER_STATUSES = ["待支付", "待发货", "已发货", "已签收", "已完成", "已取消", "售后中"]

# 必须是 postsale_status 表里真实存在的值 (9 条)
# 不然 postsale.postsale_status 的 FK 约束会失败
POSTSALE_STATUSES = ["审核中", "审核未通过", "已换货", "已退款", "已退货",
                     "换发货", "换退货", "退款中", "退货中"]

# 简单字符串即可, postsale_reason 是 varchar(500) 不是 FK
CHINESE_POSTSALE_REASONS = ["商品质量问题", "尺寸不合适", "颜色不喜欢", "与描述不符",
                            "收到破损商品", "发错货", "不想要了", "其他原因"]


# ============================================================
# 工具函数
# ============================================================
def _ulid() -> str:
    """生成 26 字符 ULID"""
    import ulid
    return ulid.new().str.lower()


def _chinese_user_id(idx: int, fake: Faker) -> str:
    """用户 ID: U + 6位数字"""
    return f"U{idx:06d}"


def _risk_tier() -> str:
    """返回风险分层: normal / medium / high (概率 80/15/5)"""
    r = random.random()
    if r < 0.05:
        return "high"
    elif r < 0.20:
        return "medium"
    else:
        return "normal"


# ============================================================
# 主函数
# ============================================================
async def gen_10w_data(
    n_user: int = 10_000,
    min_orders: int = 1,
    max_orders: int = 8,
    n_sku: int = 100,
    batch_size: int = 500,
):
    """
    生成 10w 条随机业务数据.
    """
    fake = Faker("zh_CN")
    db_url = settings.get_database_url_async()
    engine = create_async_engine(db_url, echo=False)

    print("=" * 60)
    print(f"开始生成 10w 条业务数据 (用户数: {n_user})")
    print(f"订单范围: 每用户 {min_orders}~{max_orders} 单")
    print("=" * 60)

    # 1. 灌字典表 (省/区域/商品类别/SKU)
    print("\n[1/7] 灌字典表 (省/区域/商品类别/SKU)...")
    async with engine.begin() as conn:
        # region
        for i, prov in enumerate(CHINESE_PROVINCES):
            city = CHINESE_CITIES[prov]
            for j, dist in enumerate(CHINESE_DISTRICTS[:5]):
                await conn.execute(text(
                    "INSERT IGNORE INTO region (province, city, district) VALUES (:p, :c, :d)"
                ), {"p": prov, "c": city, "d": dist})
        # product_category
        for cat in CHINESE_SKU_CATEGORIES:
            await conn.execute(text(
                "INSERT IGNORE INTO product_category (product_category) VALUES (:c)"
            ), {"c": cat})
        # sku_info
        for i in range(1, n_sku + 1):
            cat = random.choice(CHINESE_SKU_CATEGORIES)
            await conn.execute(text("""
                INSERT IGNORE INTO sku_info
                (sku_id, sku_name, sku_price, sku_category, sku_count)
                VALUES (:id, :name, :price, :cat, :cnt)
            """), {
                "id": f"SKU{i:04d}",
                "name": fake.word() + " " + random.choice(["Pro", "Plus", "Max", "Lite", "标准版"]),
                "price": round(random.uniform(10, 5000), 2),
                "cat": cat,
                "cnt": random.randint(1, 1000),
            })
    print(f"  → {n_sku} 个 SKU")

    # 2. 灌用户 (N_USER) + 风险分层
    print(f"\n[2/7] 灌用户 ({n_user} 条)...")
    user_ids = [_chinese_user_id(i, fake) for i in range(1, n_user + 1)]
    user_risk = {uid: _risk_tier() for uid in user_ids}

    async with engine.begin() as conn:
        for i in range(0, n_user, batch_size):
            batch = user_ids[i:i + batch_size]
            values = ", ".join([f"('{uid}')" for uid in batch])
            await conn.execute(text(
                f"INSERT IGNORE INTO user_info (user_id) VALUES {values}"
            ))
    print(f"  → {n_user} 用户 (高风险 {sum(1 for v in user_risk.values() if v == 'high')}, 中风险 {sum(1 for v in user_risk.values() if v == 'medium')})")

    # 3. 灌收货地址 (用户数 * 2, 多地址用户更多)
    print(f"\n[3/7] 灌收货地址 (~{n_user * 2} 条)...")
    receive_rows = []
    receive_id_counter = 0
    for uid in user_ids:
        risk = user_risk[uid]
        # 高风险用户 4-5 个地址, 中风险 2-3 个, 正常 1-2 个
        if risk == "high":
            n_addr = random.randint(4, 5)
        elif risk == "medium":
            n_addr = random.randint(2, 3)
        else:
            n_addr = random.randint(1, 2)

        for _ in range(n_addr):
            receive_id_counter += 1
            prov = random.choice(CHINESE_PROVINCES)
            receive_rows.append({
                "receive_id": f"REC{receive_id_counter:08d}",
                "user_id": uid,
                "receiver_name": fake.name(),
                "receiver_phone": fake.phone_number()[:11],
                "receive_province": prov,
                "receive_city": CHINESE_CITIES[prov],
                "receive_district": random.choice(CHINESE_DISTRICTS),
                "receive_street_address": fake.street_address()[:50],
            })

    async with engine.begin() as conn:
        for i in range(0, len(receive_rows), batch_size):
            batch = receive_rows[i:i + batch_size]
            values = ", ".join([
                f"('{r['receive_id']}', '{r['user_id']}', '{r['receiver_name']}', "
                f"'{r['receiver_phone']}', '{r['receive_province']}', "
                f"'{r['receive_city']}', '{r['receive_district']}', "
                f"'{r['receive_street_address']}')"
                for r in batch
            ])
            await conn.execute(text(
                f"INSERT IGNORE INTO receive_info "
                f"(receive_id, user_id, receiver_name, receiver_phone, "
                f"receive_province, receive_city, receive_district, receive_street_address) "
                f"VALUES {values}"
            ))
    print(f"  → {len(receive_rows)} 收货地址")

    # 4. 灌订单 (用户数 * 3, 高风险大额)
    print(f"\n[4/7] 灌订单 (~{n_user * 3} 条)...")
    user_addresses: dict[str, list[str]] = {}
    for r in receive_rows:
        user_addresses.setdefault(r["user_id"], []).append(r["receive_id"])

    order_rows = []
    detail_rows = []
    order_id_counter = 0
    detail_id_counter = 0
    now = datetime.now()

    for uid in user_ids:
        risk = user_risk[uid]
        n_orders = random.randint(min_orders, max_orders)

        for _ in range(n_orders):
            order_id_counter += 1
            order_id = f"ORD{order_id_counter:08d}"
            # 下单时间: 过去 90 天内随机
            days_ago = random.randint(0, 90)
            hours_ago = random.randint(0, 23)
            order_time = now - timedelta(days=days_ago, hours=hours_ago)
            # 30% 已发货, 50% 已完成, 10% 已签收, 5% 已取消, 5% 待发货
            r = random.random()
            if r < 0.30:
                payment_time = order_time + timedelta(minutes=random.randint(1, 60))
                status = "已发货"
            elif r < 0.80:
                payment_time = order_time + timedelta(minutes=random.randint(1, 60))
                status = "已完成"
            elif r < 0.90:
                payment_time = order_time + timedelta(minutes=random.randint(1, 60))
                status = "已签收"
            elif r < 0.95:
                payment_time = None
                status = "待发货"
            else:
                payment_time = None
                status = "已取消"

            receive_id = random.choice(user_addresses[uid])
            order_rows.append({
                "order_id": order_id,
                "user_id": uid,
                "receive_id": receive_id,
                "create_time": order_time,
                "payment_time": payment_time,
                "status": status,
            })

            # 1-5 个明细; 高风险用户单笔 1000-20000, 正常用户 50-2000
            n_items = random.randint(1, 5)
            if risk == "high":
                base_price = random.uniform(1000, 20000)
            else:
                base_price = random.uniform(50, 2000)

            for _ in range(n_items):
                detail_id_counter += 1
                sku_id = f"SKU{random.randint(1, n_sku):04d}"
                sku_count = random.randint(1, 5)
                total_amount = round(base_price * sku_count, 2)
                discount_amount = round(total_amount * random.uniform(0, 0.3), 2)
                final_amount = round(total_amount - discount_amount, 2)
                detail_rows.append({
                    "order_detail_id": f"OD{detail_id_counter:010d}",
                    "order_id": order_id,
                    "sku_id": sku_id,
                    "sku_count": sku_count,
                    "total_amount": total_amount,
                    "discount_amount": discount_amount,
                    "final_amount": final_amount,
                })

    async with engine.begin() as conn:
        # orders
        for i in range(0, len(order_rows), batch_size):
            batch = order_rows[i:i + batch_size]
            value_strs = []
            for o in batch:
                payment = f"'{o['payment_time']}'" if o['payment_time'] else "NULL"
                value_strs.append(
                    f"('{o['order_id']}', '{o['user_id']}', '{o['status']}', "
                    f"'{o['receive_id']}', '{o['create_time']}', {payment})"
                )
            values = ", ".join(value_strs)
            await conn.execute(text(
                f"INSERT IGNORE INTO order_info "
                f"(order_id, user_id, order_status, receive_id, create_time, payment_time) "
                f"VALUES {values}"
            ))
        # order_details
        for i in range(0, len(detail_rows), batch_size):
            batch = detail_rows[i:i + batch_size]
            values = ", ".join([
                f"('{d['order_detail_id']}', '{d['order_id']}', '{d['sku_id']}', "
                f"{d['sku_count']}, {d['total_amount']}, {d['discount_amount']}, {d['final_amount']})"
                for d in batch
            ])
            await conn.execute(text(
                f"INSERT IGNORE INTO order_detail "
                f"(order_detail_id, order_id, sku_id, sku_count, total_amount, discount_amount, final_amount) "
                f"VALUES {values}"
            ))
    print(f"  → {len(order_rows)} 订单 + {len(detail_rows)} 明细")

    # 5. 灌售后 (订单数 * 15%, 高风险/中风险用户率高)
    print(f"\n[5/7] 灌售后 (~{int(len(order_rows) * 0.15)} 条)...")
    postsale_rows = []
    order_to_user: dict[str, str] = {o["order_id"]: o["user_id"] for o in order_rows}
    order_to_address: dict[str, str] = {o["order_id"]: o["receive_id"] for o in order_rows}
    user_order_details: dict[str, list[dict]] = {}
    for d in detail_rows:
        user_order_details.setdefault(d["order_id"], []).append(d)

    for order_id, details in user_order_details.items():
        uid = order_to_user[order_id]
        risk = user_risk[uid]
        # 风险用户退款率高
        if risk == "high":
            refund_prob = 0.90
        elif risk == "medium":
            refund_prob = 0.40
        else:
            refund_prob = 0.10
        if random.random() < refund_prob:
            for d in details:
                # 60% 退款 / 25% 退货 / 15% 换货
                r = random.random()
                if r < 0.60:
                    ptype = "退款"
                    refund = d["final_amount"]
                elif r < 0.85:
                    ptype = "退货"
                    refund = round(d["final_amount"] * 0.95, 2)
                else:
                    ptype = "换货"
                    refund = 0
                postsale_rows.append({
                    "postsale_id": f"PS{len(postsale_rows) + 1:08d}",
                    "order_detail_id": d["order_detail_id"],
                    "postsale_type": ptype,
                    "refund_amount": refund,
                    "postsale_status": random.choice(POSTSALE_STATUSES),
                    "postsale_reason": random.choice(CHINESE_POSTSALE_REASONS),
                    "receive_id": order_to_address[order_id],
                    "create_time": now - timedelta(days=random.randint(0, 30)),
                })

    if postsale_rows:
        async with engine.begin() as conn:
            for i in range(0, len(postsale_rows), batch_size):
                batch = postsale_rows[i:i + batch_size]
                values = ", ".join([
                    f"('{p['postsale_id']}', '{p['order_detail_id']}', '{p['postsale_type']}', "
                    f"{p['refund_amount']}, '{p['postsale_status']}', "
                    f"'{p['postsale_reason']}', '{p['receive_id']}', '{p['create_time']}')"
                    for p in batch
                ])
                await conn.execute(text(
                    f"INSERT IGNORE INTO postsale "
                    f"(postsale_id, order_detail_id, postsale_type, refund_amount, "
                    f"postsale_status, postsale_reason, receive_id, create_time) "
                    f"VALUES {values}"
                ))
    print(f"  → {len(postsale_rows)} 售后")

    # 6. 灌物流投诉 (订单数 * 3%, 高风险率高)
    # ⚠ logistics_id 是 FK → logistics 表, 必须从真实存在的 ID 选, 不然 FK 失败
    print(f"\n[6/7] 灌物流投诉 (~{int(len(order_rows) * 0.03)} 条)...")
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT logistics_id FROM logistics"))
        valid_logistics_ids = [row[0] for row in result.fetchall()]
    if not valid_logistics_ids:
        print("  ⚠ logistics 表为空, 跳过投诉灌入")
        complaint_rows = []
    else:
        complaint_rows = []
        for order_id in order_to_user.keys():
            uid = order_to_user[order_id]
            risk = user_risk[uid]
            # 高风险用户投诉率高
            if risk == "high":
                complaint_prob = 0.50
            elif risk == "medium":
                complaint_prob = 0.10
            else:
                complaint_prob = 0.02
            if random.random() < complaint_prob:
                complaint_rows.append({
                    "logistics_id": random.choice(valid_logistics_ids),
                    "logistics_complaint": random.choice(["物流延迟", "商品破损", "派送错误", "签收问题"]),
                    "complaint_time": now - timedelta(days=random.randint(0, 30)),
                    "user_id": uid,
                })

    if complaint_rows:
        async with engine.begin() as conn:
            for i in range(0, len(complaint_rows), batch_size):
                batch = complaint_rows[i:i + batch_size]
                values = ", ".join([
                    f"('{c['logistics_id']}', '{c['logistics_complaint']}', "
                    f"'{c['complaint_time']}', '{c['user_id']}')"
                    for c in batch
                ])
                await conn.execute(text(
                    f"INSERT IGNORE INTO logistics_complaints_record "
                    f"(logistics_id, logistics_complaint, complaint_time, user_id) "
                    f"VALUES {values}"
                ))
    print(f"  → {len(complaint_rows)} 物流投诉")

    # 7. 汇总
    total = (
        len(user_ids)
        + len(receive_rows)
        + len(order_rows)
        + len(detail_rows)
        + len(postsale_rows)
        + len(complaint_rows)
    )
    print(f"\n{'=' * 60}")
    print(f"完成! 总计生成 {total} 条业务数据")
    print(f"  - 用户:           {len(user_ids)}")
    print(f"  - 收货地址:       {len(receive_rows)}")
    print(f"  - 订单:           {len(order_rows)}")
    print(f"  - 订单明细:       {len(detail_rows)}")
    print(f"  - 售后:           {len(postsale_rows)}")
    print(f"  - 物流投诉:       {len(complaint_rows)}")
    print(f"\n下一步: 跑 gen_risk_data_with_dates.py 生成评估数据 + train_xgb_model.py 训练 XGBoost")
    print("=" * 60)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="10w 条随机业务数据生成 (一次性, 跑完即结束)"
    )
    parser.add_argument("--users", type=int, default=10_000, help="用户数 (默认 10000, 决定总条数)")
    parser.add_argument("--min-orders", type=int, default=1, help="每用户最少订单数 (默认 1)")
    parser.add_argument("--max-orders", type=int, default=8, help="每用户最多订单数 (默认 8)")
    parser.add_argument("--sku", type=int, default=100, help="SKU 数量 (默认 100)")
    parser.add_argument("--batch", type=int, default=500, help="批量 insert 批次大小 (默认 500)")
    args = parser.parse_args()

    asyncio.run(gen_10w_data(
        n_user=args.users,
        min_orders=args.min_orders,
        max_orders=args.max_orders,
        n_sku=args.sku,
        batch_size=args.batch,
    ))
