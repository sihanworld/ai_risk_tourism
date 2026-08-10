# docker 目录 (P4-L4 2026-08-08)

> Docker + nginx 部署相关文件，**所有路径都相对 `docker/` 目录**

## 这是什么？

`docker/` 目录里放**生产部署用的所有文件**：

| 文件 | 作用 | 何时用 |
|---|---|---|
| `Dockerfile` | 多阶段构建镜像（builder + runtime） | `docker build` |
| `docker-compose.yml` | 一键启动 MySQL + app + nginx | `docker compose up` |
| `nginx.conf` | 反向代理 FastAPI + 静态文件 | 容器 nginx 加载 |
| `.env.example` | 环境变量模板（DB/密钥/端口） | `cp .env.example .env` 填值 |
| `.dockerignore` | 排除不需要打入镜像的文件 | `docker build` 自动用 |
| `README.md` | 本文件 | 部署前必看 |

## 跟 `uv/` 目录的关系

- `uv/` 管 Python 依赖（pip 装什么）
- `docker/` 管系统环境（容器/OS/nginx）

两个**独立**，但可组合：Dockerfile 内部用 `pip install -r requirements.txt` 装依赖（也可用 `uv pip install` 加速，见下方进阶）。

## 5 分钟上手（生产部署）

### 1. 准备环境变量

```bash
cd docker
cp .env.example .env
# 编辑 .env, 改 MYSQL_ROOT_PASSWORD + LLM_API_KEY
```

### 2. 一键启动

```bash
cd docker
docker compose up -d
# 3 个容器启动: MySQL + app (FastAPI) + nginx
```

### 3. 验证

```bash
# 容器状态
docker compose ps

# 等待 30 秒 (MySQL init + app 启动)
curl http://localhost:8000/docs        # FastAPI Swagger 文档

# 健康检查
curl http://localhost:80/healthz      # nginx 反代通

# 看应用日志
docker compose logs -f app

# 初始化数据库
docker compose exec app python scripts/init_db.py --yes
```

### 4. 造数据 + 训练 XGBoost

```bash
# 业务数据
docker compose exec app python scripts/gen_10w_data.py
docker compose exec app python scripts/gen_risk_data_with_dates.py --days 7 --per-day 20

# 训练 (P4-L3 第二轮: 早停 + AUC/F1)
docker compose exec app python scripts/train_xgb_model.py
# 训练日志会显示 [特征重要性 TOP 10]
```

## 目录结构视角

```
项目根/
├── app/                          ← 应用代码 (打进镜像)
├── scripts/                      ← 启动/训练/迁移脚本
├── sql/                          ← DDL + migration
├── requirements.txt              ← pip 装 (Dockerfile COPY)
├── templates/ static/            ← 静态资源
├── logs/                         ← 应用日志 (挂载 volume)
├── uv/                           ← uv 工具管理 (不进镜像, .dockerignore 排除)
│   ├── pyproject.toml
│   ├── requirements-uv.txt
│   ├── uv.lock
│   └── README.md
└── docker/                       ← 本目录
    ├── Dockerfile                ← 镜像构建
    ├── docker-compose.yml        ← 一键启动
    ├── nginx.conf                ← 反代配置
    ├── .env.example              ← 环境变量模板
    ├── .dockerignore             ← 镜像排除
    └── README.md                 ← 本文件
```

## docker-compose.yml 路径说明

```yaml
services:
  mysql:
    volumes:
      - ../sql/init_all.sql:/docker-entrypoint-initdb.d/01_init_all.sql:ro
      # ↑ 相对 docker/ 目录, 回到项目根拿 sql/
  app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
      # ↑ context 是项目根, Dockerfile 在 docker/ 子目录
  nginx:
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      # ↑ 相对 docker/ 目录
```

**为什么用相对路径？** 用户从 `cd docker && docker compose up` 启动，所有相对路径都从 `docker/` 算起，部署时不用改任何路径。

## 4 个核心容器

### 1. MySQL 8.0（`mysql`）
- 端口 `3306`（主机映射）
- 首次启动自动执行 `sql/init_all.sql` + `sql/migration_add_2026_08_07_fields.sql`
- 数据持久化到 `ai_risk_mysql_data` volume
- 健康检查 `mysqladmin ping`

### 2. FastAPI app（`app`）
- 端口 `8000`（主机映射）
- 4 个 gunicorn worker + uvicorn
- `depends_on: mysql: condition: service_healthy`（等 MySQL 起来再启动）
- 日志挂载到 `ai_risk_app_logs` volume
- 健康检查 `GET /docs`

### 3. Nginx（`nginx`）
- 端口 `80`（HTTP，生产用）
- 端口 `443`（HTTPS，需要 SSL 证书时启用）
- 反代 `app:8000` + 静态文件 `/static/` + 健康检查 `/healthz`
- SSE 流式响应支持（`proxy_buffering off`）

### 4. 后续扩展
- 加 Redis 缓存（黑名单、案件工作台）
- 加 Prometheus + Grafana 监控
- 加 Loki 日志聚合

## 进阶：Dockerfile 改用 uv（装包快 100 倍）

默认 Dockerfile 用 `pip install`，改成 uv 加速：

```dockerfile
# 阶段 1: builder
FROM python:3.11-slim AS builder

# 装 uv
RUN pip install --no-cache-dir uv

# 装依赖 (用 uv/requirements-uv.txt 锁定的精确版本)
COPY uv/requirements-uv.txt /app/requirements-uv.txt
RUN uv pip install --system -r /app/requirements-uv.txt
```

**实测**：项目 25 个包，pip 装 60s，uv 装 8s。

## HTTPS 部署（生产可选）

1. 准备 SSL 证书：
```bash
mkdir -p docker/ssl
# 把 fullchain.pem 和 privkey.pem 放到 docker/ssl/
```

2. 编辑 `docker/nginx.conf`，取消 HTTPS server 注释

3. 编辑 `docker-compose.yml`，启用 SSL volume：
```yaml
volumes:
  - ./ssl:/etc/nginx/ssl:ro
```

4. 重启 nginx：
```bash
docker compose restart nginx
```

## 常见问题

**Q: 改代码后怎么重新部署？**

```bash
# 改完代码, 重新构建镜像
docker compose build app
docker compose up -d app
```

**Q: 数据库重置？**

```bash
# 危险操作: 删 volume 重置
docker compose down -v
docker compose up -d
# 自动重新执行 init SQL
```

**Q: 只跑 app 不跑 nginx？**

```bash
# 只启动 mysql + app
docker compose up -d mysql app

# 访问: http://localhost:8000
```

**Q: 容器日志在哪？**

```bash
# 实时
docker compose logs -f app

# 应用文件 (挂载到 volume)
docker volume inspect ai_risk_app_logs
# 或
ls $(docker volume inspect ai_risk_app_logs -f '{{ .Mountpoint }}')
```

**Q: 我不想用 Docker，能直接 `python _run.py` 吗？**

A: 当然。Docker 是生产部署方案，开发还是直接 `python _run.py` 跑本地 MySQL 更方便。
