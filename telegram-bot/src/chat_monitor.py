from database import Database

class ChatMonitor:
    def __init__(self, db):
        self.db = db
    
    def log_message(self, user_id, chat_id, message):
        with self.db.get_cursor() as cursor:
            if self.db.is_postgres:
                cursor.execute('''
                    INSERT INTO chat_logs (user_id, chat_id, message)
                    VALUES (%s, %s, %s)
                ''', (user_id, chat_id, message))
            else:
                cursor.execute('''
                    INSERT INTO chat_logs (user_id, chat_id, message)
                    VALUES (?, ?, ?)
                ''', (user_id, chat_id, message))
    
    def analyze_chat_mood(self, user_id, limit=100):
        with self.db.get_cursor() as cursor:
            if self.db.is_postgres:
                cursor.execute('''
                    SELECT message FROM chat_logs 
                    WHERE user_id = %s 
                    ORDER BY created_at DESC 
                    LIMIT %s
                ''', (user_id, limit))
            else:
                cursor.execute('''
                    SELECT message FROM chat_logs 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT ?
                ''', (user_id, limit))
            
            messages = [row['message'] for row in cursor.fetchall()]
            
            # Простой анализ настроения по ключевым словам
            positive_words = ['отлично', 'хорошо', 'прекрасно', 'супер', 'спасибо', 'рад', 'доволен']
            negative_words = ['плохо', 'грустно', 'ужасно', 'злой', 'разочарован', 'обидно']
            
            positive_count = sum(1 for msg in messages for word in positive_words if word in msg.lower())
            negative_count = sum(1 for msg in messages for word in negative_words if word in msg.lower())
            
            if positive_count > negative_count:
                mood = "😊 Положительный"
            elif negative_count > positive_count:
                mood = "😔 Отрицательный"
            else:
                mood = "😐 Нейтральный"
            
            return {
                'total_messages': len(messages),
                'positive': positive_count,
                'negative': negative_count,
                'mood': mood
            }