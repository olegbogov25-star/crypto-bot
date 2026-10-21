import os
import telebot
from openai import OpenAI

# 1. Получаем токены и ключи из переменных окружения Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Проверка, что ключи на месте
if not TELEGRAM_TOKEN:
    raise ValueError("Не найден TELEGRAM_TOKEN в переменных окружения!")
if not OPENROUTER_API_KEY:
    raise ValueError("Не найден OPENROUTER_API_KEY в переменных окружения!")

# 2. Инициализируем Telegram-бота
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# 3. Инициализируем клиент OpenRouter (он использует стандартный OpenAI-формат)
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Модель, которую используем (быстрая и недорогая Gemini 2.0 Flash через OpenRouter)
MODEL_NAME = "google/gemini-2.0-flash-001"


@bot.message_handler(commands=['start', 'help'])
class CommandHandler:
    pass # Заглушка для декоратора


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "Привет! Я крипто-бот, работающий через OpenRouter. Отправь мне текст анонса или вопрос, и я проанализирую его!"
    )


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_text = message.text
    
    # Отправляем пользователю статус, что бот думает
    sent_msg = bot.reply_to(message, "🔍 Анализирую запрос через OpenRouter...")

    try:
        # Делаем запрос к OpenRouter API
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
            top_p=1,
            temperature=0.7,
        )

        # Достаем ответ от модели
        answer = completion.choices[0].message.content

        # Редактируем сообщение с результатами анализа
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=sent_msg.message_id,
            text=answer
        )

    except Exception as e:
        error_text = f"❌ Произошла ошибка при обращении к OpenRouter:\n{str(e)}"
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=sent_msg.message_id,
            text=error_text
        )


if __name__ == "__main__":
    print("Бот запущен и слушает сообщения...")
    bot.infinity_polling()
