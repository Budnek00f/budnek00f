import logging
import os
import requests
import sqlite3
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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
                CREATE TABLE IF NOT EXISTS chat_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE NOT NULL,
                    last_topics TEXT,
                    key_entities TEXT,
                    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
                    summary TEXT
                )
            ''')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_messages_timestamp ON chat_messages(timestamp)')
            
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
            
            cursor.execute('''
                INSERT OR REPLACE INTO chat_context 
                (chat_id, last_activity) 
                VALUES (?, CURRENT_TIMESTAMP)
            ''', (chat_id,))
            
            conn.commit()
            message_id = cursor.lastrowid
            conn.close()
            
            logger.debug(f"Message saved: chat_id={chat_id}, user_id={user_id}")
            return message_id
            
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return None

    def get_chat_history(self, chat_id: int, limit: int = 50) -> list:
        """Получение истории чата"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT username, message_text, timestamp, is_bot_message
                FROM chat_messages 
                WHERE chat_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (chat_id, limit))
            
            messages = []
            for row in cursor.fetchall():
                messages.append({
                    'username': row[0],
                    'text': row[1],
                    'timestamp': row[2],
                    'is_bot': bool(row[3])
                })
            
            conn.close()
            return list(reversed(messages))
            
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []

    def search_messages(self, chat_id: int, query: str, limit: int = 10) -> list:
        """Поиск сообщений по ключевым словам"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT username, message_text, timestamp
                FROM chat_messages 
                WHERE chat_id = ? AND message_text LIKE ?
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (chat_id, f'%{query}%', limit))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'username': row[0],
                    'text': row[1],
                    'timestamp': row[2]
                })
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error searching messages: {e}")
            return []

    def get_chat_summary(self, chat_id: int) -> dict:
        """Получение сводки по чату"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_messages,
                    COUNT(DISTINCT user_id) as unique_users,
                    MIN(timestamp) as first_message,
                    MAX(timestamp) as last_message
                FROM chat_messages 
                WHERE chat_id = ?
            ''', (chat_id,))
            
            stats = cursor.fetchone()
            
            cursor.execute('''
                SELECT username, COUNT(*) as message_count
                FROM chat_messages 
                WHERE chat_id = ?
                GROUP BY username 
                ORDER BY message_count DESC 
                LIMIT 5
            ''', (chat_id,))
            
            top_users = [{'username': row[0], 'count': row[1]} for row in cursor.fetchall()]
            
            conn.close()
            
            return {
                'total_messages': stats[0] if stats else 0,
                'unique_users': stats[1] if stats else 0,
                'first_message': stats[2] if stats else None,
                'last_message': stats[3] if stats else None,
                'top_users': top_users,
                'top_keywords': []
            }
            
        except Exception as e:
            logger.error(f"Error getting chat summary: {e}")
            return {}

    def clear_chat_history(self, chat_id: int):
        """Очистка истории чата"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM chat_messages WHERE chat_id = ?', (chat_id,))
            cursor.execute('DELETE FROM chat_context WHERE chat_id = ?', (chat_id,))
            
            conn.commit()
            conn.close()
            logger.info(f"Cleared history for chat {chat_id}")
            
        except Exception as e:
            logger.error(f"Error clearing chat history: {e}")

# Инициализация базы данных
db = ChatDatabase()

YANDEX_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

# Триггеры для обращения к боту
BOT_TRIGGERS = ['/bot', 'бот', '@bot']

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    welcome_text = (
        f"🤖 Привет, {user.first_name}!\n\n"
        "Я - умный помощник с памятью! Я запоминаю всё, что происходит в чате.\n\n"
        "**Как со мной общаться:**\n"
        "• Напиши `/bot [вопрос]` - для обращения ко мне\n"
        "• Или просто начни сообщение с «бот» или упомяни меня\n"
        "• Я помню контекст предыдущих сообщений\n\n"
        "**Другие команды:**\n"
        "/help - показать справку\n"
        "/search <запрос> - поиск в истории чата\n"
        "/summary - статистика чата\n"
        "/clear - очистить историю (только для админов)"
    )
    
    await update.message.reply_text(welcome_text)
    db.save_message(chat_id, user.id, user.username or user.first_name, "/start", False)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "💡 **Как использовать бота:**\n\n"
        "**Обращение к боту:**\n"
        "• `/bot [ваш вопрос]` - основной способ обращения\n"
        "• `бот [ваш вопрос]` - можно без слеша\n"
        "• Ответ на сообщение бота с `@bot`\n\n"
        "**Особенности:**\n"
        "• Я запоминаю весь контекст чата\n"
        "• При ответе учитываю предыдущие сообщения\n"
        "• Отвечаю только на прямые обращения\n\n"
        "**Команды управления:**\n"
        "/search <запрос> - поиск в истории\n"
        "/summary - статистика чата\n"
        "/clear - очистить историю (админы)\n\n"
        "**Примеры:**\n"
        "`/bot привет!`\n"
        "`бот какая погода?`\n"
        "`@bot помоги с проектом`"
    )
    
    await update.message.reply_text(help_text)
    db.save_message(update.effective_chat.id, update.effective_user.id, 
                   update.effective_user.username or update.effective_user.first_name, 
                   "/help", False)

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
    db.save_message(chat_id, user_id, update.effective_user.username or update.effective_user.first_name, 
                   f"/search {query}", False)

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика чата"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    summary = db.get_chat_summary(chat_id)
    
    if not summary or summary['total_messages'] == 0:
        await update.message.reply_text("📊 В этом чате пока нет сообщений для анализа.")
        return
    
    response = "📊 **Статистика чата:**\n\n"
    response += f"• Всего сообщений: {summary['total_messages']}\n"
    response += f"• Участников: {summary['unique_users']}\n"
    response += f"• Первое сообщение: {summary['first_message'][:10]}\n"
    response += f"• Последнее сообщение: {summary['last_message'][:16]}\n\n"
    
    if summary['top_users']:
        response += "👥 **Самые активные пользователи:**\n"
        for user in summary['top_users'][:3]:
            response += f"• {user['username']} ({user['count']} сообщ.)\n"
    
    await update.message.reply_text(response)
    db.save_message(chat_id, user_id, update.effective_user.username or update.effective_user.first_name, 
                   "/summary", False)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистка истории чата (только для админов)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    chat_member = await context.bot.get_chat_member(chat_id, user_id)
    if chat_member.status not in ['creator', 'administrator']:
        await update.message.reply_text("❌ Эта команда доступна только администраторам чата.")
        return
    
    db.clear_chat_history(chat_id)
    await update.message.reply_text("✅ История чата очищена.")
    db.save_message(chat_id, user_id, update.effective_user.username or update.effective_user.first_name, 
                   "/clear", False)

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

def main():
    """Основная функция"""
    try:
        logger.info("Starting AI bot with context memory...")
        
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("bot", bot_command))
        application.add_handler(CommandHandler("search", search_command))
        application.add_handler(CommandHandler("summary", summary_command))
        application.add_handler(CommandHandler("clear", clear_command))
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        application.add_error_handler(error_handler)
        
        logger.info("Bot started successfully with context memory")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Critical error: {e}")
        raise

if __name__ == '__main__':
    main()