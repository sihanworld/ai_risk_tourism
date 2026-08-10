"""
统一日志配置 (P4-L4 2026-08-08).

设计目标:
  1. 业务 logger (logger = logging.getLogger(__name__)) 和 uvicorn access/error 日志
     都同时输出到 stdout + logs/app.log
  2. logs/app.log 用 RotatingFileHandler: 单文件 50 MB, 保留 5 个历史, 防磁盘爆
  3. 容器化部署 (Docker) 时 stdout 自动进容器日志, 文件作为历史归档

3 个层次:
  - root logger:    level=INFO, 同时走 console + file (开发/生产通用)
  - uvicorn:        单独配 handlers, 不 propagate (避免被 root 重复打)
  - app.* loggers:  走 root 配置 (propagate=True), 不用单独配

使用:
  # _run.py / scripts/main.py
  from app.logging_config import LOGGING_CONFIG
  uvicorn.run(app, ..., log_config=LOGGING_CONFIG)
"""
import logging
import logging.config
import logging.handlers
import os


# 日志目录: 项目根/logs/  (跟 _run.py 保持一致)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
APP_LOG_FILE = os.path.join(LOG_DIR, "app.log")

# 轮转参数: 50 MB × 5 个备份 = 最多占 300 MB
MAX_BYTES = 50 * 1024 * 1024
BACKUP_COUNT = 5


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# 默认 formatter: 所有 handler 共用
DEFAULT_FORMATTER = {
    "format": LOG_FORMAT,
    "datefmt": DATE_FORMAT,
}


def build_logging_config(log_file: str = APP_LOG_FILE, level: str = "INFO") -> dict:
    """构造 logging.dictConfig 配置字典.

    Args:
        log_file: 日志文件路径, 默认 logs/app.log
        level: 根 logger 级别, 默认 INFO

    Returns:
        符合 logging.dictConfig 规范的 dict, 直接传给 dictConfig() 或 uvicorn.run(log_config=)
    """
    # 确保 logs 目录存在 (避免启动时 RotatingFileHandler 抛 FileNotFoundError)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    return {
        "version": 1,
        "disable_existing_loggers": False,   # 不动已有 logger, 避免 import 顺序问题
        "formatters": {
            "default": DEFAULT_FORMATTER,
        },
        "handlers": {
            # stdout: 容器/Docker 自动捕获, 开发时也实时看
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
                "level": level,
            },
            # 文件: RotatingFileHandler, 50 MB 自动轮转, 保留 5 个历史
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_file,
                "maxBytes": MAX_BYTES,
                "backupCount": BACKUP_COUNT,
                "encoding": "utf-8",
                "formatter": "default",
                "level": level,
            },
        },
        "loggers": {
            # uvicorn 系列: 走 console + file, 不 propagate (避免 root 重复打)
            "uvicorn": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            # 业务 logger (app.*) 走 root 配置, 不用单独配
            # 例: app.engine.decision → logger = logging.getLogger(__name__)
        },
        "root": {
            "handlers": ["console", "file"],
            "level": level,
        },
    }


# 默认配置 (level=INFO, 文件=logs/app.log)
LOGGING_CONFIG = build_logging_config()


# ============================================================
# Demo: 看一眼日志配置 — 跑法: python app/logging_config.py
# ============================================================
if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("AI_Risk 日志配置 (P4-L4 2026-08-08)")
    print("=" * 60)

    print(f"\n[1] 日志目录: {LOG_DIR}")
    print(f"    日志文件: {APP_LOG_FILE}")
    print(f"    轮转:     {MAX_BYTES // 1024 // 1024} MB × {BACKUP_COUNT} 个备份 = 最多 {MAX_BYTES * BACKUP_COUNT // 1024 // 1024} MB")

    print(f"\n[2] 日志格式: {LOG_FORMAT}")

    print("\n[3] handlers (输出目标):")
    for name, conf in LOGGING_CONFIG["handlers"].items():
        cls = conf["class"].split(".")[-1]
        print(f"    - {name}: {cls} (level={conf.get('level', 'INFO')})")
        if "filename" in conf:
            print(f"      → 文件: {conf['filename']}")

    print("\n[4] uvicorn 系列 logger 配置:")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        conf = LOGGING_CONFIG["loggers"][name]
        print(f"    - {name}: handlers={conf['handlers']}, level={conf['level']}, propagate={conf['propagate']}")

    print("\n[5] root logger:")
    root = LOGGING_CONFIG["root"]
    print(f"    handlers={root['handlers']}, level={root['level']}")

    print("\n[6] 实际触发一下日志 (验证 dictConfig 能用):")
    logging.config.dictConfig(LOGGING_CONFIG)
    log = logging.getLogger("demo")
    log.info("这条消息会进 stdout + logs/app.log")
    log.warning("warning 也会被记录")
    print("    [OK] 日志已配置, 可去 logs/app.log 查看")

    print("\n" + "=" * 60)
    print("使用:")
    print("  1. 启动服务: python _run.py   (uvicorn 用本配置)")
    print("  2. 业务代码: logger = logging.getLogger(__name__)")
    print("  3. 看日志:   tail -f logs/app.log  (Linux/Mac)")
    print("               Get-Content logs/app.log -Wait  (PowerShell)")
