# ---------- 构建阶段：安装依赖 ----------
# 依赖均有 linux/amd64 wheel，无需 apt 安装编译工具链
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 默认走国内镜像；网络环境不同可 --build-arg PIP_INDEX_URL=https://pypi.org/simple 覆盖
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app

RUN pip install --index-url "${PIP_INDEX_URL}" --timeout 60 --retries 3 .

# ---------- 运行阶段：只保留运行时依赖，非 root 运行 ----------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY --from=builder /usr/local /usr/local
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
