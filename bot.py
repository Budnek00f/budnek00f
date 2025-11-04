import logging
import os
import requests
import sqlite3
import json
import speech_recognition as sr
from pydub import AudioSegment
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext, CallbackQueryHandler, ConversationHandler
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

# Состояния для ConversationHandler
REMINDER_TEXT, REMINDER_TIME = range(2)
TODO_TEXT = range(1)

# Проверка обязательных переменных
if not all([TELEGRAM_TOKEN, YANDEX_API_KEY, YANDEX_FOLDER_ID]):
    missing = []
    if not TELEGRAM_TOKEN: missing.append('TELEGRAM_TOKEN')
    if not YANDEX_API_KEY: missing.append('YANDEX_API_KEY')
    if not YANDEX_FOLDER_ID: missing.append('YANDEX_FOLDER_ID')
    raise ValueError(f"Missing environment variables: {', '.join(missing)}")

# Класс базы данных (остается без изменений)
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

# === КЛАВИАТУРЫ ===
def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = [
        [KeyboardButton("📅 Напоминания"), KeyboardButton("✅ Задачи")],
        [KeyboardButton("📁 Архив"), KeyboardButton("🤖 AI Помощник")],
        [KeyboardButton("🎤 Голосовое сообщение"), KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_reminders_keyboard():
    """Клавиатура для напоминаний"""
    keyboard = [
        [InlineKeyboardButton("➕ Создать напоминание", callback_data="create_reminder")],
        [InlineKeyboardButton("📋 Мои напоминания", callback_data="list_reminders")],
        [InlineKeyboardButton("❌ Удалить напоминание", callback_data="delete_reminder")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_todos_keyboard():
    """Клавиатура для задач"""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить задачу", callback_data="create_todo")],
        [InlineKeyboardButton("📋 Активные задачи", callback_data="list_todos")],
        [InlineKeyboardButton("✅ Выполненные задачи", callback_data="list_done_todos")],
        [InlineKeyboardButton("✔️ Завершить задачу", callback_data="complete_todo")],
        [InlineKeyboardButton("❌ Удалить задачу", callback_data="delete_todo")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_archive_keyboard():
    """Клавиатура для архива"""
    keyboard = [
        [InlineKeyboardButton("📸 Архив фото", callback_data="archive_photos")],
        [InlineKeyboardButton("📄 Архив документов", callback_data="archive_docs")],
        [InlineKeyboardButton("🔍 Поиск в архиве", callback_data="search_archive")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_ai_keyboard():
    """Клавиатура для AI помощника"""
    keyboard = [
        [InlineKeyboardButton("💬 Задать вопрос", callback_data="ask_ai")],
        [InlineKeyboardButton("🔍 Поиск в истории", callback_data="search_history")],
        [InlineKeyboardButton("📊 Статистика", callback_data="show_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_quick_time_keyboard():
    """Быстрый выбор времени для напоминаний"""
    keyboard = [
        [
            InlineKeyboardButton("Через 1 час", callback_data="time_1h"),
            InlineKeyboardButton("Через 2 часа", callback_data="time_2h")
        ],
        [
            InlineKeyboardButton("Завтра 09:00", callback_data="time_tomorrow_9"),
            InlineKeyboardButton("Завтра 18:00", callback_data="time_tomorrow_18")
        ],
        [
            InlineKeyboardButton("Своё время", callback_data="time_custom"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# === УТИЛИТЫ ===
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

def speech_to_text(audio_file_path: str) -> str:
    """Преобразование голоса в текст"""
    try:
        recognizer = sr.Recognizer()
        
        # Конвертируем в WAV если нужно
        if audio_file_path.endswith('.ogg'):
            audio = AudioSegment.from_ogg(audio_file_path)
            wav_path = audio_file_path.replace('.ogg', '.wav')
            audio.export(wav_path, format='wav')
            audio_file_path = wav_path
        
        with sr.AudioFile(audio_file_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language='ru-RU')
            return text
            
    except Exception as e:
        logger.error(f"Error in speech recognition: {e}")
        return None

# === ОСНОВНЫЕ КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    welcome_text = (
        f"🤖 Привет, {user.first_name}!\n\n"
        "Я - умный помощник с удобным управлением!\n\n"
        "🎛️ **Управление:**\n"
        "• Используйте кнопки ниже для быстрого доступа\n"
        "• Отправляйте голосовые сообщения\n"
        "• Используйте команды или текстовый ввод\n\n"
        "💡 **Подсказка:** Нажмите '🎤 Голосовое сообщение' и скажите команду!"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard()
    )
    db.save_message(chat_id, user.id, user.username or user.first_name, "/start", False)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "🎛️ **Управление ботом:**\n\n"
        "📋 **Кнопки:**\n"
        "• Используйте кнопки для быстрого доступа\n"
        "• Каждая кнопка открывает меню с действиями\n\n"
        "🎤 **Голосовые команды:**\n"
        "• 'Создай напоминание на завтра 10 утра'\n"
        "• 'Добавь задачу купить продукты'\n"
        "• 'Покажи мои задачи'\n"
        "• 'Спроси у AI о погоде'\n\n"
        "💬 **Текстовые команды:**\n"
        "• `/remind 18:30 Позвонить` - напоминание\n"
        "• `/todo Задача` - добавить задачу\n"
        "• `/bot вопрос` - спросить AI\n"
        "• Просто напишите сообщение боту\n\n"
        "📁 **Отправка файлов:**\n"
        "• Фото и документы автоматически сохраняются"
    )
    
    await update.message.reply_text(
        help_text,
        reply_markup=get_main_keyboard()
    )

# === ОБРАБОТЧИКИ КНОПОК ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    if query.data == "main_menu":
        await query.edit_message_text(
            "🎛️ **Главное меню**\n\nВыберите раздел:",
            reply_markup=get_main_keyboard()
        )
    
    elif query.data == "create_reminder":
        await query.edit_message_text(
            "📅 **Создание напоминания**\n\n"
            "Выберите время быстрого доступа или введите своё:\n"
            "Формат: `18:30` или `2024-12-25 10:00`",
            reply_markup=get_quick_time_keyboard()
        )
    
    elif query.data.startswith("time_"):
        time_mapping = {
            "time_1h": ("через 1 час", timedelta(hours=1)),
            "time_2h": ("через 2 часа", timedelta(hours=2)),
            "time_tomorrow_9": ("завтра 09:00", None),
            "time_tomorrow_18": ("завтра 18:00", None)
        }
        
        if query.data in time_mapping:
            time_text, delta = time_mapping[query.data]
            context.user_data['reminder_time'] = time_text
            
            if query.data == "time_custom":
                await query.edit_message_text(
                    "⏰ Введите время в формате:\n"
                    "• `18:30` - сегодня в 18:30\n"
                    "• `2024-12-25 10:00` - конкретная дата\n"
                    "• `через 2 часа` - через 2 часа\n"
                    "• `завтра 09:00` - завтра в 9 утра"
                )
            else:
                await query.edit_message_text(
                    f"⏰ Время: {time_text}\n\n"
                    "📝 Теперь введите текст напоминания:"
                )
                return REMINDER_TEXT
    
    elif query.data == "list_reminders":
        reminders = db.get_active_reminders(chat_id)
        
        if not reminders:
            await query.edit_message_text(
                "📭 У вас нет активных напоминаний",
                reply_markup=get_reminders_keyboard()
            )
            return
        
        response = "🔔 **Ваши напоминания:**\n\n"
        for reminder in reminders:
            reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M:%S')
            response += (
                f"🆔 **{reminder['id']}**\n"
                f"📅 {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 {reminder['text']}\n\n"
            )
        
        await query.edit_message_text(
            response,
            reply_markup=get_reminders_keyboard()
        )
    
    elif query.data == "create_todo":
        await query.edit_message_text(
            "✅ **Добавление задачи**\n\nВведите текст задачи:"
        )
        return TODO_TEXT
    
    elif query.data == "list_todos":
        todos = db.get_todos(chat_id, completed=False)
        
        if not todos:
            await query.edit_message_text(
                "✅ У вас нет активных задач!",
                reply_markup=get_todos_keyboard()
            )
            return
        
        response = "✅ **Ваши задачи:**\n\n"
        for todo in todos:
            priority_emoji = "🔴" if todo['priority'] == 3 else "🟡" if todo['priority'] == 2 else "🟢"
            response += f"{priority_emoji} **{todo['id']}**. {todo['task_text']}"
            
            if todo['due_date']:
                due_date = datetime.strptime(todo['due_date'], '%Y-%m-%d %H:%M:%S')
                response += f" (до {due_date.strftime('%d.%m.%Y %H:%M')})"
            
            response += "\n"
        
        await query.edit_message_text(
            response,
            reply_markup=get_todos_keyboard()
        )
    
    elif query.data == "ask_ai":
        await query.edit_message_text(
            "🤖 **AI Помощник**\n\nЗадайте ваш вопрос:"
        )
        # Здесь можно добавить состояние для AI вопроса
    
    elif query.data == "show_stats":
        todos = db.get_todos(chat_id, completed=False)
        reminders = db.get_active_reminders(chat_id)
        archives = db.search_archives(chat_id)
        
        response = "📊 **Статистика:**\n\n"
        response += f"✅ Активных задач: {len(todos)}\n"
        response += f"🔔 Активных напоминаний: {len(reminders)}\n"
        response += f"📁 Файлов в архиве: {len(archives)}\n"
        
        await query.edit_message_text(
            response,
            reply_markup=get_ai_keyboard()
        )

# === ОБРАБОТЧИКИ СООБЩЕНИЙ С КНОПКАМИ ===
async def handle_main_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик основных кнопок"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    if text == "📅 Напоминания":
        await update.message.reply_text(
            "📅 **Управление напоминаниями**",
            reply_markup=get_reminders_keyboard()
        )
    
    elif text == "✅ Задачи":
        await update.message.reply_text(
            "✅ **Управление задачами**",
            reply_markup=get_todos_keyboard()
        )
    
    elif text == "📁 Архив":
        await update.message.reply_text(
            "📁 **Управление архивом**",
            reply_markup=get_archive_keyboard()
        )
    
    elif text == "🤖 AI Помощник":
        await update.message.reply_text(
            "🤖 **AI Помощник**",
            reply_markup=get_ai_keyboard()
        )
    
    elif text == "🎤 Голосовое сообщение":
        await update.message.reply_text(
            "🎤 **Голосовое управление**\n\n"
            "Отправьте голосовое сообщение с командой:\n"
            "• 'Создай напоминание на завтра 10 утра'\n"
            "• 'Добавь задачу купить продукты'\n"
            "• 'Покажи мои задачи'\n"
            "• 'Спроси у AI о погоде'"
        )
    
    elif text == "ℹ️ Помощь":
        await help_command(update, context)
    
    else:
        # Сохраняем сообщение и проверяем, нужно ли отвечать
        db.save_message(chat_id, update.effective_user.id, 
                       update.effective_user.username or update.effective_user.first_name, 
                       text, False)
        
        bot_username = context.bot.username
        if should_respond_to_message(text, bot_username):
            clean_query = extract_user_message(text, bot_username)
            if clean_query:
                await process_bot_request(update, context, chat_id, 
                                        update.effective_user.id,
                                        update.effective_user.username or update.effective_user.first_name,
                                        clean_query)

# === ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ ===
async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка голосовых сообщений"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    
    # Создаем папку для голосовых сообщений
    voice_dir = "voice_messages"
    os.makedirs(voice_dir, exist_ok=True)
    
    file_path = os.path.join(voice_dir, f"{voice.file_id}.ogg")
    await file.download_to_drive(file_path)
    
    await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...")
    
    # Преобразуем голос в текст
    text = speech_to_text(file_path)
    
    if text:
        await update.message.reply_text(f"📝 Распознано: _{text}_")
        
        # Сохраняем распознанный текст
        db.save_message(chat_id, user_id, username, f"[VOICE] {text}", False)
        
        # Обрабатываем команду из голосового сообщения
        await process_voice_command(update, context, chat_id, user_id, username, text)
    else:
        await update.message.reply_text("❌ Не удалось распознать голосовое сообщение")

async def process_voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               chat_id: int, user_id: int, username: str, text: str):
    """Обработка команд из голосовых сообщений"""
    text_lower = text.lower()
    
    # Напоминания
    if any(word in text_lower for word in ['напомни', 'напоминание', 'напомни']):
        if 'завтра' in text_lower:
            time_match = 'завтра'
            if '9' in text_lower or 'девять' in text_lower:
                time_match += ' 09:00'
            elif '10' in text_lower:
                time_match += ' 10:00'
            else:
                time_match += ' 18:00'
        else:
            time_match = '18:30'
        
        # Извлекаем текст напоминания
        reminder_text = text.replace('напомни', '').replace('создай напоминание', '').strip()
        
        reminder_time = parse_reminder_time(time_match)
        if reminder_time and reminder_text:
            reminder_id = db.create_reminder(chat_id, user_id, username, reminder_text, reminder_time)
            if reminder_id:
                await update.message.reply_text(
                    f"✅ Голосовое напоминание создано!\n\n"
                    f"📅 **Когда:** {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📝 **Текст:** {reminder_text}"
                )
    
    # Задачи
    elif any(word in text_lower for word in ['задача', 'добавь задачу', 'создай задачу']):
        task_text = text.replace('добавь задачу', '').replace('создай задачу', '').strip()
        if task_text:
            task_id = db.create_todo(chat_id, user_id, username, task_text)
            if task_id:
                await update.message.reply_text(f"✅ Голосовая задача добавлена: _{task_text}_")
    
    # Показать задачи
    elif any(word in text_lower for word in ['покажи задачи', 'мои задачи', 'список задач']):
        todos = db.get_todos(chat_id, completed=False)
        if todos:
            response = "✅ **Ваши задачи:**\n\n"
            for todo in todos[:5]:  # Ограничиваем вывод
                response += f"• {todo['task_text']}\n"
            await update.message.reply_text(response)
        else:
            await update.message.reply_text("✅ У вас нет активных задач!")
    
    # AI вопрос
    elif any(word in text_lower for word in ['спроси', 'расскажи', 'что ты думаешь']):
        question = text
        for word in ['спроси', 'расскажи', 'что ты думаешь о']:
            question = question.replace(word, '')
        question = question.strip()
        
        if question:
            await process_bot_request(update, context, chat_id, user_id, username, question)
    
    else:
        # Если не распознана команда, отправляем в AI
        await process_bot_request(update, context, chat_id, user_id, username, text)

# === СУЩЕСТВУЮЩИЕ ФУНКЦИИ (немного адаптированные) ===
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
        
        system_message = """Ты - умный помощник в чате Telegram с голосовым управлением и кнопками. Отвечай кратко и полезно."""
        
        if context:
            system_message += f"\n\nКонтекст чата:\n{context}"

        data = {
            "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
            "completionOptions": {
                "stream": False,
                "temperature": 0.7,
                "maxTokens": 1500
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
    
    # Добавляем кнопки для продолжения диалога
    keyboard = [
        [InlineKeyboardButton("💬 Еще вопрос", callback_data="ask_ai")],
        [InlineKeyboardButton("📋 Меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    sent_message = await update.message.reply_text(bot_response, reply_markup=reply_markup)
    db.save_message(chat_id, context.bot.id, context.bot.username, bot_response, True)

# === Conversation Handlers ===
async def reminder_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик текста напоминания"""
    reminder_text = update.message.text
    reminder_time = context.user_data.get('reminder_time')
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    reminder_time_obj = parse_reminder_time(reminder_time)
    
    if reminder_time_obj:
        reminder_id = db.create_reminder(chat_id, user_id, username, reminder_text, reminder_time_obj)
        
        if reminder_id:
            await update.message.reply_text(
                f"✅ Напоминание создано!\n\n"
                f"📅 **Когда:** {reminder_time_obj.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 **Текст:** {reminder_text}\n"
                f"🆔 **ID:** {reminder_id}",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при создании напоминания",
                reply_markup=get_main_keyboard()
            )
    else:
        await update.message.reply_text(
            "❌ Неверный формат времени",
            reply_markup=get_main_keyboard()
        )
    
    return ConversationHandler.END

async def todo_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик текста задачи"""
    task_text = update.message.text
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    task_id = db.create_todo(chat_id, user_id, username, task_text)
    
    if task_id:
        await update.message.reply_text(
            f"✅ Задача добавлена!\n\n📝 **Задача:** {task_text}\n🆔 **ID:** {task_id}",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Ошибка при добавлении задачи",
            reply_markup=get_main_keyboard()
        )
    
    return ConversationHandler.END

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена диалога"""
    await update.message.reply_text(
        "❌ Операция отменена",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

# === ОБРАБОТЧИКИ ФАЙЛОВ (остаются без изменений) ===
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка документов"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    document = update.message.document
    file = await context.bot.get_file(document.file_id)
    
    archive_dir = "archives"
    os.makedirs(archive_dir, exist_ok=True)
    
    file_path = os.path.join(archive_dir, document.file_name)
    await file.download_to_drive(file_path)
    
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
        
        await update.message.reply_text(response, reply_markup=get_main_keyboard())
    else:
        await update.message.reply_text("❌ Ошибка при сохранении документа", reply_markup=get_main_keyboard())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    archive_dir = "archives"
    os.makedirs(archive_dir, exist_ok=True)
    
    file_name = f"photo_{photo.file_id}.jpg"
    file_path = os.path.join(archive_dir, file_name)
    await file.download_to_drive(file_path)
    
    archive_id = db.save_to_archive(
        chat_id, user_id, username,
        file_name, 'photo', file_path,
        "", "", photo.file_size
    )
    
    if archive_id:
        response = f"📸 Фото сохранено в архив!\n\n🆔 **ID:** {archive_id}"
        await update.message.reply_text(response, reply_markup=get_main_keyboard())
    else:
        await update.message.reply_text("❌ Ошибка при сохранении фото", reply_markup=get_main_keyboard())

# === ФУНКЦИИ ДЛЯ НАПОМИНАНИЙ ===
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

def reminder_worker(context: CallbackContext):
    """Фоновая задача для проверки напоминаний"""
    import asyncio
    asyncio.create_task(check_reminders(context))

def main():
    """Основная функция"""
    try:
        logger.info("Starting bot with buttons and voice control...")
        
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Conversation Handlers
        reminder_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^time_")],
            states={
                REMINDER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_text_handler)],
            },
            fallbacks=[CommandHandler('cancel', cancel_handler)]
        )
        
        todo_conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern="^create_todo$")],
            states={
                TODO_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, todo_text_handler)],
            },
            fallbacks=[CommandHandler('cancel', cancel_handler)]
        )
        
        # Основные команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        
        # Conversation handlers
        application.add_handler(reminder_conv_handler)
        application.add_handler(todo_conv_handler)
        
        # Обработчики кнопок
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_buttons))
        
        # Обработчики голосовых сообщений
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        
        # Обработчики файлов
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        # Настройка планировщика для напоминаний
        job_queue = application.job_queue
        job_queue.run_repeating(reminder_worker, interval=60, first=10)
        
        logger.info("Bot started successfully with buttons and voice control!")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise

if __name__ == '__main__':
    main()