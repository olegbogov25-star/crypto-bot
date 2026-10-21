import os
import telebot
from openai import OpenAI

# 1. Загрузка токенов из переменных окружения Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("Ошибка: Не найден TELEGRAM_TOKEN или OPENROUTER_API_KEY в переменных окружения!")

# 2. Инициализация Telegram-бота и клиента OpenRouter
bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Исправленный ID модели для OpenRouter без ошибки 404
MODEL_NAME = "google/gemini-2.5-flash"

# 3. Полная системная инструкция (10 бирж + Web3 Wallets + Все теги + Фиксированный шаблон)
SYSTEM_PROMPT = """
Ты — специализированный криптоаналитик для автоматического отслеживания и разбора официальных анонсов, акций, листингов, Web3-квестов и промо-кампаний от следующих 10 ключевых бирж и связанных экосистем:
1. Binance (включая Binance Web3 Wallet)
2. Bybit
3. OKX (включая OKX Web3 Wallet / Cryptopedia)
4. MEXC
5. BingX
6. Gate.io
7. Bitget
8. KuCoin
9. Kraken
10. WhiteBIT

Твоя задача — проанализировать входящий текст анонса и составить чёткий, структурированный отчёт на русском языке strictly по следующему шаблону:

📌 **Биржа / Источник:** [Укажи конкретную биржу или Web3-кошелек из списка выше]
🏷 **Тип события / Теги:** [Подбери точные англоязычные теги из списка: #Listing, #NewListing, #InitialListing, #PreMarket, #Launchpad, #Launchpool, #Pool, #Kickstarter, #AirDrop, #Web3Airdrop, #Web3Quest, #Cryptopedia, #Campaign, #Promotion, #Activity, #Event, #TradingCompetition, #FuturesCompetition, #SpotCompetition, #PredictToWin, #FuturesPricePrediction, #Leaderboard, #WODL, #WordOfTheDay, #LearnAndEarn, #Quiz, #TaskCenter, #RewardsHub, #MysteryBox, #LuckyDraw, #SpinAndWin, #DailyCheckIn, #ReferralProgram, #Staking, #Earn, #SimpleEarn, #Savings, #DualInvestment, #FeeRebate, #FuturesBonus, #ZeroFee, #Futures, #Spot, #CopyTrading, #GridTrading, #P2P, #Delisting]

💰 **Токен / Проект:** [Название токена и тикер, например: BTC, NOT, DOGS, HMSTR]
📅 **Даты / Время проведения:** [Период проведения, даты снимков баланса, время листинга, дедлайны]
📋 **Краткое описание:** [2-3 предложения — главная суть анонса/акции/квеста]

⚡ **Что нужно сделать (Инструкция / Пошагово):**
- [Шаг 1: Пройти KYC / Подключить Web3 Wallet / Депозит / Регистрация]
- [Шаг 2: Сделать Swap / Торговый объем / Прогноз / Угадывание слов (WODL) / Стейкинг]
- [Шаг 3: Ожидание распределения наград или клейм]

🎁 **Награды / Призовой фонд:** [Общий призовой пул, ваучеры, плечи, размеры наград на человека]
⚠️ **Важные условия / Ограничения:** [Ограничения по странам, комиссии сети, уровни KYC, мин. объем]

Если присланный текст не относится напрямую к анонсам вышеуказанных бирж или Web3-кошельков, сделай краткую выжимку текста и проставь подходящие крипто-теги.
"""

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "👋 **CryptoMonitor Bot готов к работе!**\n\n"
        "Отправь мне текст анонса или промоакции с биржи или Web3-кошелька "
        "(Binance / Web3 Wallet, Bybit, OKX / Web3 Wallet, MEXC, BingX, Gate.io, Bitget, KuCoin, Kraken, WhiteBIT), "
        "и я сделаю полный разбор по тегам, датам и шагам!"
    )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_text = message.text
    sent_msg = bot.reply_to(message, "🔍 Анализирую анонс через OpenRouter...")

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
    bot.infinity_polling()
