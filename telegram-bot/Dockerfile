FROM python:3.9-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements и установка Python зависимостей
COPY src/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Создание директорий для данных
RUN mkdir -p /app/data

# Копирование исходного кода
COPY src/ /app/src/

# Переменные окружения
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Точка входа
CMD ["python", "/app/src/bot.py"]