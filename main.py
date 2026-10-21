import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

# Настройка логов
logging.basicConfig(level=logging.INFO)

# Получаем ключи из переменных окружения Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Настраиваем Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Инструкция для нейросети (Промпт со словарем всех промоакций)
SYSTEM_PROMPT = """
Ты — профессиональный крипто-аналитик, листинг-трекер и охотник за халявой на биржах.
Твоя задача — проанализировать текст анонса с биржи (Binance, OKX, Bybit, MEXC, Bitget, KuCoin, Gate, HTX, BingX и др.), перевести его на русский язык и выдать четкую сухую выжимку строго по шаблону.

Учитывай все типы биржевых активностей:
- Листинги (Listing, New Coin, Spot/Futures)
- Фарминг (Launchpool, Launchpad, Megadrop, Staking)
- Прогнозы и игры (Prediction Market, Price Prediction, Esports Prediction, Voting, Quiz, M-Day, Candy Bomb)
- Посты и контент (Binance Square, Feed, Write to Earn, Creators Campaign)
- Промо и конкурсы (Activity Splash, Trading Competition, Tournament, Mystery Box, Airdrop, Bounty, Boost, Giveaways)

Шаблон ответа:
🚀 **[Название биржи] Событие (Категория события)**

📝 **Суть акции:**
(Короткая выжимка в 1-2 предложениях: что за событие, призовой фонд, условия и даты)

⚡ **Что делать:**
1. (Пошаговое действие)
2. (Пошаговое действие)

⚠️ **Риски и вложения:**
(Нужны ли вложения, есть ли риски или это бесплатно)

🔗 **[Перейти к анонсу / акции](ВСТАВЬ_ССЫЛКУ_ЕСЛИ_ЕСТЬ)**

Пиши кратко, по делу, без воды и приветствий.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Бот-трекер анонсов и промоакций бирж успешно запущен!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await update.message.reply_text("🔍 Анализирую анонс...")

    try:
        full_prompt = f"{SYSTEM_PROMPT}\n\nВот текст анонса для анализа:\n{user_text}"
        response = model.generate_content(full_prompt)
        await update.message.reply_text(response.text, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Ошибка Gemini: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при обработке. Попробуйте еще раз.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот запускается...")
    app.run_polling()

if __name__ == '__main__':
    main()
