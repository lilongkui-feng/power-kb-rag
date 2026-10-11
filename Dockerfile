# syntax=docker/dockerfile:1
# PowerKB 镜像：api 与 web 共用，由 docker-compose 的 command 决定角色（api | web | build）
# 依赖层（torch / requirements）在复制代码之前，改代码不会重装依赖；模型缓存与索引全部走卷
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# 国内构建可加速：PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple/（compose 从 .env 传入）；TORCH_INDEX_URL 可换成可用的 CPU wheel 源
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG PIP_MIRROR=
RUN pip install torch==2.14.1 --index-url "$TORCH_INDEX_URL"
COPY requirements-docker.txt /tmp/requirements-docker.txt
RUN pip install ${PIP_MIRROR:+-i "$PIP_MIRROR"} -r /tmp/requirements-docker.txt

FROM python:3.12-slim
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 curl tini \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 1000 -s /bin/sh app
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models/hf OCR_ENGINE=rapid KB_DATA=/data DOCS_ROOT=/data/power_docs
WORKDIR /app
COPY --chown=app:app . .
RUN mv output output.dist && mkdir -p /data /models/hf && chown -R app:app /app /data /models
USER app
EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${API_PORT:-8000}/health | grep -q '"models_loaded":true' || exit 1
ENTRYPOINT ["tini", "--", "sh", "deploy/docker-entrypoint.sh"]
CMD ["api"]
