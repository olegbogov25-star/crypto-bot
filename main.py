import os
import telebot
from openai import OpenAI

# Получаем ключи из переменных окружения Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Проверка токенов
if not TELEGRAM_TOKEN:
    raise ValueError("Не найден TELEGRAM_TOKEN в переменных окружения!")
if not OPENROUTER_API_KEY:
    raise ValueError("Не найден OPENROUTER_API_KEY в переменных окружения!")

# Инициализация Telegram-бота
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Инициализация клиента OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Используем стабильный идентификатор модели через OpenRouter
MODEL_NAME = "google/gemini-flash-1.5"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я крипто-бот. Отправь мне текст анонса, и я проанализирую его через OpenRouter.")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_text = message.text
    sent_msg = bot.reply_to(message, "🔍 Анализирую анонс через OpenRouter...")

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system", 
                    "content": "Ты профессиональный криптоаналитик. Отвечай чётко, структурировано и по делу на русском языке."
                },
                {
                    "role": "user", 
                    "content": user_text
                }
            ],
            temperature=0.7,
        )

        answer = completion.choices[0].message.content

        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=sent_msg.message_id,
            text=answer
        )

    except Exception as e:
        error_text = f"❌ Ошибка при запросе:\n{str(e)}"
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=sent_msg.message_id,
            text=error_text
        )

if __name__ == "__main__":
    bot.infinity_polling()
