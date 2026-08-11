"""
一键启动脚本 (P4-L4 2026-08-08 升级).

启动前自动做 6 步自检:
  1. .env 文件是否存在
  2. Python 核心依赖是否装好 (xgboost / sklearn / sqlalchemy 等)
  3. MySQL 是否在跑 (localhost:3306)
  4. 数据库是否已初始化 (risk_rule 表能否查询)
  5. 8000 端口是否被占
  6. XGBoost 模型文件是否存在 (可选, 没训过也能跑)

致命问题 (FAIL) → 直接 sys.exit(1)
警告 (WARN)     → 打印提示 + 让用户决定是否继续
"""
import os
import socket
import sys

# 让中文日志别报 UnicodeEncodeError
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 【旅游行业迁移 2026-08-11】把 .env 加载进 os.environ,
# 让下方自检的 os.getenv("DB_PASSWORD"/"DB_USER"/"DB_NAME") 能读到真实配置
def _load_dotenv() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_dotenv()


# ============================================================
# 启动前自检
# ============================================================
def _check_env_file() -> tuple[str, str]:
    """检查 .env 文件. 返回 (级别, 消息)."""
    if not os.path.exists(".env"):
        return "WARN", (
            ".env 不存在, 复制 docker/.env.example .env 并填真实值 "
            "(LLM_API_KEY / MYSQL_ROOT_PASSWORD)"
        )
    return "OK", ".env 存在"


def _check_dependencies() -> tuple[str, str]:
    """检查核心 Python 依赖. 任意一个失败 → FAIL."""
    required = {
        "fastapi": "FastAPI Web 框架",
        "uvicorn": "ASGI 服务器",
        "sqlalchemy": "ORM",
        "pymysql": "MySQL 驱动 (同步)",
        "aiomysql": "MySQL 驱动 (异步)",
        "pydantic": "数据校验",
        "pydantic_settings": "配置管理",
        "xgboost": "XGBoost 模型 (P4)",
        "sklearn": "XGBoost 训练 + 评估",
        "numpy": "数值计算",
        "pandas": "数据处理",
    }
    missing = []
    for mod, desc in required.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(f"{mod} ({desc})")
    if missing:
        return "FAIL", (
            f"缺 {len(missing)} 个依赖: " + ", ".join(missing[:3]) +
            ("..." if len(missing) > 3 else "") +
            "\n         跑: pip install -r requirements.txt   "
            "(或 uv pip install -r uv/requirements-uv.txt)"
        )
    return "OK", f"所有 {len(required)} 个核心依赖已装"


def _check_mysql_alive() -> tuple[str, str]:
    """检查 MySQL 是否在 localhost:3306 跑. 用 socket 探测, 不依赖 pymysql."""
    import pymysql
    from app.config import settings as _  # 加载 .env 配置
    password = os.getenv("DB_PASSWORD", "123456")
    user = os.getenv("DB_USER", "root")
    db = os.getenv("DB_NAME", "ecs")
    try:
        conn = pymysql.connect(
            host="localhost", port=3306, user=user, password=password,
            database=db, connect_timeout=3,
        )
        conn.close()
        return "OK", f"MySQL {user}@{db} 可连"
    except Exception as e:
        return "WARN", (
            f"MySQL 连不上 (localhost:3306 {user}@{db}): {type(e).__name__}\n"
            f"         业务功能会失败. 检查: MySQL 启动了? 密码对了? 端口 3306 通?"
        )


def _check_db_initialized() -> tuple[str, str]:
    """检查数据库是否已初始化 (risk_rule 表能查)."""
    try:
        import pymysql
        password = os.getenv("DB_PASSWORD", "123456")
        user = os.getenv("DB_USER", "root")
        db = os.getenv("DB_NAME", "ecs")
        conn = pymysql.connect(
            host="localhost", port=3306, user=user, password=password,
            database=db, connect_timeout=3,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM risk_rule")
                count = cur.fetchone()[0]
            return "OK", f"数据库已初始化, risk_rule 有 {count} 条规则"
        finally:
            conn.close()
    except Exception as e:
        err = str(e)
        if "1146" in err or "doesn't exist" in err.lower():
            return "WARN", (
                "risk_rule 表不存在, 数据库没初始化. 跑: "
                "python scripts/init_db.py --yes"
            )
        return "WARN", f"数据库状态未知: {type(e).__name__}: {err[:80]}"


def _check_port_available(port: int = 8000) -> tuple[str, str]:
    """检查 8000 端口是否被占."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.bind(("0.0.0.0", port))
        return "OK", f"端口 {port} 空闲"
    except OSError:
        return "WARN", (
            f"端口 {port} 被占, uvicorn 启动会失败. 杀掉占用进程 或改 APP_PORT 环境变量"
        )
    finally:
        sock.close()


def _check_xgb_model() -> tuple[str, str]:
    """检查 XGBoost 模型文件 (可选, 没训过 ML 走兜底)."""
    try:
        from app.config import settings
        path = settings.XGB_MODEL_PATH
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
        if os.path.exists(path):
            size_kb = os.path.getsize(path) / 1024
            return "OK", f"XGBoost 模型已加载 ({size_kb:.1f} KB, 路径: {settings.XGB_MODEL_PATH})"
        return "WARN", (
            f"XGBoost 模型不存在 ({settings.XGB_MODEL_PATH}), "
            f"业务仍能跑 (纯规则模式), 想用 ML 跑: python scripts/train_xgb_model.py"
        )
    except Exception as e:
        return "WARN", f"XGBoost 模型检查失败: {e}"


def preflight_checks() -> list[tuple[str, str, str]]:
    """跑全部 6 步自检, 返回 [(级别, 检查项, 消息), ...] 列表.

    严重错误 (FAIL) 会让调用方 sys.exit(1).
    """
    checks = [
        (".env", _check_env_file),
        ("Python 依赖", _check_dependencies),
        ("MySQL 连接", _check_mysql_alive),
        ("数据库初始化", _check_db_initialized),
        ("端口 8000", _check_port_available),
        ("XGBoost 模型", _check_xgb_model),
    ]
    results = []
    for name, fn in checks:
        try:
            level, msg = fn()
        except Exception as e:
            level, msg = "FAIL", f"自检脚本异常: {type(e).__name__}: {e}"
        results.append((level, name, msg))
    return results


def _print_preflight(results: list[tuple[str, str, str]]) -> bool:
    """打印自检结果. 返回 True 表示可以继续 (无 FAIL)."""
    print("=" * 60)
    print("【启动前自检】 (P4-L4 2026-08-08)")
    print("=" * 60)
    for level, name, msg in results:
        if level == "OK":
            mark = "OK"
        elif level == "WARN":
            mark = "WARN"
        else:
            mark = "FAIL"
        # 多行消息用缩进对齐
        first, *rest = msg.split("\n")
        print(f"  [{mark}] {name:<14} {first}")
        for line in rest:
            print(f"           {line.strip()}")
    print("=" * 60)
    # 统计
    fail = sum(1 for l, _, _ in results if l == "FAIL")
    warn = sum(1 for l, _, _ in results if l == "WARN")
    ok = sum(1 for l, _, _ in results if l == "OK")
    print(f"汇总: {ok} OK / {warn} WARN / {fail} FAIL")
    if fail > 0:
        print("有致命问题, 启动取消. 修完上面 FAIL 项再跑.")
        return False
    if warn > 0:
        print("有警告, 业务可能受影响. 按回车继续 (Ctrl+C 取消)...")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print("\n启动取消")
            return False
    else:
        print("一切就绪, 启动 uvicorn...")
    return True


# ============================================================
# 启动入口
# ============================================================
if __name__ == "__main__":
    # 1. 启动前自检
    results = preflight_checks()
    if not _print_preflight(results):
        sys.exit(1)

    # 2. 加载日志配置 + 启动 uvicorn
    from app.logging_config import LOGGING_CONFIG  # noqa: E402
    import uvicorn  # noqa: E402
    from scripts.main import app  # noqa: E402

    port = int(os.getenv("APP_PORT", "8000"))
    uvicorn.run(
        app, host="0.0.0.0", port=port,
        log_level="info", log_config=LOGGING_CONFIG,
    )
