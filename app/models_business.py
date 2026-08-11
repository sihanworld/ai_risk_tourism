"""
旅游风控系统 - 业务表 ORM (17 张)
只读映射现有业务系统的核心实体 (用户/预订订单/行程/退改签/出行人等)
不参与风控决策本身, 但被特征工程和规则引擎查询

旅游行业语义映射:
- sku_info: 旅游产品 (酒店/门票/跟团游/机票/火车票/租车)
- order_info: 预订订单 (travel_date 出行日期, travel_persons 出行人数)
- receive_info: 出行人/行程信息 (receiver_name=出行人, receive_city=目的地城市)
- logistics: 行程履约记录 (logistics_category=出行方式)
- logistics_company: 旅游供应商 (航司/酒店集团/票务平台)
- logistics_complaint(s_record): 行程服务投诉问题/记录
- postsale: 退改签记录 (退款/改期/退订)
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ============================================================
# 用户与产品基础
# ============================================================

class UserInfo(Base):
    """用户信息表"""
    __tablename__ = "user_info"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="用户ID")


class Region(Base):
    """地区表 (目的地行政区划) """
    __tablename__ = "region"

    province: Mapped[str] = mapped_column(String(20), primary_key=True, comment="省")
    city: Mapped[str] = mapped_column(String(20), primary_key=True, comment="市")
    district: Mapped[str] = mapped_column(String(20), primary_key=True, comment="区")


class ProductCategory(Base):
    """旅游产品类别表"""
    __tablename__ = "product_category"

    product_category: Mapped[str] = mapped_column(String(20), primary_key=True, comment="产品类别")


class SkuInfo(Base):
    """旅游产品信息表"""
    __tablename__ = "sku_info"

    sku_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="产品ID")
    sku_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="产品名称")
    sku_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="产品单价")
    sku_category: Mapped[str] = mapped_column(String(20), nullable=False, comment="产品类别")
    sku_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="产品库存")


# ============================================================
# 订单域
# ============================================================

class OrderStatus(Base):
    """订单状态表"""
    __tablename__ = "order_status"

    order_status: Mapped[str] = mapped_column(String(20), primary_key=True, comment="订单状态")
    status_code: Mapped[Optional[int]] = mapped_column(Integer, comment="状态码")


class OrderInfo(Base):
    """预订订单表"""
    __tablename__ = "order_info"

    order_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="订单ID")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="创建时间")
    payment_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="支付时间")
    delivered_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="出行确认时间")
    complete_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="完成时间")
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户ID")
    receive_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="出行人/行程信息ID")
    order_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="订单状态")
    travel_date: Mapped[Optional[date]] = mapped_column(Date, comment="出行日期")
    travel_persons: Mapped[Optional[int]] = mapped_column(Integer, default=1, comment="出行人数")


class OrderDetail(Base):
    """订单明细表"""
    __tablename__ = "order_detail"

    order_detail_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="订单明细ID")
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="订单ID")
    sku_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="产品ID")
    sku_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="产品名称")
    sku_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="产品数量")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="总计金额")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, comment="优惠金额")
    final_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="实付金额")


# ============================================================
# 行程履约域
# ============================================================

class Logistics(Base):
    """行程履约表"""
    __tablename__ = "logistics"

    logistics_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="行程ID")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="创建时间")
    delivered_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="行程完成时间")
    logistics_tracking: Mapped[Optional[str]] = mapped_column(String(500), comment="行程详细")
    logistics_category: Mapped[Optional[str]] = mapped_column(
        Enum("自由行", "跟团游", "定制游", name="logistics_category_enum"),
        comment="出行方式",
    )


class OrderLogistics(Base):
    """订单行程关联关系表 """
    __tablename__ = "order_logistics"

    order_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="订单ID")
    logistics_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="行程ID")


class LogisticsCompany(Base):
    """旅游供应商表"""
    __tablename__ = "logistics_company"

    company_name: Mapped[str] = mapped_column(String(20), primary_key=True, comment="供应商名称")


class LogisticsComplaint(Base):
    """行程投诉内容对照表 """
    __tablename__ = "logistics_complaint"

    logistics_status: Mapped[str] = mapped_column(String(20), primary_key=True, comment="行程状态")
    logistics_complaint: Mapped[str] = mapped_column(String(100), primary_key=True, comment="行程投诉内容")


class LogisticsComplaintsRecord(Base):
    """行程投诉记录表"""
    __tablename__ = "logistics_complaints_record"

    record_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="投诉记录ID")
    logistics_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="行程ID")
    logistics_complaint: Mapped[str] = mapped_column(String(500), nullable=False, comment="行程投诉内容")
    complaint_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="投诉时间")
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户ID")


# ============================================================
# 退改签域
# ============================================================

class PostsaleStatus(Base):
    """退改签状态表"""
    __tablename__ = "postsale_status"

    postsale_status: Mapped[str] = mapped_column(String(20), primary_key=True, comment="退改签状态")
    is_refund: Mapped[int] = mapped_column(Integer, nullable=False, comment="是否退款")
    is_return: Mapped[int] = mapped_column(Integer, nullable=False, comment="是否改期")
    is_exchange: Mapped[int] = mapped_column(Integer, nullable=False, comment="是否退订")
    status_code: Mapped[Optional[int]] = mapped_column(Integer, comment="状态码")


class PostsaleReason(Base):
    """退改签原因表"""
    __tablename__ = "postsale_reason"

    postsale_reason: Mapped[str] = mapped_column(String(100), primary_key=True, comment="退改签原因")
    product_category: Mapped[Optional[str]] = mapped_column(String(20), comment="产品类别")


class Postsale(Base):
    """退改签表"""
    __tablename__ = "postsale"

    postsale_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="退改签ID")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="创建时间")
    complete_time: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="完成时间")
    order_detail_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="订单明细ID")
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, comment="退款金额")
    postsale_type: Mapped[Optional[str]] = mapped_column(
        Enum("退款", "改期", "退订", name="postsale_type_enum"),
        comment="退改签类型",
    )
    postsale_reason: Mapped[str] = mapped_column(String(500), nullable=False, comment="退改签原因")
    postsale_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="退改签状态")
    receive_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="出行人/行程信息ID")


class PostsaleLogistics(Base):
    """退改签行程关联关系表 """
    __tablename__ = "postsale_logistics"

    postsale_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="退改签ID")
    logistics_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="行程ID")


# ============================================================
# 出行人/行程信息域
# ============================================================

class ReceiveInfo(Base):
    """出行人/行程信息表"""
    __tablename__ = "receive_info"

    receive_id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="行程信息ID")
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户ID")
    receiver_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="出行人姓名")
    receiver_phone: Mapped[str] = mapped_column(String(50), nullable=False, comment="出行人手机")
    receive_province: Mapped[str] = mapped_column(String(50), nullable=False, comment="目的地省")
    receive_city: Mapped[str] = mapped_column(String(50), nullable=False, comment="目的地市")
    receive_district: Mapped[str] = mapped_column(String(50), nullable=False, comment="目的地区")
    receive_street_address: Mapped[str] = mapped_column(String(50), nullable=False, comment="行程详细地址")
