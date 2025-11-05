FROM python:3.9-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements и установка Python зависимостей
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создание директорий для данных и логов
RUN mkdir -p /app/data /app/logs /app/src

# Копирование исходного кода
COPY src/ /app/src/

# Копирование скриптов
COPY scripts/ /app/scripts/

# Создание непривилегированного пользователя
RUN groupadd -r botuser && useradd -r -g botuser botuser
RUN chown -R botuser:botuser /app
USER botuser

# Переменные окружения
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Точка входа
CMD ["python", "/app/src/bot.py"]