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
        
        # Обработчики кнопок
        self.application.add_handler(CallbackQueryHandler(self.button_handler, pattern="^(subscribe|reminders|finance|analytics|back_to_main)$"))
        
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
🔔 **Мониторинг** - слежу за твоими чатами

Для доступа ко всем функциям нужна подписка - 500₽/месяц
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
            [InlineKeyboardButton("📅 Напоминания", callback_data="reminders")],
            [InlineKeyboardButton("💰 Финансы", callback_data="finance")],
            [InlineKeyboardButton("📊 Аналитика", callback_data="analytics")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if self.db.check_subscription(user_id):
            await update.message.reply_text("✅ У вас уже есть активная подписка!")
            return
        
        try:
            payment = self.payment_system.create_payment(user_id)
            
            if payment and 'confirmation' in payment and 'confirmation_url' in payment['confirmation']:
                payment_url = payment['confirmation']['confirmation_url']
                keyboard = [
                    [InlineKeyboardButton("💳 Оплатить подписку", url=payment_url)],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "💳 **Оформление подписки**\n\n"
                    "Подписка стоит 500₽ в месяц и дает доступ ко всем функциям бота:\n"
                    "• 📅 Умные напоминания\n"
                    "• 💰 Финансовый учет\n"
                    "• 📊 Аналитика чатов\n"
                    "• 🔔 Мониторинг активности\n\n"
                    "Для оплаты нажмите кнопку ниже:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                # Если платежная система не настроена
                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "⚠️ **Платежная система временно недоступна**\n\n"
                    "Для тестирования функционала вы можете получить тестовый доступ.\n"
                    "Обратитесь к администратору для настройки платежей.",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Payment error: {e}")
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Ошибка при создании платежа. Платежная система временно недоступна.",
                reply_markup=reply_markup
            )
    
    async def reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к напоминаниям нужна активная подписка.\n"
                "Получите подписку чтобы использовать все функции бота!",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Логика для работы с напоминаниями
        if context.args:
            # Добавление напоминания
            try:
                if len(context.args) < 2:
                    await update.message.reply_text(
                        "📝 **Добавление напоминания**\n\n"
                        "Использование: `/reminders [текст] [ГГГГ-ММ-ДД ЧЧ:ММ]`\n"
                        "Пример: `/reminders Позвонить маме 2024-01-15 18:00`",
                        parse_mode='Markdown'
                    )
                    return
                
                text = ' '.join(context.args[:-2])
                date_str = context.args[-2] + ' ' + context.args[-1]
                success, message = self.reminder_manager.add_reminder(user_id, text, date_str)
                
                keyboard = [[InlineKeyboardButton("📋 Мои напоминания", callback_data="reminders")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(message, reply_markup=reply_markup)
                
            except Exception as e:
                await update.message.reply_text(
                    f"❌ **Ошибка**\n\n"
                    f"Неверный формат команды.\n"
                    f"Использование: `/reminders [текст] [ГГГГ-ММ-ДД ЧЧ:ММ]`\n"
                    f"Пример: `/reminders Позвонить маме 2024-01-15 18:00`",
                    parse_mode='Markdown'
                )
        else:
            # Показать список напоминаний
            reminders = self.reminder_manager.get_reminders(user_id)
            
            if not reminders:
                keyboard = [
                    [InlineKeyboardButton("➕ Добавить напоминание", callback_data="reminders")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "📝 **Мои напоминания**\n\n"
                    "У вас пока нет активных напоминаний.\n"
                    "Добавьте первое напоминание командой:\n"
                    "`/reminders [текст] [ГГГГ-ММ-ДД ЧЧ:ММ]`",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                return
            
            text = "📝 **Ваши напоминания:**\n\n"
            for reminder in reminders:
                status = "✅" if reminder['completed'] else "⏳"
                text += f"{status} {reminder['text']}\n   📅 {reminder['due_date']}\n\n"
            
            keyboard = [
                [InlineKeyboardButton("➕ Добавить еще", callback_data="reminders")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def finance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к финансовому учету нужна активная подписка.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Логика для работы с финансами
        if context.args and len(context.args) >= 3:
            # Добавление транзакции
            try:
                amount = float(context.args[0])
                transaction_type = context.args[1].lower()
                category = context.args[2]
                description = ' '.join(context.args[3:]) if len(context.args) > 3 else ""
                
                if transaction_type not in ['income', 'expense']:
                    await update.message.reply_text("❌ Тип должен быть 'income' (доход) или 'expense' (расход)")
                    return
                
                self.finance_manager.add_transaction(user_id, amount, category, description, transaction_type)
                
                type_emoji = "💵" if transaction_type == 'income' else "💸"
                await update.message.reply_text(f"{type_emoji} Транзакция добавлена!")
                
            except ValueError:
                await update.message.reply_text(
                    "❌ **Неверный формат**\n\n"
                    "Использование: `/finance [сумма] [income/expense] [категория] [описание]`\n"
                    "Примеры:\n"
                    "• `/finance 50000 income зарплата`\n"
                    "• `/finance 1500 expense продукты еда на неделю`",
                    parse_mode='Markdown'
                )
        else:
            # Финансовый отчет
            report = self.finance_manager.get_financial_report(user_id)
            
            text = f"""
💰 **Финансовый отчет**

💵 Доходы: {report['income']:.2f}₽
💸 Расходы: {report['expense']:.2f}₽
📊 Баланс: {report['balance']:.2f}₽

Добавьте транзакцию:
`/finance [сумма] [income/expense] [категория]`
            """
            
            keyboard = [
                [InlineKeyboardButton("💵 Добавить доход", callback_data="finance")],
                [InlineKeyboardButton("💸 Добавить расход", callback_data="finance")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к аналитике нужна активная подписка.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Аналитика
        chat_analysis = self.chat_monitor.analyze_chat_mood(user_id)
        finance_report = self.finance_manager.get_financial_report(user_id)
        
        text = f"""
📊 **Аналитика вашей активности**

💬 Сообщений проанализировано: {chat_analysis['total_messages']}
😊 Позитивных сообщений: {chat_analysis['positive']}
😔 Негативных сообщений: {chat_analysis['negative']}
📈 Настроение: {chat_analysis['mood']}

💰 **Финансы:**
• Доходы: {finance_report['income']:.2f}₽
• Расходы: {finance_report['expense']:.2f}₽
• Баланс: {finance_report['balance']:.2f}₽
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ У вас нет прав администратора")
            return
        
        # Админские функции
        with self.db.get_cursor() as cursor:
            if self.db.is_postgres:
                cursor.execute('SELECT COUNT(*) as count FROM users')
            else:
                cursor.execute('SELECT COUNT(*) as count FROM users')
            
            total_users = cursor.fetchone()['count']
            
            if self.db.is_postgres:
                cursor.execute('SELECT COUNT(*) as count FROM users WHERE subscription_end > CURRENT_DATE')
            else:
                cursor.execute('SELECT COUNT(*) as count FROM users WHERE subscription_end > DATE("now")')
            
            active_subscriptions = cursor.fetchone()['count']
        
        text = f"""
👑 **Панель администратора**

👥 Всего пользователей: {total_users}
💳 Активных подписок: {active_subscriptions}

**Для настройки ЮKassa:**
1. Получите ключи в кабинете ЮKassa
2. Добавьте в .env файл:
   YOOKASSA_SHOP_ID=ваш_shop_id
   YOOKASSA_SECRET_KEY=ваш_secret_key
3. Перезапустите бота
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
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        data = query.data
        
        if data == "subscribe":
            await self.subscribe_callback(query)
        elif data == "reminders":
            await self.reminders_callback(query)
        elif data == "finance":
            await self.finance_callback(query)
        elif data == "analytics":
            await self.analytics_callback(query)
        elif data == "back_to_main":
            await self.back_to_main_callback(query)
    
    async def subscribe_callback(self, query):
        user_id = query.from_user.id
        
        if self.db.check_subscription(user_id) or user_id == ADMIN_ID:
            await query.edit_message_text(
                "✅ **Подписка активна**\n\n"
                "У вас есть доступ ко всем функциям бота!",
                parse_mode='Markdown'
            )
            return
        
        try:
            payment = self.payment_system.create_payment(user_id)
            
            if payment and 'confirmation' in payment and 'confirmation_url' in payment['confirmation']:
                payment_url = payment['confirmation']['confirmation_url']
                keyboard = [
                    [InlineKeyboardButton("💳 Оплатить подписку", url=payment_url)],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "💳 **Оформление подписки**\n\n"
                    "Подписка стоит 500₽ в месяц и дает доступ ко всем функциям бота.\n\n"
                    "Для оплаты нажмите кнопку ниже:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "⚠️ **Платежная система временно недоступна**\n\n"
                    "Для тестирования обратитесь к администратору.",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Payment error in callback: {e}")
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "❌ Ошибка при создании платежа. Платежная система временно недоступна.",
                reply_markup=reply_markup
            )
    
    async def reminders_callback(self, query):
        user_id = query.from_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к напоминаниям нужна активная подписка.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        reminders = self.reminder_manager.get_reminders(user_id)
        
        if not reminders:
            text = "📝 **Мои напоминания**\n\nУ вас пока нет активных напоминаний."
        else:
            text = "📝 **Ваши напоминания:**\n\n"
            for reminder in reminders:
                status = "✅" if reminder['completed'] else "⏳"
                text += f"{status} {reminder['text']}\n   📅 {reminder['due_date']}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def finance_callback(self, query):
        user_id = query.from_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к финансовому учету нужна активная подписка.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        report = self.finance_manager.get_financial_report(user_id)
        
        text = f"""
💰 **Финансовый отчет**

💵 Доходы: {report['income']:.2f}₽
💸 Расходы: {report['expense']:.2f}₽
📊 Баланс: {report['balance']:.2f}₽

Используйте команды:
• `/finance 50000 income зарплата`
• `/finance 1500 expense продукты`
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def analytics_callback(self, query):
        user_id = query.from_user.id
        
        if not self.db.check_subscription(user_id) and user_id != ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "❌ **Требуется подписка**\n\n"
                "Для доступа к аналитике нужна активная подписка.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
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
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def back_to_main_callback(self, query):
        user = query.from_user
        
        welcome_text = f"""
👋 С возвращением, {user.first_name}!

Выберите нужный раздел:
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Купить подписку", callback_data="subscribe")],
            [InlineKeyboardButton("📅 Напоминания", callback_data="reminders")],
            [InlineKeyboardButton("💰 Финансы", callback_data="finance")],
            [InlineKeyboardButton("📊 Аналитика", callback_data="analytics")],
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
/finance 1500 expense продукты еда на неделю
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