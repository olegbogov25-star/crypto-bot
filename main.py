import os
import time
import threading
import requests
import feedparser
from openai import OpenAI
import telebot

# ==================== НАСТРОЙКИ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "ВАШ_ТОКЕН_БОТА_ОТ_BOTFATHER")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "ВАШ_КЛЮЧ_OPENROUTER")

# ID вашей целевой супергруппы ANTIGOI
CHAT_ID = "-1004451728851"

# 🔴 ВПИШИ СЮДА СВОЙ TELEGRAM ID (число без кавычек, например: 987654321)
ADMIN_IDS = [123456789]  # Узнать свой ID можно в боте @userinfobot

# 📌 Актуализированные ID веток супергруппы:
EXCHANGE_CHATS = {
    "BINANCE": 3,
    "BYBIT": 4,
    "OKX": 6,
    "GATE": 7,
    "BITGET": 8,
    "MEXC": 9,
    "BINGX": 10,
    "KUCOIN": 11,
    "KRAKEN": 12,
    "WHITEBIT": 13,
    "SUMMARY": 17,  # Ветка Сводки
    "STAKING": 14,
    "FUNDING": 15,
    "SPREAD": 16,
}

RESTRICTED_TOPICS = set(EXCHANGE_CHATS.values())
# ===================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "openai/gpt-4o-mini"

# Исключаем тех. шум: депозиты, выводы, техобслуживание
EXCLUDED_KEYWORDS = [
    "deposit", "withdrawal", "wallet maintenance", "system upgrade",
    "scheduled maintenance", "delisting", "resume deposit", "resume withdrawal"
]

SYSTEM_PROMPT = """
Ты — специализированный криптоаналитик для автоматического отслеживания и разбора важной информации по акциям, листингам, Web3-квестам, кампаниям и Launchpad/Launchpool от ключевых бирж.

⚠️ ИГНОРИРУЙ и НЕ СОСТАВЛЯЙ отчеты по техническим новостям о вводе/выводе средств (Deposits/Withdrawals), плановом обслуживании кошельков (Maintenance) или мелких внутренних обновлениях!

Составляй чёткий, структурированный отчёт на русском языке strictly по следующему шаблону:

📌 **Биржа / Источник:** [Укажи конкретную биржу или направление]
🏷 **Тип события / Теги:** [Подбери точные англоязычные теги из списка: #Listing, #NewListing, #InitialListing, #PreMarket, #Launchpad, #Launchpool, #CandyDrop, #Startup, #Kickstarter, #AirDrop, #Web3Airdrop, #Web3Quest, #Campaign, #Promotion, #Activity, #Event, #TradingCompetition, #LearnAndEarn, #Staking, #Earn]

💰 **Токен / Проект:** [Название токена и тикер, например: BTC, NOT, DOGS, HMSTR]
📅 **Даты / Время проведения:** [Период проведения, даты листинга, дедлайны]
📋 **Краткое описание:** [2-3 предложения — главная суть анонса/акции/квеста]

⚡ **Что нужно сделать (Инструкция / Пошагово):**
- [Шаг 1: Пройти KYC / Подключить Web3 Wallet / Депозит / Регистрация]
- [Шаг 2: Торговый объем / Участие в акции / Сбор наград]
- [Шаг 3: Ожидание распределения наград или клейм]

🎁 **Награды / Призовой фонд:** [Общий призовой пул, размеры наград]
⚠️ **Важные условия / Ограничения и риски:** [Ограничения по странам, комиссии сети, уровни KYC, оценка рисков]
🔗 **Ссылка на источник/акцию:** [Вставь прямую официальную ссылку из текста]
📱 **Переход в приложение:** [Укажи инструкцию, как открыть акцию в мобильном приложении]
"""

RSS_FEEDS = {
    "BINANCE": "https://www.binance.com/en/support/announcement/rss",
    "BYBIT": "https://announcements.bybit.com/en-US/rss/",
    "OKX": "https://www.okx.com/support/rss",
    "GATE": "https://www.gate.io/rss/article/all",
    "BITGET": "https://www.bitget.com/support/rss"
}

# Множество для защиты от дубликатов новостей
processed_links = set()


def is_noise(text):
    """Фильтрация служебных анонсов о вводах/выводах и техобслуживании"""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in EXCLUDED_KEYWORDS)


def analyze_and_send(title, summary, link, exchange_name):
    exchange_key = exchange_name.upper()
    if exchange_key not in EXCHANGE_CHATS:
        return
    
    # Отсекаем технический шум
    if is_noise(title) or is_noise(summary):
        print(f"ℹ️ Пропущен служебный анонс (ввод/вывод/обслуживание): {title}")
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
        
        # Отправляем сообщение в обычном режиме с нормальными уведомлениями
        bot.send_message(
            chat_id=CHAT_ID,
            message_thread_id=thread_id,
            text=answer,
            parse_mode="Markdown",
            reply_markup=markup
        )
        print(f"✅ Успешно проанализировано и отправлено в ветку {exchange_key}")
    except Exception as e:
        print(f"❌ Ошибка при ИИ-анализе RSS для {exchange_key}: {e}")


def monitor_rss():
    print("🚀 Модуль автомониторинга RSS запущен...")
    
    # 🛡 Предварительная загрузка текущих новостей при старте для исключения дубликатов
    for exchange, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                link = entry.get("link", "")
                if link:
                    processed_links.add(link)
        except Exception as e:
            print(f"⚠️ Ошибка первичной подгрузки RSS {exchange}: {e}")
            
    print(f"✅ База защиты от дублей сформирована ({len(processed_links)} ссылок). Мониторинг в работе.")

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
                print(f"❌ Ошибка при парсинге {exchange}: {e}")
                
        time.sleep(300)


def monitor_funding():
    """Фоновый поток: мониторинг критического фандинга каждые 30 минут (порог ±0.9%)"""
    print("🚀 Модуль мониторинга фандинга запущен...")
    while True:
        try:
            url = "https://api.bybit.com/v5/market/tickers?category=linear"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if data.get("retCode") == 0:
                for item in data["result"]["list"]:
                    symbol = item.get("symbol", "")
                    funding_rate = float(item.get("fundingRate", 0)) * 100
                    
                    if abs(funding_rate) >= 0.9:
                        markup = telebot.types.InlineKeyboardMarkup()
                        trade_url = f"https://www.bybit.com/trade/usdt/{symbol}"
                        markup.add(telebot.types.InlineKeyboardButton(f"📱 Открыть {symbol} на Bybit", url=trade_url))
                        
                        text = (
                            f"⚡ **Внимание! Высокий фандинг**\n\n"
                            f"📌 **Биржа:** Bybit\n"
                            f"🪙 **Монета:** `{symbol}`\n"
                            f"📊 **Ставка:** `{funding_rate:.4f}%`\n"
                            f"⚙️ **Макс. плечо:** Доступно в терминале\n"
                            f"🔗 **Ссылка:** [Открыть фьючерсы]({trade_url})"
                        )
                        
                        bot.send_message(
                            chat_id=CHAT_ID,
                            message_thread_id=EXCHANGE_CHATS["FUNDING"],
                            text=text,
                            parse_mode="Markdown",
                            reply_markup=markup
                        )
                        time.sleep(1)
        except Exception as e:
            print(f"❌ Ошибка в мониторинге фандинга: {e}")
            
        time.sleep(1800)


def monitor_spread():
    """Фоновый поток: мониторинг спреда"""
    print("🚀 Модуль мониторинга спреда запущен...")
    while True:
        try:
            pass
        except Exception as e:
            print(f"❌ Ошибка в мониторинге спреда: {e}")
            
        time.sleep(600)


# 1. Автоудаление пользовательских сообщений в защищенных топиках
@bot.message_handler(func=lambda message: message.message_thread_id in RESTRICTED_TOPICS)
def auto_delete_user_messages(message):
    if not message.from_user.is_bot:
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            pass


# 2. Команды /start и /help (Доступ только для владельца в ЛС)
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.chat.type == "private" and message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ ограничен. Этот бот работает в приватном режиме.")
        return
    bot.reply_to(message, "👋 **CryptoMonitor Bot запущен и работает в штатном режиме!**")


# 3. Обработка ручных запросов (Защита от сторонних пользователей)
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    # Блокировка личных сообщений от сторонних пользователей
    if message.chat.type == "private" and message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ в личные сообщения бота ограничен.")
        return

    # В супергруппе реагируем только в разрешенных незащищенных ветках
    if message.chat.type in ["group", "supergroup"] and message.message_thread_id in RESTRICTED_TOPICS:
        return

    user_text = message.text
    sent_msg = bot.reply_to(message, "🔍 Анализирую анонс...")

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
    # Запуск всех модулей без приветственного спама
    threading.Thread(target=monitor_rss, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    
    print("🤖 CryptoMonitor Bot запущен и готов к работе!")
    
    # Защищенный цикл бесконечного подбора сообщений
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as e:
            print(f"⚠️ Сбой сети/Telegram API: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
