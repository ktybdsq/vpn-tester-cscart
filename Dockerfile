FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    traceroute \
    && rm -rf /var/lib/apt/lists/*

# Установка Xray-core
RUN curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    && unzip /tmp/xray.zip -d /app/xray/ \
    && chmod +x /app/xray/xray \
    && rm /tmp/xray.zip

# Установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY scripts/ /app/scripts/
COPY web/ /app/web/

# Создание директорий
RUN mkdir -p /app/configs /app/reports /app/logs

# Порты
EXPOSE 5000

WORKDIR /app/scripts

CMD ["python", "web_api.py"]
