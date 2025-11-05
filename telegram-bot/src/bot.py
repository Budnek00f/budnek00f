import logging
import sys
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from datetime import datetime

from config import TELEGRAM_TOKEN, ADMIN_ID, LOG_LEVEL, LOG_FILE
from database import Database
from payment import PaymentSystem
from reminder import ReminderManager
from finance import FinanceManager
from chat_monitor import ChatMonitor

# Настройка логирования
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class LifeAssistantBot:
    def __init__(self):
        try:
            self.db = Database()
            self.payment_system = PaymentSystem()
            self.reminder_manager = ReminderManager(self.db)
            self.finance_manager = FinanceManager(self.db)
            self.chat_monitor = ChatMonitor(self.db)
            
            self.application = Application.builder().token(TELEGRAM_TOKEN).build()
            self.setup_handlers()
            
            logger.info("Bot initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            raise
    
    def setup_handlers(self):
        # Команды
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("subscribe", self.subscribe))
        self.application.add_handler(CommandHandler("reminders", self.reminders))
        self.application.add_handler(CommandHandler("finance", self.finance))
        self.application.add_handler(CommandHandler("analytics", self.analytics))
        self.application.add_handler(CommandHandler("admin", self.admin))
        
        # Обработчики кнопок
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Обработка всех сообщений для мониторинга
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Обработка ошибок
        self.application.add_error_handler(self.error_handler)
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Exception while handling an update: {context.error}")
    
    # ... остальные методы остаются такими же как в предыдущей версии ...
    # (start, subscribe, reminders, finance, analytics, admin, handle_message, button_handler, etc.)

    def run(self):
        logger.info("Starting bot...")
        try:
            self.application.run_polling()
        except Exception as e:
            logger.error(f"Bot stopped with error: {e}")
            raise

if __name__ == "__main__":
    bot = LifeAssistantBot()
    bot.run()