import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import telebot
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)

KEYWORDS = [
    "airdrop", "drop", "claim", "alpha", "node", "campaign",
    "аирдроп", "листинг", "тестнет", "binance", "binance web3",
    "okx", "okx web3", "bybit", "bitget", "mexc", "gate",
    "kucoin", "bingx", "kraken", "whitebit", "promo", "listing",
    def analyze_with_gemini(text): url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
prompt = f"""Ты — экспертный ИИ-аналитик крипто-сигналов и аирдропов.
Проанализируй данный пост и ответь СТРОГО по следующей структуре:
📋 СУТЬ И ПЕРЕВОД: (Коротко объясни суть проекта и переведи ключевую мысль на русский язык)
📝 ПОШАГОВЫЙ ЧЕКЛИСТ: (Выдели конкретные действия: что нужно сделать пользователю)
⚖️ ОЦЕНКА РИСКОВ И ВЕРДИКТ: (Оцени потенциал и риски: скам/высокий риск/надежно, стоит ли участвовать)
Текст поста: {text}"""
payload = {"contents": [{"parts": [{"text": prompt}]}]}

try:
    response = requests.post(url, json=payload, timeout=20)
    if response.status_code == 200:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return f"Ошибка Gemini API (Статус {response.status_code}): {response.text}"
except Exception as e:
    return f"Ошибка запроса к Gemini: {str(e)}"
    "pool", "testnet", "giveaway"
]
@bot.message_handler(func=lambda message: True) def handle_message(message): text = message.text or "" if any(keyword.lower() in text.lower() for keyword in KEYWORDS): msg = bot.reply_to(message, "⏳ Анализирую сигнал с помощью Gemini ИИ...")
    analysis = analyze_with_gemini(text)
    
    full_response = f"🚀 **АНАЛИЗ СИГНАЛА (Gemini AI)**\n\n{analysis}"
    
    bot.send_message(message.chat.id, full_response, parse_mode="Markdown")
def run_dummy_server(): port = int(os.environ.get("PORT", 10000)) server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler) server.serve_forever()
if name == "main": threading.Thread(target=run_dummy_server, daemon=True).start() bot.infinity_polling()
