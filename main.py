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

TOPICS = {
    "NEWS": 2, "OKX_BOOST": 4, "MEXC": 6, "BYBIT": 8, "BINANCE": 10,
    "BITGET": 12, "BINGX": 14, "KUCOIN": 16, "WHITEBIT": 18, "KRAKEN": 20,
    "FUNDING": 22, "SPREAD": 24
}

processed_ids = set()
processed_arbitrage = set()

# ==================== HEALTHCHECK SERVER ====================
@app.route('/')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==================== AI ANALYSIS ====================
def analyze_text(text):
    if not OPENROUTER_API_KEY:
        return text
    prompt = f"""
Ты — профессиональный крипто-аналитик. Проанализируй текст и выдели только самое важное:
- Название акции/события, награды (в $ или токенах), даты, требования.
- Если это служебное объявление (ввод/вывод, техобслуживание, листинг без наград) — ответь строго одним словом: SKIP.

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
            bot.send_message(chat_id=CHAT_ID, message_thread_id=thread_id, text=text, parse_mode="Markdown")
        except Exception as e:
            print(f"Send Error ({topic_name}): {e}")

def process_item(item_id, raw_text, default_topic):
    if item_id in processed_ids:
        return
    processed_ids.add(item_id)
    
    ai_result = analyze_text(raw_text)
    if "SKIP" in ai_result.upper():
        return
    
    send_to_topic(default_topic, ai_result)

# ==================== ALL 11 EXCHANGES SPOT SPREAD SCANNER ====================
def fetch_prices_all_exchanges():
    """Собирает спотовые цены по всем 11 биржам"""
    prices = {} # symbol -> {exchange: price}
    
    # 1. Binance
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5).json()
        for item in r:
            sym = item['symbol']
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['Binance'] = float(item['price'])
    except Exception: pass

    # 2. Bybit
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=spot", timeout=5).json()
        for item in r.get('result', {}).get('list', []):
            sym = item['symbol']
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['Bybit'] = float(item['lastPrice'])
    except Exception: pass

    # 3. MEXC
    try:
        r = requests.get("https://api.mexc.com/api/v3/ticker/price", timeout=5).json()
        for item in r:
            sym = item['symbol']
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['MEXC'] = float(item['price'])
    except Exception: pass

    # 4. Gate.io
    try:
        r = requests.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=5).json()
        for item in r:
            sym = item['currency_pair'].replace('_', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['Gate'] = float(item['last'])
    except Exception: pass

    # 5. Bitget
    try:
        r = requests.get("https://api.bitget.com/api/v2/spot/market/tickers", timeout=5).json()
        for item in r.get('data', []):
            sym = item['symbol']
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['Bitget'] = float(item['close'])
    except Exception: pass

    # 6. OKX
    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SPOT", timeout=5).json()
        for item in r.get('data', []):
            sym = item['instId'].replace('-', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['OKX'] = float(item['last'])
    except Exception: pass

    # 7. BingX
    try:
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=5).json()
        for item in r.get('data', []):
            sym = item['symbol'].replace('-', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['BingX'] = float(item['lastPrice'])
    except Exception: pass

    # 8. KuCoin
    try:
        r = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=5).json()
        for item in r.get('data', {}).get('ticker', []):
            sym = item['symbol'].replace('-', '')
            if sym.endswith('USDT'):
                prices.setdefault(sym, {})['KuCoin'] = float(item['last'])
    except Exception: pass

    # 9. WhiteBit
    try:
        r = requests.get("https://whitebit.com/api/v4/public/ticker", timeout=5).json()
        for pair, data in r.items():
            sym = pair.replace('_', '')
            if sym.endswith('USDT') and 'last_price' in data:
                prices.setdefault(sym, {})['WhiteBit'] = float(data['last_price'])
    except Exception: pass

    # 10. Kraken
    try:
        r = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSDT,ETHUSDT,SOLUSDT,XRPUSDT", timeout=5).json()
        for pair, data in r.get('result', {}).items():
            sym = pair.replace('XBT', 'BTC').replace('X', '').replace('Z', '')
            if 'c' in data:
                prices.setdefault(sym, {})['Kraken'] = float(data['c'][0])
    except Exception: pass

    # 11. Ourbit (Spot)
    try:
        r = requests.get("https://api.ourbit.com/api/v1/spot/market/tickers", timeout=5).json()
        for item in r.get('data', []):
            sym = item.get('symbol', '')
            if sym.endswith('USDT') and 'close' in item:
                prices.setdefault(sym, {})['Ourbit'] = float(item['close'])
    except Exception: pass

    return prices

def monitor_spread():
    while True:
        try:
            prices = fetch_prices_all_exchanges()
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
                    sig_id = f"SPREAD_{sym}_{min_ex}_{max_ex}_{int(spread)}"
                    if sig_id not in processed_arbitrage:
                        processed_arbitrage.add(sig_id)
                        msg = (
                            f"🚨 **ARBITRAGE SPREAD >= 3%**\n\n"
                            f"🪙 **Монета:** #{sym}\n"
                            f"📈 **Спред:** `{spread:.2f}%`\n\n"
                            f"🟢 **Дешевле ({min_ex}):** `${min_p}`\n"
                            f"🔴 **Дороже ({max_ex}):** `${max_p}`"
                        )
                        send_to_topic("SPREAD", msg)
        except Exception as e:
            print(f"Spread Monitor Error: {e}")
        time.sleep(60)

# ==================== ALL 11 EXCHANGES FUNDING SCANNER ====================
def monitor_funding():
    while True:
        try:
            # 1. Binance
            try:
                r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5).json()
                for item in r:
                    check_and_send_funding("Binance", item['symbol'], float(item['lastFundingRate']) * 100)
            except Exception: pass

            # 2. Bybit
            try:
                r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=5).json()
                for item in r.get('result', {}).get('list', []):
                    if item.get('fundingRate'):
                        check_and_send_funding("Bybit", item['symbol'], float(item['fundingRate']) * 100)
            except Exception: pass

            # 3. OKX
            try:
                r = requests.get("https://www.okx.com/api/v5/public/funding-rate-all", timeout=5).json()
                for item in r.get('data', []):
                    sym = item['instId'].replace('-USDT-SWAP', 'USDT').replace('-', '')
                    check_and_send_funding("OKX", sym, float(item['fundingRate']) * 100)
            except Exception: pass

            # 4. Gate.io
            try:
                r = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json()
                for item in r:
                    if 'funding_rate' in item:
                        check_and_send_funding("Gate", item['contract'].replace('_', ''), float(item['funding_rate']) * 100)
            except Exception: pass

            # 5. Bitget
            try:
                r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=5).json()
                for item in r.get('data', []):
                    if item.get('fundingRate'):
                        check_and_send_funding("Bitget", item['symbol'].replace('_UMCBL', ''), float(item['fundingRate']) * 100)
            except Exception: pass

            # 6. MEXC
            try:
                r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json()
                for item in r.get('data', []):
                    if 'fundingRate' in item:
                        check_and_send_funding("MEXC", item['symbol'].replace('_', ''), float(item['fundingRate']) * 100)
            except Exception: pass

            # 7. BingX
            try:
                r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", timeout=5).json()
                for item in r.get('data', []):
                    if 'lastFundingRate' in item:
                        check_and_send_funding("BingX", item['symbol'].replace('-', ''), float(item['lastFundingRate']) * 100)
            except Exception: pass

            # 8. KuCoin
            try:
                r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=5).json()
                for item in r.get('data', []):
                    if 'fundingFeeRate' in item:
                        check_and_send_funding("KuCoin", item['symbol'].replace('USDTM', 'USDT'), float(item['fundingFeeRate']) * 100)
            except Exception: pass

            # 9. WhiteBit
            try:
                r = requests.get("https://whitebit.com/api/v4/public/futures", timeout=5).json()
                for item in r.get('result', []):
                    if 'funding_rate' in item:
                        check_and_send_funding("WhiteBit", item['ticker'].replace('_', ''), float(item['funding_rate']) * 100)
            except Exception: pass

            # 10. Kraken Futures
            try:
                r = requests.get("https://futures.kraken.com/derivatives/api/v3/tickers", timeout=5).json()
                for item in r.get('tickers', []):
                    if 'fundingRate' in item:
                        check_and_send_funding("Kraken", item['symbol'].replace('PF_', '').replace('USD', 'USDT'), float(item['fundingRate']) * 100)
            except Exception: pass

            # 11. Ourbit Futures
            try:
                r = requests.get("https://api.ourbit.com/api/v1/futures/market/tickers", timeout=5).json()
                for item in r.get('data', []):
                    if 'fundingRate' in item:
                        check_and_send_funding("Ourbit", item['symbol'], float(item['fundingRate']) * 100)
            except Exception: pass

        except Exception as e:
            print(f"Funding Monitor Error: {e}")
            
        time.sleep(180)

def check_and_send_funding(exchange, symbol, rate):
    if abs(rate) >= 0.5:
        sig_id = f"FUND_{exchange}_{symbol}_{rate:.2f}"
        if sig_id not in processed_arbitrage:
            processed_arbitrage.add(sig_id)
            msg = (
                f"🔥 **HIGH FUNDING RATE >= ±0.5%**\n\n"
                f"🏦 **Биржа:** {exchange}\n"
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
    bot.reply_to(message, "👋 **CryptoMonitor Bot запущен! Сканируем спреды и фандинг по 11 биржам (включая Ourbit)!**", parse_mode="Markdown")

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    send_to_topic("SPREAD", "🟢 Сканер спредов и фандинга обновлен: полный охват 11 бирж (включая Ourbit) активен!")
    
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_news, daemon=True).start()
    
    bot.infinity_polling()
