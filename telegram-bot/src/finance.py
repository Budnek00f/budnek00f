from database import Database

class FinanceManager:
    def __init__(self, db):
        self.db = db
    
    def add_transaction(self, user_id, amount, category, description, transaction_type):
        with self.db.get_cursor() as cursor:
            if self.db.is_postgres:
                cursor.execute('''
                    INSERT INTO finances (user_id, amount, category, description, type)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (user_id, amount, category, description, transaction_type))
            else:
                cursor.execute('''
                    INSERT INTO finances (user_id, amount, category, description, type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, amount, category, description, transaction_type))
        
        return True
    
    def get_financial_report(self, user_id, period="month"):
        with self.db.get_cursor() as cursor:
            if self.db.is_postgres:
                cursor.execute('''
                    SELECT type, SUM(amount) as total, category
                    FROM finances 
                    WHERE user_id = %s 
                    GROUP BY type, category
                ''', (user_id,))
            else:
                cursor.execute('''
                    SELECT type, SUM(amount) as total, category
                    FROM finances 
                    WHERE user_id = ? 
                    GROUP BY type, category
                ''', (user_id,))
            
            results = cursor.fetchall()
            
            income = 0
            expense = 0
            categories = {}
            
            for row in results:
                if row['type'] == 'income':
                    income += row['total']
                else:
                    expense += row['total']
                
                category_key = f"{row['type']}_{row['category']}"
                categories[category_key] = row['total']
            
            balance = income - expense
            
            return {
                'income': income,
                'expense': expense,
                'balance': balance,
                'categories': categories
            }