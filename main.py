import asyncio
import os
from bs4 import BeautifulSoup
from flask import Flask
from openai import OpenAI
import telebot
from telebot import TeleBot
from telethon import TelegramClient, events
import threading

# ==================== 1. ИНИЦИАЛИЗАЦИЯ ПЕРЕМЕННЫХ ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Данные для Telethon (нужны для чтения публичных каналов без ограничений)
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")

# Куда отправлять готовые разборы из каналов (ID чата, группы или канала)
# Можно указать числовой ID (например, -1001234567890) или @username
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID", "")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
  raise ValueError(
      "Ошибка: не найден TELEGRAM_TOKEN или OPENROUTER_API_KEY в переменных"
      " окружения!"
  )

# Инициализация ботов и клиентов
bot = TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1/",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "openai/gpt-4o-mini"

# ==================== 2. СИСТЕМНЫЙ ПРОМПТ ====================
SYSTEM_PROMPT = """
Ты — специализированный криптоаналитик для автоматического отслеживания и разбора официальных анонсов, акций, листингов, web3-квестов и промо-кампаний:
1. Binance (включая Binance Web3 Wallet / Binance Alpha)
2. Bybit
3. OKX (включая OKX Web3 Wallet / Cryptopedia / X Launch / X Trade)
4. MEXC
5. BingX
6. Gate.io (включая Gate CandyDrop, Startup, Kickstarter)
7. Bitget
8. KuCoin
9. Kraken
10. WhiteBIT

Твоя задача — проанализировать входящий текст анонса и составить чёткий, структурированный отчёт на русском языке strictly по следующему шаблону:

📌 **Биржа / Источник:** [Укажи конкретную биржу или Web3-кошелек из списка выше]
🏷 **Тип события / Теги:** [Подбери точные англоязычные теги из списка: #Listing, #NewListing, #InitialListing, #PreMarket, #Launchpad, #Launchpool, #AirDrop, #Launch, #Pool, #Alpha, #CandyDrop, #Startup, #Kickstarter]

💰 **Токен / Проект:** [Название токена и тикер, например: BTC, NOT, DOGS, HMSTR]
📅 **Даты / Время проведения:** [Период проведения, даты снимков баланса, время листинга, дедлайны]
📋 **Краткое описание:** [2-3 предложения — главная суть анонса/акции/квеста]

⚡ **Что нужно сделать (Инструкция / Пошагово):**
- [Шаг 1: Пройти KYC / Подключить Web3 Wallet / Депозит / Регистрация]
- [Шаг 2: Сделать Swap / Торговый объем / Собрать конфеты в CandyDrop / Участие в Startup]
- [Шаг 3: Ожидание распределения наград или клейм]

🎁 **Награды / Призовой фонд:** [Общий призовой пул, ваучеры, плечи, размеры наград на человека]
⚠️ **Важные условия / Ограничения и риски:** [Ограничения по странам, комиссии сети, уровни KYC, мин. объем, оценка рисков]
🔗 **Ссылка на источник/акцию:** [Вставь прямую глубокую ссылку на мобильное приложение биржи или источника, если есть]

Если присланный текст не относится напрямую к анонсам вышеуказанных бирж или web3-кошельков, сделай краткую выжимку текста и проставь подходящие крипто-теги.
"""

TARGET_CHANNELS = [
    "binance_announcements",
    "Bybit_Announcements",
    "OKXAnnouncements",
    "MEXC_OfficialAnnouncements",
    "BingXAnnouncement",
    "gate_announcements",
    "bitget_announcements",
    "Kucoin_News",
    "WhiteBIT",
]


# ==================== 3. ФУНКЦИИ АНАЛИЗА ИИ ====================
def analyze_text_with_ai(raw_text: str) -> str:
  """Отправляет текст в OpenRouter (GPT-4o-mini) и возвращает готовый разбор."""
  try:
    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        temperature=0.2,
    )
    return completion.choices[0].message.content
  except Exception as e:
    return f"❌ Ошибка при обращении к ИИ: {str(e)}"


# ==================== 4. ОБРАБОТЧИКИ TELEGRAM BOT ====================
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
  bot.reply_to(
      message,
      "🤖 **CryptoMonitor Bot запущен и готов к работе!**\n\n"
      "• Отправь мне любой текст анонса вручную, и я сделаю разбор.\n"
      "• Бот также автоматически слушает официальные Telegram-каналы бирж.",
  )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
  user_text = message.text
  sent_msg = bot.reply_to(message, "🔍 Анализирую анонс...")

  answer = analyze_text_with_ai(user_text)

  try:
    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=sent_msg.message_id,
        text=answer,
        parse_mode="Markdown",
    )
  except Exception as e:
    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=sent_msg.message_id,
        text=f"❌ Ошибка отправки:\n{str(e)}",
    )


# ==================== 5. TELETHON МОНИТОРИНГ КАНАЛОВ ====================
async def start_telegram_monitor():
  if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
    print(
        "[Telegram Monitor] API_ID или API_HASH не заданы. Telethon пропущен."
    )
    return

  tg_client = TelegramClient(
      "crypto_bot_session", TELEGRAM_API_ID, TELEGRAM_API_HASH
  )

  @tg_client.on(events.NewMessage(chats=TARGET_CHANNELS))
  async def handle_new_channel_post(event):
    raw_text = event.raw_text
    if not raw_text:
      return

    print(
        f"[Telegram Monitor] Пойман новый пост из канала: {event.chat.username}"
    )

    # Анализируем текст через ИИ
    analysis_result = analyze_text_with_ai(raw_text)

    # Если задан чат для отправки результатов — отправляем туда
    if TARGET_CHAT_ID:
      try:
        # Используем стандартный синхронный bot через asyncio.to_thread, чтобы не блокировать event loop
        await asyncio.to_thread(
            bot.send_message,
            chat_id=TARGET_CHAT_ID,
            text=analysis_result,
            parse_mode="Markdown",
        )
      except Exception as e:
        print(f"[Telegram Monitor] Ошибка отправки отчета в чат: {e}")

  await tg_client.start()
  print("[Telegram Monitor] Успешно запущен и слушает каналы 24/7.")
  await tg_client.run_until_disconnected()


# ==================== 6. FLASK ДЛЯ WEB-СЕРВЕРА (Render/Railway) ====================
app = Flask("")


@app.route("/")
def home():
  return "Crypto Monitor Bot is running 24/7!"


def run_web():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


# ==================== 7. ТОЧКА ВХОДА (MAIN) ====================
async def main():
  # Запускаем мониторинг каналов в фоновой задаче asyncio
  asyncio.create_task(start_telegram_monitor())
  print("Бот запущен в режиме Long Polling...")

  # Запускаем поллинг бота в отдельном потоке, чтобы не блокировать asyncio
  await asyncio.to_thread(bot.infinity_polling, skip_pending=True)


if __name__ == "__main__":
  # Запуск Flask-сервера в фоновом потоке (чтобы хостинг видел живой порт)
  web_thread = threading.Thread(target=run_web)
  web_thread.daemon = True
  web_thread.start()

  # Запуск основного асинхронного цикла
  asyncio.run(main())
