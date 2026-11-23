# 生产镜像：构建上下文为仓库根目录（需要 migrations/ 与 alembic.ini 一起进镜像）
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# 构建时必须注入 tag commit；缺失或非 40 位 SHA 直接失败，避免 unknown label 被当成成功。
ARG RELEASE_COMMIT
RUN test -n "$RELEASE_COMMIT" \
    && test "${#RELEASE_COMMIT}" -eq 40 \
    && printf '%s' "$RELEASE_COMMIT" | grep -Eq '^[0-9a-f]{40}$'
LABEL org.opencontainers.image.revision="${RELEASE_COMMIT}"

COPY backend/requirements.txt ./requirements.txt
# 允许覆盖 PyPI 源：国内构建时传 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

# 以非 root 运行（Celery 启动时会因 root 身份告警）；证据文件目录需可写
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/var/evidence \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
