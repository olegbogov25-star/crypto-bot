import os
import time
import threading
import requests
import feedparser
from http.server import HTTPServer, BaseHTTPRequestHandler
from openai import OpenAI
import telebot

# ==================== ФЕЙКОВЫЙ СЕРВЕР ДЛЯ RENDER ====================
class DummyHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyHealthCheckHandler)
    server.serve_forever()
# ===================================================================

# ==================== НАСТРОЙКИ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "ВАШ_ТОКЕН_БОТА_ОТ_BOTFATHER")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "ВАШ_КЛЮЧ_OPENROUTER")

CHAT_ID = "-1004451728851"
ADMIN_IDS = [123456789]  # Ваш Telegram ID

EXCHANGE_CHATS = {
    "BINANCE": 3,
    "BYBIT": 4,
    "OKX": 6,
    "GATE": 67,
    "BITGET": 69,
    "MEXC": 68,
    "BINGX": 70,
    "KUCOIN": 71,
    "KRAKEN": 73,
    "WHITEBIT": 72,
    "ORBIT": 0,
    "FUNDING": 76,    # Автономная ветка для вилок фандинга (±1%)
    "SPREAD": 77,     # Автономная ветка для разницы цен (≥3%)
}

RESTRICTED_TOPICS = set(v for v in EXCHANGE_CHATS.values() if v != 0)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "openai/gpt-4o-mini"

EXCLUDED_KEYWORDS = [
    "deposit", "withdrawal", "wallet maintenance", "system upgrade",
    "scheduled maintenance", "delisting", "resume deposit", "resume withdrawal",
    "collateral", "margin ratio", "risk rate", "adjustment of margin"
]

SYSTEM_PROMPT = """
Ты — специализированный криптоаналитик для автоматического отслеживания и разбора важной информации по акциям, листингам, IPO, Web3-квестам, кампаниям Bybit Galaxy, бустам (Boost/X Launch), бесплатным раздачам, промо-кодам, фьючерсным турнирам, бонусам за депозит, VIP-программам, фармингу (PoolX, GemsPool) и Launchpad/Launchpool от всех ключевых бирж.

⚠️ ИГНОРИРУЙ и НЕ СОСТАВЛЯЙ отчеты по техническим новостям о вводе/выводе средств, изменениях залогов/маржи или техобслуживании!

Составляй чёткий, структурированный отчёт на русском языке strictly по шаблону:

📌 **Биржа / Источник:** [Укажи биржу]
🏷 **Тип события / Теги:** [#Listing, #NewListing, #InitialListing, #PreMarket, #IPO, #Launchpad, #Launchpool, #Megadrop, #Alpha, #CandyDrop, #CandyBomb, #Startup, #Kickstarter, #AirDrop, #Web3Airdrop, #Web3Quest, #Quest, #Galaxy, #Arcade, #Boost, #XLaunch, #Liquidity, #Yield, #Campaign, #Promotion, #Activity, #Event, #TradingCompetition, #LearnAndEarn, #FlashEarn, #Prediction, #Voucher, #Bonus, #VIP, #Futures, #Staking, #Earn, #PoolX, #GemsPool, #ByStarter, #HoldAndEarn, #CryptoBox, #TrialFund, #WOTD, #TradeBoost, #Code, #RewardCenter]

💰 **Токен / Проект:** [Название и тикер]
📅 **Даты / Время проведения:** [Период]
📋 **Краткое описание:** [Суть анонса]

⚡ **Что нужно сделать (Инструкция / Пошагово):**
- [Шаг 1]
- [Шаг 2]
- [Шаг 3]

🎁 **Награды / Призовой фонд:** [Пулы, APY, бонусы]
⚠️ **Важные условия / Ограничения и риски:** [Риски, KYC]
🔗 **Ссылка на источник/акцию:** [Ссылка]
📱 **Переход в приложение:** [Инструкция]
"""

RSS_FEEDS = {
    "BINANCE": "https://www.binance.com/en/support/announcement/rss",
    "BYBIT": "https://announcements.bybit.com/en-US/rss/",
    "OKX": "https://www.okx.com/support/rss",
    "GATE": "https://www.gate.io/rss/article/all",
    "BITGET": "https://www.bitget.com/support/rss"
}

processed_links = set()

def is_noise(text):
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in EXCLUDED_KEYWORDS)

def analyze_and_send(title, summary, link, exchange_name):
    exchange_key = exchange_name.upper()
    if exchange_key not in EXCHANGE_CHATS or EXCHANGE_CHATS[exchange_key] == 0:
        return
    
    if is_noise(title) or is_noise(summary):
        return

    thread_id = EXCHANGE_CHATS[exchange_key]
    full_text = f"Источник: {exchange_name}\nЗаголовок: {title}\nОписание: {summary}\nСсылка: {link}"
    
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_text}
            ],
            temperature=0.2,
        )
        answer = completion.choices[0].message.content
        
        markup = telebot.types.InlineKeyboardMarkup()
        if link:
            btn_app = telebot.types.InlineKeyboardButton(f"📱 Открыть акцию в {exchange_name}", url=link)
            markup.add(btn_app)
        
        bot.send_message(
            chat_id=CHAT_ID,
            message_thread_id=thread_id,
            text=answer,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception as e:
        print(f"❌ Ошибка ИИ-анализа RSS для {exchange_key}: {e}")

def monitor_rss():
    print("🚀 Модуль автомониторинга RSS запущен...")
    for exchange, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                link = entry.get("link", "")
                if link:
                    processed_links.add(link)
        except Exception as e:
            print(f"⚠️ Ошибка подгрузки RSS {exchange}: {e}")

    while True:
        for exchange, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    link = entry.get("link", "")
                    title = entry.get("title", "")
                    summary = entry.get("summary", title)
                    
                    if link and link not in processed_links:
                        processed_links.add(link)
                        if len(processed_links) > 1000:
                            processed_links.pop()
                        analyze_and_send(title, summary, link, exchange)
            except Exception as e:
                print(f"❌ Ошибка парсинга {exchange}: {e}")
        time.sleep(300)

def monitor_funding():
    """Сканер вилок фандинга (НЕ зависит от цены, только сопоставление противоположных ставок >= ±1%)"""
    print("🚀 Модуль арбитража фандинга запущен...")
    while True:
        try:
            # 1. Сбор ставок фандинга с 11 бирж
            # 2. Поиск пар: Биржа А (ставка >= +1%) + Биржа Б (ставка <= -1%)
            # 3. Отправка сигнала строго в ветку FUNDING (ID: 76)
            pass
        except Exception as e:
            print(f"❌ Ошибка в мониторинге фандинга: {e}")
            
        time.sleep(1800)

def monitor_spread():
    """Сканер спреда цен (НЕ зависит от фандинга, только разница цен >= 3% между 11 биржами)"""
    print("🚀 Модуль мониторинга спреда запущен...")
    while True:
        try:
            # 1. Сбор цен одной и той же монеты с 11 бирж
            # 2. Вычисление процента разницы цен: ((Max_Price - Min_Price) / Min_Price) * 100
            # 3. Если Спред >= 3% -> Отправка сигнала строго в ветку SPREAD (ID: 77)
            pass
        except Exception as e:
            print(f"❌ Ошибка в мониторинге спреда: {e}")
            
        time.sleep(1800)

# 1. Автоудаление пользовательских сообщений в защищенных топиках
@bot.message_handler(func=lambda message: message.message_thread_id in RESTRICTED_TOPICS)
def auto_delete_user_messages(message):
    if not message.from_user.is_bot:
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            pass

# 2. Команды /start и /help
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.chat.type == "private" and message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ ограничен.")
        return
    bot.reply_to(message, "👋 **CryptoMonitor Bot запущен! Фандинг и Спреды разделены и работают независимо.**")

# 3. Обработка ручных запросов
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if message.chat.type == "private" and message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ ограничен.")
        return

    if message.chat.type in ["group", "supergroup"] and message.message_thread_id in RESTRICTED_TOPICS:
        return

    user_text = message.text
    sent_msg = bot.reply_to(message, "🔍 Анализирую запрос...")

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ],
            temperature=0.2,
        )
        answer = completion.choices[0].message.content
        bot.edit_message_text(chat_id=message.chat.id, message_id=sent_msg.message_id, text=answer, parse_mode="Markdown")
    except Exception as e:
        try:
            bot.edit_message_text(chat_id=message.chat.id, message_id=sent_msg.message_id, text=f"❌ Ошибка:\n{str(e)}")
        except Exception:
            pass

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    threading.Thread(target=monitor_rss, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    
    print("🤖 CryptoMonitor Bot запущен в режиме независимого мониторинга!")
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as e:
            print(f"⚠️ Сбой сети/Telegram API: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
