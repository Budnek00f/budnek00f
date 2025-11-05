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
            logger.info("Initializing bot...")
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
        
        # Обработчики кнопок
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Обработка всех сообщений для мониторинга
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

Я твой универсальный помощник по жизни! Вот что я умею:

📅 **Напоминания** - создавай задачи и напоминания
💰 **Финансы** - веди учет доходов и расходов
📊 **Аналитика** - анализирую твои сообщения и финансы

Для доступа ко всем функциям нужна подписка - 500₽/месяц
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
            [InlineKeyboardButton("📅 Напоминания", callback_data="reminders")],
            [InlineKeyboardButton("💰 Финансы", callback_data="finance")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.db.check_subscription(user_id):
            await update.message.reply_text("✅ У вас уже есть активная подписка!")
            return
        
        payment = self.payment_system.create_payment(user_id)
        
        if payment:
            payment_url = payment['confirmation']['confirmation_url']
            keyboard = [[InlineKeyboardButton("💳 Оплатить", url=payment_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "Для оплаты подписки нажмите кнопку ниже:",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("❌ Ошибка при создании платежа")
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if data == "subscribe":
            await self.subscribe_callback(query)
        elif data == "reminders":
            await query.edit_message_text("📅 Функция напоминаний будет доступна после настройки подписки")
        elif data == "finance":
            await query.edit_message_text("💰 Функция финансов будет доступна после настройки подписки")
    
    async def subscribe_callback(self, query):
        user_id = query.from_user.id
        
        if self.db.check_subscription(user_id):
            await query.edit_message_text("✅ У вас уже есть активная подписка!")
        else:
            payment = self.payment_system.create_payment(user_id)
            
            if payment:
                payment_url = payment['confirmation']['confirmation_url']
                keyboard = [[InlineKeyboardButton("💳 Оплатить", url=payment_url)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "Для оплаты подписки нажмите кнопку ниже:",
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text("❌ Ошибка при создании платежа")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        message = update.message.text
        
        # Логируем сообщение для анализа
        self.chat_monitor.log_message(user.id, update.effective_chat.id, message)
        
        # Простой ответ на приветствия
        if any(word in message.lower() for word in ['привет', 'hello', 'hi', 'start']):
            await update.message.reply_text(f"Привет, {user.first_name}! Используй /start для начала работы.")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📋 Доступные команды:

/start - Запустить бота
/subscribe - Купить подписку
/help - Помощь

После покупки подписки станут доступны:
/reminders - Управление напоминаниями
/finance - Финансовый учет
/analytics - Аналитика
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