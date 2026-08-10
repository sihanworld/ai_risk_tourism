# uv 目录 (P4-L4 2026-08-08)

> 用 [uv](https://github.com/astral-sh/uv) 管理 Python 环境和依赖

## 这是什么？

`uv/` 目录里放的是**用 uv 工具创建的环境配置**。3 个文件配合使用：

| 文件 | 作用 | 何时用 |
|---|---|---|
| `pyproject.toml` | 项目元数据 + 依赖范围（PEP 621） | `uv` 工具识别项目结构 |
| `requirements-uv.txt` | 锁定的精确版本（==x.y.z） | `uv pip install -r` 或传统 pip |
| `uv.lock` | uv 自动生成的依赖树哈希锁 | 跨机器完全复现环境（CI/CD） |

## 跟 `requirements.txt` 的关系

```
项目根/
├── requirements.txt          ← pip 宽松版本, 教学/默认用
├── uv/
│   ├── pyproject.toml        ← uv 项目配置
│   ├── requirements-uv.txt   ← uv 精确锁定版本
│   ├── uv.lock               ← uv 自动生成的完整锁 (git 跟踪)
│   └── README.md             ← 本文件
```

- **`requirements.txt`**：版本范围宽松（`fastapi>=0.115.0`），方便学员/PyPI 直装
- **`uv/requirements-uv.txt`**：版本精确（`fastapi==0.115.6`），保证跨环境一致

## 5 分钟上手

### 0. 安装 uv（一次性）

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 1. 创建虚拟环境 + 装依赖

```bash
# 在项目根目录
uv venv .venv                       # 创建 .venv (比 venv 快 100 倍)
uv pip install -r uv/requirements-uv.txt    # 装依赖
```

### 2. 或用 `uv sync` 一键复现（推荐）

```bash
uv sync                              # 自动读 uv.lock, 装一模一样的环境
```

### 3. 跑项目

```bash
# Windows PowerShell
.\.venv\Scripts\activate
python _run.py

# macOS / Linux
source .venv/bin/activate
python _run.py
```

## 常用命令

```bash
# 装新包
uv add <package>            # 加到 pyproject.toml + 更新 uv.lock

# 升级某个包
uv add --upgrade <package>  # 升级到最新版 + 重新锁定

# 重新生成 uv.lock (pyproject.toml 改了之后)
uv lock

# 在 .venv 跑命令 (不用 activate)
uv run python _run.py
uv run pytest tests/

# 删除虚拟环境
uv venv --remove .venv
```

## 验证环境

```bash
# 查看已装版本
uv pip list | grep -E "fastapi|xgboost|sqlalchemy"

# 跑测试
uv run pytest tests/ -v

# 跑 ml_model demo
uv run python app/engine/ml_model.py
```

## 教学场景：3 种安装方式对比

| 场景 | 用什么 | 理由 |
|---|---|---|
| 学员第一次跑项目 | `pip install -r requirements.txt` | 简单直接，PyPI 直装 |
| 生产部署 / CI | `uv sync` 或 `uv pip install -r uv/requirements-uv.txt` | 版本精确，跨环境一致 |
| 加新包 | `uv add <package>` | 自动更新 pyproject + lock |

## 常见问题

**Q: `uv` 和 `pip` 区别？**

A: uv 是用 Rust 写的 pip 替代品，**装包快 10-100 倍**（解析依赖树也快），还内置虚拟环境管理。语法跟 pip 90% 兼容。

**Q: 我用 pip 装行不行？**

A: 行！`requirements-uv.txt` 就是个普通 requirements 文件，`pip install -r` 一样能装。只是没有 lock 文件的哈希校验。

**Q: `uv.lock` 怎么生成？**

A: `uv lock` 自动生成（已有 `pyproject.toml` 时）。锁文件应该**提交到 git**，保证所有协作者用同版本。

**Q: 我不想用 uv，能直接用 `requirements.txt` 吗？**

A: 当然。`requirements.txt` 一直在根目录，所有命令都兼容。

## 跟 `docker/` 目录的关系

`uv/` 管 Python 环境，`docker/` 管系统环境（OS + nginx + 容器）。两者可以组合用：

```bash
# 1. 本地用 uv
uv venv && uv pip install -r uv/requirements-uv.txt

# 2. 生产用 docker
cd docker && docker compose up -d
```

Dockerfile 内部也可以用 uv（速度快 100 倍），详见 `docker/README.md`。
