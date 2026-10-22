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
CHAT_ID = "-1004451728851"
ADMIN_IDS = [1043209905]

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

TOPICS = {
    "NEWS": 2, 
    "MEXC": 68,     
    "BYBIT": 4,     
    "BINANCE": 3,   
    "BITGET": 69,   
    "BINGX": 70,    
    "KUCOIN": 71,   
    "WHITEBIT": 72, 
    "KRAKEN": 73,   
    "GATE": 67,     
    "FUNDING": 76,  
    "SPREAD": 77    
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

# ==================== LINK GENERATORS ====================
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
    if not raw_sym:
        return ""
    sym = raw_sym.upper().replace('_', '').replace('-', '').replace('/', '')
    if sym.endswith('USDTM'):
        sym = sym[:-1]
    if not sym.endswith('USDT'):
        if sym.endswith('USD'):
            sym = sym[:-3] + 'USDT'
        else:
            sym += 'USDT'
    return sym

# ==================== ADVANCED AI & PROMO ANALYZER (42 ТЕГА) ====================
def analyze_text(text):
    if not OPENROUTER_API_KEY:
        return text
    prompt = f"""
Ты — главный крипто-аналитик и эксперт по абузу биржевых промо-акций, Web3-экосистем, лаунчпулов, пулов ликвидности и контентных программ. Проанализируй текст официального анонса из RSS-ленты и сформируй детальный структурированный отчет:

1. 📌 **Источник / Платформа:** Название биржи (Binance, Bybit, OKX, Bitget, MEXC и т.д.).
2. 🏷 **Тип события / Теги:** Присвой ВСЕ подпадающие теги из расширенного списка (всего 42 тега):
   - Web3 и Экосистемы: #OKX_Web3 #Binance_Web3 #Bybit_Web3 #Web3 #DApp #Quest #Task #XLiquidity
   - Разделы: #XLaunch #XTrade #TokenSplash #Megadrop #ByVotes #BinancePay
   - Контент: #BinanceSquare #Square #WriteToEarn #CreatorPad
   - Биржи: #Binance #Bybit #OKX #Bitget #MEXC #BingX #KuCoin #WhiteBit #Kraken #Gate #Ourbit
   - Активности: #Promotion #RewardCenter #Alpha #AlphaBox #MysteryBox #TradingTournament #Challenge #Boost #Booster #Launchpool #Launchpad #Airdrop #DepositBonus #Listing #NewListing #Earn #Savings #Staking #SimpleEarn #Flexible #Locked #VoteToList #FeeRebate #Voucher #BetVoucher #MarginVoucher #Margin #IPO #PreMarket #IDO #IEO #VIP

3. 🪙 **Токен / Проект:** Участвующие монеты или активы.
4. 📅 **Даты проведения:** Период проведения.
5. 📋 **Краткое описание:** Суть акции, буста, турнира, лаунчпула или квеста.
6. ⚡ **Пошаговая инструкция:** Четкие действия для участия.
7. 🎁 **Награды / Призовой фонд:** Официальные награды.
8. 💡 **Детальный расчет комиссий, затрат на газ и профита:** Посчитай затраты и выдай математический вердикт для разных уровней депозитов ($100, $1,000, $5,000, $20,000+).

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

def send_to_topic(topic_name, text, reply_to_message_id=None):
    thread_id = TOPICS.get(topic_name)
    if thread_id and CHAT_ID:
        try:
            res = bot.send_message(
                chat_id=CHAT_ID, 
                message_thread_id=thread_id, 
                text=text, 
                parse_mode="Markdown", 
                disable_web_page_preview=True,
                reply_to_message_id=reply_to_message_id
            )
            return res.message_id
        except Exception as e:
            print(f"❌ Send Error ({topic_name}): {e}")
    return None

def process_item(item_id, raw_text, default_topic):
    if item_id in processed_ids:
        return
    processed_ids.add(item_id)
    
    ai_result = analyze_text(raw_text)
    if "SKIP" in ai_result.upper():
        return
    
    target_topic = default_topic
    upper_res = ai_result.upper()
    
    for ex_name in TOPICS.keys():
        if f"#{ex_name}" in upper_res or ex_name in upper_res:
            target_topic = ex_name
            break
            
    send_to_topic(target_topic, ai_result)

# ==================== FUTURES DATA & LIQUIDITY FETCHING ====================
def fetch_futures_data():
    prices = {}
    volumes = {}
    
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=5).json()
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['Binance'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['Binance'] = float(item['quoteVolume'])
    except Exception: pass

    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=5).json().get('result', {}).get('list', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['Bybit'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['Bybit'] = float(item.get('turnover24h', 0))
    except Exception: pass

    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['instId'])
            if sym:
                prices.setdefault(sym, {})['OKX'] = float(item['last'])
                volumes.setdefault(sym, {})['OKX'] = float(item.get('volCcy24h', 0))
    except Exception: pass

    try:
        r = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json()
        for item in r:
            sym = normalize_symbol(item['contract'])
            if sym:
                prices.setdefault(sym, {})['Gate'] = float(item['last'])
                volumes.setdefault(sym, {})['Gate'] = float(item.get('total_size', 0)) * float(item['last'])
    except Exception: pass

    try:
        r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['Bitget'] = float(item['lastPr'])
                volumes.setdefault(sym, {})['Bitget'] = float(item.get('quoteVolume', 0))
    except Exception: pass

    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['MEXC'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['MEXC'] = float(item.get('amount24h', 0))
    except Exception: pass

    try:
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['BingX'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['BingX'] = float(item.get('volume', 0))
    except Exception: pass

    try:
        r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym and 'lastTradePrice' in item:
                prices.setdefault(sym, {})['KuCoin'] = float(item['lastTradePrice'])
                volumes.setdefault(sym, {})['KuCoin'] = float(item.get('turnoverOf24h', 0))
    except Exception: pass

    try:
        r = requests.get("https://api.ourbit.com/api/v1/futures/market/tickers", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item.get('symbol', ''))
            if sym and 'close' in item:
                prices.setdefault(sym, {})['Ourbit'] = float(item['close'])
                volumes.setdefault(sym, {})['Ourbit'] = float(item.get('vol', 0))
    except Exception: pass

    return prices, volumes

# ==================== SPREAD MONITOR (>= 7% и <= 50%) ====================
def monitor_spread():
    while True:
        try:
            prices, volumes = fetch_futures_data()
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
                
                # Спред от 7% до 50%
                if spread >= 7.0 and spread <= 50.0:
                    current_scanned_syms.add(sym)
                    
                    if sym not in active_spreads:
                        if spread >= 15.0:
                            badge = "🔥🔥🔥 **MEGA SPREAD (>= 15%)**"
                        elif spread >= 10.0:
                            badge = "🔥 **HIGH SPREAD (>= 10%)**"
                        else:
                            badge = "⚡ **STRONG SPREAD (>= 7%)**"

                        min_url = get_exchange_url(min_ex, sym)
                        max_url = get_exchange_url(max_ex, sym)
                        
                        vol_min = volumes.get(sym, {}).get(min_ex, 50000) * 0.01
                        vol_max = volumes.get(sym, {}).get(max_ex, 50000) * 0.01
                        max_pos_usdt = int(min(vol_min, vol_max, 50000))
                        if max_pos_usdt < 100: max_pos_usdt = 100

                        overview_list = [f"🔹 [{ex}]({get_exchange_url(ex, sym)}): `${p}`" for ex, p in ex_data.items()]
                        overview = "\n".join(overview_list)
                        
                        msg_text = (
                            f"{badge}\n"
                            f"🪙 **#{sym} | Spread: `{spread:.2f}%`**\n\n"
                            f"🟢 **Long:** `${min_p}`\n"
                            f"🔴 **Short:** `${max_p}`\n\n"
                            f"💰 **Доступный объем позиции:** `~${max_pos_usdt:,} USDT`\n\n"
                            f"📝 **All Exchanges Overview:**\n{overview}\n\n"
                            f"🔗 **Открыть в приложениях:**\n"
                            f"📱 [Открыть в {min_ex}]({min_url}) | 📱 [Открыть в {max_ex}]({max_url})"
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
                            if curr_spread < 1.0:
                                expired_syms.append(sym)

            for sym in expired_syms:
                data = active_spreads.pop(sym, None)
                if data:
                    duration = int(time.time() - data["start_time"])
                    mins = duration // 60
                    secs = duration % 60
                    time_str = f"{mins}:{secs:02d}"
                    
                    aligned_msg = f"✅ `[{sym}]` prices aligned in `{time_str}`"
                    send_to_topic("SPREAD", aligned_msg, reply_to_message_id=data["msg_id"])

        except Exception as e:
            print(f"Spread Monitor Error: {e}")
        
        time.sleep(45)

# ==================== FUNDING MONITOR ====================
def monitor_funding():
    while True:
        try:
            all_funding = {}
            volumes_cache = {}

            def collect_rate(exchange, raw_sym, rate, vol=0):
                sym = normalize_symbol(raw_sym)
                if sym:
                    all_funding.setdefault(sym, {})[exchange] = rate
                    if vol > 0:
                        volumes_cache.setdefault(sym, {})[exchange] = vol

            try:
                for item in requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5).json():
                    collect_rate("Binance", item['symbol'], float(item['lastFundingRate']) * 100)
                for item in requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=5).json():
                    sym = normalize_symbol(item['symbol'])
                    if sym: volumes_cache.setdefault(sym, {})['Binance'] = float(item['quoteVolume'])
            except Exception: pass

            try:
                for item in requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=5).json().get('result', {}).get('list', []):
                    if item.get('fundingRate'):
                        vol = float(item.get('turnover24h', 0))
                        collect_rate("Bybit", item['symbol'], float(item['fundingRate']) * 100, vol)
            except Exception: pass

            try:
                for item in requests.get("https://www.okx.com/api/v5/public/funding-rate-all", timeout=5).json().get('data', []):
                    collect_rate("OKX", item['instId'], float(item['fundingRate']) * 100)
                for item in requests.get("https://api.okx.com/api/v5/market/tickers?instType=SWAP", timeout=5).json().get('data', []):
                    sym = normalize_symbol(item['instId'])
                    if sym: volumes_cache.setdefault(sym, {})['OKX'] = float(item.get('volCcy24h', 0))
            except Exception: pass

            try:
                for item in requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json():
                    if 'funding_rate' in item:
                        vol = float(item.get('total_size', 0)) * float(item.get('last', 1))
                        collect_rate("Gate", item['contract'], float(item['funding_rate']) * 100, vol)
            except Exception: pass

            try:
                for item in requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=5).json().get('data', []):
                    if item.get('fundingRate'):
                        vol = float(item.get('quoteVolume', 0))
                        collect_rate("Bitget", item['symbol'], float(item['fundingRate']) * 100, vol)
            except Exception: pass

            try:
                for item in requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json().get('data', []):
                    if 'fundingRate' in item:
                        vol = float(item.get('amount24h', 0))
                        collect_rate("MEXC", item['symbol'], float(item['fundingRate']) * 100, vol)
            except Exception: pass

            try:
                for item in requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", timeout=5).json().get('data', []):
                    if 'lastFundingRate' in item:
                        collect_rate("BingX", item['symbol'], float(item['lastFundingRate']) * 100)
                for item in requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=5).json().get('data', []):
                    sym = normalize_symbol(item['symbol'])
                    if sym: volumes_cache.setdefault(sym, {})['BingX'] = float(item.get('volume', 0))
            except Exception: pass

            try:
                for item in requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=5).json().get('data', []):
                    if 'fundingFeeRate' in item:
                        vol = float(item.get('turnoverOf24h', 0))
                        collect_rate("KuCoin", item['symbol'], float(item['fundingFeeRate']) * 100, vol)
            except Exception: pass

            for symbol, ex_rates in all_funding.items():
                if len(ex_rates) < 2:
                    continue
                
                min_ex = min(ex_rates, key=ex_rates.get)
                max_ex = max(ex_rates, key=ex_rates.get)
                min_rate = ex_rates[min_ex]
                max_rate = ex_rates[max_ex]
                
                funding_spread = max_rate - min_rate
                
                has_high_absolute = any(abs(rate) >= 1.0 for rate in ex_rates.values())
                has_funding_spread = funding_spread >= 1.0
                
                if has_high_absolute or has_funding_spread:
                    rates_str = "_".join([f"{ex}:{rate:.2f}" for ex, rate in sorted(ex_rates.items())])
                    sig_id = f"FUND_SPREAD_{symbol}_{rates_str}"
                    
                    if sig_id not in processed_arbitrage:
                        processed_arbitrage.add(sig_id)
                        
                        vol_min = volumes_cache.get(symbol, {}).get(min_ex, 50000) * 0.01
                        vol_max = volumes_cache.get(symbol, {}).get(max_ex, 50000) * 0.01
                        max_pos_usdt = int(min(vol_min, vol_max, 50000))
                        if max_pos_usdt < 100: max_pos_usdt = 100

                        overview_list = [f"🔹 [{ex}]({get_exchange_url(ex, symbol)}): `{r:+.2f}%`" for ex, r in sorted(ex_rates.items(), key=lambda x: x[1], reverse=True)]
                        overview = "\n".join(overview_list)

                        sorted_exs = sorted(ex_rates.items(), key=lambda x: abs(x[1]), reverse=True)
                        links_list = [f"📱 [Открыть в {ex}]({get_exchange_url(ex, symbol)})" for ex, rate in sorted_exs[:4]]
                        links_text = " | ".join(links_list)

                        msg = (
                            f"🔥 **FUNDING ARBITRAGE / HIGH RATE (>= ±1.0%)**\n"
                            f"🪙 **#{symbol}** (Spread: `{funding_spread:.2f}%`)\n\n"
                            f"💰 **Доступный объем позиции:** `~${max_pos_usdt:,} USDT`\n\n"
                            f"📊 **All Exchanges Rates:**\n{overview}\n\n"
                            f"🔗 **Открыть приложения:**\n{links_text}"
                        )

                        send_to_topic("FUNDING", msg)

        except Exception as e:
            print(f"Funding Monitor Error: {e}")
            
        time.sleep(300)

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
        
        time.sleep(600)

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    
    send_to_topic("SPREAD", "🚀 **Бот запущен с обновленным фильтром спредов (7-50%) и расчетом объема позиций!**")
    
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_news, daemon=True).start()
    
    while True:
        time.sleep(3600)
