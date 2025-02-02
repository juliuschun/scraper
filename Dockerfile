FROM python:3.9-slim

# Chrome 및 필요한 dependencies 설치
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 필요한 Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 포트 노출
EXPOSE 8099

# 실행 명령
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8099"] 