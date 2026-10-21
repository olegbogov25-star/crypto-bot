import os
import time
import threading
import feedparser
import telebot
from openai import OpenAI

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID")  # ID твоего чата или канала, куда слать авто-разборы

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("Ошибка: Не найден TELEGRAM_TOKEN или OPENROUTER_API_KEY в переменных окружения!")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """
Ты — специализированный криптоаналитик для автоматического отслеживания и разбора официальных анонсов, акций, листингов, Web3-квестов и промо-кампаний от следующих 10 ключевых бирж и связанных экосистем:
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

Твоя задача — проанализировать входящий текст официального анонса и составить чёткий, структурированный отчёт на русском языке strictly по следующему шаблону:

📌 **Биржа / Источник:** [Укажи конкретную биржу или Web3-кошелек из списка выше]
🏷 **Тип события / Теги:** [Подбери точные англоязычные теги из списка: #Listing, #NewListing, #InitialListing, #PreMarket, #Launchpad, #Launchpool, #CandyDrop, #Startup, #Kickstarter, #Pool, #AirDrop, #Web3Airdrop, #Web3Quest, #Cryptopedia, #Campaign, #Promotion, #Activity, #Event, #TradingCompetition, #FuturesCompetition, #SpotCompetition, #PredictToWin, #FuturesPricePrediction, #Leaderboard, #WODL, #WordOfTheDay, #LearnAndEarn, #Quiz, #TaskCenter, #RewardsHub, #MysteryBox, #LuckyDraw, #SpinAndWin, #DailyCheckIn, #ReferralProgram, #Staking, #Earn, #SimpleEarn, #Savings, #DualInvestment, #FeeRebate, #FuturesBonus, #ZeroFee, #Futures, #Spot, #CopyTrading, #GridTrading, #P2P, #Delisting]

💰 **Токен / Проект:** [Название токена и тикер, например: BTC, NOT, DOGS, HMSTR]
📅 **Даты / Время проведения:** [Период проведения, даты снимков баланса, время листинга, дедлайны]
📋 **Краткое описание:** [2-3 предложения — главная суть анонса/акции/квеста]

⚡ **Что нужно сделать (Инструкция / Пошагово):**
- [Шаг 1: Пройти KYC / Подключить Web3 Wallet / Депозит / Регистрация]
- [Шаг 2: Сделать Swap / Торговый объем / Собрать конфеты в CandyDrop / Участие в Startup]
- [Шаг 3: Ожидание распределения наград или клейм]

🎁 **Награды / Призовой фонд:** [Общий призовой пул, ваучеры, плечи, размеры наград на человека]
⚠️ **Важные условия / Ограничения и риски:** [Ограничения по странам, комиссии сети, уровни KYC, мин. объем, оценка рисков]
🔗 **Ссылка на источник/акцию:** [Вставь прямую официальную ссылку из текста]
📱 **Переход в приложение:** [Укажи инструкцию, как открыть акцию в официальном мобильном приложении биржи, например: Откройте приложение Binance -> Меню More -> Binance Alpha / Launchpad]
"""

# Список официальных RSS-источников бирж для автоматического мониторинга
RSS_FEEDS = {
    "Binance": "https://www.binance.com/en/support/announcement/rss",
    "Bybit": "https://announcements.bybit.com/en-US/rss/",
    "OKX": "https://www.okx.com/support/rss",
    "Gate.io": "https://www.gate.io/rss/article/all",
    "Bitget": "https://www.bitget.com/support/rss"
}

# Множество для хранения уже обработанных ссылок, чтобы не слать дубликаты
processed_links = set()

def analyze_and_send(title, summary, link, exchange_name):
    """Функция отправки текста на анализ в ИИ и рассылки в Telegram"""
    if not TARGET_CHAT_ID:
        return
    
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
        
        # Отправляем готовый отчет в целевой чат
        bot.send_message(TARGET_CHAT_ID, answer, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка при ИИ-анализе RSS: {e}")

def monitor_rss():
    """Фоновый поток для периодической проверки официальных RSS-лент бирж"""
    print("🚀 Модуль автомониторинга официальных источников запущен...")
    while True:
        for exchange, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                # Берем свежие 3 новости из ленты
                for entry in feed.entries[:3]:
                    link = entry.get("link", "")
                    title = entry.get("title", "")
                    summary = entry.get("summary", title)
                    
                    if link and link not in processed_links:
                        processed_links.add(link)
                        # Ограничиваем размер кеша обработанных ссылок
                        if len(processed_links) > 500:
                            processed_links.pop()
                            
                        # Запускаем анализ и постинг
                        analyze_and_send(title, summary, link, exchange)
            except Exception as e:
                print(f"Ошибка при парсинге {exchange}: {e}")
                
        # Проверяй новые анонсы каждые 5 минут (300 секунд)
        time.sleep(300)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "👋 **CryptoMonitor Bot с автомониторингом запущен!**\n\n"
        "Я автоматически сканирую официальные RSS-ленты Binance, Bybit, OKX, Gate.io и Bitget, "
        "делаю ИИ-разбор и присылаю сюда структурированные отчеты со ссылками и инструкциями для мобильных приложений."
    )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
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

        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=sent_msg.message_id,
            text=answer,
            parse_mode="Markdown"
        )

    except Exception as e:
        try:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=sent_msg.message_id,
                text=f"❌ Ошибка при обработке:\n{str(e)}"
            )
        except Exception:
            pass

if __name__ == "__main__":
    # Запускаем фоновый поток мониторинга официальных источников в параллельном режиме
    bg_thread = threading.Thread(target=monitor_rss, daemon=True)
    bg_thread.start()
    
    # Запуск приема команд и сообщений ботом
    bot.infinity_polling()
