import os
import time
import threading
import datetime
import re
import pytz
import requests
import feedparser
import telebot
from bs4 import BeautifulSoup
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
    "OKX": 2,       
    "FUNDING": 76,  
    "SPREAD": 77,
    "CHAT": 1       # ID топика «Чат» для калькулятора монет
}

processed_ids = set()
active_spreads = {}   
active_fundings = {}  

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

# ==================== SECURE REQUESTS ====================
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0"
}

def secure_request(url, timeout=10):
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        if response.status_code == 200:
            return response
        else:
            return None
    except Exception as e:
        print(f"❌ Secure Request Error ({url}): {e}")
        return None

# ==================== LINK GENERATORS ====================
def get_exchange_url(exchange, symbol="BTCUSDT"):
    base_sym = symbol.replace('USDT', '')
    ex_upper = exchange.upper()
    links = {
        "BINANCE": f"https://www.binance.com/en/futures/{base_sym}USDT",
        "BYBIT": f"https://www.bybit.com/trade/usdt/{base_sym}USDT",
        "OKX": f"https://www.okx.com/trade-swap/{base_sym.lower()}-usdt-swap",
        "GATE": f"https://www.gate.io/futures/USDT/{base_sym}_USDT",
        "BITGET": f"https://www.bitget.com/futures/usdt/{base_sym}USDT",
        "MEXC": f"https://futures.mexc.com/exchange/{base_sym}_USDT",
        "BINGX": f"https://bingx.com/en/futures/forward/{base_sym}USDT",
        "KUCOIN": f"https://www.kucoin.com/futures/trade/{base_sym}USDTM",
        "WHITEBIT": f"https://whitebit.com/trade/{base_sym}_USDT?type=futures",
        "KRAKEN": f"https://futures.kraken.com",
        "OURBIT": f"https://www.ourbit.com/futures/trade/{base_sym}_USDT"
    }
    return links.get(ex_upper, None)

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

# Глобальный кэш цен для калькулятора монет
latest_prices_cache = {}

# ==================== ADVANCED AI & PROMO ANALYZER ====================
def analyze_text(text):
    if not OPENROUTER_API_KEY:
        return text
    prompt = f"""
Ты — профессиональный финансовый аналитик крипто-анонсов, промо-акций, кешбеков и торговых турниров. 
Найди и структурируй любые активности, лаунчпулы, баунти, раздачи, аирдропы, кешбеки и торговые арены/турниры.
Ответь строго одним словом "SKIP", только если это чисто техническое обслуживание без бонусов или судебные иски. Любые промо, бонусы и турниры НЕ пропускай!
Сформируй отчет по форме:
1. 📌 **Источник / Платформа:**
2. 🏷 **Тип события / Теги:**
3. 🪙 **Токен / Проект.**
4. 📅 **Даты проведения.**
5. 📋 **Краткое описание.**
6. ⚡ **Пошаговая инструкция.**
7. 🎁 **Награды / Призовой фонд.**
8. 💡 **Финансовый расчет (Затраты и Профит).**

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
    except Exception as e:
        print(f"AI Error: {e}")
        return text

def send_to_topic(topic_name, text, reply_to_message_id=None, reply_markup=None):
    thread_id = TOPICS.get(topic_name, TOPICS.get("NEWS"))
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
            time.sleep(0.5)
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
            time.sleep(0.3)
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
    
    target_topic = default_topic.upper()
    if target_topic not in TOPICS:
        target_topic = "NEWS"

    exchange_url = get_exchange_url(target_topic) if target_topic in TOPICS and target_topic not in ["NEWS", "SPREAD", "FUNDING", "CHAT"] else None

    markup = InlineKeyboardMarkup()
    if exchange_url and exchange_url.startswith("http"):
        markup.add(InlineKeyboardButton(f"🌐 Биржа ({target_topic})", url=exchange_url))
    if link and link.startswith("http"):
        markup.add(InlineKeyboardButton("📱 Источник", url=link))

    send_to_topic(target_topic, ai_result, reply_markup=markup)
    time.sleep(1)

# ==================== TELEGRAM CHANNELS PROMO MONITOR ====================
def fetch_telegram_channels_promos():
    channels = {
        "BINANCE": ["Binance_UA_official", "BinanceUkrainian", "binance_announcements", "Binance_Announcements"],
        "OKX": ["okx_ru", "okx_campaign_announcement", "okxwalletannouncement", "OKX_Official"],
        "BYBIT": ["bybitukrainian", "bybitukrainiannews", "Bybit_CIS", "BybitAnnouncements"],
        "BITGET": ["BitgetUA", "BitgetENOfficial"],
        "MEXC": ["MEXCKraineOfficial", "MEXCofficialNews", "MEXCofficial"],
        "GATE": ["Gate_Ukrainian", "GateCom_EN"],
        "KRAKEN": ["kraken_announcements"],
        "BINGX": ["BingXOfficial", "BingXAnnouncement"],
        "KUCOIN": ["Kucoin_Exchange", "Kucoin_News"],
        "WHITEBIT": ["whitebit_ua_news", "White_Bit"]
    }
    
    while True:
        try:
            for exchange, chan_list in channels.items():
                for chan in chan_list:
                    url = f"https://t.me/s/{chan}"
                    res = secure_request(url, timeout=8)
                    if not res: continue
                    
                    soup = BeautifulSoup(res.text, 'html.parser')
                    messages = soup.find_all('div', class_='tgme_widget_message')
                    
                    for msg in messages[-3:]:
                        msg_id_attr = msg.get('data-post', '')
                        if not msg_id_attr: continue
                        
                        date_elem = msg.find('time', class_='tgme_widget_message_date')
                        if date_elem and date_elem.has_attr('datetime'):
                            post_date_str = date_elem['datetime'][:10]
                            try:
                                post_year = int(post_date_str[:4])
                                if post_year < 2025:
                                    continue
                            except:
                                pass

                        item_id = f"tg_chan_{msg_id_attr.replace('/', '_')}"
                        text_div = msg.find('div', class_='tgme_widget_message_text')
                        if not text_div: continue
                        
                        raw_text = text_div.get_text(separator='\n', strip=True)
                        post_link = f"https://t.me/{msg_id_attr}"
                        btn = msg.find('a', class_='tgme_widget_message_url')
                        if btn and btn.get('href'):
                            post_link = btn.get('href')
                        
                        full_payload = f"Telegram Channel [{exchange} / @{chan}]:\n{raw_text}\nLink: {post_link}"
                        process_item(item_id, full_payload, post_link, exchange)
                        
            time.sleep(600)
        except Exception as e:
            print(f"Telegram Channels Monitor Error: {e}")
            time.sleep(60)

# ==================== DIRECT EXCHANGE PROMOS API PARSER ====================
def fetch_direct_exchange_promos():
    while True:
        try:
            binance_api = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageNo=1&pageSize=10"
            res = secure_request(binance_api, timeout=6)
            if res:
                data = res.json()
                for art in data.get('data', {}).get('articles', []):
                    art_id = f"dir_binance_{art.get('id')}"
                    title = art.get('title', '')
                    code = art.get('code', '')
                    link = f"https://www.binance.com/en/support/announcement/{code}" if code else "https://www.binance.com"
                    raw_text = f"Binance Direct API Promo / Campaign: {title}\nLink: {link}"
                    process_item(art_id, raw_text, link, "BINANCE")

            mexc_api = "https://www.mexc.com/api/support/list?categoryId=19&page=1&pageSize=10"
            res_mexc = secure_request(mexc_api, timeout=6)
            if res_mexc:
                mexc_data = res_mexc.json()
                for item in mexc_data.get('data', {}).get('result', []):
                    item_id = f"dir_mexc_{item.get('id')}"
                    title = item.get('title', '')
                    link = f"https://www.mexc.com/support/articles/{item.get('id')}"
                    raw_text = f"MEXC Direct API Promo / Campaign: {title}\nLink: {link}"
                    process_item(item_id, raw_text, link, "MEXC")
        except Exception as e:
            print(f"Direct Promos API Error: {e}")
        time.sleep(1200)

# ==================== GLOBAL CRYPTO APIS & RSS ====================
def fetch_global_crypto_promos():
    sources = [
        ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=161&pageNo=1&pageSize=20", "BINANCE"),
        ("https://coinmarketcap.com/headlines/news/", "NEWS"),
    ]

    while True:
        try:
            for api_url, topic in sources[:1]:
                res = secure_request(api_url, timeout=6)
                if not res: continue
                data = res.json()
                articles = data.get('data', {}).get('articles', [])
                for art in articles:
                    art_id = f"global_api_{art.get('id')}"
                    title = art.get('title', '')
                    code = art.get('code', '')
                    link = f"https://www.binance.com/en/support/announcement/{code}" if code else "https://www.binance.com"
                    raw_text = f"Global Official Announcement / Event: {title}\nLink: {link}"
                    process_item(art_id, raw_text, link, topic)

            rss_feeds = ["https://cointelegraph.com/rss", "https://cryptopotato.com/feed/"]
            for feed_url in rss_feeds:
                try:
                    feed = feedparser.parse(feed_url)
                    for entry in feed.entries[:10]:
                        entry_id = f"rss_{entry.get('id', entry.get('link'))}"
                        title = entry.get('title', '')
                        summary = entry.get('summary', '')
                        link = entry.get('link', '')
                        raw_text = f"Crypto Aggregator / RSS News & Airdrop Quest: {title}\n{summary}\nLink: {link}"
                        process_item(entry_id, raw_text, link, "NEWS")
                except Exception as rss_err:
                    print(f"RSS Parse Error ({feed_url}): {rss_err}")
        except Exception as e:
            print(f"Global Promos Monitor Error: {e}")
        time.sleep(900)

# ==================== FUTURES & SPOT DATA FETCHING ====================
def fetch_futures_data():
    global latest_prices_cache
    prices, volumes, fundings, funding_times = {}, {}, {}, {}
    
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
                if next_time > 0: funding_times.setdefault(sym, {})['Binance'] = next_time
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
                    if next_time > 0: funding_times.setdefault(sym, {})['Bybit'] = next_time
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
                if next_time > 0: funding_times.setdefault(sym, {})['OKX'] = next_time
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
                    if next_time > 0: funding_times.setdefault(sym, {})['Gate'] = next_time
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
                    if next_time > 0: funding_times.setdefault(sym, {})['Bitget'] = next_time
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
                    if next_time > 0: funding_times.setdefault(sym, {})['MEXC'] = next_time
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
                if next_time > 0: funding_times.setdefault(sym, {})['BingX'] = next_time
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
                    if next_time > 0: funding_times.setdefault(sym, {})['KuCoin'] = next_time
    except Exception: pass

    try:
        r = requests.get("https://api.ourbit.com/api/v1/futures/market/tickers", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item.get('symbol', ''))
            if sym and 'close' in item:
                prices.setdefault(sym, {})['Ourbit'] = float(item['close'])
                volumes.setdefault(sym, {})['Ourbit'] = float(item.get('vol', 0))
    except Exception: pass

    # Подтягиваем SPOT рынки для щитков и редких монет
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5).json()
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['BinanceSpot'] = float(item['price'])
    except Exception: pass

    try:
        r = requests.get("https://www.mexc.com/open/api/v2/market/ticker", timeout=5).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item.get('symbol', ''))
            if sym:
                prices.setdefault(sym, {})['MEXCSpot'] = float(item.get('close', 0))
    except Exception: pass

    try:
        r = requests.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=5).json()
        for item in r:
            sym = normalize_symbol(item.get('currency_pair', ''))
            if sym and 'last' in item:
                prices.setdefault(sym, {})['GateSpot'] = float(item['last'])
    except Exception: pass

    try:
        r = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=5).json().get('data', {}).get('ticker', [])
        for item in r:
            sym = normalize_symbol(item.get('symbol', ''))
            if sym and 'last' in item:
                prices.setdefault(sym, {})['KuCoinSpot'] = float(item['last'])
    except Exception: pass

    for sym, ex_dict in prices.items():
        if ex_dict:
            latest_prices_cache[sym] = list(ex_dict.values())[0]

    return prices, volumes, fundings, funding_times

def format_volume(vol):
    if vol >= 1_000_000: return f"${vol / 1_000_000:.1f}M (24h)"
    elif vol >= 1_000: return f"${vol / 1_000:.1f}K (24h)"
    else: return f"${vol:.0f} (24h)"

def format_countdown(target_timestamp):
    if not target_timestamp: return "N/A"
    diff = target_timestamp - time.time()
    if diff <= 0: return "0ч 00м"
    hours = int(diff // 3600)
    minutes = int((diff % 3600) // 60)
    return f"{hours}ч {minutes:02d}м"

# ==================== SPREAD & FUNDING MONITORS ====================
def monitor_spread():
    while True:
        try:
            prices, volumes, fundings, _ = fetch_futures_data()
            current_scanned_syms = set()
            curr_time_str = get_kyiv_time()

            for sym, ex_data in prices.items():
                sym_vols = volumes.get(sym, {})
                valid_ex_data = {ex: p for ex, p in ex_data.items() if sym_vols.get(ex, 0) >= 200_000}

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
                    if spread > 25.0:
                        risk_tag = "\n⚠️ **RISK: Аномальный спред / Риск делистинга!**\n"

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
                        f"🪙 **#{sym} | Spread: `{spread:.2f}%`**\n"
                        f"{risk_tag}\n"
                        f"🟢 **Long ({min_ex}):** `${min_p}` (Funding: `{min_fund:.2f}%`)\n"
                        f"🔴 **Short ({max_ex}):** `${max_p}` (Funding: `{max_fund:.2f}%`)\n\n"
                        f"💰 **Доступный объем позиции:** `~${max_pos_usdt:,} USDT`\n\n"
                        f"📝 **All Exchanges Overview (ликвидные стаканы):**\n{overview}\n\n"
                        f"🔄 _Обновлено: {curr_time_str} (Киев)_"
                    )

                    if sym in active_spreads:
                        fund_info = active_spreads[sym]
                        fund_info["min_ex"] = min_ex
                        fund_info["max_ex"] = max_ex
                        fund_info["min_p"] = min_p
                        fund_info["max_p"] = max_p
                        fund_info["last_text"] = msg_text

                        if fund_info["last_text"] != msg_text:
                            edit_topic_message("SPREAD", fund_info["msg_id"], msg_text)
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
        except Exception as e:
            print(f"Spread Monitor Error: {e}")
        time.sleep(15)

def monitor_funding():
    while True:
        try:
            _, volumes_cache, all_funding, funding_times = fetch_futures_data()
            current_active_symbols = set()
            curr_time_str = get_kyiv_time()

            for symbol, ex_rates in all_funding.items():
                if len(ex_rates) < 2: continue
                min_ex = min(ex_rates, key=ex_rates.get)
                max_ex = max(ex_rates, key=ex_rates.get)
                funding_spread = ex_rates[max_ex] - ex_rates[min_ex]
                
                if any(abs(rate) >= 1.0 for rate in ex_rates.values()) or funding_spread >= 1.0:
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
                        countdown_str = format_countdown(sym_times.get(ex, 0))
                        overview_list.append(f"🔹 [{ex}]({url}): `{r:.2f}%` (⏱ {countdown_str})")
                    
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
                            active_fundings[symbol] = {"msg_id": msg_id, "last_rates_str": rates_key, "last_text": msg}
        except Exception as e:
            print(f"Funding Monitor Error: {e}")
        time.sleep(300)

# ==================== HANDLERS: VOLUME CALCULATOR & COIN PRICE ====================
@bot.message_handler(func=lambda message: message.text and message.text.startswith('/vol'))
def handle_volume_calculator(message):
    try:
        parts = message.text.strip().split()
        if len(parts) < 3:
            bot.send_message(message.chat.id, "⚠️ **Формат команды:** `/vol [затраты_usdt] [объем_в_тысячах]`\nПример: `/vol 52.5 11`", parse_mode="Markdown")
            return

        cost = float(parts[1])
        volume_k = float(parts[2])

        if volume_k <= 0:
            return

        cost_per_1k = cost / volume_k

        reply_text = (
            f"📊 **Расчет стоимости объема:**\n"
            f"💵 **Затраты:** `${cost:,.2f}`\n"
            f"📈 **Объем:** `{volume_k * 1000:,.0f}` (`{volume_k}K`)\n"
            f"💎 **Цена за 1K объема:** **`${cost_per_1k:,.2f}`**"
        )

        bot.send_message(
            chat_id=message.chat.id,
            message_thread_id=getattr(message, 'message_thread_id', None),
            text=reply_text,
            parse_mode="Markdown",
            reply_to_message_id=message.message_id
        )
    except Exception as e:
        print(f"Volume Calculator Error: {e}")

@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/'))
def handle_calculator(message):
    try:
        text = message.text.strip()
        
        # Поддержка как раздельного написания ("10000 zig"), так и слитного ("1zig", "10000zig")
        match = re.match(r'^([\d\.\s]+)\s*([a-zA-Z0-9]+)$', text)
        if not match:
            return

        amount_str = match.group(1).replace(' ', '')
        amount = float(amount_str)
        raw_coin = match.group(2).upper()
        symbol = normalize_symbol(raw_coin)

        price = 0.0

        # 1. Ищем в глобальном кэше (фьючерсы + спот-агрегатор)
        if symbol in latest_prices_cache and latest_prices_cache[symbol] > 0:
            price = latest_prices_cache[symbol]

        if price <= 0:
            for cached_sym, cached_price in latest_prices_cache.items():
                if raw_coin in cached_sym:
                    price = cached_price
                    symbol = cached_sym
                    break

        # 2. Фоллбэк: точечный запрос на Binance Spot
        if price <= 0:
            try:
                r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=3).json()
                if 'price' in r:
                    price = float(r['price'])
            except: pass

        # 3. Фоллбэк: точечный запрос на MEXC Spot
        if price <= 0:
            try:
                r = requests.get(f"https://www.mexc.com/open/api/v2/market/ticker?symbol={symbol}", timeout=3).json()
                data_list = r.get('data', [])
                if isinstance(data_list, list) and len(data_list) > 0:
                    price = float(data_list[0].get('close', 0))
                elif isinstance(r.get('data'), dict):
                    price = float(r.get('data', {}).get('close', 0))
            except: pass

        # 4. Фоллбэк: точечный запрос на Gate.io Spot
        if price <= 0:
            try:
                r = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={raw_coin}_USDT", timeout=3).json()
                if isinstance(r, list) and len(r) > 0 and 'last' in r[0]:
                    price = float(r[0]['last'])
            except: pass

        # 5. Фоллбэк: CoinGecko API для редких альтов и щитков
        if price <= 0:
            try:
                cg = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={raw_coin.lower()}&vs_currencies=usdt", timeout=3).json()
                if raw_coin.lower() in cg and 'usdt' in cg[raw_coin.lower()]:
                    price = float(cg[raw_coin.lower()]['usdt'])
            except: pass

        if price <= 0:
            return

        total_usdt = amount * price
        clean_base = symbol.replace('USDT', '')

        exchange_url = get_exchange_url("BINANCE", symbol) or f"https://www.binance.com/en/trade/{clean_base}_USDT"
        markup = InlineKeyboardMarkup()
        if exchange_url:
            markup.add(InlineKeyboardButton(f"🌐 Биржа ({clean_base})", url=exchange_url))

        reply_text = (
            f"🔍 **{amount:,.4f} {clean_base}**\n"
            f"💵 **${total_usdt:,.2f} USDT**"
        )

        bot.send_message(
            chat_id=message.chat.id,
            message_thread_id=getattr(message, 'message_thread_id', None),
            text=reply_text,
            parse_mode="Markdown",
            reply_to_message_id=message.message_id,
            reply_markup=markup
        )
    except Exception as e:
        print(f"Calculator Error: {e}")

# ==================== MAIN INITIALIZATION ====================
if __name__ == "__main__":
    print("===> Clearing webhooks & starting bot...")
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e:
        print(f"Webhook remove warning: {e}")

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    threading.Thread(target=fetch_telegram_channels_promos, daemon=True).start()
    threading.Thread(target=fetch_global_crypto_promos, daemon=True).start()
    threading.Thread(target=fetch_direct_exchange_promos, daemon=True).start()
    
    print("===> Your service is live 🚀")
    bot.infinity_polling()
