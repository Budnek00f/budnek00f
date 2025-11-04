import logging
import os
import requests
import sqlite3
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext
from PIL import Image
import io
import tempfile

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
YANDEX_API_KEY = os.getenv('YANDEX_API_KEY')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

# Проверка обязательных переменных
if not all([TELEGRAM_TOKEN, YANDEX_API_KEY, YANDEX_FOLDER_ID]):
    missing = []
    if not TELEGRAM_TOKEN: missing.append('TELEGRAM_TOKEN')
    if not YANDEX_API_KEY: missing.append('YANDEX_API_KEY')
    if not YANDEX_FOLDER_ID: missing.append('YANDEX_FOLDER_ID')
    raise ValueError(f"Missing environment variables: {', '.join(missing)}")

# Класс базы данных
class ChatDatabase:
    def __init__(self, db_path: str = "data/chat_history.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Инициализация базы данных"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Таблица для хранения сообщений чата
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    message_text TEXT NOT NULL,
                    message_type TEXT DEFAULT 'text',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_bot_message BOOLEAN DEFAULT FALSE
                )
            ''')
            
            # Таблица для напоминаний
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    reminder_text TEXT NOT NULL,
                    reminder_time DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_completed BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            
            # Таблица для списка дел
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    task_text TEXT NOT NULL,
                    priority INTEGER DEFAULT 1,
                    due_date DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    is_completed BOOLEAN DEFAULT FALSE,
                    category TEXT DEFAULT 'general'
                )
            ''')
            
            # Таблица для архива документов и фото
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_path TEXT,
                    text_content TEXT,
                    ocr_text TEXT,
                    file_size INTEGER,
                    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    tags TEXT
                )
            ''')
            
            # Индексы
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(reminder_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_reminders_active ON reminders(is_active)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_todos_completed ON todos(is_completed)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_todos_due_date ON todos(due_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_archives_type ON archives(file_type)')
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def save_message(self, chat_id: int, user_id: int, username: str, 
                    message_text: str, is_bot_message: bool = False,
                    message_type: str = 'text'):
        """Сохранение сообщения в базу данных"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO chat_messages 
                (chat_id, user_id, username, message_text, is_bot_message, message_type)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (chat_id, user_id, username, message_text, is_bot_message, message_type))
            
            conn.commit()
            message_id = cursor.lastrowid
            conn.close()
            
            return message_id
            
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return None

    # === НАПОМИНАНИЯ ===
    def create_reminder(self, chat_id: int, user_id: int, username: str, 
                       reminder_text: str, reminder_time: datetime):
        """Создание напоминания"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO reminders 
                (chat_id, user_id, username, reminder_text, reminder_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (chat_id, user_id, username, reminder_text, reminder_time))
            
            conn.commit()
            reminder_id = cursor.lastrowid
            conn.close()
            
            logger.info(f"Reminder created: {reminder_id}")
            return reminder_id
            
        except Exception as e:
            logger.error(f"Error creating reminder: {e}")
            return None

    def get_active_reminders(self, chat_id: int = None):
        """Получение активных напоминаний"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if chat_id:
                cursor.execute('''
                    SELECT * FROM reminders 
                    WHERE is_active = TRUE AND is_completed = FALSE 
                    AND chat_id = ? AND reminder_time > datetime('now')
                    ORDER BY reminder_time
                ''', (chat_id,))
            else:
                cursor.execute('''
                    SELECT * FROM reminders 
                    WHERE is_active = TRUE AND is_completed = FALSE 
                    AND reminder_time <= datetime('now', '+1 hour')
                    ORDER BY reminder_time
                ''')
            
            reminders = []
            for row in cursor.fetchall():
                reminders.append({
                    'id': row[0],
                    'chat_id': row[1],
                    'user_id': row[2],
                    'username': row[3],
                    'text': row[4],
                    'time': row[5],
                    'created_at': row[6]
                })
            
            conn.close()
            return reminders
            
        except Exception as e:
            logger.error(f"Error getting reminders: {e}")
            return []

    def complete_reminder(self, reminder_id: int):
        """Отметить напоминание как выполненное"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE reminders 
                SET is_completed = TRUE, is_active = FALSE 
                WHERE id = ?
            ''', (reminder_id,))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error completing reminder: {e}")
            return False

    def delete_reminder(self, reminder_id: int, user_id: int):
        """Удалить напоминание"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM reminders 
                WHERE id = ? AND user_id = ?
            ''', (reminder_id, user_id))
            
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"Error deleting reminder: {e}")
            return False

    # === СПИСОК ДЕЛ ===
    def create_todo(self, chat_id: int, user_id: int, username: str, 
                   task_text: str, due_date: datetime = None, priority: int = 1):
        """Создание задачи"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO todos 
                (chat_id, user_id, username, task_text, due_date, priority)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (chat_id, user_id, username, task_text, due_date, priority))
            
            conn.commit()
            task_id = cursor.lastrowid
            conn.close()
            
            return task_id
            
        except Exception as e:
            logger.error(f"Error creating todo: {e}")
            return None

    def get_todos(self, chat_id: int, completed: bool = False):
        """Получение списка дел"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM todos 
                WHERE chat_id = ? AND is_completed = ?
                ORDER BY 
                    CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                    due_date,
                    priority DESC,
                    created_at
            ''', (chat_id, completed))
            
            todos = []
            for row in cursor.fetchall():
                todos.append({
                    'id': row[0],
                    'task_text': row[4],
                    'priority': row[5],
                    'due_date': row[6],
                    'created_at': row[7],
                    'completed_at': row[8],
                    'category': row[10]
                })
            
            conn.close()
            return todos
            
        except Exception as e:
            logger.error(f"Error getting todos: {e}")
            return []

    def complete_todo(self, task_id: int, user_id: int):
        """Отметить задачу как выполненную"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE todos 
                SET is_completed = TRUE, completed_at = datetime('now')
                WHERE id = ? AND user_id = ?
            ''', (task_id, user_id))
            
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"Error completing todo: {e}")
            return False

    def delete_todo(self, task_id: int, user_id: int):
        """Удалить задачу"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM todos 
                WHERE id = ? AND user_id = ?
            ''', (task_id, user_id))
            
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"Error deleting todo: {e}")
            return False

    # === АРХИВ ДОКУМЕНТОВ И ФОТО ===
    def save_to_archive(self, chat_id: int, user_id: int, username: str,
                       file_name: str, file_type: str, file_path: str = None,
                       text_content: str = None, ocr_text: str = None, 
                       file_size: int = None, tags: str = None):
        """Сохранение файла в архив"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO archives 
                (chat_id, user_id, username, file_name, file_type, file_path, 
                 text_content, ocr_text, file_size, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, user_id, username, file_name, file_type, file_path,
                  text_content, ocr_text, file_size, tags))
            
            conn.commit()
            archive_id = cursor.lastrowid
            conn.close()
            
            return archive_id
            
        except Exception as e:
            logger.error(f"Error saving to archive: {e}")
            return None

    def search_archives(self, chat_id: int, query: str = None, file_type: str = None):
        """Поиск в архиве"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if query and file_type:
                cursor.execute('''
                    SELECT * FROM archives 
                    WHERE chat_id = ? AND file_type = ? 
                    AND (file_name LIKE ? OR text_content LIKE ? OR ocr_text LIKE ?)
                    ORDER BY uploaded_at DESC
                ''', (chat_id, file_type, f'%{query}%', f'%{query}%', f'%{query}%'))
            elif query:
                cursor.execute('''
                    SELECT * FROM archives 
                    WHERE chat_id = ? 
                    AND (file_name LIKE ? OR text_content LIKE ? OR ocr_text LIKE ?)
                    ORDER BY uploaded_at DESC
                ''', (chat_id, f'%{query}%', f'%{query}%', f'%{query}%'))
            elif file_type:
                cursor.execute('''
                    SELECT * FROM archives 
                    WHERE chat_id = ? AND file_type = ?
                    ORDER BY uploaded_at DESC
                ''', (chat_id, file_type))
            else:
                cursor.execute('''
                    SELECT * FROM archives 
                    WHERE chat_id = ? 
                    ORDER BY uploaded_at DESC
                    LIMIT 20
                ''', (chat_id,))
            
            archives = []
            for row in cursor.fetchall():
                archives.append({
                    'id': row[0],
                    'file_name': row[4],
                    'file_type': row[5],
                    'file_path': row[6],
                    'text_content': row[7],
                    'ocr_text': row[8],
                    'file_size': row[9],
                    'uploaded_at': row[10],
                    'tags': row[11]
                })
            
            conn.close()
            return archives
            
        except Exception as e:
            logger.error(f"Error searching archives: {e}")
            return []

# Инициализация базы данных
db = ChatDatabase()

YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# Триггеры для обращения к боту
BOT_TRIGGERS = ['/bot', 'бот', '@bot']

def parse_reminder_time(time_str: str) -> datetime:
    """Парсинг времени для напоминаний"""
    try:
        time_str = time_str.lower().strip()
        now = datetime.now()
        
        # Относительное время (через 2 часа, через 30 минут)
        if time_str.startswith('через'):
            parts = time_str.split()
            if 'минут' in time_str:
                minutes = int(''.join(filter(str.isdigit, parts[1])))
                return now + timedelta(minutes=minutes)
            elif 'час' in time_str:
                hours = int(''.join(filter(str.isdigit, parts[1])))
                return now + timedelta(hours=hours)
            elif 'день' in time_str or 'дня' in time_str or 'дней' in time_str:
                days = int(''.join(filter(str.isdigit, parts[1])))
                return now + timedelta(days=days)
        
        # Абсолютное время (18:30, 2024-12-25 18:30)
        elif ':' in time_str:
            if len(time_str) == 5:  # 18:30
                time_obj = datetime.strptime(time_str, '%H:%M')
                reminder_time = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
                if reminder_time < now:
                    reminder_time += timedelta(days=1)
                return reminder_time
            else:  # 2024-12-25 18:30
                return datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        
        # Завтра в определенное время
        elif time_str.startswith('завтра'):
            time_part = time_str.replace('завтра', '').strip()
            if ':' in time_part:
                time_obj = datetime.strptime(time_part, '%H:%M')
                reminder_time = (now + timedelta(days=1)).replace(
                    hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0
                )
                return reminder_time
        
        return None
        
    except Exception as e:
        logger.error(f"Error parsing reminder time: {e}")
        return None

# === ФУНКЦИИ ДЛЯ РАБОТЫ С НАПОМИНАНИЯМИ ===
async def check_reminders(context: CallbackContext):
    """Проверка и отправка напоминаний"""
    try:
        reminders = db.get_active_reminders()
        
        for reminder in reminders:
            reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M:%S')
            
            if reminder_time <= datetime.now():
                message = f"🔔 **Напоминание**\n\n{reminder['text']}"
                
                await context.bot.send_message(
                    chat_id=reminder['chat_id'],
                    text=message
                )
                
                db.complete_reminder(reminder['id'])
                logger.info(f"Sent reminder: {reminder['id']}")
                
    except Exception as e:
        logger.error(f"Error checking reminders: {e}")

# === КОМАНДЫ БОТА ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    welcome_text = (
        f"🤖 Привет, {user.first_name}!\n\n"
        "Я - умный помощник с расширенным функционалом!\n\n"
        "**Основные возможности:**\n"
        "• Запоминаю историю чата\n"
        "• Отвечаю на вопросы через AI\n"
        "• Управляю напоминаниями\n"
        "• Веду список дел\n"
        "• Архивирую документы и фото\n\n"
        "**Команды:**\n"
        "📅 Напоминания:\n"
        "/remind [время] [текст] - создать напоминание\n"
        "/reminders - мои напоминания\n"
        "/delete_remind [id] - удалить напоминание\n\n"
        "✅ Список дел:\n"
        "/todo [задача] - добавить задачу\n"
        "/todos - мои задачи\n"
        "/done [id] - завершить задачу\n"
        "/delete_todo [id] - удалить задачу\n\n"
        "📁 Архив:\n"
        "/archive - поиск в архиве\n"
        "Отправьте файл или фото - я сохраню его\n\n"
        "💬 AI помощник:\n"
        "/bot [вопрос] - задать вопрос AI\n"
        "/search [запрос] - поиск в истории\n"
        "/summary - статистика чата"
    )
    
    await update.message.reply_text(welcome_text)
    db.save_message(chat_id, user.id, user.username or user.first_name, "/start", False)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "📋 **Доступные команды:**\n\n"
        "🔔 **Напоминания:**\n"
        "`/remind 18:30 Позвонить маме`\n"
        "`/remind 2024-12-25 10:00 Поздравления`\n"
        "`/remind через 2 часа Проверить почту`\n"
        "`/reminders` - список напоминаний\n"
        "`/delete_remind 1` - удалить напоминание\n\n"
        "✅ **Список дел:**\n"
        "`/todo Купить продукты`\n"
        "`/todo Завтра 14:00 Забрать посылку`\n"
        "`/todos` - активные задачи\n"
        "`/todos_done` - выполненные задачи\n"
        "`/done 1` - завершить задачу\n"
        "`/delete_todo 1` - удалить задачу\n\n"
        "📁 **Архив файлов:**\n"
        "Просто отправьте фото или документ - я сохраню его в архив\n"
        "`/archive ключевые слова` - поиск в архиве\n\n"
        "🤖 **AI помощник:**\n"
        "`/bot [вопрос]` - задать вопрос\n"
        "`бот [вопрос]` - альтернативный вызов\n"
        "`@бот [вопрос]` - через упоминание"
    )
    
    await update.message.reply_text(help_text)
    db.save_message(update.effective_chat.id, update.effective_user.id, 
                   update.effective_user.username or update.effective_user.first_name, 
                   "/help", False)

# === КОМАНДЫ НАПОМИНАНИЙ ===
async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание напоминания"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Используйте: `/remind [время] [текст]`\n\n"
            "Примеры:\n"
            "`/remind 18:30 Позвонить маме`\n"
            "`/remind 2024-12-25 10:00 Поздравления`\n"
            "`/remind через 2 часа Проверить почту`\n"
            "`/remind завтра 09:00 Совещание`"
        )
        return
    
    # Парсим время (первые 1-2 слова)
    time_parts = []
    text_parts = []
    time_parsed = False
    
    for arg in context.args:
        if not time_parsed and (':' in arg or 'через' in arg or 'завтра' in arg):
            time_parts.append(arg)
            if ':' in arg or len(time_parts) >= 2:
                time_parsed = True
        else:
            text_parts.append(arg)
            time_parsed = True
    
    time_str = ' '.join(time_parts)
    reminder_text = ' '.join(text_parts)
    
    reminder_time = parse_reminder_time(time_str)
    
    if not reminder_time:
        await update.message.reply_text(
            "❌ Не могу распознать время. Примеры:\n"
            "`18:30` - сегодня в 18:30\n"
            "`2024-12-25 10:00` - конкретная дата\n"
            "`через 2 часа` - через 2 часа\n"
            "`завтра 09:00` - завтра в 9 утра"
        )
        return
    
    reminder_id = db.create_reminder(chat_id, user_id, username, reminder_text, reminder_time)
    
    if reminder_id:
        await update.message.reply_text(
            f"✅ Напоминание создано!\n\n"
            f"📅 **Когда:** {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"📝 **Текст:** {reminder_text}\n"
            f"🆔 **ID:** {reminder_id}"
        )
    else:
        await update.message.reply_text("❌ Ошибка при создании напоминания")

async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать активные напоминания"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    reminders = db.get_active_reminders(chat_id)
    
    if not reminders:
        await update.message.reply_text("📭 У вас нет активных напоминаний")
        return
    
    response = "🔔 **Ваши напоминания:**\n\n"
    
    for reminder in reminders:
        reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M:%S')
        response += (
            f"🆔 **{reminder['id']}**\n"
            f"📅 {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"📝 {reminder['text']}\n\n"
        )
    
    response += "❌ Удалить: `/delete_remind [id]`"
    
    await update.message.reply_text(response)

async def delete_remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить напоминание"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ID напоминания: `/delete_remind 1`")
        return
    
    try:
        reminder_id = int(context.args[0])
        success = db.delete_reminder(reminder_id, user_id)
        
        if success:
            await update.message.reply_text(f"✅ Напоминание {reminder_id} удалено")
        else:
            await update.message.reply_text("❌ Не удалось удалить напоминание")
            
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")

# === КОМАНДЫ СПИСКА ДЕЛ ===
async def todo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить задачу в список дел"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if not context.args:
        await update.message.reply_text(
            "❌ Используйте: `/todo [задача]`\n\n"
            "Примеры:\n"
            "`/todo Купить продукты`\n"
            "`/todo Завтра 14:00 Забрать посылку`\n"
            "`/todo !!! СРОЧНО Сделать отчет`"
        )
        return
    
    task_text = ' '.join(context.args)
    due_date = None
    
    # Пытаемся найти дату в тексте задачи
    task_time = parse_reminder_time(task_text)
    if task_time:
        due_date = task_time
    
    task_id = db.create_todo(chat_id, user_id, username, task_text, due_date)
    
    if task_id:
        response = f"✅ Задача добавлена!\n\n📝 **Задача:** {task_text}"
        if due_date:
            response += f"\n📅 **Срок:** {due_date.strftime('%d.%m.%Y %H:%M')}"
        response += f"\n🆔 **ID:** {task_id}"
        
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("❌ Ошибка при добавлении задачи")

async def todos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список дел"""
    chat_id = update.effective_chat.id
    
    todos = db.get_todos(chat_id, completed=False)
    
    if not todos:
        await update.message.reply_text("✅ У вас нет активных задач!")
        return
    
    response = "✅ **Ваши задачи:**\n\n"
    
    for todo in todos:
        priority_emoji = "🔴" if todo['priority'] == 3 else "🟡" if todo['priority'] == 2 else "🟢"
        response += f"{priority_emoji} **{todo['id']}**. {todo['task_text']}"
        
        if todo['due_date']:
            due_date = datetime.strptime(todo['due_date'], '%Y-%m-%d %H:%M:%S')
            response += f" (до {due_date.strftime('%d.%m.%Y %H:%M')})"
        
        response += "\n"
    
    response += "\n✅ Завершить: `/done [id]`\n❌ Удалить: `/delete_todo [id]`"
    
    await update.message.reply_text(response)

async def todos_done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать выполненные задачи"""
    chat_id = update.effective_chat.id
    
    todos = db.get_todos(chat_id, completed=True)
    
    if not todos:
        await update.message.reply_text("📊 У вас нет выполненных задач")
        return
    
    response = "📊 **Выполненные задачи:**\n\n"
    
    for todo in todos:
        completed_date = datetime.strptime(todo['completed_at'], '%Y-%m-%d %H:%M:%S')
        response += f"✅ **{todo['id']}**. {todo['task_text']}\n"
        response += f"   📅 Выполнено: {completed_date.strftime('%d.%m.%Y %H:%M')}\n\n"
    
    await update.message.reply_text(response)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершить задачу"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ID задачи: `/done 1`")
        return
    
    try:
        task_id = int(context.args[0])
        success = db.complete_todo(task_id, user_id)
        
        if success:
            await update.message.reply_text(f"✅ Задача {task_id} выполнена!")
        else:
            await update.message.reply_text("❌ Не удалось завершить задачу")
            
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")

async def delete_todo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить задачу"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ID задачи: `/delete_todo 1`")
        return
    
    try:
        task_id = int(context.args[0])
        success = db.delete_todo(task_id, user_id)
        
        if success:
            await update.message.reply_text(f"✅ Задача {task_id} удалена")
        else:
            await update.message.reply_text("❌ Не удалось удалить задачу")
            
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")

# === КОМАНДЫ АРХИВА ===
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка документов"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    document = update.message.document
    file = await context.bot.get_file(document.file_id)
    
    # Создаем папку для архива если нет
    archive_dir = "archives"
    os.makedirs(archive_dir, exist_ok=True)
    
    file_path = os.path.join(archive_dir, document.file_name)
    await file.download_to_drive(file_path)
    
    # Извлекаем текст в зависимости от типа файла
    text_content = ""
    
    if document.file_name.lower().endswith(('.txt', '.md')):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text_content = f.read()
        except:
            try:
                with open(file_path, 'r', encoding='cp1251') as f:
                    text_content = f.read()
            except:
                text_content = "Не удалось прочитать файл"
    
    # Сохраняем в базу
    archive_id = db.save_to_archive(
        chat_id, user_id, username,
        document.file_name, 'document', file_path,
        text_content, "", document.file_size
    )
    
    if archive_id:
        response = f"📄 Документ сохранен в архив!\n\n📁 **Файл:** {document.file_name}"
        if text_content:
            preview = text_content[:200] + "..." if len(text_content) > 200 else text_content
            response += f"\n📝 **Содержание:** {preview}"
        response += f"\n🆔 **ID:** {archive_id}"
        
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("❌ Ошибка при сохранении документа")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    photo = update.message.photo[-1]  # Берем самое качественное фото
    file = await context.bot.get_file(photo.file_id)
    
    # Создаем папку для архива если нет
    archive_dir = "archives"
    os.makedirs(archive_dir, exist_ok=True)
    
    file_name = f"photo_{photo.file_id}.jpg"
    file_path = os.path.join(archive_dir, file_name)
    await file.download_to_drive(file_path)
    
    # Сохраняем в базу (без OCR для упрощения)
    archive_id = db.save_to_archive(
        chat_id, user_id, username,
        file_name, 'photo', file_path,
        "", "", photo.file_size
    )
    
    if archive_id:
        response = f"📸 Фото сохранено в архив!\n\n🆔 **ID:** {archive_id}"
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("❌ Ошибка при сохранении фото")

async def archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск в архиве"""
    chat_id = update.effective_chat.id
    
    query = ' '.join(context.args) if context.args else None
    archives = db.search_archives(chat_id, query)
    
    if not archives:
        await update.message.reply_text("📭 В архиве ничего не найдено")
        return
    
    response = "📁 **Результаты поиска в архиве:**\n\n"
    
    for archive in archives[:10]:  # Ограничиваем вывод
        emoji = "📸" if archive['file_type'] == 'photo' else "📄"
        response += f"{emoji} **{archive['id']}**. {archive['file_name']}\n"
        
        if archive['uploaded_at']:
            upload_date = datetime.strptime(archive['uploaded_at'], '%Y-%m-%d %H:%M:%S')
            response += f"   📅 {upload_date.strftime('%d.%m.%Y %H:%M')}\n"
        
        if archive['text_content']:
            preview = archive['text_content'][:100] + "..." if len(archive['text_content']) > 100 else archive['text_content']
            response += f"   📝 {preview}\n"
        
        response += "\n"
    
    await update.message.reply_text(response)

# === СУЩЕСТВУЮЩИЕ КОМАНДЫ (AI помощник) ===
async def bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /bot"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if not context.args:
        await update.message.reply_text(
            "❌ Напишите вопрос после команды. Пример: `/bot расскажи о последних обсуждениях`"
        )
        return
    
    user_message = " ".join(context.args)
    await process_bot_request(update, context, chat_id, user_id, username, user_message)

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск в истории чата"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Укажите запрос для поиска. Пример: `/search проект задачи`")
        return
    
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Ищу: \"{query}\"...")
    
    results = db.search_messages(chat_id, query, limit=5)
    
    if not results:
        await update.message.reply_text("😔 Ничего не найдено по вашему запросу.")
        return
    
    response = f"**Результаты поиска по запросу \"{query}\":**\n\n"
    
    for i, result in enumerate(results, 1):
        response += f"{i}. **{result['username']}** ({result['timestamp'][:10]}):\n"
        response += f"   {result['text'][:100]}...\n\n"
    
    await update.message.reply_text(response)

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика чата"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Простая статистика
    todos = db.get_todos(chat_id, completed=False)
    reminders = db.get_active_reminders(chat_id)
    archives = db.search_archives(chat_id)
    
    response = "📊 **Статистика чата:**\n\n"
    response += f"✅ Активных задач: {len(todos)}\n"
    response += f"🔔 Активных напоминаний: {len(reminders)}\n"
    response += f"📁 Файлов в архиве: {len(archives)}\n"
    
    await update.message.reply_text(response)

def should_respond_to_message(message_text: str, bot_username: str) -> bool:
    """Проверяет, должно ли сообщение trigger ответ бота"""
    if not message_text:
        return False
    
    message_lower = message_text.lower()
    
    for trigger in BOT_TRIGGERS:
        if trigger in message_lower:
            return True
    
    if bot_username and f"@{bot_username}" in message_text:
        return True
    
    return False

def extract_user_message(message_text: str, bot_username: str) -> str:
    """Извлекает чистый запрос пользователя из сообщения"""
    clean_text = message_text
    
    for trigger in BOT_TRIGGERS:
        clean_text = clean_text.replace(trigger, '').replace(trigger.upper(), '')
    
    if bot_username:
        clean_text = clean_text.replace(f"@{bot_username}", '')
    
    return clean_text.strip()

def get_conversation_context(chat_id: int, current_message: str, limit: int = 15) -> str:
    """Получает контекст разговора для AI"""
    try:
        chat_history = db.get_chat_history(chat_id, limit=limit)
        
        if not chat_history:
            return ""
        
        context_lines = []
        context_lines.append("Контекст предыдущего разговора в чате:")
        
        for msg in chat_history:
            role = "Ассистент" if msg['is_bot'] else "Пользователь"
            name = msg['username']
            context_lines.append(f"{role} {name}: {msg['text']}")
        
        context_lines.append(f"\nТекущий запрос пользователя: {current_message}")
        
        return "\n".join(context_lines)
        
    except Exception as e:
        logger.error(f"Error getting conversation context: {e}")
        return ""

def get_yandex_gpt_response(prompt: str, context: str = "") -> str:
    """Получение ответа от YandexGPT с контекстом"""
    try:
        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "Content-Type": "application/json"
        }
        
        system_message = """Ты - умный помощник в групповом чате. Ты имеешь доступ к истории сообщений и контексту обсуждения. 

Важные правила:
1. Отвечай ТОЛЬКО на вопросы, направленные конкретно тебе
2. Учитывай контекст предыдущих сообщений в чате
3. Будь полезным, дружелюбным и кратким
4. Отвечай на русском языке
5. Если в контексте есть relevant информация - используй её
6. Не отвечай на сообщения, не предназначенные тебе"""

        if context:
            system_message += f"\n\n{context}"

        data = {
            "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
            "completionOptions": {
                "stream": False,
                "temperature": 0.7,
                "maxTokens": 2000
            },
            "messages": [
                {
                    "role": "system",
                    "text": system_message
                },
                {
                    "role": "user", 
                    "text": prompt
                }
            ]
        }
        
        logger.info(f"Sending request to YandexGPT with context length: {len(context)}")
        response = requests.post(YANDEX_GPT_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        return result['result']['alternatives'][0]['message']['text']
        
    except Exception as e:
        logger.error(f"YandexGPT error: {e}")
        return "❌ Извините, произошла ошибка при обращении к AI."

async def process_bot_request(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                             chat_id: int, user_id: int, username: str, user_message: str):
    """Обрабатывает запрос к боту"""
    await update.message.chat.send_action(action="typing")
    
    conversation_context = get_conversation_context(chat_id, user_message)
    
    bot_response = get_yandex_gpt_response(user_message, conversation_context)
    
    sent_message = await update.message.reply_text(bot_response)
    db.save_message(chat_id, context.bot.id, context.bot.username, bot_response, True)
    
    logger.info(f"Bot responded to user {username} in chat {chat_id}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех сообщений"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    message_text = update.message.text
    
    db.save_message(chat_id, user_id, username, message_text, False)
    
    bot_username = context.bot.username
    should_respond = should_respond_to_message(message_text, bot_username)
    
    if should_respond:
        clean_query = extract_user_message(message_text, bot_username)
        
        if clean_query:
            await process_bot_request(update, context, chat_id, user_id, username, clean_query)
        else:
            await update.message.reply_text("🤖 Чем могу помочь? Напишите ваш вопрос после обращения ко мне.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Error: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже."
        )

def reminder_worker(context: CallbackContext):
    """Фоновая задача для проверки напоминаний"""
    import asyncio
    asyncio.create_task(check_reminders(context))

def main():
    """Основная функция"""
    try:
        logger.info("Starting enhanced AI bot with reminders, todos and archive...")
        
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Основные команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        
        # Напоминания
        application.add_handler(CommandHandler("remind", remind_command))
        application.add_handler(CommandHandler("reminders", reminders_command))
        application.add_handler(CommandHandler("delete_remind", delete_remind_command))
        
        # Список дел
        application.add_handler(CommandHandler("todo", todo_command))
        application.add_handler(CommandHandler("todos", todos_command))
        application.add_handler(CommandHandler("todos_done", todos_done_command))
        application.add_handler(CommandHandler("done", done_command))
        application.add_handler(CommandHandler("delete_todo", delete_todo_command))
        
        # Архив
        application.add_handler(CommandHandler("archive", archive_command))
        
        # AI помощник
        application.add_handler(CommandHandler("bot", bot_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("summary", summary_command))
        
        # Обработчики файлов
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        # Обработчик текстовых сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Настройка планировщика для напоминаний
        job_queue = application.job_queue
        job_queue.run_repeating(reminder_worker, interval=60, first=10)  # Проверка каждую минуту
        
        logger.info("Bot started successfully with enhanced features")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise

if __name__ == '__main__':
    main()