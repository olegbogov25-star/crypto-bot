import time
import threading
import feedparser
from openai import OpenAI
import telebot

# ==================== НАСТРОЙКИ ====================
TELEGRAM_TOKEN = "ВАШ_ТОКЕН_БОТА_ОТ_BOTFATHER"  # Замени на свой токен
OPENROUTER_API_KEY = "ВАШ_КЛЮЧ_OPENROUTER"       # Замени на свой ключ OpenRouter

# ID твоей супергруппы ANTIGOI
CHAT_ID = "-1004451728851"

# Словарь веток (биржи + стейкинг) с их message_thread_id
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
    "STAKING": 14,  # Дополнительная ветка для Earn / Стейкинга
}

# Множество ID защищенных веток, куда обычным пользователям писать запрещено
RESTRICTED_TOPICS = set(EXCHANGE_CHATS.values())
# ===================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "openai/gpt-4o-mini"

SYSTEM_PROMPT = """
Ты — специализированный криптоаналитик для автоматического отслеживания и разбора официальных анонсов, акций, листингов, Web3-квестов и промо-кампаний от следующих ключевых бирж и связанных экосистем:
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
11. Staking / Earn / SimpleEarn / Savings / DualInvestment

Твоя задача — проанализировать входящий текст официального анонса и составить чёткий, структурированный отчёт на русском языке strictly по следующему шаблону:

📌 **Биржа / Источник:** [Укажи конкретную биржу или направление из списка выше]
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
📱 **Переход в приложение:** [Укажи инструкцию, как открыть акцию в официальном мобильном приложении биржи]
"""

# Список официальных RSS-источников бирж для автоматического мониторинга
RSS_FEEDS = {
    "BINANCE": "https://www.binance.com/en/support/announcement/rss",
    "BYBIT": "https://announcements.bybit.com/en-US/rss/",
    "OKX": "https://www.okx.com/support/rss",
    "GATE": "https://www.gate.io/rss/article/all",
    "BITGET": "https://www.bitget.com/support/rss"
}

# Множество для хранения уже обработанных ссылок (защита от дубликатов)
processed_links = set()


def analyze_and_send(title, summary, link, exchange_name):
    """Функция отправки текста на анализ в ИИ и рассылки в соответствующую ветку форума"""
    exchange_key = exchange_name.upper()
    if exchange_key not in EXCHANGE_CHATS:
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
        
        # Создаем инлайн-кнопку для быстрого перехода на акцию/источник
        markup = telebot.types.InlineKeyboardMarkup()
        if link:
            btn_app = telebot.types.InlineKeyboardButton(f"📱 Открыть акцию в {exchange_name}", url=link)
            markup.add(btn_app)
        
        # Отправляем готовый отчет в конкретную ветку биржи
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
    """Фоновый поток для периодической проверки официальных RSS-лент бирж"""
    print("🚀 Модуль автомониторинга официальных источников запущен...")
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
                        if len(processed_links) > 500:
                            processed_links.pop()
                            
                        analyze_and_send(title, summary, link, exchange)
            except Exception as e:
                print(f"❌ Ошибка при парсинге {exchange}: {e}")
                
        time.sleep(300)


def broadcast_start_messages():
    """Отправляет приветственное сообщение во все ветки при старте бота"""
    print("🚀 Запуск стартовой рассылки по всем веткам...")
    for category, thread_id in EXCHANGE_CHATS.items():
        if category == "STAKING":
            text = "💰 <b>Канал Staking & Earn активен!</b>\n\nЗдесь публикуются лучшие предложения по пассивному доходу."
        else:
            text = f"🤖 <b>Канал новостей {category} активен!</b>\n\nЗдесь будут публиковаться актуальные анонсы и обновления биржи."
            
        try:
            bot.send_message(
                chat_id=CHAT_ID,
                message_thread_id=thread_id,
                text=text,
                parse_mode="HTML"
            )
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ Ошибка при стартовой отправке в тему {category}: {e}")


# -------------------------------------------------------------
# Модерация: автоудаление сообщений пользователей из защищенных веток
# -------------------------------------------------------------
@bot.message_handler(func=lambda message: message.message_thread_id in RESTRICTED_TOPICS)
def auto_delete_user_messages(message):
    """Удаляет любые сообщения участников в темах бирж и стейкинга"""
    if not message.from_user.is_bot:
        try:
            bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            print(f"🗑 Удалено сообщение от @{message.from_user.username or message.from_user.id} из защищенной ветки.")
        except Exception as e:
            print(f"❌ Не удалось удалить сообщение: {e}")


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "👋 **CryptoMonitor Bot активен!**\n\n"
        "Бот автоматически отслеживает официальные RSS-ленты бирж, делает ИИ-разбор и присылает структурированные отчеты "
        "в соответствующие ветки форума."
    )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Ручной анализ текста, если отправить его боту напрямую"""
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
    # 1. Отправляем приветствия по всем веткам форума
    broadcast_start_messages()

    # 2. Запускаем фоновый поток мониторинга официальных RSS-источников
    bg_thread = threading.Thread(target=monitor_rss, daemon=True)
    bg_thread.start()
    
    # 3. Запуск приема команд и сообщений ботом
    print("🤖 Бот запущен и слушает события...")
    bot.infinity_polling(skip_pending=True)
