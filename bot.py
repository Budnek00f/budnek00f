import logging
import os
import requests
import sqlite3
import json
import speech_recognition as sr
from pydub import AudioSegment
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext, CallbackQueryHandler
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

# Класс базы данных (упрощенный)
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
            
            # Таблицы остаются без изменений
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
                ORDER BY created_at DESC
            ''', (chat_id, completed))
            
            todos = []
            for row in cursor.fetchall():
                todos.append({
                    'id': row[0],
                    'task_text': row[4],
                    'priority': row[5],
                    'due_date': row[6],
                    'created_at': row[7]
                })
            
            conn.close()
            return todos
            
        except Exception as e:
            logger.error(f"Error getting todos: {e}")
            return []

# Инициализация базы данных
db = ChatDatabase()

YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# === ПРОСТЫЕ КНОПКИ ===
def get_main_menu():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("📅 Напоминания", callback_data="reminders")],
        [InlineKeyboardButton("✅ Задачи", callback_data="todos")],
        [InlineKeyboardButton("🤖 AI Помощник", callback_data="ai")],
        [InlineKeyboardButton("🎤 Голосовое", callback_data="voice")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_reminders_menu():
    """Меню напоминаний"""
    keyboard = [
        [InlineKeyboardButton("➕ Создать напоминание", callback_data="create_reminder")],
        [InlineKeyboardButton("📋 Мои напоминания", callback_data="list_reminders")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_todos_menu():
    """Меню задач"""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить задачу", callback_data="create_todo")],
        [InlineKeyboardButton("📋 Мои задачи", callback_data="list_todos")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_time_menu():
    """Меню времени"""
    keyboard = [
        [InlineKeyboardButton("⏰ Через 1 час", callback_data="time_1h")],
        [InlineKeyboardButton("⏰ Через 2 часа", callback_data="time_2h")],
        [InlineKeyboardButton("🌅 Завтра 09:00", callback_data="time_tomorrow_9")],
        [InlineKeyboardButton("🌇 Завтра 18:00", callback_data="time_tomorrow_18")],
        [InlineKeyboardButton("🔙 Назад", callback_data="reminders")]
    ]
    return InlineKeyboardMarkup(keyboard)

# === ОСНОВНЫЕ КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    
    welcome_text = (
        f"Привет, {user.first_name}! 👋\n\n"
        "Я твой умный помощник! Выбери что хочешь сделать:"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=get_main_menu())
    db.save_message(update.effective_chat.id, user.id, user.username or user.first_name, "/start", False)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    help_text = (
        "🤖 **Помощь по боту:**\n\n"
        "• Используй кнопки для навигации\n"
        "• После нажатия кнопки автоматически обновляются\n"
        "• Можно отправлять голосовые сообщения\n"
        "• Задавай вопросы AI помощнику\n\n"
        "Начни с команды /start"
    )
    
    if hasattr(update, 'callback_query'):
        await update.callback_query.edit_message_text(help_text, reply_markup=get_main_menu())
    else:
        await update.message.reply_text(help_text, reply_markup=get_main_menu())

# === ОБРАБОТЧИК КНОПОК ===
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    
    logger.info(f"Button pressed: {data}")
    
    # Главное меню
    if data == "main":
        await query.edit_message_text("Выбери действие:", reply_markup=get_main_menu())
    
    # Разделы
    elif data == "reminders":
        await query.edit_message_text("📅 Управление напоминаниями:", reply_markup=get_reminders_menu())
    
    elif data == "todos":
        await query.edit_message_text("✅ Управление задачами:", reply_markup=get_todos_menu())
    
    elif data == "ai":
        await query.edit_message_text(
            "🤖 AI Помощник\n\nЗадай мне вопрос:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main")]])
        )
    
    elif data == "voice":
        await query.edit_message_text(
            "🎤 Голосовое управление\n\n"
            "Отправь голосовое сообщение с командой:\n"
            "• 'Создай напоминание'\n"
            "• 'Добавь задачу'\n"
            "• 'Покажи задачи'",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main")]])
        )
    
    elif data == "help":
        await help_command(update, context)
    
    # Напоминания
    elif data == "create_reminder":
        await query.edit_message_text("⏰ Выбери время:", reply_markup=get_time_menu())
    
    elif data.startswith("time_"):
        time_mapping = {
            "time_1h": "через 1 час",
            "time_2h": "через 2 часа", 
            "time_tomorrow_9": "завтра 09:00",
            "time_tomorrow_18": "завтра 18:00"
        }
        
        if data in time_mapping:
            context.user_data['reminder_time'] = time_mapping[data]
            await query.edit_message_text(
                f"⏰ Время: {time_mapping[data]}\n\n"
                "📝 Теперь введи текст напоминания:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="reminders")]])
            )
    
    elif data == "list_reminders":
        reminders = db.get_active_reminders(chat_id)
        
        if not reminders:
            await query.edit_message_text(
                "📭 Нет активных напоминаний",
                reply_markup=get_reminders_menu()
            )
        else:
            response = "🔔 Твои напоминания:\n\n"
            for reminder in reminders:
                reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M:%S')
                response += f"• {reminder_time.strftime('%d.%m %H:%M')} - {reminder['text']}\n"
            
            await query.edit_message_text(response, reply_markup=get_reminders_menu())
    
    # Задачи
    elif data == "create_todo":
        await query.edit_message_text(
            "✅ Введи текст задачи:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="todos")]])
        )
    
    elif data == "list_todos":
        todos = db.get_todos(chat_id, completed=False)
        
        if not todos:
            await query.edit_message_text(
                "🎉 Нет активных задач!",
                reply_markup=get_todos_menu()
            )
        else:
            response = "✅ Твои задачи:\n\n"
            for todo in todos:
                response += f"• {todo['task_text']}\n"
            
            await query.edit_message_text(response, reply_markup=get_todos_menu())

# === ОБРАБОТКА ТЕКСТА ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    text = update.message.text
    
    # Сохраняем сообщение
    db.save_message(chat_id, user_id, username, text, False)
    
    # Проверяем ожидание ввода
    if 'reminder_time' in context.user_data:
        # Создаем напоминание
        reminder_time_str = context.user_data['reminder_time']
        reminder_time = parse_reminder_time(reminder_time_str)
        
        if reminder_time:
            reminder_id = db.create_reminder(chat_id, user_id, username, text, reminder_time)
            
            if reminder_id:
                await update.message.reply_text(
                    f"✅ Напоминание создано!\n"
                    f"📅 {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📝 {text}",
                    reply_markup=get_main_menu()
                )
            else:
                await update.message.reply_text("❌ Ошибка", reply_markup=get_main_menu())
        else:
            await update.message.reply_text("❌ Ошибка времени", reply_markup=get_main_menu())
        
        context.user_data.clear()
    
    elif 'waiting_todo' in context.user_data:
        # Создаем задачу
        task_id = db.create_todo(chat_id, user_id, username, text)
        
        if task_id:
            await update.message.reply_text(f"✅ Задача добавлена: {text}", reply_markup=get_main_menu())
        else:
            await update.message.reply_text("❌ Ошибка", reply_markup=get_main_menu())
        
        context.user_data.clear()
    
    else:
        # Обычный AI запрос
        if any(word in text.lower() for word in ['бот', '/bot']):
            clean_text = text.replace('бот', '').replace('/bot', '').strip()
            if clean_text:
                await process_ai_request(update, context, chat_id, user_id, username, clean_text)
        else:
            # Показываем меню
            await update.message.reply_text("Выбери действие:", reply_markup=get_main_menu())

# === УТИЛИТЫ ===
def parse_reminder_time(time_str: str) -> datetime:
    """Парсинг времени"""
    try:
        now = datetime.now()
        
        if time_str == "через 1 час":
            return now + timedelta(hours=1)
        elif time_str == "через 2 часа":
            return now + timedelta(hours=2)
        elif time_str == "завтра 09:00":
            return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        elif time_str == "завтра 18:00":
            return (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        
        return None
    except Exception as e:
        logger.error(f"Error parsing time: {e}")
        return None

async def process_ai_request(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                           chat_id: int, user_id: int, username: str, text: str):
    """Обработка AI запроса"""
    await update.message.chat.send_action(action="typing")
    
    try:
        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
            "completionOptions": {
                "stream": False,
                "temperature": 0.7,
                "maxTokens": 1000
            },
            "messages": [
                {
                    "role": "user", 
                    "text": text
                }
            ]
        }
        
        response = requests.post(YANDEX_GPT_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        answer = result['result']['alternatives'][0]['message']['text']
        
        await update.message.reply_text(
            answer,
            reply_markup=get_main_menu()
        )
        db.save_message(chat_id, context.bot.id, context.bot.username, answer, True)
        
    except Exception as e:
        logger.error(f"AI error: {e}")
        await update.message.reply_text("❌ Ошибка AI", reply_markup=get_main_menu())

# === НАПОМИНАНИЯ ===
async def check_reminders(context: CallbackContext):
    """Проверка напоминаний"""
    try:
        reminders = db.get_active_reminders()
        
        for reminder in reminders:
            reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M:%S')
            
            if reminder_time <= datetime.now():
                await context.bot.send_message(
                    chat_id=reminder['chat_id'],
                    text=f"🔔 Напоминание: {reminder['text']}"
                )
                db.complete_reminder(reminder['id'])
                
    except Exception as e:
        logger.error(f"Reminder error: {e}")

async def reminder_job(context: CallbackContext):
    """Фоновая задача"""
    await check_reminders(context)

# === ГОЛОСОВЫЕ СООБЩЕНИЯ ===
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений"""
    await update.message.reply_text(
        "🎤 Голосовые сообщения временно недоступны",
        reply_markup=get_main_menu()
    )

# === ОШИБКИ ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Error: {context.error}")

# === ЗАПУСК ===
def main():
    """Основная функция"""
    try:
        logger.info("Starting simple bot...")
        
        # Создаем приложение
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Добавляем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        
        # Обработчик кнопок - ДОЛЖЕН БЫТЬ ПЕРВЫМ после команд!
        application.add_handler(CallbackQueryHandler(handle_button))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Планировщик
        job_queue = application.job_queue
        job_queue.run_repeating(reminder_job, interval=60, first=10)
        
        logger.info("Bot started!")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Start error: {e}")
        raise

if __name__ == '__main__':
    main()