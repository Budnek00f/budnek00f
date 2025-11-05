import os
import sqlite3
import datetime
from contextlib import contextmanager
from config import DATABASE_URL

class Database:
    def __init__(self):
        self.db_url = DATABASE_URL
        self.is_postgres = self.db_url.startswith('postgresql://')
        self.init_database()
    
    def get_connection(self):
        if self.is_postgres:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            conn = psycopg2.connect(self.db_url)
            conn.autocommit = False
            return conn
        else:
            # Для SQLite создаем директорию data если её нет
            db_path = self.db_url.replace('sqlite:///', '')
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn
    
    @contextmanager
    def get_cursor(self):
        conn = self.get_connection()
        try:
            if self.is_postgres:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def init_database(self):
        try:
            with self.get_cursor() as cursor:
                if self.is_postgres:
                    # PostgreSQL таблицы
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            user_id BIGINT PRIMARY KEY,
                            username TEXT,
                            first_name TEXT,
                            last_name TEXT,
                            subscription_end DATE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS payments (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            amount REAL,
                            payment_id TEXT,
                            status TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS reminders (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            text TEXT,
                            due_date TIMESTAMP,
                            completed BOOLEAN DEFAULT FALSE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS finances (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            amount REAL,
                            category TEXT,
                            description TEXT,
                            type TEXT CHECK(type IN ('income', 'expense')),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS chat_logs (
                            id SERIAL PRIMARY KEY,
                            user_id BIGINT,
                            chat_id BIGINT,
                            message TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                else:
                    # SQLite таблицы
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            user_id INTEGER PRIMARY KEY,
                            username TEXT,
                            first_name TEXT,
                            last_name TEXT,
                            subscription_end DATE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS payments (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            amount REAL,
                            payment_id TEXT,
                            status TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS reminders (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            text TEXT,
                            due_date TIMESTAMP,
                            completed BOOLEAN DEFAULT FALSE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS finances (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            amount REAL,
                            category TEXT,
                            description TEXT,
                            type TEXT CHECK(type IN ('income', 'expense')),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS chat_logs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER,
                            chat_id INTEGER,
                            message TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
        except Exception as e:
            print(f"Database initialization error: {e}")
            raise
    
    def add_user(self, user_id, username, first_name, last_name):
        try:
            with self.get_cursor() as cursor:
                if self.is_postgres:
                    cursor.execute('''
                        INSERT INTO users (user_id, username, first_name, last_name)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id) DO NOTHING
                    ''', (user_id, username, first_name, last_name))
                else:
                    cursor.execute('''
                        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, username, first_name, last_name))
        except Exception as e:
            print(f"Error adding user: {e}")
    
    def update_subscription(self, user_id, months=1):
        try:
            with self.get_cursor() as cursor:
                if self.is_postgres:
                    cursor.execute('SELECT subscription_end FROM users WHERE user_id = %s', (user_id,))
                else:
                    cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
                
                result = cursor.fetchone()
                
                if result and result['subscription_end']:
                    current_end = result['subscription_end']
                    if isinstance(current_end, str):
                        current_end = datetime.datetime.strptime(current_end, '%Y-%m-%d')
                    new_end = current_end + datetime.timedelta(days=30*months)
                else:
                    new_end = datetime.datetime.now() + datetime.timedelta(days=30*months)
                
                if self.is_postgres:
                    cursor.execute('''
                        UPDATE users SET subscription_end = %s WHERE user_id = %s
                    ''', (new_end, user_id))
                else:
                    cursor.execute('''
                        UPDATE users SET subscription_end = ? WHERE user_id = ?
                    ''', (new_end.strftime('%Y-%m-%d'), user_id))
        except Exception as e:
            print(f"Error updating subscription: {e}")
    
    def check_subscription(self, user_id):
        if user_id == int(os.getenv('ADMIN_ID', 86458589)):
            return True
            
        try:
            with self.get_cursor() as cursor:
                if self.is_postgres:
                    cursor.execute('SELECT subscription_end FROM users WHERE user_id = %s', (user_id,))
                else:
                    cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
                
                result = cursor.fetchone()
                
                if not result or not result['subscription_end']:
                    return False
                
                subscription_end = result['subscription_end']
                if isinstance(subscription_end, str):
                    subscription_end = datetime.datetime.strptime(subscription_end, '%Y-%m-%d')
                
                return subscription_end > datetime.datetime.now()
        except Exception as e:
            print(f"Error checking subscription: {e}")
            return False