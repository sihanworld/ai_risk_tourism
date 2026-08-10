"""
电商风控系统 - 一键数据库初始化脚本 (异步)
按顺序执行所有 SQL 脚本: 创建数据库 → 业务表 → 业务数据 → 风控表 → 风控规则

总表数: 17 业务 + 9 风控 = 26 张 (2026-08-07 含 P4 2 张: risk_action_log + risk_alert)
老环境升级: 跑 sql/migration_add_p4_tables.sql + sql/migration_add_2026_08_07_fields.sql
   (后者含 6 个字段: 4 原 + 2 合并自 case_source_id migration)
"""

import argparse
import asyncio
import os
import sys

import aiomysql

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_DIR = os.path.join(BASE_DIR, "sql")

# SQL 脚本执行顺序
SQL_FILES = [
    ("init_business_tables.sql", "创建 17 张业务表"),
    ("init_business_data.sql", "导入业务测试数据"),
    ("init_risk_tables.sql", "创建 9 张风控表 (7 原 + 2 P4 系统管理表)"),
    ("init_risk_data.sql", "导入 30 条预置风控规则 (R001-R030)"),
]

# 默认连接配置 (与 .env 一致)
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 3306
DEFAULT_USER = "root"
DEFAULT_PASSWORD = "123321"
DEFAULT_DB = "ecs"


async def get_connection(host, port, user, password, db=None):
    """获取 MySQL 异步连接"""
    return await aiomysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        db=db,
        charset="utf8mb4",
        autocommit=True,
    )


async def create_database(conn, db_name, drop_first=False):
    """创建数据库"""
    async with conn.cursor() as cur:
        if drop_first:
            print(f"  删除数据库 {db_name} ...")
            await cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        await cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
    print(f"  数据库 {db_name} 已就绪")


async def execute_sql_file(conn, filepath, description):
    """执行单个 SQL 脚本文件 (异步)"""
    filename = os.path.basename(filepath)
    print(f"\n[{filename}] {description}")

    with open(filepath, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # 按分号拆分语句，过滤空语句和注释
    statements = split_sql_statements(sql_content)
    total = len(statements)
    success = 0
    errors = 0

    async with conn.cursor() as cur:
        for stmt in statements:
            try:
                await cur.execute(stmt)
                success += 1
            except aiomysql.Error as e:
                code = e.args[0]
                # 1051 = Unknown table 'X' (DROP TABLE IF EXISTS 的正常提示)
                # 1062 = Duplicate entry (数据已存在, 重复跑 init_db.py 时正常)
                if code in (1051, 1062):
                    success += 1  # 视为幂等成功, 不计入错误
                else:
                    errors += 1
                    print(f"  警告 [{code}]: {e.args[1][:120]}")

    status = "完成" if errors == 0 else f"完成 (成功 {success}, 失败 {errors})"
    print(f"  共 {total} 条语句, {status}")
    return errors


def split_sql_statements(sql_text):
    """将 SQL 文本拆分为独立语句，处理字符串中的分号"""
    statements = []
    current = []
    in_single_quote = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    chars = sql_text

    while i < len(chars):
        c = chars[i]

        # 处理行注释
        if not in_single_quote and not in_block_comment and c == '-' and i + 1 < len(chars) and chars[i + 1] == '-':
            in_line_comment = True
            i += 2
            continue
        if in_line_comment:
            if c == '\n':
                in_line_comment = False
            i += 1
            continue

        # 处理块注释
        if not in_single_quote and not in_line_comment and c == '/' and i + 1 < len(chars) and chars[i + 1] == '*':
            in_block_comment = True
            i += 2
            continue
        if in_block_comment:
            if c == '*' and i + 1 < len(chars) and chars[i + 1] == '/':
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        # 处理单引号字符串
        if c == "'" and not in_block_comment and not in_line_comment:
            if in_single_quote:
                # 检查转义的单引号 ''
                if i + 1 < len(chars) and chars[i + 1] == "'":
                    current.append(c)
                    current.append(chars[i + 1])
                    i += 2
                    continue
                in_single_quote = False
            else:
                in_single_quote = True
            current.append(c)
            i += 1
            continue

        # 处理反斜杠转义 (在字符串内)
        if c == '\\' and in_single_quote and i + 1 < len(chars):
            current.append(c)
            current.append(chars[i + 1])
            i += 2
            continue

        # 分号 = 语句结束
        if c == ';' and not in_single_quote:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(c)
        i += 1

    # 处理最后一条不以分号结尾的语句
    last = ''.join(current).strip()
    if last:
        statements.append(last)

    return statements


async def main():
    parser = argparse.ArgumentParser(
        description="电商风控系统 - 一键数据库初始化 (异步). 默认 --reset 重置整个数据库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
用法:
  python scripts/init_db.py                       # 默认: --reset (删库重建, 适合教学/演示)
  python scripts/init_db.py --keep-data          # 保留: 只补表结构 (业务数据不重置)
  python scripts/init_db.py --reset --yes        # 重置 + 自动确认 (CI/脚本用)
  python scripts/init_db.py --db ecs_test        # 初始化测试库
        """,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="MySQL 主机")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MySQL 端口")
    parser.add_argument("--user", default=DEFAULT_USER, help="MySQL 用户名")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="MySQL 密码")
    parser.add_argument("--db", default=DEFAULT_DB, help="数据库名称")
    # 默认 reset (重置); --keep-data 跳过 reset (只补表)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--reset", dest="reset", action="store_true", default=True,
        help="默认行为: 先 DROP DATABASE 再 CREATE (重置整个库, 删所有数据)",
    )
    group.add_argument(
        "--keep-data", dest="reset", action="store_false",
        help="保留数据, 只补表结构 (不删库, CREATE TABLE IF NOT EXISTS)",
    )
    # 兼容老参数 --drop (deprecated, 走同样 reset 路径)
    parser.add_argument(
        "--drop", action="store_true", default=False,
        help="(已废弃, 用 --reset) 先删除再重建数据库",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="跳过重置确认 (CI/脚本场景)",
    )
    args = parser.parse_args()

    # --drop 是老参数, 等价于 --reset
    if args.drop:
        args.reset = True

    print("=" * 60)
    print("电商风控系统 - 数据库初始化 (异步)")
    print(f"目标: {args.user}@{args.host}:{args.port}/{args.db}")
    print(f"模式: {'[RESET] 先删后建' if args.reset else '[KEEP-DATA] 保留数据, 只补表'}")
    print("=" * 60)

    # 危险操作确认 (除非 --yes)
    if args.reset and not args.yes:
        print(f"\n[WARNING] --reset 模式会删除数据库 {args.db} 的所有表和数据!")
        try:
            confirm = input("确认继续? (yes/no): ").strip().lower()
        except EOFError:
            confirm = "no"
        if confirm != "yes":
            print("已取消 (输入 yes 才会执行).")
            sys.exit(0)
        print(f"  确认: yes, 开始重置 {args.db}")

    # 步骤 1: 创建数据库
    print("\n[步骤 1/5] 创建数据库")
    try:
        conn = await get_connection(args.host, args.port, args.user, args.password)
        try:
            await create_database(conn, args.db, drop_first=args.reset)
        finally:
            await conn.ensure_closed()
    except aiomysql.Error as e:
        print(f"  错误: 无法连接 MySQL - {e}")
        sys.exit(1)

    # 步骤 2-5: 按顺序执行 SQL 脚本
    conn = await get_connection(args.host, args.port, args.user, args.password, db=args.db)
    total_errors = 0

    try:
        for idx, (filename, desc) in enumerate(SQL_FILES, start=2):
            filepath = os.path.join(SQL_DIR, filename)
            if not os.path.exists(filepath):
                print(f"\n[步骤 {idx}/5] 跳过: {filename} 不存在")
                continue
            print(f"\n[步骤 {idx}/5]", end="")
            errors = await execute_sql_file(conn, filepath, desc)
            total_errors += errors
    finally:
        await conn.ensure_closed()

    # 汇总
    print("\n" + "=" * 60)
    if total_errors == 0:
        print("初始化完成! 所有脚本执行成功。")
        if args.reset:
            print("数据库已重置: 26 张表重建 + 业务数据 + 30 条规则全部就绪")
    else:
        print(f"初始化完成，但有 {total_errors} 个错误，请检查上方输出。")
    print("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
