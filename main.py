import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import telebot

BOT_TOKEN = "8839509486:AAFSjzuYLhQ82dnRLPSx18JRtAoV-wNC_iw"
CHAT_ID = 1043209905

bot = telebot.TeleBot(BOT_TOKEN)

KEYWORDS = [
    "airdrop", "drop", "claim", "alpha", "node", "campaign",
    "аирдроп", "листинг", "тестнет", "binance", "binance web3",
    "okx", "okx web3", "bybit", "bitget", "mexc", "gate",
    "kucoin", "bingx", "kraken", "whitebit", "promo", "listing",
    "pool", "testnet", "giveaway"
]

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = (message.text or "").lower()
    if any(k in text for k in KEYWORDS):
        msg = f"🚨 Новый крипто-алерт!\n\n{message.text}"
        bot.send_message(CHAT_ID, msg)

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

print("Запуск бота...")
bot.infinity_polling()
