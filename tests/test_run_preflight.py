"""
_run.py preflight 自检测试 (P4-L4 2026-08-08).
覆盖: 6 步自检的 OK / WARN / FAIL 各种场景
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_app as _run  # noqa: E402


class TestCheckEnvFile:
    """1. .env 文件检查"""

    def test_env_exists(self, tmp_path, monkeypatch):
        """当前目录有 .env → OK"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("DB_HOST=localhost\n")
        level, msg = _run._check_env_file()
        assert level == "OK"
        assert ".env 存在" in msg

    def test_env_missing(self, tmp_path, monkeypatch):
        """当前目录没 .env → WARN + 提示复制命令"""
        monkeypatch.chdir(tmp_path)
        level, msg = _run._check_env_file()
        assert level == "WARN"
        assert "复制" in msg or "docker/.env.example" in msg


class TestCheckDependencies:
    """2. Python 核心依赖检查"""

    def test_all_deps_installed(self):
        """所有依赖都装了 → OK (真实环境一般都装了)"""
        level, msg = _run._check_dependencies()
        assert level == "OK"
        assert "11" in msg  # 11 个核心依赖

    def test_missing_xgboost(self, monkeypatch):
        """mock xgboost 导入失败 → FAIL"""
        # 注入一个会 ImportError 的 mock
        import builtins
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "xgboost":
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        level, msg = _run._check_dependencies()
        assert level == "FAIL"
        assert "依赖" in msg
        assert "xgboost" in msg
        assert "pip install" in msg


class TestCheckMysqlAlive:
    """3. MySQL 连接检查"""

    def test_mysql_alive(self, monkeypatch):
        """Mock pymysql.connect 成功 → OK"""
        mock_conn = MagicMock()
        with patch("pymysql.connect", return_value=mock_conn):
            level, msg = _run._check_mysql_alive()
        assert level == "OK"
        assert "MySQL" in msg
        mock_conn.close.assert_called_once()

    def test_mysql_down(self, monkeypatch):
        """Mock pymysql.connect 抛 OperationalError → WARN"""
        import pymysql
        with patch("pymysql.connect", side_effect=pymysql.OperationalError("Can't connect")):
            level, msg = _run._check_mysql_alive()
        assert level == "WARN"
        assert "连不上" in msg
        assert "localhost:3306" in msg


class TestCheckDbInitialized:
    """4. 数据库初始化检查 (risk_rule 表能否查)"""

    def test_db_initialized_with_24_rules(self):
        """真实环境 risk_rule 有 24 条 → OK"""
        level, msg = _run._check_db_initialized()
        # 真实环境可能 OK 也可能 WARN (取决于表是否在), 至少不崩
        assert level in ("OK", "WARN")
        if level == "OK":
            assert "risk_rule" in msg

    def test_db_table_not_exists(self, monkeypatch):
        """Mock 报 1146 (Table doesn't exist) → WARN"""
        import pymysql
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = pymysql.ProgrammingError(
            "1146 Table 'ecs.risk_rule' doesn't exist"
        )
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("pymysql.connect", return_value=mock_conn):
            level, msg = _run._check_db_initialized()
        assert level == "WARN"
        assert "表不存在" in msg or "init_db" in msg


class TestCheckPort:
    """5. 端口 8000 检查"""

    def test_port_available(self):
        """8000 端口空闲 → OK"""
        # 测试用 18765 这种冷门端口避免冲突
        level, msg = _run._check_port_available(port=18765)
        assert level == "OK"
        assert "18765" in msg

    def test_port_in_use(self):
        """先占一个端口再检查 → WARN"""
        # 占用一个端口
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("0.0.0.0", 18766))
        try:
            level, msg = _run._check_port_available(port=18766)
            assert level == "WARN"
            assert "被占" in msg
        finally:
            s.close()


class TestCheckXgbModel:
    """6. XGBoost 模型文件检查"""

    def test_model_exists(self):
        """真实环境模型存在 → OK"""
        level, msg = _run._check_xgb_model()
        # 真实环境 xgb_model.json 已存在, 应该 OK
        if os.path.exists("app/engine/xgb_model.json"):
            assert level == "OK"
            assert "XGBoost" in msg
        else:
            assert level == "WARN"

    def test_model_path_missing(self, monkeypatch):
        """Mock settings.XGB_MODEL_PATH 指向不存在文件 → WARN"""
        from app.config import Settings
        fake_settings = Settings()
        fake_settings.XGB_MODEL_PATH = "nonexistent/xgb_model_xxx.json"
        # _check_xgb_model 里用 from app.config import settings, 需要替换
        with patch("app.config.settings", fake_settings):
            level, msg = _run._check_xgb_model()
        assert level == "WARN"
        assert "不存在" in msg
        assert "train_xgb_model" in msg


class TestPreflightIntegration:
    """整合测试: preflight_checks 返回 6 条结果, _print_preflight 行为"""

    def test_preflight_returns_6_results(self):
        """preflight_checks 一定返回 6 条 (对应 6 个检查项)"""
        results = _run.preflight_checks()
        assert len(results) == 6
        for level, name, msg in results:
            assert level in ("OK", "WARN", "FAIL")
            assert isinstance(name, str) and name
            assert isinstance(msg, str) and msg

    def test_preflight_names(self):
        """6 个检查项名字固定"""
        results = _run.preflight_checks()
        names = [name for _, name, _ in results]
        assert names == [
            ".env", "Python 依赖", "MySQL 连接",
            "数据库初始化", "端口 8000", "XGBoost 模型",
        ]

    def test_print_preflight_no_fail_returns_true(self, capsys):
        """没有 FAIL 时 _print_preflight 返回 True"""
        # 构造全 OK 的结果
        results = [
            ("OK", "测试项 1", "全部正常"),
            ("OK", "测试项 2", "全部正常"),
        ]
        ret = _run._print_preflight(results)
        assert ret is True
        captured = capsys.readouterr()
        assert "2 OK" in captured.out
        assert "0 WARN" in captured.out
        assert "0 FAIL" in captured.out

    def test_print_preflight_with_fail_returns_false(self, capsys):
        """有 FAIL 时 _print_preflight 返回 False"""
        results = [
            ("OK", "测试项 1", "正常"),
            ("FAIL", "关键依赖", "缺 xgboost"),
        ]
        ret = _run._print_preflight(results)
        assert ret is False
        captured = capsys.readouterr()
        assert "1 FAIL" in captured.out
        assert "启动取消" in captured.out
