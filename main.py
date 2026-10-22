import os
import time
import threading
import requests
import feedparser
import telebot
from flask import Flask

# ==================== CONFIGURATION ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
CHAT_ID = os.environ.get("CHAT_ID")
ADMIN_IDS = [1043209905]

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# Полная карта топиков со всеми Web3, бустами, лаунчпулами и биржами
TOPICS = {
    "NEWS": 2, 
    "OKX_BOOST": 4, 
    "MEXC": 6, 
    "BYBIT": 8, 
    "BINANCE": 10,
    "BITGET": 12, 
    "BINGX": 14, 
    "KUCOIN": 16, 
    "WHITEBIT": 18, 
    "KRAKEN": 20,
    "FUNDING": 22, 
    "SPREAD": 24,
    "WEB3_MONITOR": 26  # Топик для OKX Web3, Binance Web3, альфа-боксов и квестов
}

processed_ids = set()
processed_arbitrage = set()
active_spreads = {}

# ==================== HEALTHCHECK SERVER ====================
@app.route('/')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==================== LINK GENERATOR ====================
def get_exchange_link(exchange, symbol):
    base_sym = symbol.replace('USDT', '')
    links = {
        "Binance": f"https://www.binance.com/en/futures/{base_sym}USDT",
        "Bybit": f"https://www.bybit.com/trade/usdt/{base_sym}USDT",
        "OKX": f"https://www.okx.com/trade-swap/{base_sym.lower()}-usdt-swap",
        "Gate": f"https://www.gate.io/futures/USDT/{base_sym}_USDT",
        "Bitget": f"https://www.bitget.com/futures/usdt/{base_sym}USDT",
        "MEXC": f"https://futures.mexc.com/exchange/{base_sym}_USDT",
        "BingX": f"https://bingx.com/futures/forward/{base_sym}USDT",
        "KuCoin": f"https://www.kucoin.com/futures/trade/{base_sym}USDTM",
        "WhiteBit": f"https://whitebit.com/trade/{base_sym}_USDT?type=futures",
        "Kraken": f"https://futures.kraken.com/derivatives/api/v3/tickers",
        "Ourbit": f"https://www.ourbit.com/futures/trade/{base_sym}_USDT"
    }
    url = links.get(exchange, "https://google.com")
    return f"[{exchange}]({url})"

def get_message_link(message_id):
    if not CHAT_ID:
        return ""
    clean_chat_id = str(CHAT_ID).replace("-100", "")
    thread_id = TOPICS.get("SPREAD", 24)
    return f"https://t.me/c/{clean_chat_id}/{message_id}?thread={thread_id}"

# ==================== ADVANCED AI & FULL WEB3 / PROMO CALCULATOR ====================
def analyze_text(text):
    if not OPENROUTER_API_KEY:
        return text
    prompt = f"""
Ты — главный крипто-аналитик и эксперт по абузу биржевых промо-акций, Web3-квестов, альфа-боксов, турниров и ваучерных механик. Проанализируй текст официального анонса и сформируй детальный структурированный отчет:

1. 📌 **Источник / Платформа:** Название биржи или экосистемы (OKX Web3, Binance Web3, Bybit, Bitget и т.д.).
2. 🏷 **Тип события / Теги:** Присвой ВСЕ подпадающие теги из расширенного списка:
   - Экосистемы и Web3: #OKX_Web3 #Binance_Web3 #Bybit_Web3 #Bitget_Web3 #Web3 #DApp #Quest #Task
   - Биржи: #Binance #Bybit #OKX #Bitget #MEXC #BingX #KuCoin #WhiteBit #Kraken #Gate #Ourbit
   - Активности, Альфа и Ваучеры: #Promotion #RewardCenter #Alpha #AlphaBox #MysteryBox #TradingTournament #Challenge #Boost #Booster #Launchpool #Launchpad #Airdrop #DepositBonus #Listing #NewListing #Earn #Savings #Staking #VoteToList #FeeRebate #Voucher #BetVoucher #MarginVoucher #IPO #PreMarket #IDO #IEO

3. 🪙 **Токен / Проект:** Участвующие монеты или активы.
4. 📅 **Даты проведения:** Период проведения.
5. 📋 **Краткое описание:** Суть акции, буста, турнира, ваучерной ставки или Web3-квеста.
6. ⚡ **Пошаговая инструкция:** Что нужно сделать (подключение кошелька, транзакции, фарминг, набивание объема под ваучеры).
7. 🎁 **Награды / Призовой фонд:** Все официальные награды (альфа-боксы, ваучеры на ставки/маржу, пулы токенов, бусты доходности).
8. 💡 **Детальный расчет комиссий, затрат на газ и профита (ОБЯЗАТЕЛЬНО для всех уровней):**
   - Распиши уровни объемов, депозитов, набивания оборота или транзакционных затрат ($100, $1,000, $5,000, $20,000 и т.д.).
   - Посчитай фьючерсную/спотовую комиссию (Taker ~0.05% x 2, Maker ~0.02% x 2) или затраты на газ в Web3-сетях.
   - Сопоставь затраты с официальной наградой (учитывая номинал ваучеров, шанс выпадения в альфа/мистери боксах) и выдай четкий математический вердикт: выгодно ли участвовать на каждом уровне!

- Если это служебное объявление без наград (ввод/вывод, техобслуживание, делистинг) — ответь строго одним словом: SKIP.

Текст для анализа:
{text}
"""
    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        data = res.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"AI Error: {e}")
        return text

def send_to_topic(topic_name, text):
    thread_id = TOPICS.get(topic_name)
    if thread_id and CHAT_ID:
        try:
            res = bot.send_message(chat_id=CHAT_ID, message_thread_id=thread_id, text=text, parse_mode="Markdown", disable_web_page_preview=True)
            return res.message_id
        except Exception as e:
            print(f"Send Error ({topic_name}): {e}")
    return None

def process_item(item_id, raw_text, default_topic):
    if item_id in processed_ids:
        return
    processed_ids.add(item_id)
    
    ai_result = analyze_text(raw_text)
    if "SKIP" in ai_result.upper():
        return
    
    # Автоматическая маршрутизация Web3 и Альфа новостей в отдельный топик
    target_topic = default_topic
    if any(tag in ai_result for tag in ["#OKX_Web3", "#Binance_Web3", "#Web3", "#Alpha", "#AlphaBox"]):
        target_topic = "WEB3_MONITOR"
        
    send_to_topic(target_topic, ai_result)

# ==================== FUTURES PRICES FETCHING (11 EXCHANGES) ====================
def fetch_futures_prices():
    prices = {}
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/price", timeout=5).json()
        for item in r:
            if item['symbol'].endswith('USDT'):
                prices.setdefault(item['symbol'], {})['Binance'] = float(item['price'])
    except Exception: pass

    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=5).json()
        for item in r.get('result', {}).get('list', []):
            if item['symbol'].endswith('USDT'):
                prices.setdefault(item['symbol'], {})['Bybit'] = float(item['lastPrice'])
    except Exception: pass

    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=5).json()
        for item in r.get('data', []):
            sym = item['instId'].replace('-USDT-SWAP', 'USDT').replace('-', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['OKX'] = float(item['last'])
    except Exception: pass

    try:
        r = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json()
        for item in r:
            sym = item['contract'].replace('_', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['Gate'] = float(item['last'])
    except Exception: pass

    try:
        r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=5).json()
        for item in r.get('data', []):
            sym = item['symbol'].replace('_UMCBL', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['Bitget'] = float(item['lastPr'])
    except Exception: pass

    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json()
        for item in r.get('data', []):
            sym = item['symbol'].replace('_', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['MEXC'] = float(item['lastPrice'])
    except Exception: pass

    try:
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=5).json()
        for item in r.get('data', []):
            sym = item['symbol'].replace('-', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['BingX'] = float(item['lastPrice'])
    except Exception: pass

    try:
        r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=5).json()
        for item in r.get('data', []):
            sym = item['symbol'].replace('USDTM', 'USDT')
            if sym.endswith('USDT') and 'lastTradePrice' in item:
                prices.setdefault(sym, {})['KuCoin'] = float(item['lastTradePrice'])
    except Exception: pass

    try:
        r = requests.get("https://whitebit.com/api/v4/public/futures", timeout=5).json()
        for item in r.get('result', []):
            sym = item['ticker'].replace('_', '')
            if sym.endswith('USDT') and 'last_price' in item:
                prices.setdefault(sym, {})['WhiteBit'] = float(item['last_price'])
    except Exception: pass

    try:
        r = requests.get("https://futures.kraken.com/derivatives/api/v3/tickers", timeout=5).json()
        for item in r.get('tickers', []):
            sym = item['symbol'].replace('PF_', '').replace('USD', 'USDT')
            if 'last' in item:
                prices.setdefault(sym, {})['Kraken'] = float(item['last'])
    except Exception: pass

    try:
        r = requests.get("https://api.ourbit.com/api/v1/futures/market/tickers", timeout=5).json()
        for item in r.get('data', []):
            sym = item.get('symbol', '')
            if sym.endswith('USDT') and 'close' in item:
                prices.setdefault(sym, {})['Ourbit'] = float(item['close'])
    except Exception: pass

    return prices

# ==================== SPREAD MONITOR (FAST SIGNALS, NO AI) ====================
def monitor_spread():
    while True:
        try:
            prices = fetch_futures_prices()
            current_scanned_syms = set()

            for sym, ex_data in prices.items():
                if len(ex_data) < 2:
                    continue
                
                min_ex = min(ex_data, key=ex_data.get)
                max_ex = max(ex_data, key=ex_data.get)
                min_p = ex_data[min_ex]
                max_p = ex_data[max_ex]
                
                if min_p <= 0: continue
                spread = ((max_p - min_p) / min_p) * 100
                
                if spread >= 3.0:
                    current_scanned_syms.add(sym)
                    
                    if sym not in active_spreads:
                        min_link = get_exchange_link(min_ex, sym)
                        max_link = get_exchange_link(max_ex, sym)
                        
                        overview_list = [f"🔹 {get_exchange_link(ex, sym)}: `${p}`" for ex, p in ex_data.items()]
                        overview = "\n".join(overview_list)
                        
                        msg_text = (
                            f"🚨 **#{sym} | Spread: {spread:.2f}%**\n\n"
                            f"🟢 **Long ({min_link}):** `${min_p}`\n"
                            f"🔴 **Short ({max_link}):** `${max_p}`\n\n"
                            f"📝 **All Exchanges Overview:**\n{overview}"
                        )
                        
                        msg_id = send_to_topic("SPREAD", msg_text)
                        if msg_id:
                            active_spreads[sym] = {
                                "msg_id": msg_id,
                                "start_time": time.time()
                            }
            
            expired_syms = []
            for sym in list(active_spreads.keys()):
                if sym not in current_scanned_syms or sym not in prices:
                    expired_syms.append(sym)
                else:
                    ex_data = prices[sym]
                    if len(ex_data) >= 2:
                        curr_min = min(ex_data.values())
                        curr_max = max(ex_data.values())
                        if curr_min > 0:
                            curr_spread = ((curr_max - curr_min) / curr_min) * 100
                            if curr_spread < 1.5:
                                expired_syms.append(sym)

            for sym in expired_syms:
                data = active_spreads.pop(sym, None)
                if data:
                    duration = int(time.time() - data["start_time"])
                    mins = duration // 60
                    secs = duration % 60
                    time_str = f"{mins}:{secs:02d}"
                    
                    post_link = get_message_link(data["msg_id"])
                    aligned_msg = f"[{sym}]({post_link}) aligned in {time_str}"
                    send_to_topic("SPREAD", aligned_msg)

        except Exception as e:
            print(f"Futures Spread Monitor Error: {e}")
        time.sleep(30)

# ==================== FUNDING MONITOR (FAST SIGNALS, NO AI) ====================
def monitor_funding():
    while True:
        try:
            try:
                for item in requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5).json():
                    check_and_send_funding("Binance", item['symbol'], float(item['lastFundingRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=5).json().get('result', {}).get('list', []):
                    if item.get('fundingRate'):
                        check_and_send_funding("Bybit", item['symbol'], float(item['fundingRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://www.okx.com/api/v5/public/funding-rate-all", timeout=5).json().get('data', []):
                    sym = item['instId'].replace('-USDT-SWAP', 'USDT').replace('-', '')
                    check_and_send_funding("OKX", sym, float(item['fundingRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json():
                    if 'funding_rate' in item:
                        check_and_send_funding("Gate", item['contract'].replace('_', ''), float(item['funding_rate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=5).json().get('data', []):
                    if item.get('fundingRate'):
                        check_and_send_funding("Bitget", item['symbol'].replace('_UMCBL', ''), float(item['fundingRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json().get('data', []):
                    if 'fundingRate' in item:
                        check_and_send_funding("MEXC", item['symbol'].replace('_', ''), float(item['fundingRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", timeout=5).json().get('data', []):
                    if 'lastFundingRate' in item:
                        check_and_send_funding("BingX", item['symbol'].replace('-', ''), float(item['lastFundingRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=5).json().get('data', []):
                    if 'fundingFeeRate' in item:
                        check_and_send_funding("KuCoin", item['symbol'].replace('USDTM', 'USDT'), float(item['fundingFeeRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://whitebit.com/api/v4/public/futures", timeout=5).json().get('result', []):
                    if 'funding_rate' in item:
                        check_and_send_funding("WhiteBit", item['ticker'].replace('_', ''), float(item['funding_rate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://futures.kraken.com/derivatives/api/v3/tickers", timeout=5).json().get('tickers', []):
                    if 'fundingRate' in item:
                        check_and_send_funding("Kraken", item['symbol'].replace('PF_', '').replace('USD', 'USDT'), float(item['fundingRate']) * 100)
            except Exception: pass

            try:
                for item in requests.get("https://api.ourbit.com/api/v1/futures/market/tickers", timeout=5).json().get('data', []):
                    if 'fundingRate' in item:
                        check_and_send_funding("Ourbit", item['symbol'], float(item['fundingRate']) * 100)
            except Exception: pass

        except Exception as e:
            print(f"Funding Monitor Error: {e}")
            
        time.sleep(120)

def check_and_send_funding(exchange, symbol, rate):
    if abs(rate) >= 0.5:
        sig_id = f"FUND_{exchange}_{symbol}_{rate:.2f}"
        if sig_id not in processed_arbitrage:
            processed_arbitrage.add(sig_id)
            ex_link = get_exchange_link(exchange, symbol)
            msg = (
                f"🔥 **HIGH FUNDING RATE >= ±0.5%**\n\n"
                f"🏦 **Биржа:** {ex_link}\n"
                f"🪙 **Монета:** #{symbol}\n"
                f"📊 **Ставка фандинга:** `{rate:+.2f}%`"
            )
            send_to_topic("FUNDING", msg)

# ==================== NEWS & RSS MONITORS ====================
def monitor_news():
    feeds = [
        ("https://cointelegraph.com/rss", "NEWS"),
        ("https://coindesk.com/arc/outboundfeeds/rss/", "NEWS")
    ]
    while True:
        for url, topic in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    process_item(entry.id, f"{entry.title}\n{entry.link}", topic)
            except Exception as e:
                print(f"RSS Error ({url}): {e}")
        time.sleep(120)

# ==================== TELEGRAM HANDLERS ====================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    if message.chat.type == "private" and message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "⛔ Доступ ограничен.")
        return
    bot.reply_to(message, "👋 **Bot запущен! Все Web3-модули, альфа-боксы, ваучерные ставки и ИИ-анализ активны.**", parse_mode="Markdown")

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    send_to_topic("SPREAD", "🟢 Бот запущен: мониторинг спредов, фандинга, Web3 и всех промо-акций активен!")
    
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_news, daemon=True).start()
    
    bot.infinity_polling()
