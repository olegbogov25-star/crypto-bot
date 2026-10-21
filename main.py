import os
import telebot
from openai import OpenAI

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "google/gemini-2.0-flash-001"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я готов анализировать запросы через OpenRouter.")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_text = message.text
    sent_msg = bot.reply_to(message, "🔍 Анализирую анонс через OpenRouter...")

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Ты профессиональный криптоаналитик. Отвечай чётко и по делу на русском языке."},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
        )

        answer = completion.choices[0].message.content
        bot.edit_message_text(chat_id=message.chat.id, message_id=sent_msg.message_id, text=answer)

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=sent_msg.message_id, text=f"❌ Ошибка: {str(e)}")

if __name__ == "__main__":
    bot.infinity_polling()
