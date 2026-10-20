import os
from telethon import TelegramClient, events

API_ID = 36041164
API_HASH = "14b25c0df36f39ed248e22ee8f258b74"
BOT_TOKEN = "8839509486:AAFlXDiLu4vM7a6RWYGxLZ_EQkYsnstdYk"
CHAT_ID = 1043209905
SESSION_NAME = "cryptobot"
print("Инициализация клиента Telegram...")
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
KEYWORDS = ["airdrop", "binance web3", "okx web3", "promo", "listing", "pool", "testnet", "giveaway"]
@client.on(events.NewMessage(incoming=True)) async def handle_new_message(event): message_text = (event.raw_text or "").lower() if any(keyword in message_text for keyword in KEYWORDS): alert_message = f"🚨 Новый крипто-алерт!\n\n{event.raw_text}" await client.send_message(CHAT_ID, alert_message)
print("Авторизация и запуск бота...")
client.start(bot_token=BOT_TOKEN)
print("Бот успешно авторизован и запущен!")
client.run_until_disconnected()
