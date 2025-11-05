#!/bin/bash

echo "Initializing Telegram Life Assistant Bot..."

# Создание директорий
mkdir -p data logs

# Копирование .env.example если .env не существует
if [ ! -f .env ]; then
    echo "Copying .env.example to .env..."
    cp .env.example .env
    echo "Please edit .env file with your actual configuration"
fi

# Установка прав на скрипт
chmod +x scripts/init.sh

echo "Initialization complete!"
echo "Please edit .env file with your actual configuration before running docker-compose up"