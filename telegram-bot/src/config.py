import os
import logging
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
YOOKASSA_SHOP_ID = os.getenv('YOOKASSA_SHOP_ID')
YOOKASSA_SECRET_KEY = os.getenv('YOOKASSA_SECRET_KEY')

ADMIN_ID = int(os.getenv('ADMIN_ID', 86458589))
SUBSCRIPTION_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 500.00))

# Яндекс Cloud
YANDEX_API_KEY = os.getenv('YANDEX_API_KEY')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

# Настройки базы данных
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/bot_database.db')

# Логирование
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'logs/bot.log')

# Проверка обязательных переменных
required_vars = ['TELEGRAM_TOKEN', 'YOOKASSA_SHOP_ID', 'YOOKASSA_SECRET_KEY']
for var in required_vars:
    if not globals()[var]:
        raise ValueError(f"Missing required environment variable: {var}")

# Создание директории для логов если не существует
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)