import logging
import sys
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from datetime import datetime

from config import TELEGRAM_TOKEN, ADMIN_ID, LOG_LEVEL
from database import Database
from payment import PaymentSystem
from reminder import ReminderManager
from finance import FinanceManager
from chat_monitor import ChatMonitor

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
        
        # Обработчики кнопок - ВАЖНО: должен быть после команд
        self.application.add_handler(CallbackQueryHandler(self.handle_button))
        
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
            [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe_btn")],
            [InlineKeyboardButton("📅 Напоминания", callback_data="reminders_btn")],
            [InlineKeyboardButton("💰 Финансы", callback_data="finance_btn")],
            [InlineKeyboardButton("📊 Аналитика", callback_data="analytics_btn")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.process_subscription(update, context)
    
    async def reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.process_reminders(update, context)
    
    async def finance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.process_finance(update, context)
    
    async def analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.process_analytics(update, context)
    
    async def admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ У вас нет прав администратора")
            return
        
        # Админские функции
        with self.db.get_cursor() as cursor:
            cursor.execute('SELECT COUNT(*) as count FROM users')
            total_users = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) as count FROM users WHERE subscription_end > DATE("now")')
            active_subscriptions = cursor.fetchone()['count']
        
        text = f"""
👑 **Панель администратора**

👥 Всего пользователей: {total_users}
💳 Активных подписок: {active_subscriptions}

**Для настройки ЮKassa добавьте в .env:**
YOOKASSA_SHOP_ID=ваш_shop_id
YOOKASSA_SECRET_KEY=ваш_secret_key
        """
        
        await update.message.reply_text(text, parse_mode='Markdown')
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        message = update.message.text
        
        # Логируем сообщение для анализа
        self.chat_monitor.log_message(user.id, update.effective_chat.id, message)
        
        # Простой ответ на приветствия
        if any(word in message.lower() for word in ['привет', 'hello', 'hi']):
            await update.message.reply_text(f"👋 Привет, {user.first_name}! Используй /start для начала работы.")
    
    # ОБРАБОТКА КНОПОК - ГЛАВНЫЙ МЕТОД
    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        logger.info(f"Button pressed: {data} by user {user_id}")
        
        # Обработка разных кнопок
        if data == "subscribe_btn":
            await self.process_subscription_button(query)
        elif data == "reminders_btn":
            await self.process_reminders_button(query)
        elif data == "finance_btn":
            await self.process_finance_button(query)
        elif data == "analytics_btn":
            await self.process_analytics_button(query)
        elif data == "back_to_main":
            await self.show_main_menu(query)
        else:
            await query.edit_message_text(f"❌ Неизвестная команда: {data}")
    
    # МЕТОДЫ ДЛЯ КОМАНД
    async def process_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.db.check_subscription(user_id) or user_id == ADMIN_ID:
            await update.message.reply_text("✅ У вас уже есть активная подписка!")
            return
        
        # Даем тестовый доступ для всех
        self.db.update_subscription(user_id, months=1)
        keyboard = [
            [InlineKeyboardButton("📅 Напоминания", callback_data="reminders_btn")],
            [InlineKeyboardButton("💰 Финансы", callback_data="finance_btn")],
            [InlineKeyboardButton("📊 Аналитика", callback_data="analytics_btn")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🎉 **Тестовый доступ активирован!**\n\n"
            "Вам предоставлен бесплатный доступ на 1 месяц для тестирования всех функций!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def process_reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            await update.message.reply_text("❌ Для доступа к напоминаниям нужна подписка! Используйте /subscribe")
            return
        
        if context.args:
            # Добавление напоминания
            try:
                if len(context.args) < 2:
                    await update.message.reply_text("Использование: /reminders [текст] [ГГГГ-ММ-ДД ЧЧ:ММ]")
                    return
                
                text = ' '.join(context.args[:-2])
                date_str = context.args[-2] + ' ' + context.args[-1]
                success, message = self.reminder_manager.add_reminder(user_id, text, date_str)
                await update.message.reply_text(message)
            except Exception as e:
                await update.message.reply_text(f"Ошибка: {e}")
        else:
            # Показать список напоминаний
            reminders = self.reminder_manager.get_reminders(user_id)
            
            if not reminders:
                await update.message.reply_text("📝 У вас нет активных напоминаний")
                return
            
            text = "📅 Ваши напоминания:\n\n"
            for reminder in reminders:
                status = "✅" if reminder['completed'] else "⏳"
                text += f"{status} {reminder['text']} - {reminder['due_date']}\n"
            
            await update.message.reply_text(text)
    
    async def process_finance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            await update.message.reply_text("❌ Для доступа к финансовому учету нужна подписка! Используйте /subscribe")
            return
        
        if context.args and len(context.args) >= 3:
            # Добавление транзакции
            try:
                amount = float(context.args[0])
                transaction_type = context.args[1].lower()
                category = context.args[2]
                description = ' '.join(context.args[3:]) if len(context.args) > 3 else ""
                
                if transaction_type not in ['income', 'expense']:
                    await update.message.reply_text("Тип должен быть 'income' или 'expense'")
                    return
                
                self.finance_manager.add_transaction(user_id, amount, category, description, transaction_type)
                await update.message.reply_text("✅ Транзакция добавлена!")
            except ValueError:
                await update.message.reply_text("Использование: /finance [сумма] [income/expense] [категория] [описание]")
        else:
            # Финансовый отчет
            report = self.finance_manager.get_financial_report(user_id)
            
            text = f"""
💰 Финансовый отчет:

💵 Доходы: {report['income']:.2f}₽
💸 Расходы: {report['expense']:.2f}₽
📊 Баланс: {report['balance']:.2f}₽
            """
            
            await update.message.reply_text(text)
    
    async def process_analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            await update.message.reply_text("❌ Для доступа к аналитике нужна подписка! Используйте /subscribe")
            return
        
        chat_analysis = self.chat_monitor.analyze_chat_mood(user_id)
        finance_report = self.finance_manager.get_financial_report(user_id)
        
        text = f"""
📊 Аналитика вашей активности:

💬 Сообщений проанализировано: {chat_analysis['total_messages']}
😊 Позитивных сообщений: {chat_analysis['positive']}
😔 Негативных сообщений: {chat_analysis['negative']}
📈 Настроение: {chat_analysis['mood']}

💰 Финансы:
• Доходы: {finance_report['income']:.2f}₽
• Расходы: {finance_report['expense']:.2f}₽
• Баланс: {finance_report['balance']:.2f}₽
        """
        
        await update.message.reply_text(text)
    
    # МЕТОДЫ ДЛЯ КНОПОК
    async def process_subscription_button(self, query):
        user_id = query.from_user.id
        
        if self.db.check_subscription(user_id) or user_id == ADMIN_ID:
            await query.edit_message_text(
                "✅ **Подписка активна**\n\n"
                "У вас есть доступ ко всем функциям бота!\n\n"
                "Выберите раздел:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📅 Напоминания", callback_data="reminders_btn")],
                    [InlineKeyboardButton("💰 Финансы", callback_data="finance_btn")],
                    [InlineKeyboardButton("📊 Аналитика", callback_data="analytics_btn")],
                ])
            )
            return
        
        # Даем тестовый доступ
        self.db.update_subscription(user_id, months=1)
        
        await query.edit_message_text(
            "🎉 **Тестовый доступ активирован!**\n\n"
            "Вам предоставлен бесплатный доступ на 1 месяц для тестирования всех функций!\n\n"
            "Теперь вам доступны:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Напоминания", callback_data="reminders_btn")],
                [InlineKeyboardButton("💰 Финансы", callback_data="finance_btn")],
                [InlineKeyboardButton("📊 Аналитика", callback_data="analytics_btn")],
            ])
        )
    
    async def process_reminders_button(self, query):
        user_id = query.from_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            await query.edit_message_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к напоминаниям нужна активная подписка.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Получить подписку", callback_data="subscribe_btn")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")],
                ])
            )
            return
        
        reminders_list = self.reminder_manager.get_reminders(user_id)
        
        if not reminders_list:
            text = "📝 **Управление напоминаниями**\n\nУ вас пока нет напоминаний.\n\nЧтобы добавить напоминание, используйте команду:\n`/reminders 'Текст напоминания' ГГГГ-ММ-ДД ЧЧ:ММ`"
        else:
            text = "📝 **Ваши напоминания:**\n\n"
            for rem in reminders_list:
                status = "✅" if rem['completed'] else "⏳"
                text += f"{status} {rem['text']}\n   📅 {rem['due_date']}\n\n"
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main")],
            ])
        )
    
    async def process_finance_button(self, query):
        user_id = query.from_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            await query.edit_message_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к финансовому учету нужна активная подписка.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Получить подписку", callback_data="subscribe_btn")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")],
                ])
            )
            return
        
        report = self.finance_manager.get_financial_report(user_id)
        
        text = f"""
💰 **Финансовый отчет**

💵 Доходы: {report['income']:.2f}₽
💸 Расходы: {report['expense']:.2f}₽
📊 Баланс: {report['balance']:.2f}₽

Чтобы добавить транзакцию, используйте команду:
`/finance [сумма] [income/expense] [категория]`
        """
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main")],
            ])
        )
    
    async def process_analytics_button(self, query):
        user_id = query.from_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            await query.edit_message_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к аналитике нужна активная подписка.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Получить подписку", callback_data="subscribe_btn")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")],
                ])
            )
            return
        
        chat_analysis = self.chat_monitor.analyze_chat_mood(user_id)
        finance_report = self.finance_manager.get_financial_report(user_id)
        
        text = f"""
📊 **Аналитика вашей активности**

💬 Сообщений: {chat_analysis['total_messages']}
😊 Позитивных: {chat_analysis['positive']}
😔 Негативных: {chat_analysis['negative']}
📈 Настроение: {chat_analysis['mood']}

💰 **Финансы:**
• Доходы: {finance_report['income']:.2f}₽
• Расходы: {finance_report['expense']:.2f}₽
• Баланс: {finance_report['balance']:.2f}₽
        """
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main")],
            ])
        )
    
    async def show_main_menu(self, query):
        user = query.from_user
        
        welcome_text = f"""
👋 С возвращением, {user.first_name}!

Выберите нужный раздел:
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe_btn")],
            [InlineKeyboardButton("📅 Напоминания", callback_data="reminders_btn")],
            [InlineKeyboardButton("💰 Финансы", callback_data="finance_btn")],
            [InlineKeyboardButton("📊 Аналитика", callback_data="analytics_btn")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(welcome_text, reply_markup=reply_markup)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📋 **Доступные команды:**

/start - Запустить бота
/subscribe - Купить подписку
/reminders - Управление напоминаниями
/finance - Финансовый учет  
/analytics - Аналитика
/admin - Админ-панель
/help - Помощь

**Примеры:**
/reminders Позвонить маме 2024-01-15 18:00
/finance 50000 income зарплата
/finance 1500 expense продукты
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
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