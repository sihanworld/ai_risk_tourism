"""
统一日志配置测试 (P4-L4 2026-08-08).
验证: handlers / formatters / level / 轮转参数 / 实际写文件
"""
import logging
import logging.config
import logging.handlers
import os
import sys
from pathlib import Path

import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.logging_config import (  # noqa: E402
    APP_LOG_FILE,
    BACKUP_COUNT,
    LOG_DIR,
    LOG_FORMAT,
    MAX_BYTES,
    build_logging_config,
)


class TestLoggingConfig:
    """1. 配置结构正确性"""

    def test_default_log_file_path(self):
        """默认日志文件 = 项目根/logs/app.log"""
        # Windows 路径分隔符是 \, 不能用 endswith("logs/app.log")
        assert APP_LOG_FILE.replace("\\", "/").endswith("logs/app.log")
        # 父目录 = LOG_DIR
        assert os.path.dirname(APP_LOG_FILE) == LOG_DIR

    def test_rotation_params(self):
        """轮转: 50 MB × 5 个备份"""
        assert MAX_BYTES == 50 * 1024 * 1024, f"MAX_BYTES 应为 50MB, 实际 {MAX_BYTES}"
        assert BACKUP_COUNT == 5

    def test_log_format_contains_required_fields(self):
        """日志格式含时间/级别/logger 名/消息"""
        assert "%(asctime)s" in LOG_FORMAT
        assert "%(levelname)s" in LOG_FORMAT
        assert "%(name)s" in LOG_FORMAT
        assert "%(message)s" in LOG_FORMAT

    def test_build_logging_config_returns_valid_dict(self):
        """build_logging_config 返回 dict 且符合 logging.dictConfig 规范"""
        cfg = build_logging_config()
        # 必备 keys
        for key in ("version", "formatters", "handlers", "loggers", "root"):
            assert key in cfg, f"配置缺 {key}"
        assert cfg["version"] == 1

    def test_handlers_include_console_and_file(self):
        """handlers 必须含 console (stdout) + file (RotatingFileHandler)"""
        cfg = build_logging_config()
        assert "console" in cfg["handlers"], "缺 console handler"
        assert "file" in cfg["handlers"], "缺 file handler"
        # console = StreamHandler
        assert "StreamHandler" in cfg["handlers"]["console"]["class"]
        # file = RotatingFileHandler
        assert "RotatingFileHandler" in cfg["handlers"]["file"]["class"]
        assert cfg["handlers"]["file"]["maxBytes"] == MAX_BYTES
        assert cfg["handlers"]["file"]["backupCount"] == BACKUP_COUNT
        assert cfg["handlers"]["file"]["encoding"] == "utf-8"

    def test_uvicorn_loggers_configured(self):
        """uvicorn / uvicorn.error / uvicorn.access 3 个 logger 都配了"""
        cfg = build_logging_config()
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            assert name in cfg["loggers"], f"uvicorn logger {name} 未配"
            logger_conf = cfg["loggers"][name]
            # 走 console + file
            assert "console" in logger_conf["handlers"]
            assert "file" in logger_conf["handlers"]
            # propagate=False, 避免被 root 重复打
            assert logger_conf["propagate"] is False
            assert logger_conf["level"] == "INFO"

    def test_root_logger_has_console_and_file(self):
        """root logger 也走 console + file (业务 logger 通过 propagate 到 root)"""
        cfg = build_logging_config()
        assert "console" in cfg["root"]["handlers"]
        assert "file" in cfg["root"]["handlers"]
        assert cfg["root"]["level"] == "INFO"

    def test_disable_existing_loggers_is_false(self):
        """disable_existing_loggers=False, 不动已有 logger, 防 import 顺序问题"""
        cfg = build_logging_config()
        assert cfg["disable_existing_loggers"] is False

    def test_custom_log_file_path(self):
        """build_logging_config 支持传自定义 log_file 路径 (测试用 tmp)"""
        custom = str(Path(__file__).parent / "tmp_test.log")
        cfg = build_logging_config(log_file=custom)
        assert cfg["handlers"]["file"]["filename"] == custom
        # 清掉测试文件
        if os.path.exists(custom):
            os.remove(custom)


class TestLoggingApply:
    """2. 配置实际生效: dictConfig 后 logger 能写文件 + 轮转参数正确"""

    def test_dictconfig_creates_handlers(self, tmp_path, monkeypatch):
        """dictConfig 后, root logger 有 2 个 handlers (console + file)"""
        log_file = str(tmp_path / "test.log")
        cfg = build_logging_config(log_file=log_file)
        logging.config.dictConfig(cfg)  # noqa: F821

        root = logging.getLogger()
        assert len(root.handlers) == 2
        handler_classes = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_classes
        assert "RotatingFileHandler" in handler_classes

        # 恢复 (避免污染其他测试)
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()

    def test_logging_actually_writes_to_file(self, tmp_path):
        """dictConfig 后, logger.info 能写进 logs/app.log"""
        log_file = str(tmp_path / "test_write.log")
        cfg = build_logging_config(log_file=log_file)
        logging.config.dictConfig(cfg)  # noqa: F821

        log = logging.getLogger("test_logger")
        log.info("hello test message")

        # 文件应已创建
        assert os.path.exists(log_file), f"日志文件 {log_file} 未创建"
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "hello test message" in content
        assert "test_logger" in content
        assert "INFO" in content

        # 清理
        for h in logging.getLogger().handlers[:]:
            logging.getLogger().removeHandler(h)
            h.close()

    def test_rotating_handler_has_correct_max_bytes(self, tmp_path):
        """RotatingFileHandler 的 maxBytes / backupCount 正确传递"""
        log_file = str(tmp_path / "rotate.log")
        cfg = build_logging_config(log_file=log_file)
        logging.config.dictConfig(cfg)  # noqa: F821

        root = logging.getLogger()
        rotating = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(rotating) == 1
        h = rotating[0]
        assert h.maxBytes == MAX_BYTES
        assert h.backupCount == BACKUP_COUNT
        assert h.baseFilename == log_file

        # 清理
        for hd in root.handlers[:]:
            root.removeHandler(hd)
            hd.close()

    def test_uvicorn_access_logger_uses_config(self, tmp_path):
        """uvicorn.access logger 也走 console + file (propagate=False)"""
        log_file = str(tmp_path / "uvicorn.log")
        cfg = build_logging_config(log_file=log_file)
        logging.config.dictConfig(cfg)  # noqa: F821

        uv_access = logging.getLogger("uvicorn.access")
        # 验证: handlers 含 file, propagate=False
        handler_classes = [type(h).__name__ for h in uv_access.handlers]
        assert "RotatingFileHandler" in handler_classes
        assert uv_access.propagate is False

        # 写一条访问日志
        uv_access.info('127.0.0.1:12345 - "GET /test HTTP/1.1" 200')
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "GET /test HTTP/1.1" in content
        assert "uvicorn.access" in content

        # 清理
        for h in logging.getLogger().handlers[:]:
            logging.getLogger().removeHandler(h)
            h.close()
        for h in uv_access.handlers[:]:
            uv_access.removeHandler(h)
            h.close()
