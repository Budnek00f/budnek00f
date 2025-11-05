FROM python:3.9-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Создание директории для данных
RUN mkdir -p /app/data

# Копирование исходного кода
COPY src/ /app/src/

# Установка Python зависимостей
RUN pip install --no-cache-dir python-telegram-bot==20.3 python-dotenv

# Переменные окружения
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Точка входа
CMD ["python", "/app/src/life_assistant_bot_full_project.py"]