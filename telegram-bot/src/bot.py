import logging
import sys
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from config import TELEGRAM_TOKEN, ADMIN_ID, LOG_LEVEL
from database import Database

# Настройка логирования (только в консоль)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

class LifeAssistantBot:
    def __init__(self):
        try:
            logger.info("Initializing bot...")
            self.db = Database()
            logger.info("Database initialized successfully")
            
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
        
        # Обработка всех сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Обработка ошибок
        self.application.add_error_handler(self.error_handler)
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Exception while handling an update: {context.error}")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        
        welcome_text = f"""
👋 Привет, {user.first_name}!

Я твой универсальный помощник по жизни! 

📅 Напоминания
💰 Финансы  
📊 Аналитика

Используй /subscribe для покупки подписки (500₽/месяц)
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.db.check_subscription(user_id):
            await update.message.reply_text("✅ У вас уже есть активная подписка!")
            return
        
        await update.message.reply_text("💳 Система оплаты настраивается...")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        message = update.message.text
        
        # Простой ответ на приветствия
        if any(word in message.lower() for word in ['привет', 'hello', 'hi', 'start']):
            await update.message.reply_text(f"Привет, {user.first_name}! Используй /start для начала работы.")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📋 Доступные команды:

/start - Запустить бота
/subscribe - Информация о подписке
/help - Помощь
        """
        
        await update.message.reply_text(help_text)
    
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