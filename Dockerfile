FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/app/data/hf-cache
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home agro
COPY app ./app
COPY scripts ./scripts
COPY static ./static
RUN mkdir -p /app/data && chown agro:agro /app/data
USER 10001:10001
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1","--ws-max-size","400000","--proxy-headers","--forwarded-allow-ips","*"]
