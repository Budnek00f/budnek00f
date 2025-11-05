import datetime
from datetime import datetime as dt
from database import Database

class ReminderManager:
    def __init__(self, db):
        self.db = db
    
    def add_reminder(self, user_id, text, due_date_str):
        try:
            due_date = dt.strptime(due_date_str, '%Y-%m-%d %H:%M')
            
            with self.db.get_cursor() as cursor:
                if self.db.is_postgres:
                    cursor.execute('''
                        INSERT INTO reminders (user_id, text, due_date)
                        VALUES (%s, %s, %s)
                    ''', (user_id, text, due_date))
                else:
                    cursor.execute('''
                        INSERT INTO reminders (user_id, text, due_date)
                        VALUES (?, ?, ?)
                    ''', (user_id, text, due_date.strftime('%Y-%m-%d %H:%M:%S')))
            
            return True, "Напоминание добавлено!"
        except ValueError as e:
            return False, f"Неверный формат даты. Используйте: ГГГГ-ММ-ДД ЧЧ:ММ. Ошибка: {e}"
        except Exception as e:
            return False, f"Ошибка при добавлении напоминания: {e}"
    
    def get_reminders(self, user_id, show_completed=False):
        with self.db.get_cursor() as cursor:
            if show_completed:
                if self.db.is_postgres:
                    cursor.execute('''
                        SELECT * FROM reminders 
                        WHERE user_id = %s 
                        ORDER BY due_date
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        SELECT * FROM reminders 
                        WHERE user_id = ? 
                        ORDER BY due_date
                    ''', (user_id,))
            else:
                if self.db.is_postgres:
                    cursor.execute('''
                        SELECT * FROM reminders 
                        WHERE user_id = %s AND completed = FALSE
                        ORDER BY due_date
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        SELECT * FROM reminders 
                        WHERE user_id = ? AND completed = FALSE
                        ORDER BY due_date
                    ''', (user_id,))
            
            return cursor.fetchall()
    
    def complete_reminder(self, user_id, reminder_id):
        with self.db.get_cursor() as cursor:
            if self.db.is_postgres:
                cursor.execute('''
                    UPDATE reminders 
                    SET completed = TRUE 
                    WHERE id = %s AND user_id = %s
                ''', (reminder_id, user_id))
            else:
                cursor.execute('''
                    UPDATE reminders 
                    SET completed = TRUE 
                    WHERE id = ? AND user_id = ?
                ''', (reminder_id, user_id))
        
        return True
    
    def delete_reminder(self, user_id, reminder_id):
        with self.db.get_cursor() as cursor:
            if self.db.is_postgres:
                cursor.execute('''
                    DELETE FROM reminders 
                    WHERE id = %s AND user_id = %s
                ''', (reminder_id, user_id))
            else:
                cursor.execute('''
                    DELETE FROM reminders 
                    WHERE id = ? AND user_id = ?
                ''', (reminder_id, user_id))
        
        return True