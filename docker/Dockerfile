# =============================================================================
# AI_Risk Dockerfile (P4-L3 + P4-L4 2026-08-08)
# 位置: docker/Dockerfile
# 多阶段构建: builder 装依赖, runtime 只拷 wheel 过来
# 用 gunicorn + uvicorn worker 跑生产 (4 workers)
#
# 构建: docker build -t ai-risk -f docker/Dockerfile .
# =============================================================================

# ---- 阶段 1: builder ----
FROM python:3.11-slim AS builder

WORKDIR /app

# 系统依赖 (mysqlclient 编译需要 gcc; 我们用 pymysql/aiomysql 不需要)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 先 COPY requirements 利用 docker layer 缓存 (依赖没变就不重装)
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ---- 阶段 2: runtime ----
FROM python:3.11-slim

WORKDIR /app

# 创建非 root 用户跑应用
RUN useradd --create-home --shell /bin/bash app
USER app

# 从 builder 拷已装好的依赖 (~/.local 是 pip --user 的安装位置)
COPY --from=builder --chown=app:app /root/app/.local /home/app/.local
ENV PATH=/home/app/.local/bin:$PATH

# 拷应用代码
COPY --chown=app:app . .

# 暴露端口
EXPOSE 8000

# 健康检查 (用 /docs 路径, 比 / 更快)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs').read()" || exit 1

# 启动: gunicorn + uvicorn worker (4 workers)
# 注: --reload 仅开发用, 生产要去掉
CMD ["gunicorn", "scripts.main:app", \
     "-w", "4", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--timeout", "120"]
