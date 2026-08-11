"""
旅游风控系统 - 业务数据生成脚本 (异步, 一次性脚本)
生成:
  - 出行人/行程信息 (receive_info): N_USER * 2   (平均 2 个/人, 默认 20000)
  - 预订订单 (order_info):          N_USER * 3   (默认 30000)
  - 订单明细 (order_detail):        N_ORDER * 2  (默认 60000)
  - 退改签 (postsale):              N_ORDER * 15% (默认 4500)
  - 行程投诉 (complaints):          N_ORDER * 3%  (默认 900)

用户分 3 档风险层:
  - 5%  高风险 (大额预订 / 深夜预订 / 极高退改率 90%+ / 囤票大户)
  - 15% 中风险
  - 80% 正常用户

用法:
    python scripts/gen_10w_data.py --users 10000 --min-orders 1 --max-orders 8
    python scripts/gen_10w_data.py --users 300 --max-orders 6 --seed 42   # 教学演示规模
"""
import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402

# ============================================================
# 旅游业务静态数据 (目的地与 sql/init_business_data.sql 的 region 保持一致)
# ============================================================
DESTINATIONS = [
    ("北京市", "北京市", ["东城区", "朝阳区", "海淀区"]),
    ("上海市", "上海市", ["黄浦区", "浦东新区", "徐汇区"]),
    ("广东省", "广州市", ["天河区", "越秀区"]),
    ("广东省", "深圳市", ["南山区", "福田区"]),
    ("浙江省", "杭州市", ["西湖区", "拱墅区"]),
    ("江苏省", "南京市", ["玄武区", "秦淮区"]),
    ("江苏省", "苏州市", ["姑苏区", "吴中区"]),
    ("四川省", "成都市", ["锦江区", "武侯区"]),
    ("湖北省", "武汉市", ["武昌区", "江汉区"]),
    ("湖南省", "长沙市", ["岳麓区", "天心区"]),
    ("陕西省", "西安市", ["雁塔区", "碑林区"]),
    ("重庆市", "重庆市", ["渝中区", "南岸区"]),
    ("云南省", "昆明市", ["盘龙区", "五华区"]),
    ("云南省", "大理市", ["古城区"]),
    ("云南省", "丽江市", ["古城区"]),
    ("海南省", "三亚市", ["吉阳区", "天涯区"]),
    ("福建省", "厦门市", ["思明区", "湖里区"]),
    ("山东省", "青岛市", ["市南区", "崂山区"]),
    ("辽宁省", "大连市", ["中山区", "沙河口区"]),
    ("黑龙江省", "哈尔滨市", ["道里区", "南岗区"]),
    ("广西壮族自治区", "桂林市", ["秀峰区", "七星区"]),
    ("贵州省", "贵阳市", ["南明区", "云岩区"]),
    ("新疆维吾尔自治区", "乌鲁木齐市", ["天山区"]),
    ("西藏自治区", "拉萨市", ["城关区"]),
]

# 热门旅游城市 (用于机票/火车票 SKU 命名与行程目的地偏好)
HOT_CITIES = ["三亚", "杭州", "成都", "西安", "厦门", "桂林", "哈尔滨", "大理", "丽江", "青岛", "昆明", "北京", "上海", "广州"]

# 旅游产品类别 (与 product_category 表一致)
TRAVEL_CATEGORIES = ["酒店", "门票", "跟团游", "机票", "火车票", "租车"]

# 旅游预订状态机
ORDER_STATUSES = ["待支付", "已支付", "已确认", "行程中", "已完成", "已取消", "已退订"]

# 退改签状态
POSTSALE_STATUSES = ["待审核", "审核中", "退款中", "已退款", "改期中", "已改期",
                     "退订中", "已退订", "审核未通过"]

# 退改签原因 (旅游场景)
TRAVEL_POSTSALE_REASONS = ["行程有变", "个人原因无法出行", "重复预订", "价格波动找到更低价",
                           "天气原因无法出行", "航班取消或延误", "酒店与描述不符",
                           "行程安排不合理", "门票无法入园使用", "身体原因无法出行"]

# 行程投诉内容 (与 logistics_complaint 表一致)
TRAVEL_COMPLAINTS = ["酒店与描述不符", "导游强制购物", "行程安排不合理", "交通接驳延误",
                     "餐饮卫生问题", "门票无法入园", "服务态度差", "与宣传承诺不符",
                     "退款迟迟未到账", "住宿条件差"]

HOTEL_NAMES = ["亚龙湾度假酒店", "西湖湖畔精品酒店", "中央大街酒店", "故宫景观酒店", "外滩酒店",
               "洱海海景客栈", "古城民宿", "雪山观景酒店", "滨海湾大酒店", "温泉度假村"]
ROOM_TYPES = ["豪华海景房", "标准间", "园景房", "行政套房", "亲子房", "大床房"]
SCENIC_SPOTS = ["迪士尼乐园", "故宫博物院", "张家界森林公园", "环球影城", "西湖景区", "黄山风景区",
                "九寨沟", "鼓浪屿", "兵马俑", "长隆欢乐世界", "玉龙雪山", "漓江景区"]
TOUR_LINES = ["昆明大理丽江6日5晚跟团游", "桂林阳朔4日3晚跟团游", "新疆喀纳斯伊犁8日跟团游",
              "三亚5日4晚海岛度假跟团游", "北京经典5日跟团游", "西藏拉萨林芝7日跟团游",
              "东北雪乡哈尔滨6日跟团游", "厦门鼓浪屿4日跟团游"]


def _gen_travel_skus(n_sku: int, seed: int = 0) -> list[dict]:
    """生成 n_sku 个旅游产品 (sku_info), 按类别轮转."""
    rng = random.Random(seed + 999)
    skus = []
    for i in range(1, n_sku + 1):
        cat = TRAVEL_CATEGORIES[(i - 1) % len(TRAVEL_CATEGORIES)]
        city = rng.choice(HOT_CITIES)
        if cat == "酒店":
            name = f"{city}{rng.choice(HOTEL_NAMES)}{rng.choice(ROOM_TYPES)}"
            price = round(rng.uniform(200, 2500), 2)
        elif cat == "门票":
            name = f"{rng.choice(SCENIC_SPOTS)}门票"
            price = round(rng.uniform(40, 600), 2)
        elif cat == "跟团游":
            name = rng.choice(TOUR_LINES)
            price = round(rng.uniform(1200, 6000), 2)
        elif cat == "机票":
            name = f"{rng.choice(HOT_CITIES)}至{city}机票(含税)"
            price = round(rng.uniform(400, 2600), 2)
        elif cat == "火车票":
            name = f"{rng.choice(HOT_CITIES)}至{city}高铁二等座"
            price = round(rng.uniform(60, 900), 2)
        else:  # 租车
            name = f"{city}租车{rng.choice(['经济型', 'SUV', '商务车'])}{rng.randint(1, 7)}日套餐"
            price = round(rng.uniform(120, 800), 2)
        skus.append({
            "sku_id": f"TSKU{i:04d}",
            "sku_name": name[:100],
            "sku_price": price,
            "sku_category": cat,
            "sku_count": rng.randint(50, 5000),
        })
    return skus


def _chinese_user_id(i: int, fake: Faker) -> str:
    """中文用户 ID: U_{姓名}_{序号}, 保证唯一"""
    name = fake.name().replace(" ", "")
    return f"U_{name}_{i:05d}"


def _risk_tier() -> str:
    """按 5%/15%/80% 分配风险层"""
    r = random.random()
    if r < 0.05:
        return "high"
    if r < 0.20:
        return "medium"
    return "normal"


# ============================================================
# 主函数
# ============================================================
async def gen_10w_data(
    n_user: int = 10_000,
    min_orders: int = 1,
    max_orders: int = 8,
    n_sku: int = 120,
    batch_size: int = 500,
    seed: int | None = None,
):
    """生成旅游行业随机业务数据 (预订订单/出行人/退改签/行程投诉)."""
    if seed is not None:
        random.seed(seed)
    fake = Faker("zh_CN")
    db_url = settings.get_database_url_async()
    engine = create_async_engine(db_url, echo=False)

    print("=" * 60)
    print(f"开始生成旅游业务数据 (用户数: {n_user})")
    print(f"订单范围: 每用户 {min_orders}~{max_orders} 单")
    print("=" * 60)

    # 1. 灌字典表 (目的地区域/产品类别/旅游产品)
    print("\n[1/7] 灌字典表 (目的地区域/产品类别/旅游产品)...")
    async with engine.begin() as conn:
        # region (与 init_business_data.sql 保持一致, 幂等)
        for prov, city, districts in DESTINATIONS:
            for dist in districts:
                await conn.execute(text(
                    "INSERT IGNORE INTO region (province, city, district) VALUES (:p, :c, :d)"
                ), {"p": prov, "c": city, "d": dist})
        # product_category
        for cat in TRAVEL_CATEGORIES:
            await conn.execute(text(
                "INSERT IGNORE INTO product_category (product_category) VALUES (:c)"
            ), {"c": cat})
        # sku_info (旅游产品)
        skus = _gen_travel_skus(n_sku, seed or 0)
        for s in skus:
            await conn.execute(text("""
                INSERT IGNORE INTO sku_info
                (sku_id, sku_name, sku_price, sku_category, sku_count)
                VALUES (:id, :name, :price, :cat, :cnt)
            """), {"id": s["sku_id"], "name": s["sku_name"], "price": s["sku_price"],
                   "cat": s["sku_category"], "cnt": s["sku_count"]})
    print(f"  → {n_sku} 个旅游产品")

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

    # 3. 灌出行人/行程信息 (用户数 * 2, 代订黑产用户出行人更多)
    print(f"\n[3/7] 灌出行人/行程信息 (~{n_user * 2} 条)...")
    receive_rows = []
    receive_id_counter = 0
    for uid in user_ids:
        risk = user_risk[uid]
        # 高风险用户 4-6 个出行人(代订黑产), 中风险 2-3 个, 正常 1-2 个
        if risk == "high":
            n_traveler = random.randint(4, 6)
        elif risk == "medium":
            n_traveler = random.randint(2, 3)
        else:
            n_traveler = random.randint(1, 2)

        for _ in range(n_traveler):
            receive_id_counter += 1
            prov, city, districts = random.choice(DESTINATIONS)
            receive_rows.append({
                "receive_id": f"REC{receive_id_counter:08d}",
                "user_id": uid,
                "receiver_name": fake.name(),
                "receiver_phone": fake.phone_number()[:11],
                "receive_province": prov,
                "receive_city": city,
                "receive_district": random.choice(districts),
                "receive_street_address": (fake.street_address() + random.choice(
                    ["度假酒店", "景区民宿", "商务酒店", "度假村", "客栈"]))[:50],
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
    print(f"  → {len(receive_rows)} 出行人/行程信息")

    # 4. 灌预订订单 (用户数 * (min~max), 高风险大额/深夜/临期)
    print(f"\n[4/7] 灌预订订单 (~{n_user * (min_orders + max_orders) // 2} 条)...")
    user_travelers: dict[str, list[dict]] = {}
    for r in receive_rows:
        user_travelers.setdefault(r["user_id"], []).append(r)

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
            # 预订时间: 过去 90 天内随机
            days_ago = random.randint(0, 90)
            if risk == "high" and random.random() < 0.3:
                # 高风险用户 30% 概率深夜预订 (0~6 点, 触发 R005/R010)
                hour = random.randint(0, 5)
            else:
                hour = random.randint(6, 23)
            order_time = (now - timedelta(days=days_ago)).replace(
                hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59), microsecond=0)

            # 预订提前天数: 正常 5~60 天; 高风险临期代订 0~1 天 (触发 R006)
            if risk == "high" and random.random() < 0.4:
                lead_days = random.randint(0, 1)
            else:
                lead_days = random.randint(5, 60)
            travel_date = order_time.date() + timedelta(days=lead_days)
            travel_persons = random.choice([1, 1, 2, 2, 2, 3, 4])
            if risk == "high" and random.random() < 0.2:
                travel_persons = random.randint(6, 10)  # 多出行人代订 (触发 R007)

            # 订单状态: 50% 已完成, 20% 行程中/已确认, 15% 已支付, 5% 待支付, 5% 已取消, 5% 已退订
            r = random.random()
            if r < 0.50:
                payment_time = order_time + timedelta(seconds=random.randint(30, 3600))
                status = "已完成"
                delivered_time = payment_time + timedelta(days=1)
                complete_time = payment_time + timedelta(days=random.randint(2, lead_days + 5))
            elif r < 0.65:
                payment_time = order_time + timedelta(seconds=random.randint(30, 3600))
                status = random.choice(["行程中", "已确认"])
                delivered_time = payment_time + timedelta(days=1)
                complete_time = None
            elif r < 0.80:
                payment_time = order_time + timedelta(seconds=random.randint(30, 3600))
                status = "已支付"
                delivered_time = None
                complete_time = None
            elif r < 0.85:
                payment_time = None
                status = "待支付"
                delivered_time = None
                complete_time = None
            elif r < 0.90:
                payment_time = None
                status = "已取消"
                delivered_time = None
                complete_time = None
            else:
                payment_time = order_time + timedelta(seconds=random.randint(30, 3600))
                status = "已退订"
                delivered_time = None
                complete_time = payment_time + timedelta(days=random.randint(1, 5))

            # 高风险用户 10% 未支付占库存 (触发 R009)
            if risk == "high" and random.random() < 0.10:
                payment_time = None
                status = "待支付"

            traveler = random.choice(user_travelers[uid])
            order_rows.append({
                "order_id": order_id,
                "user_id": uid,
                "receive_id": traveler["receive_id"],
                "create_time": order_time,
                "payment_time": payment_time,
                "delivered_time": delivered_time,
                "complete_time": complete_time,
                "status": status,
                "travel_date": travel_date,
                "travel_persons": travel_persons,
            })

            # 1-4 个明细; 高风险用户单笔 3000-25000, 正常用户 100-3000
            n_items = random.randint(1, 4)
            if risk == "high":
                base_price = random.uniform(3000, 25000)
            else:
                base_price = random.uniform(100, 3000)

            for _ in range(n_items):
                detail_id_counter += 1
                sku = random.choice(skus)
                # 高风险用户 15% 概率囤票 (sku_count 10~30, 触发 R024/R025)
                if risk == "high" and random.random() < 0.15:
                    sku_count = random.randint(10, 30)
                else:
                    sku_count = random.randint(1, travel_persons)
                total_amount = round(base_price * sku_count, 2)
                discount_amount = round(total_amount * random.uniform(0, 0.3), 2)
                if risk == "high" and random.random() < 0.15:
                    # 深折扣薅优惠 (触发 R026/R027)
                    discount_amount = round(total_amount * random.uniform(0.5, 0.7), 2)
                final_amount = round(total_amount - discount_amount, 2)
                detail_rows.append({
                    "order_detail_id": f"OD{detail_id_counter:010d}",
                    "order_id": order_id,
                    "sku_id": sku["sku_id"],
                    "sku_name": sku["sku_name"],
                    "sku_count": sku_count,
                    "total_amount": total_amount,
                    "discount_amount": discount_amount,
                    "final_amount": final_amount,
                })

    async with engine.begin() as conn:
        # orders (含旅游字段 travel_date/travel_persons)
        for i in range(0, len(order_rows), batch_size):
            batch = order_rows[i:i + batch_size]
            value_strs = []
            for o in batch:
                payment = f"'{o['payment_time']}'" if o['payment_time'] else "NULL"
                delivered = f"'{o['delivered_time']}'" if o['delivered_time'] else "NULL"
                complete = f"'{o['complete_time']}'" if o['complete_time'] else "NULL"
                value_strs.append(
                    f"('{o['order_id']}', '{o['create_time']}', {payment}, {delivered}, {complete}, "
                    f"'{o['user_id']}', '{o['receive_id']}', '{o['status']}', "
                    f"'{o['travel_date']}', {o['travel_persons']})"
                )
            values = ", ".join(value_strs)
            await conn.execute(text(
                f"INSERT IGNORE INTO order_info "
                f"(order_id, create_time, payment_time, delivered_time, complete_time, "
                f"user_id, receive_id, order_status, travel_date, travel_persons) "
                f"VALUES {values}"
            ))
        # order_details
        for i in range(0, len(detail_rows), batch_size):
            batch = detail_rows[i:i + batch_size]
            values = ", ".join([
                f"('{d['order_detail_id']}', '{d['order_id']}', '{d['sku_id']}', "
                f"'{d['sku_name']}', {d['sku_count']}, {d['total_amount']}, "
                f"{d['discount_amount']}, {d['final_amount']})"
                for d in batch
            ])
            await conn.execute(text(
                f"INSERT IGNORE INTO order_detail "
                f"(order_detail_id, order_id, sku_id, sku_name, sku_count, total_amount, discount_amount, final_amount) "
                f"VALUES {values}"
            ))
    print(f"  → {len(order_rows)} 订单, {len(detail_rows)} 明细")

    # 5. 灌退改签 (订单数 * 15%, 高风险用户退改率 90%+)
    print(f"\n[5/7] 灌退改签 (~{int(len(order_rows) * 0.15)} 条)...")
    # 按 user_id 分组订单
    orders_by_user: dict[str, list[dict]] = {}
    for o in order_rows:
        orders_by_user.setdefault(o["user_id"], []).append(o)
    # 按 order_id 索引明细 (退改签关联 order_detail_id)
    details_by_order: dict[str, list[dict]] = {}
    for d in detail_rows:
        details_by_order.setdefault(d["order_id"], []).append(d)

    postsale_rows = []
    postsale_counter = 0
    for uid in user_ids:
        risk = user_risk[uid]
        if risk == "high":
            refund_ratio = random.uniform(0.90, 1.0)  # 高风险: 极高退改率
        elif risk == "medium":
            refund_ratio = random.uniform(0.30, 0.60)
        else:
            refund_ratio = random.uniform(0.05, 0.15)

        user_orders = orders_by_user.get(uid, [])
        n_refunds = int(len(user_orders) * refund_ratio)
        if n_refunds == 0:
            continue

        for o in random.sample(user_orders, min(n_refunds, len(user_orders))):
            if o["status"] == "待支付":
                continue  # 未支付订单无退改签
            details = details_by_order.get(o["order_id"], [])
            if not details:
                continue
            postsale_counter += 1
            detail = random.choice(details)
            # 退改签时间: 订单创建后 1~30 天
            ps_time = o["create_time"] + timedelta(days=random.randint(1, 30),
                                                   hours=random.randint(0, 12))
            ptype = random.choices(["退款", "改期", "退订"], weights=[5, 3, 2])[0]
            refund_amount = round(float(detail["final_amount"]) * random.uniform(0.5, 1.0), 2) \
                if ptype in ("退款", "退订") else 0.0
            status = random.choice(POSTSALE_STATUSES)
            complete_time = ps_time + timedelta(days=random.randint(1, 7)) \
                if status in ("已退款", "已改期", "已退订", "审核未通过") else None
            postsale_rows.append({
                "postsale_id": f"PS{postsale_counter:08d}",
                "create_time": ps_time,
                "complete_time": complete_time,
                "order_detail_id": detail["order_detail_id"],
                "refund_amount": refund_amount,
                "postsale_type": ptype,
                "postsale_reason": random.choice(TRAVEL_POSTSALE_REASONS),
                "postsale_status": status,
                "receive_id": o["receive_id"],
                "order_id": o["order_id"],
            })

    async with engine.begin() as conn:
        for i in range(0, len(postsale_rows), batch_size):
            batch = postsale_rows[i:i + batch_size]
            value_strs = []
            for p in batch:
                complete = f"'{p['complete_time']}'" if p['complete_time'] else "NULL"
                value_strs.append(
                    f"('{p['postsale_id']}', '{p['create_time']}', {complete}, "
                    f"'{p['order_detail_id']}', {p['refund_amount']}, '{p['postsale_type']}', "
                    f"'{p['postsale_reason']}', '{p['postsale_status']}', '{p['receive_id']}')"
                )
            values = ", ".join(value_strs)
            await conn.execute(text(
                f"INSERT IGNORE INTO postsale "
                f"(postsale_id, create_time, complete_time, order_detail_id, refund_amount, "
                f"postsale_type, postsale_reason, postsale_status, receive_id) "
                f"VALUES {values}"
            ))
    print(f"  → {len(postsale_rows)} 退改签")

    # 6. 灌行程履约 (已支付订单的 ~80%) + 关联表
    print(f"\n[6/7] 灌行程履约记录...")
    logistics_rows = []
    logistics_counter = 0
    order_logistics_pairs = []
    logistics_by_order: dict[str, str] = {}
    paid_orders = [o for o in order_rows if o["payment_time"]]
    for o in random.sample(paid_orders, int(len(paid_orders) * 0.8)):
        logistics_counter += 1
        lid = f"LG{logistics_counter:08d}"
        create_time = o["payment_time"]
        delivered_time = o["complete_time"] if o["status"] == "已完成" else None
        tracking = f"{o['travel_date']} 出行; 出行方式: {random.choice(['自由行', '跟团游', '定制游'])}"
        category = random.choice(["自由行", "跟团游", "定制游"])
        logistics_rows.append({
            "logistics_id": lid,
            "create_time": create_time,
            "delivered_time": delivered_time,
            "logistics_tracking": tracking,
            "logistics_category": category,
        })
        order_logistics_pairs.append((o["order_id"], lid))
        logistics_by_order[o["order_id"]] = lid

    async with engine.begin() as conn:
        for i in range(0, len(logistics_rows), batch_size):
            batch = logistics_rows[i:i + batch_size]
            value_strs = []
            for lg in batch:
                delivered = f"'{lg['delivered_time']}'" if lg['delivered_time'] else "NULL"
                value_strs.append(
                    f"('{lg['logistics_id']}', '{lg['create_time']}', {delivered}, "
                    f"'{lg['logistics_tracking']}', '{lg['logistics_category']}')"
                )
            values = ", ".join(value_strs)
            await conn.execute(text(
                f"INSERT IGNORE INTO logistics "
                f"(logistics_id, create_time, delivered_time, logistics_tracking, logistics_category) "
                f"VALUES {values}"
            ))
        # order_logistics 关联
        for i in range(0, len(order_logistics_pairs), batch_size):
            batch = order_logistics_pairs[i:i + batch_size]
            values = ", ".join([f"('{oid}', '{lid}')" for oid, lid in batch])
            await conn.execute(text(
                f"INSERT IGNORE INTO order_logistics (order_id, logistics_id) VALUES {values}"
            ))
        # postsale_logistics (改期/退订关联行程)
        ps_pairs = [(p["postsale_id"], logistics_by_order[p["order_id"]])
                    for p in postsale_rows
                    if p["order_id"] in logistics_by_order]
        for i in range(0, len(ps_pairs), batch_size):
            batch = ps_pairs[i:i + batch_size]
            values = ", ".join([f"('{pid}', '{lid}')" for pid, lid in batch])
            await conn.execute(text(
                f"INSERT IGNORE INTO postsale_logistics (postsale_id, logistics_id) VALUES {values}"
            ))
    print(f"  → {len(logistics_rows)} 行程记录")

    # 7. 灌行程投诉 (订单数 * 3%, 高风险投诉多)
    print(f"\n[7/7] 灌行程投诉 (~{int(len(order_rows) * 0.03)} 条)...")
    complaint_rows = []
    complaint_counter = 0
    complained_orders = random.sample(paid_orders, min(int(len(paid_orders) * 0.03), len(paid_orders)))
    # 高风险用户额外投诉 (投诉骗退黑产)
    high_paid = [o for o in paid_orders if user_risk[o["user_id"]] == "high"]
    if high_paid:
        complained_orders += random.sample(high_paid, min(int(len(high_paid) * 0.3), len(high_paid)))
    for o in complained_orders:
        if o["order_id"] not in logistics_by_order:
            continue
        complaint_counter += 1
        complaint_rows.append({
            "logistics_id": logistics_by_order[o["order_id"]],
            "logistics_complaint": random.choice(TRAVEL_COMPLAINTS),
            "complaint_time": o["create_time"] + timedelta(days=random.randint(2, 20)),
            "user_id": o["user_id"],
        })

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
    print(f"  → {len(complaint_rows)} 行程投诉")

    await engine.dispose()
    print("\n" + "=" * 60)
    print("生成完成!")
    print(f"  用户: {n_user}")
    print(f"  出行人/行程信息: {len(receive_rows)}")
    print(f"  预订订单: {len(order_rows)} (明细 {len(detail_rows)})")
    print(f"  退改签: {len(postsale_rows)}")
    print(f"  行程履约: {len(logistics_rows)}")
    print(f"  行程投诉: {len(complaint_rows)}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="旅游业务数据生成")
    parser.add_argument("--users", type=int, default=10_000)
    parser.add_argument("--min-orders", type=int, default=1)
    parser.add_argument("--max-orders", type=int, default=8)
    parser.add_argument("--skus", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=None, help="随机种子 (演示复现用)")
    args = parser.parse_args()

    asyncio.run(gen_10w_data(
        n_user=args.users, min_orders=args.min_orders, max_orders=args.max_orders,
        n_sku=args.skus, batch_size=args.batch_size, seed=args.seed,
    ))
