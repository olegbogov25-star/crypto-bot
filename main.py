import os
from telethon import TelegramClient, events
API_ID = 36041164
API_HASH = "14b25c0df36f39ed248e22ee8f258b74"
BOT_TOKEN = "8839509486:AAFlXDiLu4vM7a6RWYGxLZ_EQkYsnstdYk"
CHAT_ID = 1043209905
print("Инициализация клиента Telegram...")
client = TelegramClient("cryptobot", API_ID, API_HASH)
KEYWORDS = ["airdrop", "binance web3", "okx web3", "promo", "listing", "pool", "testnet", "giveaway"]
    @client.on(events.NewMessage(incoming=True))
    async def handle_new_message(event):
      text = (event.raw_text or "").lower()
      if any(k in text for k in KEYWORDS):
          msg = f"🚨 Новый крипто-алерт!\n\n{event.raw_text}"
          await client.send_message(CHAT_ID, msg)
print("Запуск бота...")
client.start(bot_token=BOT_TOKEN)
print("Бот успешно запущен!")
client.run_until_disconnected()
