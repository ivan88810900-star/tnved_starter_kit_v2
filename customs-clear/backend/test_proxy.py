import os

import requests
from dotenv import load_dotenv

# ProxyAPI (2026): gemini-pro / gemini-1.5-pro / gemini-1.0-pro → «Model not supported»; рабочий пример — gemini-2.0-flash.
BASE_URL = "https://api.proxyapi.ru/google/v1beta/models/gemini-2.0-flash:generateContent"


def main() -> int:
    """Ручная проверка ProxyAPI; при импорте и pytest-сборе сеть не используется."""
    load_dotenv()
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("GEMINI_API_KEY не настроен; запрос не отправлен.")
        return 2

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {
        "contents": [{"parts": [{"text": "Привет! Ответь одним словом: работает?"}]}]
    }

    print(f"Отправка запроса на {BASE_URL}...")
    try:
        response = requests.post(BASE_URL, headers=headers, json=payload, timeout=20)
    except requests.RequestException as exc:
        print(f"Запрос не выполнен: {type(exc).__name__}")
        return 1

    print(f"Статус: {response.status_code}")
    print(f"Ответ сервера:\n{response.text[:2000]}")
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
