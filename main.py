import os
import time
import threading
import requests
import feedparser
import telebot
from flask import Flask

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
CHAT_ID = "-1004451728851"
ADMIN_IDS = [1043209905]

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

TOPICS = {
    "NEWS": 2, "MEXC": 68, "BYBIT": 4, "BINANCE": 3, "BITGET": 69,   
    "BINGX": 70, "KUCOIN": 71, "WHITEBIT": 72, "KRAKEN": 73, "GATE": 67,     
    "FUNDING": 76, "SPREAD": 77    
}

processed_ids = set()
processed_arbitrage = set()
active_spreads = {}

@app.route('/')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def get_exchange_url(exchange, symbol):
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
        "Kraken": f"https://futures.kraken.com",
        "Ourbit": f"https://www.ourbit.com/futures/trade/{base_sym}_USDT"
    }
    return links.get(exchange, "https://google.com")

def normalize_symbol(raw_sym):
    if not raw_sym: return ""
    sym = raw_sym.upper().replace('_', '').replace('-', '').replace('/', '')
    if sym.endswith('USDTM'): sym = sym[:-1]
    if not sym.endswith('USDT'):
        if sym.endswith('USD'): sym = sym[:-3] + 'USDT'
        else: sym += 'USDT'
    return sym

def analyze_text(text):
    if not OPENROUTER_API_KEY: return text
    prompt = f"""
Ты — крипто-аналитик. Проанализируй анонс из RSS и выдай отчет:
1. 📌 Источник: Биржа/платформа.
2. 🏷 Теги (выбери из 42 тегов: #OKX_Web3 #Binance_Web3 #Bybit_Web3 #Web3 #XLaunch #XTrade #TokenSplash #Megadrop #BinanceSquare #Binance #Bybit #OKX #Bitget #MEXC #BingX #KuCoin #WhiteBit #Kraken #Gate #Ourbit #Promotion #Launchpool #Launchpad #Airdrop #Listing и др.).
3. 🪙 Токен. 4. Даты. 5. Описание. 6. Инструкция. 7. Награды. 8. Расчет профита для $100, $1K, $5K, $20K+.
Если служебное без наград (делистинг, техобслуживание) — SKIP.
Текст: {text}
"""
    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        return res.json()['choices'][0]['message']['content'].strip()
    except Exception:
        return text

def send_to_topic(topic_name, text, reply_to_message_id=None):
    thread_id = TOPICS.get(topic_name)
    if thread_id and CHAT_ID:
        try:
            res = bot.send_message(
                chat_id=CHAT_ID, message_thread_id=thread_id, text=text, 
                parse_mode="Markdown", disable_web_page_preview=True, reply_to_message_id=reply_to_message_id
            )
            return res.message_id
        except Exception: pass
    return None

def process_item(item_id, raw_text, default_topic):
    if item_id in processed_ids: return
    processed_ids.add(item_id)
    ai_result = analyze_text(raw_text)
    if "SKIP" in ai_result.upper(): return
    target_topic = default_topic
    upper_res = ai_result.upper()
    for ex_name in TOPICS.keys():
        if f"#{ex_name}" in upper_res or ex_name in upper_res:
            target_topic = ex_name
            break
    send_to_topic(target_topic, ai_result)

def fetch_futures_data():
    prices, volumes, fundings, funding_times = {}, {}, {}, {}
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=5).json()
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s: prices.setdefault(s, {})['Binance'] = float(i['lastPrice']); volumes.setdefault(s, {})['Binance'] = float(i['quoteVolume'])
    except Exception: pass
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5).json()
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s: fundings.setdefault(s, {})['Binance'] = float(i['lastFundingRate']) * 100; funding_times.setdefault(s, {})['Binance'] = int(i.get('nextFundingTime', 0)) // 1000
    except Exception: pass
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=5).json().get('result', {}).get('list', [])
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s:
                if 'lastPrice' in i: prices.setdefault(s, {})['Bybit'] = float(i['lastPrice']); volumes.setdefault(s, {})['Bybit'] = float(i.get('turnover24h', 0))
                if i.get('fundingRate'): fundings.setdefault(s, {})['Bybit'] = float(i['fundingRate']) * 100; funding_times.setdefault(s, {})['Bybit'] = int(i.get('nextFundingTime', 0)) // 1000
    except Exception: pass
    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i['instId'])
            if s: prices.setdefault(s, {})['OKX'] = float(i['last']); volumes.setdefault(s, {})['OKX'] = float(i.get('volCcy24h', 0))
    except Exception: pass
    try:
        r = requests.get("https://api.okx.com/api/v5/public/funding-rate-all", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i['instId'])
            if s and i.get('fundingRate'): fundings.setdefault(s, {})['OKX'] = float(i['fundingRate']) * 100; funding_times.setdefault(s, {})['OKX'] = int(i.get('nextFundingTime', 0)) // 1000
    except Exception: pass
    try:
        r = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json()
        for i in r:
            s = normalize_symbol(i['contract'])
            if s:
                prices.setdefault(s, {})['Gate'] = float(i['last'])
                volumes.setdefault(s, {})['Gate'] = float(i.get('total_size', 0)) * float(i['last'])
                if 'funding_rate' in i: fundings.setdefault(s, {})['Gate'] = float(i['funding_rate']) * 100; funding_times.setdefault(s, {})['Gate'] = int(i.get('funding_next_time', 0))
    except Exception: pass
    try:
        r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s:
                prices.setdefault(s, {})['Bitget'] = float(i['lastPr']); volumes.setdefault(s, {})['Bitget'] = float(i.get('quoteVolume', 0))
                if i.get('fundingRate'): fundings.setdefault(s, {})['Bitget'] = float(i['fundingRate']) * 100; funding_times.setdefault(s, {})['Bitget'] = int(i.get('nextFundingTime', 0)) // 1000
    except Exception: pass
    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s:
                prices.setdefault(s, {})['MEXC'] = float(i['lastPrice']); volumes.setdefault(s, {})['MEXC'] = float(i.get('amount24h', 0))
                if 'fundingRate' in i: fundings.setdefault(s, {})['MEXC'] = float(i['fundingRate']) * 100; funding_times.setdefault(s, {})['MEXC'] = int(i.get('nextSettleTime', 0)) // 1000
    except Exception: pass
    try:
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s: prices.setdefault(s, {})['BingX'] = float(i['lastPrice']); volumes.setdefault(s, {})['BingX'] = float(i.get('volume', 0))
    except Exception: pass
    try:
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s and 'lastFundingRate' in i: fundings.setdefault(s, {})['BingX'] = float(i['lastFundingRate']) * 100; funding_times.setdefault(s, {})['BingX'] = int(i.get('nextFundingTime', 0)) // 1000
    except Exception: pass
    try:
        r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i['symbol'])
            if s and 'lastTradePrice' in i:
                prices.setdefault(s, {})['KuCoin'] = float(i['lastTradePrice']); volumes.setdefault(s, {})['KuCoin'] = float(i.get('turnoverOf24h', 0))
                if 'fundingFeeRate' in i: fundings.setdefault(s, {})['KuCoin'] = float(i['fundingFeeRate']) * 100; funding_times.setdefault(s, {})['KuCoin'] = int(i.get('nextFundingRateTime', 0)) // 1000
    except Exception: pass
    try:
        r = requests.get("https://api.ourbit.com/api/v1/futures/market/tickers", timeout=5).json().get('data', [])
        for i in r:
            s = normalize_symbol(i.get('symbol', ''))
            if s and 'close' in i: prices.setdefault(s, {})['Ourbit'] = float(i['close']); volumes.setdefault(s, {})['Ourbit'] = float(i.get('vol', 0))
    except Exception: pass
    return prices, volumes, fundings, funding_times

def format_volume(vol):
    if vol >= 1_000_000: return f"${vol / 1_000_000:.1f}M (24h)"
    elif vol >= 1_000: return f"${vol / 1_000:.1f}K (24h)"
    else: return f"${vol:.0f} (24h)"

def format_countdown(target_timestamp):
    if not target_timestamp: return "N/A"
    diff = target_timestamp - time.time()
    if diff <= 0: return "0ч 00м"
    return f"{int(diff // 3600)}ч {int((diff % 3600) // 60):02d}м"

def monitor_spread():
    while True:
        try:
            prices, volumes, fundings, _ = fetch_futures_data()
            current_scanned_syms = set()
            for sym, ex_data in prices.items():
                if len(ex_data) < 2: continue
                min_ex = min(ex_data, key=ex_data.get)
                max_ex = max(ex_data, key=ex_data.get)
                min_p, max_p = ex_data[min_ex], ex_data[max_ex]
                if min_p <= 0: continue
                spread = ((max_p - min_p) / min_p) * 100
                
                if 7.0 <= spread <= 30.0:
                    current_scanned_syms.add(sym)
                    if sym not in active_spreads:
                        badge = "🔥🔥🔥 **MEGA SPREAD (>= 15%)**" if spread >= 15.0 else ("🔥 **HIGH SPREAD (>= 10%)**" if spread >= 10.0 else "⚡ **STRONG SPREAD (>= 7%)**")
                        sym_vols = volumes.get(sym, {})
                        max_pos_usdt = int(min(sym_vols.get(min_ex, 50000) * 0.01, sym_vols.get(max_ex, 50000) * 0.01, 50000))
                        if max_pos_usdt < 100: max_pos_usdt = 100
                        
                        risk_tag = ""
                        low_liq_exs = [ex for ex, v in sym_vols.items() if v < 10000 and ex in ex_data]
                        if low_liq_exs:
                            risk_tag = f"\n⚠️ **RISK: Низкая ликвидность ({', '.join(low_liq_exs)})**\n"
                        elif spread > 25.0:
                            risk_tag = "\n⚠️ **WARNING: Аномальный спред (Делистинг / баг оракула!)**\n"
                        
                        sym_funds = fundings.get(sym, {})
                        overview = "\n".join([f"🔹 [{ex}](https://google.com): `${p}` ({format_volume(sym_vols.get(ex, 0))})" for ex in sorted(ex_data.keys(), key=lambda x: sym_vols.get(x, 0), reverse=True)])
                        
                        msg_id = send_to_topic("SPREAD", f"{badge}\n🪙 **#{sym} | Spread: `{spread:.2f}%`**{risk_tag}\n🟢 **Long ({min_ex}):** `${min_p}` (Funding: `{sym_funds.get(min_ex, 0.0):+.2f}%`)\n🔴 **Short ({max_ex}):** `${max_p}` (Funding: `{sym_funds.get(max_ex, 0.0):+.2f}%`)\n\n💰 **Объем:** `~${max_pos_usdt:,} USDT`\n\n📝 **Overview (24h):**\n{overview}")
                        if msg_id: active_spreads[sym] = {"msg_id": msg_id, "start_time": time.time()}
            
            for sym in list(active_spreads.keys()):
                if sym not in current_scanned_syms or sym not in prices or ((max(prices[sym].values()) - min(prices[sym].values())) / min(prices[sym].values())) * 100 < 1.0:
                    data = active_spreads.pop(sym, None)
                    if data:
                        dur = int(time.time() - data["start_time"])
                        send_to_topic("SPREAD", f"✅ `[{sym}]` prices aligned in `{dur // 60}:{dur % 60:02d}`", reply_to_message_id=data["msg_id"])
        except Exception: pass
        time.sleep(45)

def monitor_funding():
    while True:
        try:
            _, volumes_cache, all_funding, funding_times = fetch_futures_data()
            for symbol, ex_rates in all_funding.items():
                if len(ex_rates) < 2: continue
                min_rate, max_rate = min(ex_rates.values()), max(ex_rates.values())
                if max_rate - min_rate >= 1.0 or any(abs(r) >= 1.0 for r in ex_rates.values()):
                    sig_id = f"FUND_{symbol}"
                    if sig_id not in processed_arbitrage:
                        processed_arbitrage.add(sig_id)
                        overview = "\n".join([f"🔹 [{ex}]: `{r:+.2f}%` (⏱ {format_countdown(funding_times.get(symbol, {}).get(ex, 0))})" for ex, r in sorted(ex_rates.items(), key=lambda x: x[1], reverse=True)])
                        send_to_topic("FUNDING", f"🔥 **FUNDING ARBITRAGE**\n🪙 **#{symbol}** (Spread: `{max_rate - min_rate:.2f}%`)\n\n📊 **Rates & Timers:**\n{overview}")
        except Exception: pass
        time.sleep(300)

def monitor_news():
    while True:
        for url, topic in [("https://cointelegraph.com/rss", "NEWS"), ("https://coindesk.com/arc/outboundfeeds/rss/", "NEWS")]:
            try:
                for entry in feedparser.parse(url).entries[:3]:
                    process_item(entry.id, f"{entry.title}\n{entry.link}", topic)
            except Exception: pass
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    send_to_topic("SPREAD", "🚀 **Бот запущен и работает в штатном режиме!**")
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_news, daemon=True).start()
    while True: time.sleep(3600)
