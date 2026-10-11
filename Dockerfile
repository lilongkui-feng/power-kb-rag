# PowerKB（api 与 web 共用一个镜像，由 docker-compose 指定启动命令）。未在本机实际构建验证。
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 HF_HOME=/models PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt
COPY . .
EXPOSE 8000 8501
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
