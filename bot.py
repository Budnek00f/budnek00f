import logging
import os
import requests
import sqlite3
import json
import speech_recognition as sr
from pydub import AudioSegment
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

# Инициализация базы данных
db = ChatDatabase()

YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# === НОВАЯ СИСТЕМА КНОПОК ===
def get_main_menu():
    """Главное меню с большими кнопками"""
    keyboard = [
        [InlineKeyboardButton("📅 НАПОМИНАНИЯ", callback_data="menu_reminders")],
        [InlineKeyboardButton("✅ ЗАДАЧИ", callback_data="menu_todos")],
        [InlineKeyboardButton("📁 АРХИВ", callback_data="menu_archive")],
        [InlineKeyboardButton("🤖 AI ПОМОЩНИК", callback_data="menu_ai")],
        [InlineKeyboardButton("🎤 ГОЛОСОВОЕ УПРАВЛЕНИЕ", callback_data="menu_voice")],
        [InlineKeyboardButton("ℹ️ ПОМОЩЬ", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_reminders_menu():
    """Меню напоминаний"""
    keyboard = [
        [InlineKeyboardButton("➕ СОЗДАТЬ НАПОМИНАНИЕ", callback_data="reminder_create")],
        [InlineKeyboardButton("📋 МОИ НАПОМИНАНИЯ", callback_data="reminder_list")],
        [InlineKeyboardButton("🔙 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_todos_menu():
    """Меню задач"""
    keyboard = [
        [InlineKeyboardButton("➕ ДОБАВИТЬ ЗАДАЧУ", callback_data="todo_create")],
        [InlineKeyboardButton("📋 АКТИВНЫЕ ЗАДАЧИ", callback_data="todo_list")],
        [InlineKeyboardButton("✅ ВЫПОЛНЕННЫЕ ЗАДАЧИ", callback_data="todo_list_done")],
        [InlineKeyboardButton("🔙 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_archive_menu():
    """Меню архива"""
    keyboard = [
        [InlineKeyboardButton("📸 АРХИВ ФОТО", callback_data="archive_photos")],
        [InlineKeyboardButton("📄 АРХИВ ДОКУМЕНТОВ", callback_data="archive_docs")],
        [InlineKeyboardButton("🔍 ПОИСК В АРХИВЕ", callback_data="archive_search")],
        [InlineKeyboardButton("🔙 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_ai_menu():
    """Меню AI помощника"""
    keyboard = [
        [InlineKeyboardButton("💬 ЗАДАТЬ ВОПРОС", callback_data="ai_ask")],
        [InlineKeyboardButton("🔍 ПОИСК В ИСТОРИИ", callback_data="ai_search")],
        [InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="ai_stats")],
        [InlineKeyboardButton("🔙 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_time_menu():
    """Меню выбора времени"""
    keyboard = [
        [InlineKeyboardButton("⏰ ЧЕРЕЗ 1 ЧАС", callback_data="time_1h")],
        [InlineKeyboardButton("⏰ ЧЕРЕЗ 2 ЧАСА", callback_data="time_2h")],
        [InlineKeyboardButton("🌅 ЗАВТРА 09:00", callback_data="time_tomorrow_9")],
        [InlineKeyboardButton("🌇 ЗАВТРА 18:00", callback_data="time_tomorrow_18")],
        [InlineKeyboardButton("✏️ СВОЁ ВРЕМЯ", callback_data="time_custom")],
        [InlineKeyboardButton("❌ ОТМЕНА", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    """Простая кнопка назад"""
    keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_main")]]
    return InlineKeyboardMarkup(keyboard)

# === УТИЛИТЫ ===
def parse_reminder_time(time_str: str) -> datetime:
    """Парсинг времени для напоминаний"""
    try:
        time_str = time_str.lower().strip()
        now = datetime.now()
        
        if time_str == "через 1 час":
            return now + timedelta(hours=1)
        elif time_str == "через 2 часа":
            return now + timedelta(hours=2)
        elif time_str == "завтра 09:00":
            return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        elif time_str == "завтра 18:00":
            return (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        
        # Обработка пользовательского ввода
        if ':' in time_str:
            if len(time_str) == 5:  # 18:30
                time_obj = datetime.strptime(time_str, '%H:%M')
                reminder_time = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
                if reminder_time < now:
                    reminder_time += timedelta(days=1)
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
        if audio_file_path.endswith('.oga'):
            audio = AudioSegment.from_ogg(audio_file_path)
            wav_path = audio_file_path.replace('.oga', '.wav')
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
        f"🎉 **Добро пожаловать, {user.first_name}!**\n\n"
        "Я - ваш умный помощник с удобным управлением!\n\n"
        "✨ **Что я умею:**\n"
        "• Создавать напоминания\n"
        "• Вести список задач\n"
        "• Архивировать файлы\n"
        "• Отвечать на вопросы\n"
        "• Распознавать голос\n\n"
        "👇 **Выберите действие:**"
    )
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu()
    )
    db.save_message(chat_id, user.id, user.username or user.first_name, "/start", False)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать главное меню"""
    text = "🎛️ **ГЛАВНОЕ МЕНЮ**\n\n👇 Выберите раздел:"
    
    if hasattr(update, 'callback_query'):
        await update.callback_query.edit_message_text(text, reply_markup=get_main_menu())
    else:
        await update.message.reply_text(text, reply_markup=get_main_menu())

# === ОБРАБОТЧИК КНОПОК ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    logger.info(f"Button pressed: {data} by user {user_id}")
    
    # Главное меню
    if data == "menu_main":
        await show_main_menu(update, context)
        return
    
    # Разделы главного меню
    elif data == "menu_reminders":
        await query.edit_message_text(
            "📅 **УПРАВЛЕНИЕ НАПОМИНАНИЯМИ**\n\n👇 Выберите действие:",
            reply_markup=get_reminders_menu()
        )
    
    elif data == "menu_todos":
        await query.edit_message_text(
            "✅ **УПРАВЛЕНИЕ ЗАДАЧАМИ**\n\n👇 Выберите действие:",
            reply_markup=get_todos_menu()
        )
    
    elif data == "menu_archive":
        await query.edit_message_text(
            "📁 **УПРАВЛЕНИЕ АРХИВОМ**\n\n👇 Выберите действие:",
            reply_markup=get_archive_menu()
        )
    
    elif data == "menu_ai":
        await query.edit_message_text(
            "🤖 **AI ПОМОЩНИК**\n\n👇 Выберите действие:",
            reply_markup=get_ai_menu()
        )
    
    elif data == "menu_voice":
        await query.edit_message_text(
            "🎤 **ГОЛОСОВОЕ УПРАВЛЕНИЕ**\n\n"
            "Просто отправьте голосовое сообщение с командой:\n\n"
            "🎯 **Примеры команд:**\n"
            "• _«Создай напоминание на завтра 10 утра»_\n"
            "• _«Добавь задачу купить продукты»_\n"
            "• _«Покажи мои задачи»_\n"
            "• _«Спроси у AI о погоде»_\n\n"
            "Я распознаю речь и выполню команду!",
            reply_markup=get_back_button()
        )
    
    elif data == "menu_help":
        await query.edit_message_text(
            "ℹ️ **ПОМОЩЬ**\n\n"
            "🎛️ **Управление:**\n"
            "• Используйте кнопки для навигации\n"
            "• Кнопки автоматически исчезают после нажатия\n"
            "• Всегда можно вернуться в главное меню\n\n"
            "🎤 **Голосовые команды:**\n"
            "• Отправляйте голосовые сообщения\n"
            "• Говорите естественно, как человеку\n"
            "• Я пойму большинство команд\n\n"
            "💬 **Текстовые команды:**\n"
            "• `/start` - перезапуск бота\n"
            "• `/help` - показать справку\n"
            "• Просто напишите вопрос - я отвечу",
            reply_markup=get_back_button()
        )
    
    # Напоминания
    elif data == "reminder_create":
        await query.edit_message_text(
            "⏰ **СОЗДАНИЕ НАПОМИНАНИЯ**\n\n👇 Выберите время:",
            reply_markup=get_time_menu()
        )
    
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
                f"⏰ **Время установлено:** {time_mapping[data]}\n\n"
                "📝 **Теперь введите текст напоминания:**\n"
                "(Например: _Позвонить маме_)"
            )
        
        elif data == "time_custom":
            await query.edit_message_text(
                "⏰ **ВВЕДИТЕ ВРЕМЯ**\n\n"
                "📋 **Формат:** ЧЧ:ММ\n"
                "🎯 **Примеры:**\n"
                "• `18:30` - сегодня в 18:30\n"
                "• `09:00` - завтра в 9 утра\n\n"
                "👇 Введите время:"
            )
    
    elif data == "reminder_list":
        reminders = db.get_active_reminders(chat_id)
        
        if not reminders:
            await query.edit_message_text(
                "📭 **У вас нет активных напоминаний**\n\n"
                "Чтобы создать напоминание, нажмите кнопку ниже:",
                reply_markup=get_reminders_menu()
            )
            return
        
        response = "🔔 **ВАШИ НАПОМИНАНИЯ:**\n\n"
        for reminder in reminders:
            reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M:%S')
            response += (
                f"🆔 **{reminder['id']}**\n"
                f"📅 {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"📝 {reminder['text']}\n\n"
            )
        
        await query.edit_message_text(
            response,
            reply_markup=get_reminders_menu()
        )
    
    # Задачи
    elif data == "todo_create":
        await query.edit_message_text(
            "✅ **ДОБАВЛЕНИЕ ЗАДАЧИ**\n\n"
            "📝 **Введите текст задачи:**\n"
            "(Например: _Купить продукты_)"
        )
    
    elif data == "todo_list":
        todos = db.get_todos(chat_id, completed=False)
        
        if not todos:
            await query.edit_message_text(
                "🎉 **У вас нет активных задач!**\n\n"
                "Чтобы добавить задачу, нажмите кнопку ниже:",
                reply_markup=get_todos_menu()
            )
            return
        
        response = "✅ **ВАШИ ЗАДАЧИ:**\n\n"
        for todo in todos:
            priority_emoji = "🔴" if todo['priority'] == 3 else "🟡" if todo['priority'] == 2 else "🟢"
            response += f"{priority_emoji} **{todo['id']}**. {todo['task_text']}"
            
            if todo['due_date']:
                due_date = datetime.strptime(todo['due_date'], '%Y-%m-%d %H:%M:%S')
                response += f" (до {due_date.strftime('%d.%m.%Y %H:%M')})"
            
            response += "\n"
        
        await query.edit_message_text(
            response,
            reply_markup=get_todos_menu()
        )
    
    # AI помощник
    elif data == "ai_ask":
        await query.edit_message_text(
            "🤖 **AI ПОМОЩНИК**\n\n"
            "💬 **Задайте ваш вопрос:**\n"
            "(Я отвечу на основе контекста нашего разговора)"
        )
    
    elif data == "ai_stats":
        todos = db.get_todos(chat_id, completed=False)
        reminders = db.get_active_reminders(chat_id)
        archives = db.search_archives(chat_id) if hasattr(db, 'search_archives') else []
        
        response = "📊 **СТАТИСТИКА:**\n\n"
        response += f"✅ Активных задач: {len(todos)}\n"
        response += f"🔔 Активных напоминаний: {len(reminders)}\n"
        response += f"📁 Файлов в архиве: {len(archives)}\n"
        
        await query.edit_message_text(
            response,
            reply_markup=get_ai_menu()
        )

# === ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ===
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    message_text = update.message.text
    
    # Сохраняем сообщение
    db.save_message(chat_id, user_id, username, message_text, False)
    
    # Проверяем, есть ли ожидание ввода
    if 'reminder_time' in context.user_data:
        # Создаем напоминание
        reminder_time_str = context.user_data['reminder_time']
        reminder_time = parse_reminder_time(reminder_time_str)
        
        if reminder_time:
            reminder_id = db.create_reminder(chat_id, user_id, username, message_text, reminder_time)
            
            if reminder_id:
                await update.message.reply_text(
                    f"✅ **НАПОМИНАНИЕ СОЗДАНО!**\n\n"
                    f"📅 **Когда:** {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📝 **Текст:** {message_text}\n\n"
                    "Кнопки автоматически обновятся...",
                    reply_markup=get_main_menu()
                )
            else:
                await update.message.reply_text(
                    "❌ Ошибка при создании напоминания",
                    reply_markup=get_main_menu()
                )
        else:
            await update.message.reply_text(
                "❌ Неверный формат времени",
                reply_markup=get_main_menu()
            )
        
        # Очищаем временные данные
        context.user_data.clear()
        return
    
    elif 'waiting_for_todo' in context.user_data:
        # Создаем задачу
        task_id = db.create_todo(chat_id, user_id, username, message_text)
        
        if task_id:
            await update.message.reply_text(
                f"✅ **ЗАДАЧА ДОБАВЛЕНА!**\n\n"
                f"📝 **Задача:** {message_text}\n\n"
                "Кнопки автоматически обновятся...",
                reply_markup=get_main_menu()
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка при добавлении задачи",
                reply_markup=get_main_menu()
            )
        
        # Очищаем временные данные
        context.user_data.clear()
        return
    
    elif 'waiting_for_time' in context.user_data:
        # Обработка пользовательского времени
        reminder_time = parse_reminder_time(message_text)
        
        if reminder_time:
            context.user_data['reminder_time'] = message_text
            context.user_data.pop('waiting_for_time', None)
            
            await update.message.reply_text(
                f"⏰ **Время установлено:** {message_text}\n\n"
                "📝 **Теперь введите текст напоминания:**",
                reply_markup=get_back_button()
            )
        else:
            await update.message.reply_text(
                "❌ Неверный формат времени. Попробуйте снова (ЧЧ:ММ):",
                reply_markup=get_back_button()
            )
        return
    
    # Обычный AI запрос
    bot_username = context.bot.username
    should_respond = any(trigger in message_text.lower() for trigger in ['/bot', 'бот']) or (bot_username and f"@{bot_username}" in message_text)
    
    if should_respond:
        clean_query = message_text
        for trigger in ['/bot', 'бот']:
            clean_query = clean_query.replace(trigger, '')
        if bot_username:
            clean_query = clean_query.replace(f"@{bot_username}", '')
        clean_query = clean_query.strip()
        
        if clean_query:
            await process_bot_request(update, context, chat_id, user_id, username, clean_query)
    else:
        # Показываем главное меню для любого текста
        await update.message.reply_text(
            "👇 **Выберите действие:**",
            reply_markup=get_main_menu()
        )

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
    
    file_path = os.path.join(voice_dir, f"{voice.file_id}.oga")
    await file.download_to_drive(file_path)
    
    await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...")
    
    try:
        # Преобразуем голос в текст
        text = speech_to_text(file_path)
        
        if text:
            await update.message.reply_text(f"📝 **Распознано:** _{text}_")
            
            # Сохраняем распознанный текст
            db.save_message(chat_id, user_id, username, f"[VOICE] {text}", False)
            
            # Обрабатываем команду из голосового сообщения
            await process_voice_command(update, context, chat_id, user_id, username, text)
        else:
            await update.message.reply_text(
                "❌ Не удалось распознать голосовое сообщение",
                reply_markup=get_main_menu()
            )
    
    except Exception as e:
        logger.error(f"Error processing voice message: {e}")
        await update.message.reply_text(
            "❌ Ошибка при обработке голосового сообщения",
            reply_markup=get_main_menu()
        )

async def process_voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               chat_id: int, user_id: int, username: str, text: str):
    """Обработка команд из голосовых сообщений"""
    text_lower = text.lower()
    
    # Напоминания
    if any(word in text_lower for word in ['напомни', 'напоминание']):
        time_match = "18:30"  # значение по умолчанию
        if 'завтра' in text_lower and '10' in text_lower:
            time_match = "завтра 09:00"
        elif 'завтра' in text_lower:
            time_match = "завтра 18:00"
        elif 'час' in text_lower:
            time_match = "через 1 час"
        
        # Извлекаем текст напоминания
        reminder_text = text
        for word in ['напомни', 'создай напоминание', 'напоминание']:
            reminder_text = reminder_text.replace(word, '')
        reminder_text = reminder_text.strip()
        
        reminder_time = parse_reminder_time(time_match)
        if reminder_time and reminder_text:
            reminder_id = db.create_reminder(chat_id, user_id, username, reminder_text, reminder_time)
            if reminder_id:
                await update.message.reply_text(
                    f"✅ **ГОЛОСОВОЕ НАПОМИНАНИЕ СОЗДАНО!**\n\n"
                    f"📅 **Когда:** {reminder_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📝 **Текст:** {reminder_text}",
                    reply_markup=get_main_menu()
                )
    
    # Задачи
    elif any(word in text_lower for word in ['задача', 'добавь задачу', 'создай задачу']):
        task_text = text
        for word in ['добавь задачу', 'создай задачу']:
            task_text = task_text.replace(word, '')
        task_text = task_text.strip()
        
        if task_text:
            task_id = db.create_todo(chat_id, user_id, username, task_text)
            if task_id:
                await update.message.reply_text(
                    f"✅ **ГОЛОСОВАЯ ЗАДАЧА ДОБАВЛЕНА:** _{task_text}_",
                    reply_markup=get_main_menu()
                )
    
    # Показать задачи
    elif any(word in text_lower for word in ['покажи задачи', 'мои задачи', 'список задач']):
        todos = db.get_todos(chat_id, completed=False)
        if todos:
            response = "✅ **ВАШИ ЗАДАЧИ:**\n\n"
            for todo in todos[:5]:
                response += f"• {todo['task_text']}\n"
            await update.message.reply_text(response, reply_markup=get_main_menu())
        else:
            await update.message.reply_text(
                "✅ У вас нет активных задач!",
                reply_markup=get_main_menu()
            )
    
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

# === AI ФУНКЦИОНАЛ ===
def get_yandex_gpt_response(prompt: str, context: str = "") -> str:
    """Получение ответа от YandexGPT с контекстом"""
    try:
        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "Content-Type": "application/json"
        }
        
        system_message = "Ты - умный помощник в чате Telegram. Отвечай кратко и полезно."
        
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
    
    bot_response = get_yandex_gpt_response(user_message)
    
    # Создаем клавиатуру для ответа
    keyboard = [
        [InlineKeyboardButton("💬 Еще вопрос", callback_data="ai_ask")],
        [InlineKeyboardButton("📋 Главное меню", callback_data="menu_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'message'):
        sent_message = await update.message.reply_text(bot_response, reply_markup=reply_markup)
    else:
        sent_message = await update.callback_query.message.reply_text(bot_response, reply_markup=reply_markup)
    
    db.save_message(chat_id, context.bot.id, context.bot.username, bot_response, True)

# === ФУНКЦИИ ДЛЯ НАПОМИНАНИЙ ===
async def check_reminders(context: CallbackContext):
    """Проверка и отправка напоминаний"""
    try:
        reminders = db.get_active_reminders()
        
        for reminder in reminders:
            reminder_time = datetime.strptime(reminder['time'], '%Y-%m-%d %H:%M:%S')
            
            if reminder_time <= datetime.now():
                message = f"🔔 **НАПОМИНАНИЕ**\n\n{reminder['text']}"
                
                await context.bot.send_message(
                    chat_id=reminder['chat_id'],
                    text=message
                )
                
                db.complete_reminder(reminder['id'])
                logger.info(f"Sent reminder: {reminder['id']}")
                
    except Exception as e:
        logger.error(f"Error checking reminders: {e}")

async def reminder_worker(context: CallbackContext):
    """Фоновая задача для проверки напоминаний"""
    await check_reminders(context)

# === ОБРАБОТЧИКИ ФАЙЛОВ ===
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
            text_content = "Не удалось прочитать файл"
    
    archive_id = db.save_to_archive(
        chat_id, user_id, username,
        document.file_name, 'document', file_path,
        text_content, "", document.file_size
    )
    
    if archive_id:
        response = f"📄 **ДОКУМЕНТ СОХРАНЕН В АРХИВ!**\n\n📁 **Файл:** {document.file_name}"
        await update.message.reply_text(response, reply_markup=get_main_menu())
    else:
        await update.message.reply_text(
            "❌ Ошибка при сохранении документа",
            reply_markup=get_main_menu()
        )

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
        response = f"📸 **ФОТО СОХРАНЕНО В АРХИВ!**\n\n🆔 **ID:** {archive_id}"
        await update.message.reply_text(response, reply_markup=get_main_menu())
    else:
        await update.message.reply_text(
            "❌ Ошибка при сохранении фото",
            reply_markup=get_main_menu()
        )

# === ОБРАБОТЧИК ОШИБОК ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Error: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже.",
            reply_markup=get_main_menu()
        )

def main():
    """Основная функция"""
    try:
        logger.info("Starting bot with new navigation system...")
        
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", show_main_menu))
        
        # Обработчик кнопок
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Настройка планировщика для напоминаний
        job_queue = application.job_queue
        job_queue.run_repeating(reminder_worker, interval=60, first=10)
        
        logger.info("Bot started successfully with new navigation!")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise

if __name__ == '__main__':
    main()