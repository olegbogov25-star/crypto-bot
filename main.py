import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import telebot
import requests

BOT_TOKEN = "8839509486:AAFSjzuYLhQ82dnRLPSx18JRtAoV-wNC_iw"
CHAT_ID = 1043209905
GEMINI_API_KEY = "AQ.Ab8RN6KdL2iZuyHohYliGkwkpUqXd32tQvdg8-sgu7eMfmzrIQ"
XAI_API_KEY = "Grok_41b58ab557c49d1d533246884dbee328_61fbc2fa7618d27c894d34ae1251390a2d44cf71d91801edd854a28943a1c6d8"

bot = telebot.TeleBot(BOT_TOKEN)

KEYWORDS = [
    "airdrop", "drop", "claim", "alpha", "node", "campaign",
    "аирдроп", "листинг", "тестнет", "binance", "binance web3",
    "okx", "okx web3", "bybit", "bitget", "mexc", "gate",
    "kucoin", "bingx", "kraken", "whitebit", "promo", "listing",
    "pool", "testnet", "giveaway"
]

def architect_gemini(text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"Проанализируй этот крипто-пост. Сделай на русском языке:\n1. Суть проекта и перевод.\n2. Пошаговый чеклист (что делать).\nТекст поста:\n{text}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"Ошибка Gemini: {response.text}"
    except Exception as e:
        return f"Ошибка запроса к Gemini: {str(e)}"

def critic_grok(architect_text):
    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {XAI_API_KEY}"
    }
    payload = {
        "model": "grok-beta",
        "messages": [
            {"role": "system", "content": "Ты жесткий крипто-критик и риск-менеджер. Оцени разбор проекта, укажи на скрытые риски/скам и поставь итоговую оценку от 1 до 10."},
            {"role": "user", "content": f"Проверь этот разбор и дай вердикт по рискам:\n\n{architect_text}"}
        ]
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return f"Ошибка Grok: {response.text}"
    except Exception as e:
        return f"Ошибка запроса к Grok: {str(e)}"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = (message.text or "").lower()
    if any(k in text for k in KEYWORDS):
        bot.send_message(CHAT_ID, "🏗 Архитектор (Gemini) начал обработку сигнала...")
        blueprint = architect_gemini(message.text)
        bot.send_message(CHAT_ID, "🛡 Критик (Grok) проверяет риски...")
        critique = critic_grok(blueprint)
        final_report = f"🚨 МУЛЬТИАГЕНТНЫЙ АНАЛИЗ СИГНАЛА\n\n📋 План от Архитектора:\n{blueprint}\n\n⚖️ Вердикт Критика:\n{critique}"
        bot.send_message(CHAT_ID, final_report, parse_mode="Markdown")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

print("Многоагентный бот (Gemini + Grok) запущен...")
bot.infinity_polling()
