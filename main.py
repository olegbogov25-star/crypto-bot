import telebot

BOT_TOKEN = "8839509486:AAFSjzuYLhQ82dnRLPSx18JRtAoV-wNC_iw"
CHAT_ID = 1043209905
bot = telebot.TeleBot(BOT_TOKEN)
KEYWORDS = ["airdrop", "binance", "binance web3", "okx", "okx web3", "bybit", "bitget", "mexc", "gate", "kucoin", "bingx", "kraken", "whitebit", "promo", "listing", "pool", "testnet", "giveaway"]
@bot.message_handler(func=lambda message: True) 
def handle_message(message): 
    text = (message.text or "").lower() 
    if any(k in text for k in KEYWORDS): 
            msg = f"🚨 Новый крипто-алерт!\n\n{message.text}" 
            bot.send_message(CHAT_ID, msg)
print("Запуск бота...")
bot.infinity_polling()
