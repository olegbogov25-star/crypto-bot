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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ВАШ_ТОКЕН_БОТА_ОТ_BOTFATHER")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "ВАШ_КЛЮЧ_OPENROUTER")

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
    "ORBIT": 0,       # Мультибиржевой сканер
    "FUNDING": 76,    # Ветка для вилок фандинга (±1% + Плечо + Объемы)
    "SPREAD": 77,     # Ветка для межбиржевого спреда (≥3% + Плечо + Объемы)
}

RESTRICTED_TOPICS = set(v for v in EXCHANGE_CHATS.values() if v != 0)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "openai/gpt-4o-mini"

# Фильтр технического шума, маржи и займов
EXCLUDED_KEYWORDS = [
    "deposit", "withdrawal", "wallet maintenance", "system upgrade",
    "scheduled maintenance", "delisting", "resume deposit", "resume withdrawal",
    "collateral", "margin ratio", "risk rate", "adjustment of margin",
    "margin trading", "isolated margin", "cross margin", "loan service", "savings"
]

SYSTEM_PROMPT = """
Ты — специализированный криптоаналитик для автоматического отслеживания и разбора доходных событий: акций, промо-кампаний, аирдропов, Web3-квестов, кампаний Bybit Galaxy/Arcade, Binance Web3 Airdrops/Megadrop, OKX Web3 Boost (X Launch, X Liquidity), бустов, бесплатных раздач, фьючерсных турниров, бонусов за депозит, фарминга (PoolX, GemsPool) и Launchpad/Launchpool/Megadrop/Alpha от всех ключевых бирж.

⚠️ КРИТИЧЕСКИЕ ПРАВИЛА:
1. ИГНОРИРУЙ технические новости (ввод/вывод, залоги, маржа, техобслуживание, займы).
2. ИГНОРИРУЙ СУХИЕ ЛИСТИНГИ — если токен просто добавляется на спот/фьючерсы/маржу и при этом НЕТ никакой раздачи, призового пула, аирдропа, пула бустов (X Launch, Web3 Wallet Quest) или промо-акции!
3. ЕСЛИ СОБЫТИЕ НЕ СОДЕРЖИТ КОНКРЕТНЫХ НАГРАД, ПРИЗОВОГО ФОНДА ИЛИ АИРДРОПА (например, просто поздравления, сухие новости) — НАПИШИ РОВНО ОДНО СЛОВО: SKIP

✅ СОСТАВЛЯЙ ОТЧЕТ ТОЛЬКО ЕСЛИ:
Событие содержит ДОХОДНУЮ СОСТАВЛЯЮЩУЮ (аирдроп, фарминг, награды за депозит/торговлю, Web3-квесты, бонусы, X Launch, Boost, Launchpool/Megadrop/Alpha/CandyBomb).

Составляй чёткий, структурированный отчёт на русском языке strictly по шаблону:

📌 **Биржа / Источник:** [Укажи биржу и раздел, например Binance Web3 / OKX Boost]
🏷 **Тип события / Теги:** [#Listing, #NewListing, #InitialListing, #PreMarket, #IPO, #Launchpad, #Launchpool, #Megadrop, #Alpha, #CandyDrop, #CandyBomb, #Startup, #Kickstarter, #AirDrop, #Web3Airdrop, #Web3Quest, #Quest, #Galaxy, #Arcade, #Boost, #XLaunch, #Liquidity, #Yield, #Campaign, #Promotion, #Activity, #Event, #TradingCompetition, #LearnAndEarn, #FlashEarn, #Prediction, #Voucher, #Bonus, #VIP, #Futures, #Staking, #Earn, #PoolX, #GemsPool, #ByStarter, #HoldAndEarn, #CryptoBox, #TrialFund, #WOTD, #TradeBoost, #Code, #RewardCenter]

💰 **Токен / Проект:** [Название и тикер]
📅 **Даты / Время проведения:** [Период]
📋 **Краткое описание:** [Суть анонса, буста, Web3-квеста или промо-акции]

⚡ **Что нужно сделать (Инструкция / Пошагово):**
- [Шаг 1]
- [Шаг 2]
- [Шаг 3]

🎁 **Награды / Призовой фонд:** [Пулы, APY, бонусы, аирдроп]
⚠️ **Важные условия / Ограничения и риски:** [Риски, KYC, Сеть/Кошелек]
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

processed_items = set()

def is_noise(text):
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in EXCLUDED_KEYWORDS)

def analyze_and_send(title, summary, link, exchange_name):
    exchange_key = exchange_name.upper().split()[0]
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
        answer = completion.choices[0].message.content.strip()
        
        # Защита от спама: если ИИ решил пропустить событие, просто выходим
        if "SKIP" in answer or len(answer) < 30:
            return

        markup = telebot.types.InlineKeyboardMarkup()
        if link:
            btn_app = telebot.types.InlineKeyboardButton(f"📱 Открыть в {exchange_name}", url=link)
            markup.add(btn_app)
        
        bot.send_message(
            chat_id=CHAT_ID,
            message_thread_id=thread_id,
            text=answer,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception as e:
        print(f"❌ Ошибка ИИ-анализа для {exchange_name}: {e}")

# Поток 1: Мониторинг стандартных RSS (каждые 5 минут)
def monitor_rss():
    print("🚀 Модуль мониторинга RSS запущен (интервал: 5 мин)...")
    for exchange, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                item_id = entry.get("link", "") or entry.get("title", "")
                if item_id:
                    processed_items.add(item_id)
        except Exception as e:
            print(f"⚠️ Ошибка инициализации RSS {exchange}: {e}")

    while True:
        for exchange, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    link = entry.get("link", "")
                    title = entry.get("title", "")
                    summary = entry.get("summary", title)
                    item_id = link or title
                    
                    if item_id and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 1000:
                            processed_items.pop()
                        analyze_and_send(title, summary, link, exchange)
            except Exception as e:
                print(f"❌ Ошибка парсинга RSS {exchange}: {e}")
        time.sleep(300)

# Поток 2: Мониторинг Web3 (каждые 12 минут, с защитой от дублей)
def monitor_web3():
    print("🌐 Модуль мониторинга Web3 запущен (интервал: 12 мин)...")
    while True:
        try:
            okx_api_url = "https://www.okx.com/api/v5/support/announcements?page=1"
            res = requests.get(okx_api_url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("code") == "0" and "data" in data:
                    for ann in data["data"][0].get("details", [])[:5]:
                        title = ann.get("title", "")
                        link = ann.get("url", "https://www.okx.com/web3")
                        
                        # Фильтрация по уникальному названию анонса
                        if title and title not in processed_items:
                            processed_items.add(title)
                            if len(processed_items) > 1000:
                                processed_items.pop()
                            analyze_and_send(title, title, link, "OKX Web3 Boost")
        except Exception as e:
            print(f"⚠️ Ошибка подгрузки Web3 API OKX: {e}")
            
        time.sleep(720)

# Поток 3: Фандинг (каждые 30 минут)
def monitor_funding():
    print("⚡ Модуль арбитража фандинга запущен (интервал: 30 мин)...")
    while True:
        try:
            pass
        except Exception as e:
            print(f"❌ Ошибка в мониторинге фандинга: {e}")
        time.sleep(1800)

# Поток 4: Спред (каждые 30 минут)
def monitor_spread():
    print("🔀 Модуль мониторинга спреда запущен (интервал: 30 мин)...")
    while True:
        try:
            pass
        except Exception as e:
            print(f"❌ Ошибка в мониторинге спреда: {e}")
        time.sleep(1800)

@bot.message_handler(func=lambda message: message.message_thread_id in RESTRICTED_TOPICS)
def auto_delete_user_messages(message):
    if not message.from_user.is_bot:
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            pass

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.chat.type == "private" and message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ ограничен.")
        return
    bot.reply_to(message, "👋 **CryptoMonitor Bot запущен в идеальном режиме без флуда и дублей!**")

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
    
    # Запуск всех независимых потоков
    threading.Thread(target=monitor_rss, daemon=True).start()
    threading.Thread(target=monitor_web3, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    
    print("🤖 CryptoMonitor Bot успешно запущен!")
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as e:
            print(f"⚠️ Сбой сети/Telegram API: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
