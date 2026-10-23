import os
import time
import threading
import datetime
import pytz
import requests
import feedparser
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
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
active_spreads = {}   # {sym: {"msg_id": int, "start_time": float, "last_text": str, "min_ex": str, "max_ex": str, "min_p": float, "max_p": float}}
active_fundings = {}  # {symbol: {"msg_id": int, "last_rates_str": str, "last_text": str}}

KYIV_TZ = pytz.timezone("Europe/Kyiv")

def get_kyiv_time():
    return datetime.datetime.now(KYIV_TZ).strftime("%H:%M:%S")

def get_kyiv_date_time():
    return datetime.datetime.now(KYIV_TZ).strftime("%H:%M")

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
        "Binance": f"https://www.binance.com/ru-UA/futures/{base_sym}USDT",
        "Bybit": f"https://www.bybit.com/trade/usdt/{base_sym}USDT",
        "OKX": f"https://www.okx.com/ru/trade-swap/{base_sym.lower()}-usdt-swap",
        "Gate": f"https://www.gate.io/ru/futures/USDT/{base_sym}_USDT",
        "Bitget": f"https://www.bitget.com/futures/usdt/{base_sym}USDT",
        "MEXC": f"https://futures.mexc.com/exchange/{base_sym}_USDT",
        "BingX": f"https://bingx.com/ru/futures/forward/{base_sym}USDT",
        "KuCoin": f"https://www.kucoin.com/ru/futures/trade/{base_sym}USDTM",
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

# ==================== ADVANCED AI & PROMO ANALYZER (АНТИ-ШУМ) ====================
def analyze_text(text):
    if not OPENROUTER_API_KEY:
        return text
    prompt = f"""
Ты — жесткий фильтр и аналитик крипто-анонсов. Твоя задача — отсечь 100% информационного шума, но ОСТАВИТЬ все реальные промо-акции, кикстартеры, лаунчпулы, эйрдропы, Web3-ивенты и ивенты с призами (включая розыгрыши гаджетов вроде iPhone, мерча или токенов).

ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: Ответь строго одним словом "SKIP", если:
1. Это обычный листинг/добавление новой торговой пары БЕЗ какой-либо промо-кампании, баунти или призового фонда.
2. Новость про токенизированные акции, традиционные ETF или залоговые активы.
3. Новость про суды, штрафы, регуляторов, делистинг, техническое обслуживание.
(Если есть намек на призы, розыгрыш, стейкинг с наградами, Web3 или промо — НЕ пропускай).

ЕСЛИ ЭТО РЕАЛЬНАЯ АКЦИЯ, ИВЕНТ, LAUNCHPOOL, MEGADROP, WEB3 AIRDROP — сформируй отчет строго по форме:
1. 📌 **Источник / Платформа:** Название биржи или Web3-кошелька.
2. 🏷 **Тип события / Теги:** (#OKX_Web3 #Binance_Web3 #Bybit_Web3 #Web3 #Launchpool #Launchpad #Airdrop #TokenSplash #Promotion #Kickstarter #Kraken и др.).
3. 🪙 **Токен / Проект.**
4. 📅 **Даты проведения.**
5. 📋 **Краткое описание.**
6. ⚡ **Пошаговая инструкция.**
7. 🎁 **Награды / Призовой фонд.**
8. 💡 **Расчет профита для $100, $1K, $5K, $20K+.**

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

def send_to_topic(topic_name, text, reply_to_message_id=None, reply_markup=None):
    thread_id = TOPICS.get(topic_name)
    if thread_id and CHAT_ID:
        try:
            res = bot.send_message(
                chat_id=CHAT_ID, 
                message_thread_id=thread_id, 
                text=text, 
                parse_mode="Markdown", 
                disable_web_page_preview=True,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup
            )
            return res.message_id
        except Exception as e:
            print(f"❌ Send Error ({topic_name}): {e}")
    return None

def edit_topic_message(topic_name, message_id, text, reply_markup=None):
    if CHAT_ID and message_id:
        try:
            bot.edit_message_text(
                chat_id=CHAT_ID,
                message_id=message_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            return True
        except Exception as e:
            print(f"❌ Edit Error ({topic_name}): {e}")
    return False

def process_item(item_id, raw_text, link, default_topic):
    if item_id in processed_ids:
        return
    processed_ids.add(item_id)
    
    ai_result = analyze_text(raw_text)
    if "SKIP" in ai_result.upper():
        return
    
    target_topic = default_topic
    upper_res = ai_result.upper()
    
    detected_ex = "EXCHANGE"
    for ex_name in TOPICS.keys():
        if f"#{ex_name}" in upper_res or ex_name in upper_res:
            target_topic = ex_name
            detected_ex = ex_name
            break
            
    markup = None
    if link and link.startswith("http"):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"📱 Открыть в {detected_ex.upper()}", url=link))

    send_to_topic(target_topic, ai_result, reply_markup=markup)

# ==================== FUTURES DATA & LIQUIDITY FETCHING (ВКЛЮЧАЯ OURBIT) ====================
def fetch_futures_data():
    prices = {}
    volumes = {}
    fundings = {}
    funding_times = {}
    
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=5).json()
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['Binance'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['Binance'] = float(item['quoteVolume'])
    except Exception: pass

    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5).json()
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                fundings.setdefault(sym, {})['Binance'] = float(item['lastFundingRate']) * 100
                next_time = int(item.get('nextFundingTime', 0)) // 1000
                if next_time > 0:
                    funding_times.setdefault(sym, {})['Binance'] = next_time
    except Exception: pass

    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=5).json().get('result', {}).get('list', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                if 'lastPrice' in item:
                    prices.setdefault(sym, {})['Bybit'] = float(item['lastPrice'])
                    volumes.setdefault(sym, {})['Bybit'] = float(item.get('turnover24h', 0))
                if item.get('fundingRate'):
                    fundings.setdefault(sym, {})['Bybit'] = float(item['fundingRate']) * 100
                    next_time = int(item.get('nextFundingTime', 0)) // 1000
                    if next_time > 0:
                        funding_times.setdefault(sym, {})['Bybit'] = next_time
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
        r = requests.get("https://api.okx.com/api/v5/public/funding-rate-all", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['instId'])
            if sym and item.get('fundingRate'):
                fundings.setdefault(sym, {})['OKX'] = float(item['fundingRate']) * 100
                next_time = int(item.get('nextFundingTime', 0)) // 1000
                if next_time > 0:
                    funding_times.setdefault(sym, {})['OKX'] = next_time
    except Exception: pass

    try:
        r = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=5).json()
        for item in r:
            sym = normalize_symbol(item['contract'])
            if sym:
                prices.setdefault(sym, {})['Gate'] = float(item['last'])
                volumes.setdefault(sym, {})['Gate'] = float(item.get('total_size', 0)) * float(item['last'])
                if 'funding_rate' in item:
                    fundings.setdefault(sym, {})['Gate'] = float(item['funding_rate']) * 100
                    next_time = int(item.get('funding_next_time', 0))
                    if next_time > 0:
                        funding_times.setdefault(sym, {})['Gate'] = next_time
    except Exception: pass

    try:
        r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['Bitget'] = float(item['lastPr'])
                volumes.setdefault(sym, {})['Bitget'] = float(item.get('quoteVolume', 0))
                if item.get('fundingRate'):
                    fundings.setdefault(sym, {})['Bitget'] = float(item['fundingRate']) * 100
                    next_time = int(item.get('nextFundingTime', 0)) // 1000
                    if next_time > 0:
                        funding_times.setdefault(sym, {})['Bitget'] = next_time
    except Exception: pass

    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['MEXC'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['MEXC'] = float(item.get('amount24h', 0))
                if 'fundingRate' in item:
                    fundings.setdefault(sym, {})['MEXC'] = float(item['fundingRate']) * 100
                    next_time = int(item.get('nextSettleTime', 0)) // 1000
                    if next_time > 0:
                        funding_times.setdefault(sym, {})['MEXC'] = next_time
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
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym and 'lastFundingRate' in item:
                fundings.setdefault(sym, {})['BingX'] = float(item['lastFundingRate']) * 100
                next_time = int(item.get('nextFundingTime', 0)) // 1000
                if next_time > 0:
                    funding_times.setdefault(sym, {})['BingX'] = next_time
    except Exception: pass

    try:
        r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym and 'lastTradePrice' in item:
                prices.setdefault(sym, {})['KuCoin'] = float(item['lastTradePrice'])
                volumes.setdefault(sym, {})['KuCoin'] = float(item.get('turnoverOf24h', 0))
                if 'fundingFeeRate' in item:
                    fundings.setdefault(sym, {})['KuCoin'] = float(item['fundingFeeRate']) * 100
                    next_time = int(item.get('nextFundingRateTime', 0)) // 1000
                    if next_time > 0:
                        funding_times.setdefault(sym, {})['KuCoin'] = next_time
    except Exception: pass

    try:
        r = requests.get("https://api.ourbit.com/api/v1/futures/market/tickers", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item.get('symbol', ''))
            if sym and 'close' in item:
                prices.setdefault(sym, {})['Ourbit'] = float(item['close'])
                volumes.setdefault(sym, {})['Ourbit'] = float(item.get('vol', 0))
    except Exception: pass

    return prices, volumes, fundings, funding_times

def format_volume(vol):
    if vol >= 1_000_000:
        return f"${vol / 1_000_000:.1f}M (24h)"
    elif vol >= 1_000:
        return f"${vol / 1_000:.1f}K (24h)"
    else:
        return f"${vol:.0f} (24h)"

def format_countdown(target_timestamp):
    if not target_timestamp:
        return "N/A"
    diff = target_timestamp - time.time()
    if diff <= 0:
        return "0ч 00м"
    hours = int(diff // 3600)
    minutes = int((diff % 3600) // 60)
    return f"{hours}ч {minutes:02d}м"

# ==================== SPREAD MONITOR ====================
def monitor_spread():
    while True:
        try:
            prices, volumes, fundings, _ = fetch_futures_data()
            current_scanned_syms = set()
            curr_time_str = get_kyiv_time()

            for sym, ex_data in prices.items():
                sym_vols = volumes.get(sym, {})
                valid_ex_data = {ex: p for ex, p in ex_data.items() if sym_vols.get(ex, 0) > 0}

                if len(valid_ex_data) < 2:
                    continue
                
                min_ex = min(valid_ex_data, key=valid_ex_data.get)
                max_ex = max(valid_ex_data, key=valid_ex_data.get)
                min_p = valid_ex_data[min_ex]
                max_p = valid_ex_data[max_ex]
                
                if min_p <= 0: continue
                spread = ((max_p - min_p) / min_p) * 100
                
                if 7.0 <= spread <= 30.0:
                    current_scanned_syms.add(sym)
                    
                    if spread >= 15.0:
                        badge = "🔥🔥🔥 **MEGA SPREAD (>= 15%)**"
                    elif spread >= 10.0:
                        badge = "🔥 **HIGH SPREAD (>= 10%)**"
                    else:
                        badge = "⚡ **STRONG SPREAD (>= 7%)**"

                    vol_min = sym_vols.get(min_ex, 0) * 0.01
                    vol_max = sym_vols.get(max_ex, 0) * 0.01
                    max_pos_usdt = int(min(vol_min, vol_max))
                    if max_pos_usdt < 100: max_pos_usdt = 100

                    risk_tag = ""
                    low_liq_exs = [ex for ex, v in sym_vols.items() if v < 10000 and ex in valid_ex_data]
                    
                    if spread > 25.0:
                        risk_tag = "\n⚠️ **RISK: Аномальный спред / Риск делистинга!**\n"
                    elif low_liq_exs:
                        bad_exs_str = ", ".join(low_liq_exs)
                        risk_tag = f"\n⚠️ **RISK: Низкая ликвидность / Мертвый стакан ({bad_exs_str})**\n"

                    sym_funds = fundings.get(sym, {})
                    min_fund = sym_funds.get(min_ex, 0.0)
                    max_fund = sym_funds.get(max_ex, 0.0)

                    sorted_exs = sorted(valid_ex_data.keys(), key=lambda ex: sym_vols.get(ex, 0), reverse=True)
                    
                    overview_list = []
                    for ex in sorted_exs:
                        p = valid_ex_data[ex]
                        v = sym_vols.get(ex, 0)
                        v_str = format_volume(v)
                        url = get_exchange_url(ex, sym)
                        overview_list.append(f"🔹 [{ex}]({url}): `${p}` ({v_str})")
                    
                    overview = "\n".join(overview_list)
                    
                    msg_text = (
                        f"{badge}\n"
                        f"🪙 **#{sym} | Spread: `{spread:.2f}%`**"
                        f"{risk_tag}\n"
                        f"🟢 **Long ({min_ex}):** `${min_p}` (Funding: `{min_fund:+.2f}%`)\n"
                        f"🔴 **Short ({max_ex}):** `${max_p}` (Funding: `{max_fund:+.2f}%`)\n\n"
                        f"💰 **Доступный объем позиции:** `~${max_pos_usdt:,} USDT`\n\n"
                        f"📝 **All Exchanges Overview (по ликвидности):**\n{overview}\n\n"
                        f"🔄 _Обновлено: {curr_time_str} (Киев)_"
                    )
                    
                    if sym in active_spreads:
                        fund_info = active_spreads[sym]
                        fund_info["min_ex"] = min_ex
                        fund_info["max_ex"] = max_ex
                        fund_info["min_p"] = min_p
                        fund_info["max_p"] = max_p
                        if fund_info["last_text"] != msg_text:
                            success = edit_topic_message("SPREAD", fund_info["msg_id"], msg_text)
                            if success:
                                fund_info["last_text"] = msg_text
                    else:
                        msg_id = send_to_topic("SPREAD", msg_text)
                        if msg_id:
                            active_spreads[sym] = {
                                "msg_id": msg_id,
                                "start_time": time.time(),
                                "last_text": msg_text,
                                "min_ex": min_ex,
                                "max_ex": max_ex,
                                "min_p": min_p,
                                "max_p": max_p
                            }
            
            expired_syms = []
            for sym in list(active_spreads.keys()):
                if sym not in current_scanned_syms or sym not in prices:
                    expired_syms.append((sym, 0.0))
                else:
                    ex_data = prices[sym]
                    sym_vols = volumes.get(sym, {})
                    valid_ex_data = {ex: p for ex, p in ex_data.items() if sym_vols.get(ex, 0) > 0}
                    if len(valid_ex_data) >= 2:
                        curr_min = min(valid_ex_data.values())
                        curr_max = max(valid_ex_data.values())
                        if curr_min > 0:
                            curr_spread = ((curr_max - curr_min) / curr_min) * 100
                            if curr_spread < 1.0:
                                expired_syms.append((sym, curr_spread))

            for sym, final_spread in expired_syms:
                data = active_spreads.pop(sym, None)
                if data:
                    duration = int(time.time() - data["start_time"])
                    mins = duration // 60
                    secs = duration % 60
                    time_str = f"{mins}:{secs:02d}"
                    
                    aligned_msg = (
                        f"✅ `[{sym}]` prices aligned in `{time_str}` (spread: `{final_spread:.2f}%`)\n"
                        f"📌 **Финальные цены:** `{data['min_ex']}`: `${data['min_p']}` | `{data['max_ex']}`: `${data['max_p']}`"
                    )
                    send_to_topic("SPREAD", aligned_msg, reply_to_message_id=data["msg_id"])

        except Exception as e:
            print(f"Spread Monitor Error: {e}")
        
        time.sleep(45)

# ==================== FUNDING MONITOR ====================
def monitor_funding():
    while True:
        try:
            _, volumes_cache, all_funding, funding_times = fetch_futures_data()
            current_active_symbols = set()
            curr_time_str = get_kyiv_time()

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
                    current_active_symbols.add(symbol)
                    rates_key = "_".join([f"{ex}:{rate:.2f}" for ex, rate in sorted(ex_rates.items())])
                    
                    sym_vols = volumes_cache.get(symbol, {})
                    vol_min = sym_vols.get(min_ex, 50000) * 0.01
                    vol_max = sym_vols.get(max_ex, 50000) * 0.01
                    max_pos_usdt = int(min(vol_min, vol_max, 50000))
                    if max_pos_usdt < 100: max_pos_usdt = 100

                    sym_times = funding_times.get(symbol, {})
                    overview_list = []
                    for ex, r in sorted(ex_rates.items(), key=lambda x: x[1], reverse=True):
                        url = get_exchange_url(ex, symbol)
                        target_t = sym_times.get(ex, 0)
                        countdown_str = format_countdown(target_t)
                        overview_list.append(f"🔹 [{ex}]({url}): `{r:+.2f}%` (⏱ {countdown_str})")
                    
                    overview = "\n".join(overview_list)

                    msg = (
                        f"🔥 **FUNDING ARBITRAGE / HIGH RATE (>= ±1.0%)**\n"
                        f"🪙 **#{symbol}** (Spread: `{funding_spread:.2f}%`)\n\n"
                        f"💰 **Доступный объем позиции:** `~${max_pos_usdt:,} USDT`\n\n"
                        f"📊 **All Exchanges Rates & Timers:**\n{overview}\n\n"
                        f"🔄 _Данные обновлены в {curr_time_str} (Киев)_"
                    )

                    if symbol in active_fundings:
                        fund_data = active_fundings[symbol]
                        if fund_data["last_rates_str"] != rates_key:
                            success = edit_topic_message("FUNDING", fund_data["msg_id"], msg)
                            if success:
                                fund_data["last_rates_str"] = rates_key
                                fund_data["last_text"] = msg
                    else:
                        msg_id = send_to_topic("FUNDING", msg)
                        if msg_id:
                            active_fundings[symbol] = {
                                "msg_id": msg_id,
                                "last_rates_str": rates_key,
                                "last_text": msg
                            }

            normalized_syms = []
            for symbol in list(active_fundings.keys()):
                if symbol not in current_active_symbols:
                    normalized_syms.append(symbol)

            for symbol in normalized_syms:
                data = active_fundings.pop(symbol, None)
                if data:
                    norm_msg = data["last_text"] + f"\n\n✅ **Фандинг вернулся в норму в {get_kyiv_date_time()} (Киев)**"
                    edit_topic_message("FUNDING", data["msg_id"], norm_msg)

        except Exception as e:
            print(f"Funding Monitor Error: {e}")
            
        time.sleep(300)

# ==================== PROMO & WEB3 MONITORS (ПОЛНЫЙ КОМПЛЕКТ С KRAKEN И WEB3) ====================
def fetch_binance_promos():
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageNo=1&pageSize=30"
        res = requests.get(url, timeout=5).json()
        articles = res.get('data', {}).get('articles', [])
        for art in articles:
            art_id = f"binance_promo_{art.get('id')}"
            title = art.get('title', '')
            code = art.get('code', '')
            link = f"https://www.binance.com/ru-UA/support/announcement/{code}" if code else "https://www.binance.com"
            raw_text = f"Binance Event / Launchpool / Megadrop: {title}\n{link}"
            process_item(art_id, raw_text, link, "BINANCE")
    except Exception as e:
        print(f"Binance Promo Error: {e}")

def fetch_binance_web3():
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=410&pageNo=1&pageSize=20"
        res = requests.get(url, timeout=5).json()
        articles = res.get('data', {}).get('articles', [])
        for art in articles:
            art_id = f"binance_web3_{art.get('id')}"
            title = art.get('title', '')
            code = art.get('code', '')
            link = f"https://web3.binance.com/ru-UA/support/announcement/{code}" if code else "https://web3.binance.com"
            raw_text = f"#Binance_Web3 Airdrop / Quest: {title}\n{link}"
            process_item(art_id, raw_text, link, "BINANCE")
    except Exception as e:
        print(f"Binance Web3 Error: {e}")

def fetch_bybit_promos():
    try:
        url = "https://api.bybit.com/v5/announcements/index?locale=en-US&limit=30"
        res = requests.get(url, timeout=5).json()
        articles = res.get('result', {}).get('list', [])
        for art in articles:
            art_id = f"bybit_promo_{art.get('id')}"
            title = art.get('title', '')
            link = art.get('url', '')
            description = art.get('description', '')
            type_title = art.get('type', {}).get('title', 'Campaign')
            raw_text = f"Bybit Event [{type_title}]: {title}\n{description}\n{link}"
            process_item(art_id, raw_text, link, "BYBIT")
    except Exception as e:
        print(f"Bybit Promo Error: {e}")

def fetch_okx_promos():
    try:
        url = "https://www.okx.com/priapi/v5/support/news/bulletins?page=1&pageSize=30"
        res = requests.get(url, timeout=5).json()
        articles = res.get('data', [{}])[0].get('details', [])
        for art in articles[:30]:
            art_id = f"okx_promo_{art.get('id')}"
            title = art.get('title', '')
            link = f"https://www.okx.com/ru/help/{art.get('slug', '')}" if art.get('slug') else "https://www.okx.com"
            raw_text = f"OKX Event / Flash Earn / Jumpstart: {title}\n{link}"
            process_item(art_id, raw_text, link, "OKX")
    except Exception as e:
        print(f"OKX Promo Error: {e}")

def fetch_okx_web3():
    try:
        url = "https://www.okx.com/priapi/v5/support/news/bulletins?type=web3&page=1&pageSize=20"
        res = requests.get(url, timeout=5).json()
        articles = res.get('data', [{}])[0].get('details', [])
        for art in articles[:20]:
            art_id = f"okx_web3_{art.get('id')}"
            title = art.get('title', '')
            link = f"https://web3.okx.com/ru/help/{art.get('slug', '')}" if art.get('slug') else "https://web3.okx.com"
            raw_text = f"#OKX_Web3 Wallet Airdrop / Quest: {title}\n{link}"
            process_item(art_id, raw_text, link, "OKX")
    except Exception as e:
        print(f"OKX Web3 Error: {e}")

def fetch_bitget_promos():
    try:
        url = "https://api.bitget.com/api/v2/spot/public/announcements?language=en_US&pageSize=30"
        res = requests.get(url, timeout=5).json()
        articles = res.get('data', [])
        for art in articles[:30]:
            art_id = f"bitget_promo_{art.get('annId')}"
            title = art.get('annTitle', '')
            link = art.get('annUrl', '')
            ann_type = art.get('annType', 'Promotion')
            raw_text = f"Bitget Event [{ann_type}]: {title}\n{link}"
            process_item(art_id, raw_text, link, "BITGET")
    except Exception as e:
        print(f"Bitget Promo Error: {e}")

def fetch_mexc_promos():
    try:
        urls = [
            "https://www.mexc.com/api/common/announcement?page=1&pageSize=30",
            "https://www.mexc.com/api/common/announcement?page=1&pageSize=30&category=activity"
        ]
        for url in urls:
            res = requests.get(url, timeout=5).json()
            articles = res.get('data', {}).get('announcementList', [])
            for art in articles:
                art_id = f"mexc_promo_{art.get('id')}"
                title = art.get('title', '')
                link = f"https://www.mexc.com/support/articles/{art.get('id')}" if art.get('id') else "https://www.mexc.com"
                summary = art.get('summary', '')
                raw_text = f"MEXC Event / Promotion / Kickstarter: {title}\n{summary}\n{link}"
                process_item(art_id, raw_text, link, "MEXC")
    except Exception as e:
        print(f"MEXC Promo Error: {e}")

def fetch_gate_promos():
    try:
        url = "https://api.gateio.ws/api/v4/support/announcements?limit=30"
        res = requests.get(url, timeout=5).json()
        for art in res:
            art_id = f"gate_promo_{art.get('id')}"
            title = art.get('title', '')
            link = art.get('url', 'https://www.gate.io')
            raw_text = f"Gate.io Event / Promotion: {title}\n{link}"
            process_item(art_id, raw_text, link, "GATE")
    except Exception as e:
        print(f"Gate Promo Error: {e}")

def fetch_kucoin_promos():
    try:
        url = "https://api.kucoin.com/api/v1/bulletins?currentPage=1&pageSize=30"
        res = requests.get(url, timeout=5).json()
        articles = res.get('data', {}).get('items', [])
        for art in articles:
            art_id = f"kucoin_promo_{art.get('cId')}"
            title = art.get('title', '')
            link = f"https://www.kucoin.com/ru/news/{art.get('cName', '')}" if art.get('cName') else "https://www.kucoin.com"
            raw_text = f"KuCoin Event / Promotion: {title}\n{link}"
            process_item(art_id, raw_text, link, "KUCOIN")
    except Exception as e:
        print(f"KuCoin Promo Error: {e}")

def fetch_bingx_promos():
    try:
        url = "https://open-api.bingx.com/openApi/common/v1/announcements?limit=30"
        res = requests.get(url, timeout=5).json()
        articles = res.get('data', [])
        for art in articles:
            art_id = f"bingx_promo_{art.get('id')}"
            title = art.get('title', '')
            link = art.get('url', 'https://bingx.com')
            raw_text = f"BingX Event / Promotion: {title}\n{link}"
            process_item(art_id, raw_text, link, "BINGX")
    except Exception as e:
        print(f"BingX Promo Error: {e}")

def fetch_whitebit_promos():
    try:
        url = "https://whitebit.com/api/v4/public/announcements?limit=30"
        res = requests.get(url, timeout=5).json()
        articles = res.get('result', [])
        for art in articles:
            art_id = f"whitebit_promo_{art.get('id')}"
            title = art.get('title', '')
            link = art.get('url', 'https://whitebit.com')
            raw_text = f"WhiteBit Event / Promotion: {title}\n{link}"
            process_item(art_id, raw_text, link, "WHITEBIT")
    except Exception as e:
        print(f"WhiteBit Promo Error: {e}")

def fetch_kraken_promos():
    try:
        url = "https://blog.kraken.com/feed"
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            art_id = f"kraken_promo_{entry.get('id', entry.get('link'))}"
            title = entry.get('title', '')
            link = entry.get('link', 'https://www.kraken.com')
            summary = entry.get('summary', '')
            raw_text = f"Kraken Event / Promotion / Announcement: {title}\n{summary}\n{link}"
            process_item(art_id, raw_text, link, "KRAKEN")
    except Exception as e:
        print(f"Kraken Promo Error: {e}")

def run_all_promos():
    fetch_binance_promos()
    fetch_binance_web3()
    fetch_bybit_promos()
    fetch_okx_promos()
    fetch_okx_web3()
    fetch_bitget_promos()
    fetch_mexc_promos()
    fetch_gate_promos()
    fetch_kucoin_promos()
    fetch_bingx_promos()
    fetch_whitebit_promos()
    fetch_kraken_promos()

def monitor_news():
    feeds = [
        ("https://cryptopanic.com/news/rss/", "NEWS"),
        ("https://cointelegraph.com/rss", "NEWS"),
        ("https://coindesk.com/arc/outboundfeeds/rss/", "NEWS"),
        ("https://decrypt.co/feed", "NEWS"),
        ("https://bitcoinmagazine.com/.rss/full/", "NEWS")
    ]
    
    # === ОДНОРАЗОВАЯ ПРОВЕРКА ПРОМО ЗА 24 ЧАСА ПРИ СТАРТЕ ===
    print("🚀 Выполняется глубокий одноразовый сбор промо-акций и Web3 (включая Kraken и все биржи)...")
    run_all_promos()
    print("✅ Одноразовый глубокий сбор завершен. Переход в штатный режим 24/7.")
    # =======================================================

    while True:
        run_all_promos()

        for url, topic in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    link = entry.get('link', '')
                    title = entry.get('title', '')
                    summary = entry.get('summary', '')
                    raw_text = f"{title}\n{summary}\n{link}"
                    process_item(entry.id, raw_text, link, topic)
            except Exception as e:
                print(f"RSS Error ({url}): {e}")
        
        time.sleep(300)

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    
    send_to_topic("SPREAD", "🚀 **Бот запущен: Kraken, Binance/OKX Web3, 10 бирж для промо, Ourbit для спредов и киевское время!**")
    
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=monitor_news, daemon=True).start()
    
    while True:
        time.sleep(3600)
