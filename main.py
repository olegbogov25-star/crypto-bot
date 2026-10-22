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

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyHealthCheckHandler)
    server.serve_forever()
# ===================================================================

# ==================== НАСТРОЙКИ И ТОПИКИ ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ВАШ_ТОКЕН_БОТА_ОТ_BOTFATHER")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "ВАШ_КЛЮЧ_OPENROUTER")

CHAT_ID = "-1004451728851"
ADMIN_IDS = [1043209905]  # Твой административный ID

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
    "ORBIT": 0,       # Мультибиржевой поток
    "FUNDING": 76,    # Ветка для фандинга (±0.5%)
    "SPREAD": 77,     # Ветка для спреда (от 3%+)
}

RESTRICTED_TOPICS = set(v for v in EXCHANGE_CHATS.values() if v != 0)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

MODEL_NAME = "openai/gpt-4o-mini"

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
2. ИГНОРИРУЙ СУХИЕ ЛИСТИНГИ — если токен просто добавляется на спот/фьючерсы/маржу и при этом НЕТ никакой раздачи, призового пула, аирдропа, пула бустов или промо-акции!
3. ЕСЛИ СОБЫТИЕ НЕ СОДЕРЖИТ КОНКРЕТНЫХ НАГРАД, ПРИЗОВОГО ФОНДА ИЛИ АИРДРОПА — НАПИШИ РОВНО ОДНО СЛОВО: SKIP

✅ СОСТАВЛЯЙ ОТЧЕТ ТОЛЬКО ЕСЛИ:
Событие содержит ДОХОДНУЮ СОСТАВЛЯЮЩУЮ (аирдроп, фарминг, награды за депозит/торговлю, Web3-квесты, бонусы, X Launch, Boost, Launchpool/Megadrop/Alpha).

Составляй чёткий, структурированный отчёт на русском языке strictly по шаблону:

📌 **Биржа / Источник:** [Укажи биржу и раздел]
🏷 **Тип события / Теги:** [#Listing, #Launchpad, #Launchpool, #Megadrop, #Alpha, #AirDrop, #Web3Airdrop, #Web3Quest, #Boost, #XLaunch, #PoolX, #GemsPool, #Promotion, #RewardCenter]

💰 **Токен / Проект:** [Название и тикер]
📅 **Даты / Время проведения:** [Период]
📋 **Краткое описание:** [Суть анонса, буста, Web3-квеста или промо-акции]

⚡ **Что нужно сделать (Инструкция / Пошагово):**
- [Шаг 1]
- [Шаг 2]

🎁 **Награды / Призовой фонд:** [Пулы, APY, бонусы, аирдроп]
⚠️ **Важные условия / Ограничения и риски:** [Риски, KYC, Сеть/Кошелек]
🔗 **Ссылка на источник/акцию:** [Ссылка]
"""

RSS_FEEDS = {
    "BINANCE": "https://www.binance.com/en/support/announcement/rss",
    "BYBIT": "https://announcements.bybit.com/en-US/rss/",
    "OKX": "https://www.okx.com/support/rss",
    "GATE": "https://www.gate.io/rss/article/all",
    "BITGET": "https://www.bitget.com/support/rss"
}

processed_items = set()
processed_arbitrage = set()

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

# Поток 1: Гибридный мониторинг новостей (RSS + Прямые API бирж)
def monitor_news_hybrid():
    print("🚀 Тотальный гибридный модуль мониторинга новостей запущен...")
    while True:
        # 1. RSS
        for exchange, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    link = entry.get("link", "")
                    title = entry.get("title", "")
                    summary = entry.get("summary", title)
                    item_id = link or title
                    
                    if item_id and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, summary, link, exchange)
            except Exception as e:
                print(f"❌ Ошибка RSS {exchange}: {e}")

        # 2. Binance API
        try:
            b_res = requests.get("https://www.binance.com/bapi/composite/v1/public/content/support/search/list?type=1&pageNo=1&pageSize=10", timeout=10)
            if b_res.status_code == 200:
                articles = b_res.json().get("data", {}).get("catalogs", [{}])[0].get("articles", [])
                for art in articles:
                    title = art.get("title", "")
                    code = art.get("code", "")
                    link = f"https://www.binance.com/en/support/announcement/{code}" if code else "https://www.binance.com"
                    item_id = f"binance_api_{code or title}"
                    if item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "BINANCE")
        except Exception as e:
            print(f"⚠️ Ошибка Binance Direct API: {e}")

        # 3. Bybit API
        try:
            by_res = requests.get("https://api.bybit.com/v5/announcements/index?locale=en-US&limit=10", timeout=10)
            if by_res.status_code == 200:
                list_items = by_res.json().get("result", {}).get("list", [])
                for item in list_items:
                    title = item.get("title", "")
                    link = item.get("link", "https://announcements.bybit.com")
                    item_id = f"bybit_api_{title}"
                    if item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, item.get("description", title), link, "BYBIT")
        except Exception as e:
            print(f"⚠️ Ошибка Bybit Direct API: {e}")

        # 4. OKX API
        try:
            okx_res = requests.get("https://www.okx.com/api/v5/support/announcements?page=1", timeout=10)
            if okx_res.status_code == 200:
                details = okx_res.json().get("data", [{}])[0].get("details", [])
                for ann in details[:10]:
                    title = ann.get("title", "")
                    link = ann.get("url", "https://www.okx.com/support")
                    item_id = f"okx_api_{title}"
                    if item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "OKX")
        except Exception as e:
            print(f"⚠️ Ошибка OKX Direct API: {e}")

        # 5. Gate.io API
        try:
            g_res = requests.get("https://www.gate.io/json_svr/query/?u=10&c=11000&type=1&page=1&status=1", timeout=10)
            if g_res.status_code == 200:
                items = g_res.json().get("data", []) or g_res.json().get("list", [])
                for item in items:
                    title = item.get("title", "")
                    art_id = item.get("id", "")
                    link = f"https://www.gate.io/article/{art_id}" if art_id else "https://www.gate.io"
                    item_id = f"gate_api_{art_id or title}"
                    if title and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "GATE")
        except Exception as e:
            print(f"⚠️ Ошибка Gate Direct API: {e}")

        # 6. Bitget API
        try:
            bg_res = requests.get("https://www.bitget.com/v1/support/bulletin/notices?language=en_US&pageSize=10", timeout=10)
            if bg_res.status_code == 200:
                notices = bg_res.json().get("data", {}).get("resultList", [])
                for n in notices:
                    title = n.get("annTitle", "")
                    nid = n.get("annId", "")
                    link = f"https://www.bitget.com/support/articles/{nid}" if nid else "https://www.bitget.com"
                    item_id = f"bitget_api_{nid or title}"
                    if title and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "BITGET")
        except Exception as e:
            print(f"⚠️ Ошибка Bitget Direct API: {e}")

        # 7. MEXC API
        try:
            mexc_res = requests.get("https://www.mexc.com/api/platform/announcement/list?page=1&pageSize=10", timeout=10)
            if mexc_res.status_code == 200:
                mexc_list = mexc_res.json().get("data", {}).get("resultList", [])
                for m in mexc_list:
                    title = m.get("title", "")
                    mid = m.get("id", "")
                    link = f"https://www.mexc.com/support/articles/{mid}" if mid else "https://www.mexc.com"
                    item_id = f"mexc_api_{mid or title}"
                    if title and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "MEXC")
        except Exception as e:
            print(f"⚠️ Ошибка MEXC Direct API: {e}")

        # 8. BingX API
        try:
            bx_res = requests.get("https://ck.bingx.com/api/v1/notice/list?language=en-US&pageNo=1&pageSize=10", timeout=10)
            if bx_res.status_code == 200:
                bx_list = bx_res.json().get("data", {}).get("list", [])
                for bx in bx_list:
                    title = bx.get("title", "")
                    bid = bx.get("id", "")
                    link = f"https://bingx.com/en-us/support/articles/{bid}" if bid else "https://bingx.com"
                    item_id = f"bingx_api_{bid or title}"
                    if title and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "BINGX")
        except Exception as e:
            print(f"⚠️ Ошибка BingX Direct API: {e}")

        # 9. KuCoin API
        try:
            kc_res = requests.get("https://api.kucoin.com/api/v1/bulletins?currentPage=1&pageSize=10", timeout=10)
            if kc_res.status_code == 200:
                kc_items = kc_res.json().get("data", {}).get("items", [])
                for k in kc_items:
                    title = k.get("title", "")
                    kid = k.get("code", "")
                    link = f"https://www.kucoin.com/news/{kid}" if kid else "https://www.kucoin.com"
                    item_id = f"kucoin_api_{kid or title}"
                    if title and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "KUCOIN")
        except Exception as e:
            print(f"⚠️ Ошибка KuCoin Direct API: {e}")

        # 10. Kraken API
        try:
            kr_res = requests.get("https://support.kraken.com/api/v2/help_center/en-us/articles.json", timeout=10)
            if kr_res.status_code == 200:
                articles = kr_res.json().get("articles", [])
                for a in articles[:10]:
                    title = a.get("title", "")
                    link = a.get("html_url", "https://support.kraken.com")
                    item_id = f"kraken_api_{title}"
                    if title and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "KRAKEN")
        except Exception as e:
            print(f"⚠️ Ошибка Kraken Direct API: {e}")

        # 11. WhiteBit API
        try:
            wb_res = requests.get("https://whitebit.com/api/v4/public/announcements", timeout=10)
            if wb_res.status_code == 200:
                wb_data = wb_res.json().get("result", [])
                for w in wb_data[:10]:
                    title = w.get("title", "")
                    link = w.get("url", "https://whitebit.com")
                    item_id = f"whitebit_api_{title}"
                    if title and item_id not in processed_items:
                        processed_items.add(item_id)
                        if len(processed_items) > 2500:
                            processed_items.pop()
                        analyze_and_send(title, title, link, "WHITEBIT")
        except Exception as e:
            print(f"⚠️ Ошибка WhiteBit Direct API: {e}")

        time.sleep(300)

# Поток 2: Мониторинг Web3 OKX
def monitor_web3():
    print("🌐 Модуль мониторинга Web3 запущен...")
    while True:
        try:
            okx_ann_url = "https://www.okx.com/api/v5/support/announcements?page=1"
            res = requests.get(okx_ann_url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("code") == "0" and "data" in data:
                    for ann in data["data"][0].get("details", [])[:10]:
                        title = ann.get("title", "")
                        link = ann.get("url", "https://www.okx.com/web3")
                        if title and title not in processed_items:
                            processed_items.add(title)
                            if len(processed_items) > 2500:
                                processed_items.pop()
                            analyze_and_send(title, title, link, "OKX Web3 Boost")
        except Exception as e:
            print(f"⚠️ Ошибка OKX Ann API: {e}")

        try:
            okx_web3_url = "https://www.okx.com/priapi/v1/ip/web3/wallet/activity/list?page=1&limit=10"
            headers = {"User-Agent": "Mozilla/5.0"}
            res_web3 = requests.get(okx_web3_url, headers=headers, timeout=10)
            if res_web3.status_code == 200:
                web3_data = res_web3.json()
                if web3_data.get("code") == 0 and "data" in web3_data:
                    activities = web3_data.get("data", {}).get("list", [])
                    for act in activities[:5]:
                        title = act.get("title") or act.get("projectName", "")
                        desc = act.get("description", title)
                        link = "https://www.okx.com/web3/rewards"
                        item_id = f"web3_{title}"
                        
                        if title and item_id not in processed_items:
                            processed_items.add(item_id)
                            if len(processed_items) > 2500:
                                processed_items.pop()
                            analyze_and_send(title, desc, link, "OKX Web3 Boost")
        except Exception as e:
            print(f"⚠️ Ошибка OKX Web3 Direct API: {e}")
            
        time.sleep(720)

# Поток 3: Сканер фандинга (±0.5%)
def monitor_funding():
    print("⚡ Модуль арбитража фандинга запущен (порог ±0.5%)...")
    while True:
        try:
            res = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=10)
            if res.status_code == 200:
                data = res.json()
                for item in data:
                    symbol = item.get("symbol", "")
                    last_funding = float(item.get("lastFundingRate", 0)) * 100
                    
                    if abs(last_funding) >= 0.5:
                        alert_id = f"funding_{symbol}_{round(last_funding, 2)}"
                        if alert_id not in processed_arbitrage:
                            processed_arbitrage.add(alert_id)
                            if len(processed_arbitrage) > 500:
                                processed_arbitrage.pop()
                            
                            direction = "🔥 Аномальный фандинг (Лонги платят шортам)" if last_funding > 0 else "❄️ Аномальный фандинг (Шорты платят лонгам)"
                            msg = (
                                f"⚡ **Арбитраж Фандинга (Binance)**\n\n"
                                f"🪙 **Монета:** `{symbol}`\n"
                                f"📊 **Ставка фандинга:** `{last_funding:.3f}%`\n"
                                f"💡 **Тип:** {direction}\n"
                                f"⏱ **Периодичность:** Каждые 8 часов"
                            )
                            bot.send_message(CHAT_ID, message_thread_id=EXCHANGE_CHATS["FUNDING"], text=msg, parse_mode="Markdown")
        except Exception as e:
            print(f"❌ Ошибка в сканере фандинга: {e}")
        time.sleep(300)

# Поток 4: Сканер межбиржевого спреда (от 3%+)
def monitor_spread():
    print("🔀 Модуль мониторинга спреда запущен...")
    while True:
        try:
            binance_res = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=10)
            okx_res = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SPOT", timeout=10)
            
            if binance_res.status_code == 200 and okx_res.status_code == 200:
                binance_prices = {item['symbol']: float(item['price']) for item in binance_res.json()}
                okx_data = okx_res.json().get('data', [])
                okx_prices = {item['instId'].replace("-", ""): float(item['last']) for item in okx_data if "-" in item['instId']}
                
                common_symbols = set(binance_prices.keys()).intersection(set(okx_prices.keys()))
                
                for sym in common_symbols:
                    p_binance = binance_prices[sym]
                    p_okx = okx_prices[sym]
                    
                    if p_binance > 0 and p_okx > 0:
                        spread = abs(p_binance - p_okx) / min(p_binance, p_okx) * 100
                        
                        if spread >= 3.0:
                            if spread >= 10.0:
                                level_tag = "🚀 СПРЕД ≥ 10% (ЭКСТРИМ)"
                            elif spread >= 7.0:
                                level_tag = "🔥 СПРЕД ≥ 7%"
                            elif spread >= 5.0:
                                level_tag = "⚡ СПРЕД ≥ 5%"
                            else:
                                level_tag = "📊 СПРЕД ≥ 3%"
                                
                            alert_id = f"spread_{sym}_{round(spread, 1)}"
                            if alert_id not in processed_arbitrage:
                                processed_arbitrage.add(alert_id)
                                if len(processed_arbitrage) > 500:
                                    processed_arbitrage.pop()
                                
                                cheaper = "Binance" if p_binance < p_okx else "OKX"
                                expier = "OKX" if cheaper == "Binance" else "Binance"
                                
                                msg = (
                                    f"🔀 **Межбиржевой спред: {level_tag}**\n\n"
                                    f"🪙 **Монета:** `{sym}`\n"
                                    f"📈 **Разница цен:** `{spread:.2f}%`\n"
                                    f"🟢 **Дешевле на {cheaper}:** `{'%.6f' % min(p_binance, p_okx)}`\n"
                                    f"🔴 **Дороже на {expier}:** `{'%.6f' % max(p_binance, p_okx)}`\n"
                                    f"💡 **Направление:** Покупка на {cheaper} -> Перевод/Продажа на {expier}"
                                )
                                bot.send_message(CHAT_ID, message_thread_id=EXCHANGE_CHATS["SPREAD"], text=msg, parse_mode="Markdown")
        except Exception as e:
            print(f"❌ Ошибка в сканере спреда: {e}")
        time.sleep(300)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if message.chat.type == "private" and message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ ограничен.")
        return
    bot.reply_to(message, "👋 **CryptoMonitor Bot запущен в автономном режиме!**")

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Запуск фоновых задач мониторинга
    threading.Thread(target=monitor_news_hybrid, daemon=True).start()
    threading.Thread(target=monitor_web3, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    
    print("🤖 CryptoMonitor Bot полностью запущен и автономен!")
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as e:
            print(f"⚠️ Сбой сети/Telegram API: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
