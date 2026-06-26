import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
# ProxyAPI (2026): gemini-pro / gemini-1.5-pro / gemini-1.0-pro → «Model not supported»; рабочий пример — gemini-2.0-flash.
BASE_URL = "https://api.proxyapi.ru/google/v1beta/models/gemini-2.0-flash:generateContent"

headers = {
    "Content-Type": "application/json",
    # Гугловский стандарт (то, как делает SDK)
    "x-goog-api-key": API_KEY,
    # Стандарт ProxyAPI (раскомментируем, если первое не сработает)
    # "Authorization": f"Bearer {API_KEY}"
}

payload = {
    "contents": [{"parts": [{"text": "Привет! Ответь одним словом: работает?"}]}]
}

print(f"Отправка запроса на {BASE_URL}...")
response = requests.post(BASE_URL, headers=headers, json=payload)

print(f"Статус: {response.status_code}")
print(f"Ответ сервера:\n{response.text}")
