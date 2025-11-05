import logging
import sys
import os
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ---------- Настройка окружения и логов ----------
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID')) if os.getenv('ADMIN_ID') else None
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
TRIAL_DAYS = int(os.getenv('TRIAL_DAYS', '30'))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

if not TELEGRAM_TOKEN:
    logger.error('TELEGRAM_TOKEN не задан в .env. Останов.')
    sys.exit(1)

# ---------- Примитивная БД (sqlite) ----------
class Database:
    def __init__(self, path: str = 'bot_data.db'):
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self):
        cur = self.conn.cursor()
        # users: id, username, first_name, last_name, trial_used, subscription_end
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            trial_used INTEGER DEFAULT 0,
            subscription_end TEXT
        )
        ''')

        cur.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            text TEXT,
            due_date TEXT,
            completed INTEGER DEFAULT 0,
            created_at TEXT
        )
        ''')

        cur.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount TEXT,
            category TEXT,
            description TEXT,
            type TEXT,
            created_at TEXT
        )
        ''')

        self.conn.commit()

    def add_user(self, user_id: int, username: Optional[str], first_name: Optional[str], last_name: Optional[str]):
        cur = self.conn.cursor()
        cur.execute('SELECT id FROM users WHERE id = ?', (user_id,))
        if cur.fetchone():
            # обновим данные
            cur.execute('UPDATE users SET username=?, first_name=?, last_name=? WHERE id=?',
                        (username, first_name, last_name, user_id))
        else:
            cur.execute('INSERT INTO users (id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
                        (user_id, username, first_name, last_name))
        self.conn.commit()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        return cur.fetchone()

    def set_trial_used(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute('UPDATE users SET trial_used = 1 WHERE id = ?', (user_id,))
        self.conn.commit()

    def check_trial_used(self, user_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute('SELECT trial_used FROM users WHERE id = ?', (user_id,))
        row = cur.fetchone()
        return bool(row and row['trial_used'])

    def update_subscription(self, user_id: int, days: int):
        end = datetime.utcnow() + timedelta(days=days)
        end_iso = end.replace(microsecond=0).isoformat()
        cur = self.conn.cursor()
        cur.execute('UPDATE users SET subscription_end = ? WHERE id = ?', (end_iso, user_id))
        # если пользователь не существует — создадим
        if cur.rowcount == 0:
            cur.execute('INSERT INTO users (id, subscription_end) VALUES (?, ?)', (user_id, end_iso))
        self.conn.commit()

    def check_subscription(self, user_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute('SELECT subscription_end FROM users WHERE id = ?', (user_id,))
        row = cur.fetchone()
        if not row or not row['subscription_end']:
            return False
        try:
            end = datetime.fromisoformat(row['subscription_end'])
            return end > datetime.utcnow()
        except Exception:
            return False

    # reminders
    def add_reminder(self, user_id: int, chat_id: int, text: str, due_iso: str) -> int:
        cur = self.conn.cursor()
        now = datetime.utcnow().replace(microsecond=0).isoformat()
        cur.execute('''INSERT INTO reminders (user_id, chat_id, text, due_date, created_at) VALUES (?, ?, ?, ?, ?)''',
                    (user_id, chat_id, text, due_iso, now))
        self.conn.commit()
        return cur.lastrowid

    def get_reminders(self, user_id: int) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM reminders WHERE user_id = ? ORDER BY due_date', (user_id,))
        return cur.fetchall()

    def get_future_reminders(self) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM reminders WHERE completed = 0')
        return cur.fetchall()

    def mark_reminder_completed(self, reminder_id: int):
        cur = self.conn.cursor()
        cur.execute('UPDATE reminders SET completed = 1 WHERE id = ?', (reminder_id,))
        self.conn.commit()

    # finance
    def add_transaction(self, user_id: int, amount: str, category: str, description: str, ttype: str):
        cur = self.conn.cursor()
        now = datetime.utcnow().replace(microsecond=0).isoformat()
        cur.execute('INSERT INTO transactions (user_id, amount, category, description, type, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (user_id, amount, category, description, ttype, now))
        self.conn.commit()

    def get_financial_report(self, user_id: int) -> Dict[str, Decimal]:
        cur = self.conn.cursor()
        cur.execute('SELECT amount, type FROM transactions WHERE user_id = ?', (user_id,))
        rows = cur.fetchall()
        income = Decimal('0')
        expense = Decimal('0')
        for r in rows:
            try:
                amt = Decimal(r['amount'])
            except Exception:
                continue
            if r['type'] == 'income':
                income += amt
            else:
                expense += amt
        return {'income': income, 'expense': expense, 'balance': income - expense}

# ---------- ReminderManager ----------
class ReminderManager:
    def __init__(self, db: Database):
        self.db = db
        self.scheduled_jobs = {}  # reminder_id -> job

    def schedule_all(self, job_queue):
        # восстанавливаем отложенные задачи
        reminders = self.db.get_future_reminders()
        for rem in reminders:
            if rem['completed']:
                continue
            try:
                due = datetime.fromisoformat(rem['due_date'])
            except Exception:
                continue
            seconds = (due - datetime.utcnow()).total_seconds()
            if seconds <= 0:
                # просрочено — отправим немедленно через очередь
                seconds = 1
            job = job_queue.run_once(self._job_callback, seconds, data={'reminder_id': rem['id']})
            self.scheduled_jobs[rem['id']] = job
            logger.debug(f'Scheduled reminder {rem["id"]} in {seconds} seconds')

    async def _job_callback(self, context: ContextTypes.DEFAULT_TYPE):
        data = context.job.data
        rem_id = data.get('reminder_id')
        cur = self.db.conn.cursor()
        cur.execute('SELECT * FROM reminders WHERE id = ?', (rem_id,))
        rem = cur.fetchone()
        if not rem or rem['completed']:
            return
        chat_id = rem['chat_id']
        text = rem['text']
        try:
            await context.bot.send_message(chat_id=chat_id, text=f'🔔 Напоминание: {text}')
            self.db.mark_reminder_completed(rem_id)
            logger.info(f'Reminder {rem_id} sent to chat {chat_id}')
        except Exception as e:
            logger.exception(f'Не удалось отправить напоминание {rem_id}: {e}')

    def add_reminder(self, user_id: int, chat_id: int, text: str, due_iso: str, job_queue) -> (bool, str):
        # проверка формата даты
        try:
            due = datetime.fromisoformat(due_iso)
        except Exception:
            return False, 'Неверный формат даты. Используйте: YYYY-MM-DD HH:MM'
        if due < datetime.utcnow():
            return False, 'Дата в прошлом. Укажите будущую дату.'
        rem_id = self.db.add_reminder(user_id, chat_id, text, due_iso)
        seconds = (due - datetime.utcnow()).total_seconds()
        job = job_queue.run_once(self._job_callback, seconds, data={'reminder_id': rem_id})
        self.scheduled_jobs[rem_id] = job
        return True, 'Напоминание создано и запланировано.'

    def get_reminders(self, user_id: int):
        return self.db.get_reminders(user_id)

# ---------- FinanceManager ----------
class FinanceManager:
    def __init__(self, db: Database):
        self.db = db

    def add_transaction(self, user_id: int, amount: Decimal, category: str, description: str, ttype: str):
        # сохраняем строковое представление Decimal для безопасного хранения
        self.db.add_transaction(user_id, str(amount), category, description, ttype)

    def get_financial_report(self, user_id: int) -> Dict[str, Decimal]:
        return self.db.get_financial_report(user_id)

# ---------- PaymentSystem (заглушка) ----------
class PaymentSystem:
    def __init__(self):
        # здесь можно интегрировать Yookassa / другие провайдеры
        pass

    def create_payment_link(self, user_id: int, amount_rub: int) -> str:
        # возврат тестовой ссылки
        return f'https://example.com/pay?user={user_id}&amount={amount_rub}'

# ---------- ChatMonitor (простая аналитика настроения) ----------
class ChatMonitor:
    POSITIVE = {'спасибо', 'отлично', 'класс', 'хорошо', 'супер', 'рад', 'люблю'}
    NEGATIVE = {'плохо', 'ужасно', 'ненавижу', 'грустно', 'печаль', 'злой'}

    def __init__(self, db: Database):
        self.db = db
        # для простоты мы не сохраняем сообщения, только считаем при запросе
        # реальная реализация может хранить сообщения и считать статистику

    def log_message(self, user_id: int, chat_id: int, message: str):
        # в простом варианте логируем в stdout; при необходимости можно сохранить в БД
        logger.debug(f'Log message from {user_id} in {chat_id}: {message[:200]}')

    def analyze_chat_mood(self, user_id: int) -> Dict[str, Any]:
        # возврат фиктивной аналитики (на базе последних N сообщений можно расширить)
        # Для демонстрации вернём нулевые значения
        return {'total_messages': 0, 'positive': 0, 'negative': 0, 'mood': 'neutral'}

# ---------- Утилиты ----------
import telegram.helpers as helpers

def safe_markdown(text: str) -> str:
    try:
        return helpers.escape_markdown(text, version=2)
    except Exception:
        # fallback: простая замена
        return text.replace('_', '\_').replace('*', '\*')

# ---------- Бот ----------
class LifeAssistantBot:
    def __init__(self):
        logger.info('Initializing bot...')
        self.db = Database()
        self.payment_system = PaymentSystem()
        self.reminder_manager = ReminderManager(self.db)
        self.finance_manager = FinanceManager(self.db)
        self.chat_monitor = ChatMonitor(self.db)

        self.application = Application.builder().token(TELEGRAM_TOKEN).build()
        self.setup_handlers()

    def setup_handlers(self):
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('subscribe', self.subscribe))
        self.application.add_handler(CommandHandler('reminders', self.reminders))
        self.application.add_handler(CommandHandler('finance', self.finance))
        self.application.add_handler(CommandHandler('analytics', self.analytics))
        self.application.add_handler(CommandHandler('admin', self.admin))

        # CallbackQueryHandler
        self.application.add_handler(CallbackQueryHandler(self.handle_button))

        # Messages
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # Error handler
        self.application.add_error_handler(self.error_handler)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.exception('Exception while handling an update')
        # notify admin if set
        try:
            if ADMIN_ID:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f'Ошибка: {context.error}')
        except Exception:
            logger.exception('Не удалось уведомить админа')

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.db.add_user(user.id, user.username, user.first_name, user.last_name)

        welcome_text = (
            f"👋 Привет, {safe_markdown(user.first_name or '')}!\n\n"
            "Я твой универсальный помощник по жизни! Вот что я умею:\n\n"
            "📅 *Напоминания* - создавай задачи и напоминания\n"
            "💰 *Финансы* - веди учет доходов и расходов\n"
            "📊 *Аналитика* - анализирую твои сообщения и финансы\n\n"
            "Для доступа ко всем функциям нужна подписка.\n"
        )

        keyboard = [
            [InlineKeyboardButton('💳 Купить подписку', callback_data='subscribe_btn')],
            [InlineKeyboardButton('📅 Напоминания', callback_data='reminders_btn')],
            [InlineKeyboardButton('💰 Финансы', callback_data='finance_btn')],
            [InlineKeyboardButton('📊 Аналитика', callback_data='analytics_btn')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

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
        if ADMIN_ID is None or user_id != ADMIN_ID:
            await update.message.reply_text('❌ У вас нет прав администратора')
            return

        cur = self.db.conn.cursor()
        cur.execute('SELECT COUNT(*) as count FROM users')
        total_users = cur.fetchone()['count']
        # count active subscriptions
        cur.execute('SELECT COUNT(*) as count FROM users WHERE subscription_end > ?', (datetime.utcnow().isoformat(),))
        active_subscriptions = cur.fetchone()['count']

        text = (
            f'👑 *Панель администратора*\n\n'
            f'👥 Всего пользователей: {total_users}\n'
            f'💳 Активных подписок: {active_subscriptions}\n\n'
            'Для настройки ЮKassa добавьте в .env: YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY'
        )
        await update.message.reply_text(text, parse_mode='MarkdownV2')

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        message = update.message.text or ''
        self.chat_monitor.log_message(user.id, update.effective_chat.id, message)

        # простые приветствия
        if any(word in message.lower() for word in ['привет', 'hello', 'hi']):
            await update.message.reply_text(f'👋 Привет, {safe_markdown(user.first_name or "")}! Используй /start для начала работы.', parse_mode='MarkdownV2')

    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = query.from_user.id
        logger.info(f'Button pressed: {data} by user {user_id}')

        if data == 'subscribe_btn':
            await self.process_subscription_button(query, context)
        elif data == 'reminders_btn':
            await self.process_reminders_button(query, context)
        elif data == 'finance_btn':
            await self.process_finance_button(query, context)
        elif data == 'analytics_btn':
            await self.process_analytics_button(query, context)
        elif data == 'back_to_main':
            await self.show_main_menu(query)
        else:
            # fallback
            if query.message:
                await query.message.edit_text(f'❌ Неизвестная команда: {data}')

    # ----- Команды (реализация) -----
    async def process_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if self.db.check_subscription(user_id) or (ADMIN_ID and user_id == ADMIN_ID):
            await update.message.reply_text('✅ У вас уже есть активная подписка!')
            return
        # выдаём однократный trial
        if not self.db.check_trial_used(user_id):
            self.db.update_subscription(user_id, days=TRIAL_DAYS)
            self.db.set_trial_used(user_id)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('📅 Напоминания', callback_data='reminders_btn')],
                [InlineKeyboardButton('💰 Финансы', callback_data='finance_btn')],
                [InlineKeyboardButton('📊 Аналитика', callback_data='analytics_btn')],
            ])
            await update.message.reply_text('🎉 Тестовый доступ активирован на %d дней!' % TRIAL_DAYS, reply_markup=keyboard)
            return
        else:
            # если trial уже использован, предлагаем оплату
            payment_link = self.payment_system.create_payment_link(user_id, 500)
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('💳 Оплатить', url=payment_link)]])
            await update.message.reply_text('У вас уже был использован тестовый период. Оплатите подписку для продолжения.', reply_markup=keyboard)

    async def process_reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.check_subscription(user_id) and (ADMIN_ID is None or user_id != ADMIN_ID):
            await update.message.reply_text('❌ Для доступа к напоминаниям нужна подписка! Используйте /subscribe')
            return
        # если есть аргументы — добавляем
        if context.args:
            try:
                if len(context.args) < 2:
                    await update.message.reply_text("Использование: /reminders [текст] [YYYY-MM-DD HH:MM]")
                    return
                # присоединяем последние два токена как дату и время
                date_time_str = ' '.join(context.args[-2:])
                text = ' '.join(context.args[:-2])
                # приводим к ISO-like: 'YYYY-MM-DD HH:MM' -> 'YYYY-MM-DDTHH:MM:00' для fromisoformat
                try:
                    due = datetime.strptime(date_time_str, '%Y-%m-%d %H:%M')
                    due_iso = due.replace(microsecond=0).isoformat()
                except ValueError:
                    await update.message.reply_text('Неверный формат даты. Используйте: YYYY-MM-DD HH:MM')
                    return
                success, message = self.reminder_manager.add_reminder(user_id, update.effective_chat.id, text, due_iso, self.application.job_queue)
                await update.message.reply_text(message)
            except Exception as e:
                logger.exception('Ошибка при добавлении напоминания')
                await update.message.reply_text(f'Ошибка: {e}')
        else:
            reminders = self.reminder_manager.get_reminders(user_id)
            if not reminders:
                await update.message.reply_text('📝 У вас нет активных напоминаний')
                return
            text_lines = ['📅 Ваши напоминания:\n']
            for rem in reminders:
                status = '✅' if rem['completed'] else '⏳'
                # форматим дату красиво
                try:
                    due = datetime.fromisoformat(rem['due_date']).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    due = rem['due_date']
                text_lines.append(f"{status} {safe_markdown(rem['text'])} - {due}")
            await update.message.reply_text('\n'.join(text_lines), parse_mode='MarkdownV2')

    async def process_finance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.check_subscription(user_id) and (ADMIN_ID is None or user_id != ADMIN_ID):
            await update.message.reply_text('❌ Для доступа к финансового учета нужна подписка! Используйте /subscribe')
            return
        if context.args and len(context.args) >= 3:
            try:
                raw_amount = context.args[0].replace(',', '.')
                amount = Decimal(raw_amount)
                transaction_type = context.args[1].lower()
                category = context.args[2]
                description = ' '.join(context.args[3:]) if len(context.args) > 3 else ''
                if transaction_type not in ['income', 'expense']:
                    await update.message.reply_text("Тип должен быть 'income' или 'expense'")
                    return
                self.finance_manager.add_transaction(user_id, amount, category, description, transaction_type)
                await update.message.reply_text('✅ Транзакция добавлена!')
            except InvalidOperation:
                await update.message.reply_text('Неверный формат суммы. Пример использования: /finance 1500 expense продукты')
            except Exception:
                logger.exception('Ошибка при добавлении транзакции')
                await update.message.reply_text('Ошибка при добавлении транзакции')
        else:
            report = self.finance_manager.get_financial_report(user_id)
            text = (
                f"💰 Финансовый отчет:\n\n"
                f"💵 Доходы: {report['income']:.2f}₽\n"
                f"💸 Расходы: {report['expense']:.2f}₽\n"
                f"📊 Баланс: {report['balance']:.2f}₽"
            )
            await update.message.reply_text(text)

    async def process_analytics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.db.check_subscription(user_id) and (ADMIN_ID is None or user_id != ADMIN_ID):
            await update.message.reply_text('❌ Для доступа к аналитике нужна подписка! Используйте /subscribe')
            return
        chat_analysis = self.chat_monitor.analyze_chat_mood(user_id)
        finance_report = self.finance_manager.get_financial_report(user_id)
        text = (
            '📊 Аналитика вашей активности:\n\n'
            f"💬 Сообщений проанализировано: {chat_analysis['total_messages']}\n"
            f"😊 Позитивных сообщений: {chat_analysis['positive']}\n"
            f"😔 Негативных сообщений: {chat_analysis['negative']}\n"
            f"📈 Настроение: {chat_analysis['mood']}\n\n"
            '💰 Финансы:\n'
            f"• Доходы: {finance_report['income']:.2f}₽\n"
            f"• Расходы: {finance_report['expense']:.2f}₽\n"
            f"• Баланс: {finance_report['balance']:.2f}₽"
        )
        await update.message.reply_text(text)

    # ----- Кнопки -----
    async def process_subscription_button(self, query, context):
        user_id = query.from_user.id
        if self.db.check_subscription(user_id) or (ADMIN_ID and user_id == ADMIN_ID):
            await query.message.edit_text('✅ Подписка активна. Выберите раздел:')
            return
        # Trial
        if not self.db.check_trial_used(user_id):
            self.db.update_subscription(user_id, days=TRIAL_DAYS)
            self.db.set_trial_used(user_id)
            await query.message.edit_text('🎉 Тестовый доступ активирован!')
            return
        payment_link = self.payment_system.create_payment_link(user_id, 500)
        await query.message.edit_text('Оплатите подписку: ' + payment_link)

    async def process_reminders_button(self, query, context):
        user_id = query.from_user.id
        if not self.db.check_subscription(user_id) and (ADMIN_ID is None or user_id != ADMIN_ID):
            await query.message.edit_text('❌ Для доступа к напоминаниям нужна подписка.', reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('💳 Получить подписку', callback_data='subscribe_btn')],
                [InlineKeyboardButton('🔙 Назад', callback_data='back_to_main')]
            ]))
            return
        reminders = self.reminder_manager.get_reminders(user_id)
        if not reminders:
            text = '📝 Управление напоминаниями\n\nУ вас пока нет напоминаний. Чтобы добавить, используйте /reminders Текст 2025-01-01 12:00'
        else:
            lines = ['📝 Ваши напоминания:']
            for r in reminders:
                status = '✅' if r['completed'] else '⏳'
                try:
                    due = datetime.fromisoformat(r['due_date']).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    due = r['due_date']
                lines.append(f"{status} {safe_markdown(r['text'])} - {due}")
            text = '\n'.join(lines)
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Главное меню', callback_data='back_to_main')]]), parse_mode='MarkdownV2')

    async def process_finance_button(self, query, context):
        user_id = query.from_user.id
        if not self.db.check_subscription(user_id) and (ADMIN_ID is None or user_id != ADMIN_ID):
            await query.message.edit_text('❌ Для доступа к финансам нужна подписка.', reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('💳 Получить подписку', callback_data='subscribe_btn')],
                [InlineKeyboardButton('🔙 Назад', callback_data='back_to_main')],
            ]))
            return
        report = self.finance_manager.get_financial_report(user_id)
        text = (
            f'💰 Финансовый отчет\n\n💵 Доходы: {report["income"]:.2f}₽\n💸 Расходы: {report["expense"]:.2f}₽\n📊 Баланс: {report["balance"]:.2f}₽\n\nЧтобы добавить транзакцию используйте /finance [сумма] [income/expense] [категория]'
        )
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Главное меню', callback_data='back_to_main')]]))

    async def process_analytics_button(self, query, context):
        user_id = query.from_user.id
        if not self.db.check_subscription(user_id) and (ADMIN_ID is None or user_id != ADMIN_ID):
            await query.message.edit_text('❌ Для доступа к аналитике нужна подписка.', reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('💳 Получить подписку', callback_data='subscribe_btn')],
                [InlineKeyboardButton('🔙 Назад', callback_data='back_to_main')],
            ]))
            return
        chat_analysis = self.chat_monitor.analyze_chat_mood(user_id)
        finance_report = self.finance_manager.get_financial_report(user_id)
        text = (
            '📊 Аналитика вашей активности\n\n'
            f'💬 Сообщений: {chat_analysis["total_messages"]}\n'
            f'😊 Позитивных: {chat_analysis["positive"]}\n'
            f'😔 Негативных: {chat_analysis["negative"]}\n'
            f'📈 Настроение: {chat_analysis["mood"]}\n\n'
            '💰 Финансы:\n'
            f'• Доходы: {finance_report["income"]:.2f}₽\n'
            f'• Расходы: {finance_report["expense"]:.2f}₽\n'
            f'• Баланс: {finance_report["balance"]:.2f}₽'
        )
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Главное меню', callback_data='back_to_main')]]))

    async def show_main_menu(self, query):
        user = query.from_user
        welcome_text = f'👋 С возвращением, {safe_markdown(user.first_name or "")}!\n\nВыберите нужный раздел:'
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('💳 Купить подписку', callback_data='subscribe_btn')],
            [InlineKeyboardButton('📅 Напоминания', callback_data='reminders_btn')],
            [InlineKeyboardButton('💰 Финансы', callback_data='finance_btn')],
            [InlineKeyboardButton('📊 Аналитика', callback_data='analytics_btn')],
        ])
        await query.message.edit_text(welcome_text, reply_markup=keyboard, parse_mode='MarkdownV2')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            '📋 *Доступные команды:*\n\n'
            '/start - Запустить бота\n'
            '/subscribe - Получить подписку (trial 1 раз)\n'
            '/reminders - Управление напоминаниями\n'
            '/finance - Финансовый учет\n'
            '/analytics - Аналитика\n'
            '/admin - Админ-панель\n'
            '/help - Помощь\n\n'
            '*Примеры:*\n'
            '/reminders Позвонить маме 2025-01-15 18:00\n'
            '/finance 50000 income зарплата\n'
            '/finance 1500 expense продукты'
        )
        await update.message.reply_text(help_text, parse_mode='MarkdownV2')

    def run(self):
        # восстановим задачи напоминаний после старта
        logger.info('Scheduling existing reminders...')
        self.reminder_manager.schedule_all(self.application.job_queue)
        logger.info('Starting polling...')
        try:
            self.application.run_polling()
        except Exception as e:
            logger.exception('Bot stopped with error')


if __name__ == '__main__':
    bot = LifeAssistantBot()
    bot.run()
