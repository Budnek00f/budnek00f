import requests
import json
import base64
from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, SUBSCRIPTION_PRICE

class PaymentSystem:
    def __init__(self):
        self.shop_id = YOOKASSA_SHOP_ID
        self.secret_key = YOOKASSA_SECRET_KEY
    
    def create_payment(self, user_id, amount=SUBSCRIPTION_PRICE):
        url = "https://api.yookassa.ru/v3/payments"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {self._get_auth_token()}"
        }
        
        payload = {
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://t.me/your_bot?start=payment_success_{user_id}"
            },
            "description": f"Подписка на бота для пользователя {user_id}",
            "metadata": {
                "user_id": user_id
            }
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Payment error: {e}")
            return None
    
    def _get_auth_token(self):
        token = f"{self.shop_id}:{self.secret_key}"
        return base64.b64encode(token.encode()).decode()
    
    def check_payment_status(self, payment_id):
        url = f"https://api.yookassa.ru/v3/payments/{payment_id}"
        
        headers = {
            "Authorization": f"Basic {self._get_auth_token()}"
        }
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Payment status error: {e}")
            return None