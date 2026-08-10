"""数据库连接层 (全异步)"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# 所有 ORM 模型的公共基类
class Base(DeclarativeBase):
    pass


# 异步引擎 (主代码 + scripts 全部使用)
async_engine = create_async_engine(
    settings.get_database_url_async(),
    pool_pre_ping=False,
    pool_recycle=3600,  # 1 小时回收, 避开 MySQL wait_timeout
    pool_size=10,
    max_overflow=20,
    echo=False,
)

# 异步 Session 工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_async() -> AsyncGenerator[AsyncSession, None]:
    """用法: db: AsyncSession = Depends(get_db_async).

    显式 try/finally + 显式 rollback + 显式 close:
    不依赖 async with 的隐式 aexit (会触发 aiomysql 跨 event loop 时的 Event loop is closed).

    行为约定:
      - 业务代码负责 commit (自己控事务边界)
      - 异常时我们兜底 rollback, 不让 pending transaction 泄漏
      - 退出时 await db.close() 显式释放 connection 回 pool
    """
    db = AsyncSessionLocal()
    try:
        yield db
    except Exception:
        try:
            await db.rollback()
        except Exception:
            # rollback 本身失败 (connection 已死等) 静默, 别把 cleanup 异常冒到外层
            pass
        raise
    finally:
        try:
            await db.close()
        except Exception:
            pass


def get_test_engine_async(db_name: str | None = None):
    """创建异步测试数据库引擎 (供异步测试使用)"""
    name = db_name or settings.TEST_DB_NAME
    return create_async_engine(
        settings.get_database_url_async(name),
        pool_pre_ping=False,
        pool_recycle=3600,
        echo=False,
    )


# ============================================================
# Demo: 展示异步引擎 / 同步引擎 / 依赖注入 — 真实连 DB
# 跑法: python app/database.py
# ============================================================
if __name__ == "__main__":
    import asyncio
    from sqlalchemy import text

    print("=" * 60)
    print("数据库连接 — 异步引擎 / 同步引擎 / 依赖注入 演示")
    print("=" * 60)

    print(f"\n[1] 引擎信息:")
    print(f"  async_engine URL    = {async_engine.url}")
    print(f"  pool size           = {async_engine.pool.size()} (默认 5)")
    print(f"  driver              = {async_engine.url.drivername}")

    print(f"\n[2] 异步 ping (用 async_engine):")
    async def _async_ping():
        async with async_engine.begin() as conn:
            r = await conn.execute(text("SELECT 1+1 AS two"))
            return r.scalar()
    try:
        v = asyncio.run(_async_ping())
        print(f"  SELECT 1+1         = {v}  (异步 OK)")
    except Exception as e:
        print(f"  [WARN] 异步连不上: {e}")

    print(f"\n[4] 依赖注入 get_db_async (FastAPI 用):")
    import inspect
    sig = inspect.signature(get_db_async)
    print(f"  函数签名           = {sig}")
    print(f"  返回类型           = AsyncGenerator (FastAPI Depends 用 __anext__ 拿 session)")
    print(f"  使用方式           = Depends(get_db_async) → 路由函数参数 db: AsyncSession = Depends(...)")

    print("\n" + "=" * 60)
    print("注意: 26 张表的 Base 来自 app.models, 启动时 Base.metadata 自动注册")
    print("建表: python scripts/init_db.py --yes")
