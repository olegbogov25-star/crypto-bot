import os
import time
import threading
import datetime
import json
import re
import pytz
import requests
import feedparser
import telebot
from bs4 import BeautifulSoup
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, render_template_string, request

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
    "WEB3": 78,     # Топик для Web3-активностей
    "CHAT": 1       # ID топика «Чат» для калькулятора, /vol и запросов монет
}

processed_ids = set()
active_fundings = {}  
spread_history = {}  # Хранилище истории спредов для графиков

# ==================== PERSISTENT ACTIVE SPREADS (JSON) ====================
SPREADS_FILE = "active_spreads.json"

def load_active_spreads():
    """Загружает активные спреды из файла при старте бота"""
    if os.path.exists(SPREADS_FILE):
        try:
            with open(SPREADS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_active_spreads(spreads_dict):
    """Сохраняет актуальные активные спреды на диск"""
    try:
        with open(SPREADS_FILE, "w", encoding="utf-8") as f:
            json.dump(spreads_dict, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"❌ Error saving spreads json: {e}")

active_spreads = load_active_spreads()

KYIV_TZ = pytz.timezone("Europe/Kyiv")

def get_kyiv_time():
    return datetime.datetime.now(KYIV_TZ).strftime("%H:%M:%S")

def get_kyiv_date_time():
    return datetime.datetime.now(KYIV_TZ).strftime("%H:%M")

# ==================== HEALTHCHECK & WEB APP CHART SERVER ====================
@app.route('/')
def health():
    return "OK", 200

@app.route('/chart')
def web_chart():
    symbol = request.args.get('symbol', 'BTCUSDT')
    min_ex = request.args.get('min_ex', 'Long')
    max_ex = request.args.get('max_ex', 'Short')
    
    html_template = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>График спреда {{ symbol }}</title>
        <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
        <style>
            body {
                background-color: #121212;
                color: #ffffff;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                margin: 0;
                padding: 15px;
                display: flex;
                flex-direction: column;
                height: 100vh;
                box-sizing: border-box;
            }
            h2 {
                margin: 0 0 5px 0;
                font-size: 18px;
                color: #00ffcc;
            }
            .subtitle {
                font-size: 13px;
                color: #aaaaaa;
                margin-bottom: 15px;
            }
            #chart-container {
                flex-grow: 1;
                width: 100%;
                background: #1e1e1e;
                border-radius: 8px;
                overflow: hidden;
            }
            .badge {
                display: inline-block;
                padding: 4px 8px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            .badge-long { background: rgba(0, 255, 128, 0.2); color: #00ff80; }
            .badge-short { background: rgba(255, 77, 77, 0.2); color: #ff4d4d; }
        </style>
    </head>
    <body>
        <h2>📈 Спред: {{ symbol }}</h2>
        <div class="subtitle">
            🟢 Long: <span class="badge badge-long">{{ min_ex }}</span> | 
            🔴 Short: <span class="badge badge-short">{{ max_ex }}</span>
        </div>
        <div id="chart-container"></div>

        <script>
            const chart = LightweightCharts.createChart(document.getElementById('chart-container'), {
                layout: {
                    background: { type: 'solid', color: '#1e1e1e' },
                    textColor: '#d1d4dc',
                },
                grid: {
                    vertLines: { color: '#2b2b2b' },
                    horzLines: { color: '#2b2b2b' },
                },
                timeScale: {
                    timeVisible: true,
                    secondsVisible: true,
                    borderColor: '#484848',
                },
                rightPriceScale: {
                    borderColor: '#484848',
                }
            });

            const lineSeries = chart.addLineSeries({
                color: '#00ffcc',
                lineWidth: 2,
            });

            const initialData = [
                { time: Math.floor(Date.now() / 1000) - 300, value: 7.2 },
                { time: Math.floor(Date.now() / 1000) - 240, value: 7.8 },
                { time: Math.floor(Date.now() / 1000) - 180, value: 8.5 },
                { time: Math.floor(Date.now() / 1000) - 120, value: 8.1 },
                { time: Math.floor(Date.now() / 1000) - 60, value: 8.9 },
                { time: Math.floor(Date.now() / 1000), value: 9.1 },
            ];
            lineSeries.setData(initialData);

            window.addEventListener('resize', () => {
                chart.resize(document.getElementById('chart-container').clientWidth, document.getElementById('chart-container').clientHeight);
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, symbol=symbol, min_ex=min_ex, max_ex=max_ex)

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
            print(f"⚠️ Site returned status {response.status_code} for {url}")
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

latest_prices_cache = {}

# ==================== ADVANCED AI & PROMO ANALYZER ====================
def analyze_text(text):
    if not OPENROUTER_API_KEY:
        return text
    prompt = f"""
Ты — профессиональный финансовый аналитик крипто-анонсов, промо-акций, кешбеков, квизов, торговых турниров и Web3 аирдропов. 
Найди и структурируй любые активности, лаунчпулы, баунти, раздачи, аирдропы, квизы (Quiz), розыгрыши мерча, XP-программы, турниры и Web3-квесты.
Ответь строго одним словом "SKIP", только если это чисто техническое обслуживание сервера/биржи без бонусов или юридические судебные иски. Любые квизы, мерч, раздачи, поинты, Web3 и промо НЕ пропускай!
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

    exchange_url = get_exchange_url(target_topic) if target_topic in TOPICS and target_topic not in ["NEWS", "SPREAD", "FUNDING", "WEB3", "CHAT"] else None

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
        "OKX": ["okx_ukraine", "okx_ru", "okx_campaign_announcement", "okxwalletannouncement", "OKX_Official"],
        "BYBIT": ["bybitukrainian", "bybitukrainiannews", "Bybit_CIS", "BybitAnnouncements"],
        "BITGET": ["BitgetUA", "Bitget_Announcements", "BitgetENOfficial"],
        "MEXC": ["MEXCKraineOfficial", "MEXCofficialNews", "MEXCofficial"],
        "GATE": ["Gate_Ukrainian", "Gateio_NewList_News", "GateCom_EN"],
        "KRAKEN": ["kraken_announcements"],
        "BINGX": ["BingXOfficial", "BingXAnnouncement", "BingXEnglish", "BingXRussianAnnouncements"],
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
                    
                    # БЕРЕМ ТОЛЬКО 1 ПОСЛЕДНИЙ ПОСТ
                    for msg in messages[-1:]:
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

# ==================== DIRECT EXCHANGE WEBSITES, APIS & WEB3 SCRAPER ====================
def fetch_direct_exchange_promos():
    while True:
        try:
            # 1. Binance Direct APIs
            binance_apis = [
                ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageNo=1&pageSize=1", "BINANCE"),
                ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=161&pageNo=1&pageSize=1", "BINANCE"),
                ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=379&pageNo=1&pageSize=1", "WEB3")
            ]
            for api_url, top_name in binance_apis:
                res = secure_request(api_url, timeout=6)
                if res:
                    try:
                        data = res.json()
                        for art in data.get('data', {}).get('articles', [])[:1]:
                            art_id = f"dir_binance_{art.get('id')}"
                            title = art.get('title', '')
                            code = art.get('code', '')
                            link = f"https://www.binance.com/en/support/announcement/{code}" if code else "https://www.binance.com"
                            raw_text = f"Binance Direct API Promo / Campaign: {title}\nLink: {link}"
                            process_item(art_id, raw_text, link, top_name)
                    except Exception as json_err:
                        print(f"⚠️ Binance API JSON decode error: {json_err}")

            # 2. MEXC Direct API
            mexc_api = "https://www.mexc.com/api/support/list?categoryId=19&page=1&pageSize=1"
            res_mexc = secure_request(mexc_api, timeout=6)
            if res_mexc:
                try:
                    mexc_data = res_mexc.json()
                    for item in mexc_data.get('data', {}).get('result', [])[:1]:
                        item_id = f"dir_mexc_{item.get('id')}"
                        title = item.get('title', '')
                        link = f"https://www.mexc.com/support/articles/{item.get('id')}"
                        raw_text = f"MEXC Direct API Promo / Campaign: {title}\nLink: {link}"
                        process_item(item_id, raw_text, link, "MEXC")
                except Exception as json_err:
                    print(f"⚠️ MEXC API JSON decode error: {json_err}")

            # 3. Web3 Wallet Quests (OKX Cryptopedia & Binance Web3)
            web3_sources = [
                ("OKX", "https://www.okx.com/en/web3/discover/cryptopedia", "a"),
                ("BINANCE", "https://www.binance.com/en/web3", "a")
            ]
            for w_ex, w_url, w_tag in web3_sources:
                w_res = secure_request(w_url, timeout=8)
                if w_res:
                    w_soup = BeautifulSoup(w_res.text, 'html.parser')
                    for el in w_soup.find_all(w_tag, limit=1):
                        w_title = el.get_text(strip=True)
                        if len(w_title) < 20: continue
                        w_link = el.get('href', '')
                        if w_link and not w_link.startswith('http'):
                            if w_ex == "OKX": w_link = f"https://www.okx.com{w_link}"
                        item_id = f"web3_{w_ex.lower()}_{abs(hash(w_title))}"
                        raw_text = f"Web3 Wallet Quest / Airdrop [{w_ex} Wallet]: {w_title}\nLink: {w_link if w_link else w_url}"
                        process_item(item_id, raw_text, w_link if w_link else w_url, "WEB3")

            # 4. Официальные сайты бирж
            websites = [
                ("OKX", "https://www.okx.com/help/section/announcements-latest-promotions", "a"),
                ("BITGET", "https://www.bitget.com/support/articles/latest-activities", "a"),
                ("BITGET_EVENTS", "https://www.bitget.com/events", "a"),
                ("GATE", "https://www.gate.io/articlelist/ann", "a"),
                ("KUCOIN", "https://www.kucoin.com/news/categories/promotion", "a"),
                ("WHITEBIT", "https://blog.whitebit.com/category/events/", "h2")
            ]

            for ex_name, site_url, tag in websites:
                web_res = secure_request(site_url, timeout=8)
                if not web_res: continue
                soup = BeautifulSoup(web_res.text, 'html.parser')
                elements = soup.find_all(tag, limit=1)
                for el in elements:
                    title = el.get_text(strip=True)
                    if len(title) < 15: continue
                    link = el.get('href', '')
                    clean_ex = ex_name.replace("_EVENTS", "")
                    if link and not link.startswith('http'):
                        if clean_ex == "OKX": link = f"https://www.okx.com{link}"
                        elif clean_ex == "BITGET": link = f"https://www.bitget.com{link}"
                        elif clean_ex == "GATE": link = f"https://www.gate.io{link}"
                        elif clean_ex == "KUCOIN": link = f"https://www.kucoin.com{link}"
                    
                    item_id = f"web_{ex_name.lower()}_{abs(hash(title))}"
                    raw_text = f"Official Website Announcement [{clean_ex}]: {title}\nLink: {link if link else site_url}"
                    process_item(item_id, raw_text, link if link else site_url, clean_ex)

        except Exception as e:
            print(f"Direct Promos Website/API Error: {e}")
        time.sleep(1200)

# ==================== GLOBAL CRYPTO APIS & RSS ====================
def fetch_global_crypto_promos():
    sources = [
        ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=161&pageNo=1&pageSize=1", "BINANCE"),
        ("https://coinmarketcap.com/headlines/news/", "NEWS"),
    ]

    while True:
        try:
            for api_url, topic in sources[:1]:
                res = secure_request(api_url, timeout=6)
                if not res: continue
                try:
                    data = res.json()
                    articles = data.get('data', {}).get('articles', [])
                    for art in articles[:1]:
                        art_id = f"global_api_{art.get('id')}"
                        title = art.get('title', '')
                        code = art.get('code', '')
                        link = f"https://www.binance.com/en/support/announcement/{code}" if code else "https://www.binance.com"
                        raw_text = f"Global Official Announcement / Event: {title}\nLink: {link}"
                        process_item(art_id, raw_text, link, topic)
                except Exception as json_err:
                    print(f"⚠️ Global API JSON decode error: {json_err}")

            rss_feeds = ["https://cointelegraph.com/rss", "https://cryptopotato.com/feed/"]
            for feed_url in rss_feeds:
                try:
                    feed = feedparser.parse(feed_url)
                    for entry in feed.entries[:1]:
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

# ==================== FUTURES & SPOT DATA FETCHING (OPTIMIZED & SAFE) ====================
def fetch_futures_data():
    global latest_prices_cache
    prices, volumes, fundings, funding_times = {}, {}, {}, {}
    
    # 1. Binance
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=3).json()
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['Binance'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['Binance'] = float(item['quoteVolume'])
    except Exception: pass

    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=3).json()
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                fundings.setdefault(sym, {})['Binance'] = float(item['lastFundingRate']) * 100
                next_time = int(item.get('nextFundingTime', 0)) // 1000
                if next_time > 0: funding_times.setdefault(sym, {})['Binance'] = next_time
    except Exception: pass

    # 2. Bybit
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=3).json().get('result', {}).get('list', [])
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

    # 3. OKX
    try:
        r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=3).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['instId'])
            if sym:
                prices.setdefault(sym, {})['OKX'] = float(item['last'])
                volumes.setdefault(sym, {})['OKX'] = float(item.get('volCcy24h', 0))
    except Exception: pass

    try:
        r = requests.get("https://api.okx.com/api/v5/public/funding-rate-all", timeout=3).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['instId'])
            if sym and item.get('fundingRate'):
                fundings.setdefault(sym, {})['OKX'] = float(item['fundingRate']) * 100
                next_time = int(item.get('nextFundingTime', 0)) // 1000
                if next_time > 0: funding_times.setdefault(sym, {})['OKX'] = next_time
    except Exception: pass

    # 4. Gate.io
    try:
        r = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=3).json()
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

    # 5. Bitget
    try:
        r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=3).json().get('data', [])
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

    # 6. MEXC
    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=3).json().get('data', [])
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

    # 7. BingX
    try:
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=3).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['BingX'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['BingX'] = float(item.get('volume', 0))
    except Exception: pass

    try:
        r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", timeout=3).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym and 'lastFundingRate' in item:
                fundings.setdefault(sym, {})['BingX'] = float(item['lastFundingRate']) * 100
                next_time = int(item.get('nextFundingTime', 0)) // 1000
                if next_time > 0: funding_times.setdefault(sym, {})['BingX'] = next_time
    except Exception: pass

    # 8. KuCoin
    try:
        r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=3).json().get('data', [])
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

    # Spot for quick price lookup
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=3).json()
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['BinanceSpot'] = float(item['price'])
    except Exception: pass

    for sym, ex_dict in prices.items():
        if ex_dict:
            latest_prices_cache[sym] = list(ex_dict.values())[0]

    return prices, volumes, fundings, funding_times

# ==================== УНИВЕРСАЛЬНЫЙ ПОИСК ЦЕНЫ И СТАКАНОВ МОНЕТ (SPOT + FUTURES) ====================
def fetch_token_prices_on_demand(sym):
    base_sym = sym.replace('USDT', '')
    ex_prices = {}
    ex_vols = {}

    # 1. Binance (Spot + Futures)
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={base_sym}USDT", timeout=2).json()
        if 'lastPrice' in r:
            ex_prices['Binance Spot'] = float(r['lastPrice'])
            ex_vols['Binance Spot'] = float(r.get('quoteVolume', 0))
    except: pass
    try:
        r = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={base_sym}USDT", timeout=2).json()
        if 'lastPrice' in r:
            ex_prices['Binance'] = float(r['lastPrice'])
            ex_vols['Binance'] = float(r.get('quoteVolume', 0))
    except: pass

    # 2. Bybit (Spot + Futures)
    try:
        r = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={base_sym}USDT", timeout=2).json()
        lst = r.get('result', {}).get('list', [])
        if lst:
            ex_prices['Bybit Spot'] = float(lst[0]['lastPrice'])
            ex_vols['Bybit Spot'] = float(lst[0].get('turnover24h', 0))
    except: pass
    try:
        r = requests.get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={base_sym}USDT", timeout=2).json()
        lst = r.get('result', {}).get('list', [])
        if lst:
            ex_prices['Bybit'] = float(lst[0]['lastPrice'])
            ex_vols['Bybit'] = float(lst[0].get('turnover24h', 0))
    except: pass

    # 3. MEXC (Spot + Futures)
    try:
        r = requests.get(f"https://api.mexc.com/api/v3/ticker/24hr?symbol={base_sym}USDT", timeout=2).json()
        if 'lastPrice' in r:
            ex_prices['MEXC Spot'] = float(r['lastPrice'])
            ex_vols['MEXC Spot'] = float(r.get('quoteVolume', 0))
    except: pass
    try:
        r = requests.get(f"https://contract.mexc.com/api/v1/contract/ticker?symbol={base_sym}_USDT", timeout=2).json()
        data = r.get('data', {})
        if 'lastPrice' in data:
            ex_prices['MEXC'] = float(data['lastPrice'])
            ex_vols['MEXC'] = float(data.get('amount24h', 0)) * float(data['lastPrice'])
    except: pass

    # 4. Gate.io (Spot + Futures)
    try:
        r = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={base_sym}_USDT", timeout=2).json()
        if isinstance(r, list) and len(r) > 0:
            ex_prices['Gate Spot'] = float(r[0]['last'])
            ex_vols['Gate Spot'] = float(r[0].get('quote_volume', 0))
    except: pass
    try:
        r = requests.get(f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={base_sym}_USDT", timeout=2).json()
        if isinstance(r, list) and len(r) > 0:
            ex_prices['Gate'] = float(r[0]['last'])
            ex_vols['Gate'] = float(r[0].get('total_size', 0)) * float(r[0]['last'])
    except: pass

    # 5. OKX (Spot + Swap)
    try:
        r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={base_sym}-USDT", timeout=2).json().get('data', [])
        if r:
            ex_prices['OKX Spot'] = float(r[0]['last'])
            ex_vols['OKX Spot'] = float(r[0].get('volCcy24h', 0))
    except: pass
    try:
        r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={base_sym}-USDT-SWAP", timeout=2).json().get('data', [])
        if r:
            ex_prices['OKX'] = float(r[0]['last'])
            ex_vols['OKX'] = float(r[0].get('volCcy24h', 0))
    except: pass

    # 6. Bitget (Spot + Futures)
    try:
        r = requests.get(f"https://api.bitget.com/api/v2/spot/market/tickers?symbol={base_sym}USDT", timeout=2).json().get('data', [])
        if r:
            ex_prices['Bitget Spot'] = float(r[0]['close'])
            ex_vols['Bitget Spot'] = float(r[0].get('usdtVol', 0))
    except: pass
    try:
        r = requests.get(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={base_sym}USDT&productType=USDT-FUTURES", timeout=2).json().get('data', [])
        if r:
            ex_prices['Bitget'] = float(r[0]['lastPr'])
            ex_vols['Bitget'] = float(r[0].get('quoteVolume', 0))
    except: pass

    if not ex_prices and sym in latest_prices_cache:
        ex_prices['Общий кэш'] = latest_prices_cache[sym]

    return ex_prices, ex_vols

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

# ==================== SPREAD MONITOR (WITH LOGGING & WEB APP) ====================
def monitor_spread():
    global active_spreads
    print("🟢 Spread Monitor started (Threshold: $100k volume, Spread >= 7.0%)")
    while True:
        try:
            prices, volumes, fundings, _ = fetch_futures_data()
            curr_time_str = get_kyiv_time()

            max_spread_seen = 0.0

            for sym, ex_data in prices.items():
                sym_vols = volumes.get(sym, {})
                valid_ex_data = {ex: p for ex, p in ex_data.items() if sym_vols.get(ex, 0) >= 100_000}

                if len(valid_ex_data) < 2:
                    continue
                
                min_ex = min(valid_ex_data, key=valid_ex_data.get)
                max_ex = max(valid_ex_data, key=valid_ex_data.get)
                min_p = valid_ex_data[min_ex]
                max_p = valid_ex_data[max_ex]
                
                if min_p <= 0: continue
                spread = ((max_p - min_p) / min_p) * 100
                
                if spread > max_spread_seen:
                    max_spread_seen = spread
                
                if 7.0 <= spread <= 30.0:
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

                    render_url = os.environ.get('RENDER_EXTERNAL_URL', '').strip()
                    if not render_url:
                        render_url = "https://your-app.onrender.com"
                    elif not render_url.startswith('http'):
                        render_url = f"https://{render_url}"
                    
                    webapp_url = f"{render_url}/chart?symbol={sym}&min_ex={min_ex}&max_ex={max_ex}"
                    
                    markup = InlineKeyboardMarkup()
                    try:
                        markup.add(InlineKeyboardButton("📈 Живой график спреда", web_app=WebAppInfo(url=webapp_url)))
                    except Exception as btn_err:
                        print(f"⚠️ WebApp Button Error: {btn_err}")

                    send_to_topic("SPREAD", msg_text, reply_markup=markup)

        except Exception as e:
            print(f"❌ Monitor Spread Error: {e}")
        
        time.sleep(30)

# ==================== FUNDING MONITOR ====================
def monitor_funding():
    print("🟢 Funding Monitor started (Topic 76, Spread >= 0.5%)")
    while True:
        try:
            _, volumes, fundings, funding_times = fetch_futures_data()
            curr_time_str = get_kyiv_time()

            for sym, ex_funds in fundings.items():
                sym_vols = volumes.get(sym, {})
                
                valid_ex_funds = {ex: rate for ex, rate in ex_funds.items() if sym_vols.get(ex, 0) >= 100_000}
                if len(valid_ex_funds) < 2:
                    continue

                max_ex = max(valid_ex_funds, key=valid_ex_funds.get)
                min_ex = min(valid_ex_funds, key=valid_ex_funds.get)
                max_rate = valid_ex_funds[max_ex]
                min_rate = valid_ex_funds[min_ex]
                
                funding_spread = abs(max_rate - min_rate)
                
                if funding_spread >= 0.5:
                    vol_min = sym_vols.get(min_ex, 0) * 0.01
                    vol_max = sym_vols.get(max_ex, 0) * 0.01
                    max_pos_usdt = int(min(vol_min, vol_max))
                    if max_pos_usdt < 100: max_pos_usdt = 100

                    rates_list = []
                    sorted_exs = sorted(valid_ex_funds.keys(), key=lambda ex: sym_vols.get(ex, 0), reverse=True)
                    for ex in sorted_exs:
                        r = valid_ex_funds[ex]
                        next_t = funding_times.get(sym, {}).get(ex, 0)
                        countdown = format_countdown(next_t)
                        url = get_exchange_url(ex, sym)
                        rates_list.append(f"🔹 [{ex}]({url}): `{r:+.2f}%` (⏱ `{countdown}`)")

                    rates_overview = "\n".join(rates_list)

                    msg_text = (
                        f"🔥 **FUNDING ARBITRAGE / HIGH SPREAD (>= 0.5%)**\n"
                        f"🪙 **#{sym} (Spread: `{funding_spread:.2f}%`)**\n\n"
                        f"💰 **Доступный объем позиции:** `~${max_pos_usdt:,} USDT`\n\n"
                        f"📊 **All Exchanges Rates & Timers:**\n{rates_overview}\n\n"
                        f"🔄 _Данные обновлены в {curr_time_str} (Киев)_"
                    )
                    
                    send_to_topic("FUNDING", msg_text)
                    time.sleep(2)

        except Exception as e:
            print(f"❌ Funding Monitor Error: {e}")
        
        time.sleep(1800)

# ==================== TELEGRAM COMMANDS & CALCULATORS ====================
@bot.message_handler(commands=['vol', 'volume'])
def cmd_vol(message):
    text = message.text.strip()
    parts = re.findall(r'[\d.,]+', text)
    if len(parts) >= 2:
        try:
            cost = float(parts[0].replace(',', '.'))
            volume = float(parts[1].replace(',', '.'))
            if volume <= 0:
                raise ValueError
            
            # ИСПРАВЛЕННЫЙ РАСЧЕТ: Цена за 1K объема (если объем в штуках/монетах или в сотнях)
            cost_per_1k = (cost / volume) * 1000
            
            vol_display = f"{volume:,.1f} ({volume/1000:.2f}K)" if volume >= 1000 else f"{volume:,.1f}"
            
            response_text = (
                f"📊 **Расчет стоимости объема:**\n"
                f"💵 Затраты: `${cost:.2f}`\n"
                f"📈 Объем: `{vol_display}`\n"
                f"💎 Цена за 1K объема:\n`$ {cost_per_1k:.2f}`"
            )
            bot.reply_to(message, response_text, parse_mode="Markdown")
            return
        except Exception as e:
            print(f"❌ /vol error: {e}")
            
    bot.reply_to(message, "ℹ️ Использование команды: `/vol [затраты] [объем]` (например: `/vol 52.5 11000`)", parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_chat_messages(message):
    if not message.text:
        return
    text = message.text.strip()
    
    calc_match = re.search(r'^([\d.]+)\s*-\s*([\d.]+)$', text)
    if calc_match:
        try:
            val1 = float(calc_match.group(1))
            val2 = float(calc_match.group(2))
            res = val1 - val2
            bot.reply_to(message, f"🧮 **Калькулятор:**\n{val1} - {val2} = `{res:.2f}`", parse_mode="Markdown")
            return
        except Exception:
            pass

    if text.startswith('/'):
        return

    amount_token_match = re.search(r'^([\d\s,.]+?)\s*([a-zA-Z0-9_-]+)$', text)
    if amount_token_match:
        try:
            raw_amount_str = amount_token_match.group(1).replace(' ', '').replace(',', '')
            amount = float(raw_amount_str)
            raw_tkn = amount_token_match.group(2)
            sym = normalize_symbol(raw_tkn)
            
            sym_prices, sym_vols = fetch_token_prices_on_demand(sym)
            
            if sym_prices:
                avg_price = list(sym_prices.values())[0]
                total_usd = amount * avg_price
                
                lines = [
                    f"🪙 **Расчет по монете: #{sym}**",
                    f"📦 Количество: `{amount:,.4f}`",
                    f"💵 Текущая цена: `${avg_price}`",
                    f"💰 **Общая стоимость:** `~${total_usd:,.2f} USD`\n",
                    "📝 **Цены на биржах (Spot & Futures):**"
                ]
                for ex, p in sorted(sym_prices.items(), key=lambda x: x[1]):
                    v = format_volume(sym_vols.get(ex, 0))
                    url = get_exchange_url(ex.replace(' Spot', ''), sym)
                    lines.append(f"🔹 [{ex}]({url}): `${p}` ({v})")
                
                bot.reply_to(message, "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)
                return
        except Exception as e:
            print(f"Universal Amount-Token calc error: {e}")

    if len(text) > 15:
        return
        
    sym = normalize_symbol(text)
    if not sym:
        return
        
    sym_prices, sym_vols = fetch_token_prices_on_demand(sym)
    if not sym_prices:
        return
        
    sorted_exs = sorted(sym_prices.keys(), key=lambda ex: sym_prices[ex])
    lines = [f"🪙 **Монета: #{sym} (Spot & Futures)**\n"]
    for ex in sorted_exs:
        p = sym_prices[ex]
        v = format_volume(sym_vols.get(ex, 0))
        url = get_exchange_url(ex.replace(' Spot', ''), sym)
        lines.append(f"🔹 [{ex}]({url}): `${p}` ({v})")
        
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)

# ==================== MAIN START ====================
if __name__ == "__main__":
    print("🚀 Bot starting...")
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Запускаем фоновые потоки сканеров
    threading.Thread(target=fetch_telegram_channels_promos, daemon=True).start()
    threading.Thread(target=fetch_direct_exchange_promos, daemon=True).start()
    threading.Thread(target=fetch_global_crypto_promos, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()

    print("🤖 Telegram bot polling started...")
    bot.infinity_polling(skip_pending=True)
