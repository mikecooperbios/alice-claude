# Alice-Claude Bridge

Сервер-прослойка между навыком Яндекс Алисы и Anthropic Claude API.

## Быстрый старт

1. `pip install -r requirements.txt`
2. Скопируй .env.example в .env и заполни ANTHROPIC_API_KEY
3. `uvicorn main:app --port 8000 --reload`
4. Для публичного URL: `ngrok http 8000`
5. URL навыка в Яндекс Диалогах: https://<ngrok-url>/alice

## Эндпоинты

- GET /health — проверка сервера
- POST /alice — вебхук для Яндекс Алисы
