FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 (asyncpg 빌드, matplotlib 폰트 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# matplotlib 캐시 디렉토리 미리 생성
RUN mkdir -p /root/.config/matplotlib

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg

EXPOSE 8000
