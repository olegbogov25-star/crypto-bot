import os
import logging
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Получаем API-ключи из переменных окружения (Render)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("ОШИБКА: Отсутствуют ключи в Environment Variables на Render!")

# Настройка официального клиента Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
Ты — профессиональный крипто-аналитик, листинг-трекер и охотник за промоакциями на биржах.
Твоя задача — проанализировать текст анонса с биржи (Binance, OKX, Bybit, MEXC, Bitget, KuCoin, Gate, HTX, BingX, CoinEx и др.), перевести его на русский язык и выдать сухую, структурированную выжимку строго по следующему шаблону:

Учитывай абсолютно все типы биржевых событий и промо-активностей:
1. Листинги (Listing, New Coin, Spot Trading, Futures Listing)
2. Фарминг и пассивный доход (Launchpool, Launchpad, Megadrop, Staking, Earn, Simple Earn, Savings)
3. Прогнозы и игры (Prediction Market, Price Prediction, Esports Prediction, Voting, Quiz, M-Day, Candy Bomb)
4. Социальная активность и контент (Binance Square, Feed, Write to Earn, Creators Campaign, Activity Splash)
5. Промо и конкурсы (Trading Competition, Tournament, Volume Challenge, Task Center, Mystery Box, Airdrop, Bounty, Giveaways, Boost, Rebate)

Шаблон ответа:
🚀 **[Название биржи] Событие (Категория события)**

📝 **Суть акции:**
(Короткая выжимка в 1-2 предложениях: что за событие, ключевые условия, призовой фонд и даты проведения)

⚡ **Что делать:**
1. (Пошаговое простое действие)
2. (Пошаговое действие)

⚠️ **Риски и вложения:**
(Нужны ли вложения, есть ли финансовые или технические риски, либо это полностью бесплатно)

🔗 **[Перейти к анонсу / акции](ВСТАВЬ_ССЫЛКУ_ЕСЛИ_ЕСТЬ)**

Пиши кратко, емко, без приветствий и лишней «воды».
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Бот-трекер промоакций, листингов и прогнозов бирж успешно запущен!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    if user_text.strip().lower() in ["/start", "start"]:
        await start(update, context)
        return

    await update.message.reply_text("🔍 Анализирую анонс через Gemini...")

    full_prompt = f"{SYSTEM_PROMPT}\n\nВот текст анонса для анализа:\n{user_text}"
    
    response_text = None
    # Увеличиваем количество попыток до 5 и паузу до 4 секунд для бесплатного тарифа
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=full_prompt,
            )
            if response.text:
                response_text = response.text
                break
        except Exception as e:
            logging.warning(f"Попытка {attempt + 1} не удалась: {e}")
            time.sleep(4)  # Даем серверам Google 4 секунды на передышку

    if response_text:
        await update.message.reply_text(response_text, parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠️ Бесплатные сервера Google сейчас сильно перегружены. Попробуйте отправить текст ещё раз через пару минут.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот успешно запущен...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
