import os
import time
import threading
import datetime
import json
import re
import random
import io
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz
import requests
import feedparser
import telebot
from bs4 import BeautifulSoup
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, render_template_string, request, jsonify

# ==================== CONFIGURATION ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
CHAT_ID = "-1004451728851"
ADMIN_IDS = [1043209905, 7556503425, 387143257]

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
    "KRAKEN": 73,
    "GATE": 67,
    "OKX": 6,
    "FUNDING": 76,
    "SPREAD": 77,
    "WEB3": 5190,
    "NEWSMAKER": 4203,
    "ALPHA": 4273,
    "CHAT": 1
}

USER_EXCHANGES = ["Binance", "Bybit", "OKX", "Bitget", "BingX", "Gate", "KuCoin", "MEXC"]

processed_ids = set()
active_fundings = {}
spread_history = {}
price_history_long = {}
price_history_short = {}
sent_alerts_cache = {}

active_alpha_sessions = {}
alpha_price_memory = {}

# Флаг управления мониторингом спредов (по умолчанию выключен, включается командой /spread_on)
spread_monitor_enabled = False

# Пороги логики спредов
SPREAD_ENTRY_MIN = 5.0
SPREAD_ENTRY_MAX = 80.0             # Адекватный верхний фильтр против битых стаканов
SPREAD_HYSTERESIS_THRESHOLD = 2.5   # Гистерезис для удержания открытого поста
SPREAD_CLOSE_THRESHOLD = 1.0        # Реальное схождение (< 1.0%)
PENDING_BUFFER_SECONDS = 15         # Выдержка до подтверждения вектора входа
MIN_ENTRY_POS_USDT = 500            # Минимальная оценка объема для входа
MIN_EXCHANGE_VOL_USDT = 5_000       # Минимальный 24h оборот биржи для участия в поиске
MIN_VALID_PRICE = 1e-6              # Отсекаем копеечные глюки вроде 2.5e-05 / 2.5e-50
MAX_MEDIAN_DEVIATION = 0.40         # Макс. отклонение от медианной цены монеты (40%)
CLOSE_CONFIRM_POLLS = 2             # Подтверждение схождения на 2 циклах подряд
CLOSE_MISSING_LIMIT = 3             # Допуск битых/пропавших цен перед закрытием
PAIR_COOLDOWN_SECONDS = 180         # Кулдаун на конкретную связку бирж после закрытия
STALE_POLL_LIMIT = 4                # Сколько циклов подряд цена может стоять без движения при живой монете
SMOOTH_WINDOW = 3                   # Окно сглаживания спреда для защиты от качелей

SPREADS_FILE = "active_spreads.json"

def load_active_spreads():
    if os.path.exists(SPREADS_FILE):
        try:
            with open(SPREADS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_active_spreads(spreads_dict):
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

def format_price(price):
    """Форматирует цену без научной записи (e-05 / e-50)."""
    try:
        val = float(price)
    except (TypeError, ValueError):
        return "0"
    if val <= 0:
        return "0"
    if val >= 1000:
        s = f"{val:.2f}"
    elif val >= 1:
        s = f"{val:.4f}"
    elif val >= 0.01:
        s = f"{val:.6f}"
    else:
        s = f"{val:.8f}"
    return s.rstrip('0').rstrip('.') if '.' in s else s

def parse_normalized_symbol(raw_sym):
    """
    Нормализует тикер и возвращает (base_symbol, unit_multiplier),
    чтобы приводить контракты вида 1000PEPE / 1000000MOG / kBONK к цене за 1 монету.
    """
    if not raw_sym:
        return "", 1.0
    sym = raw_sym.upper().replace('_', '').replace('-', '').replace('/', '')
    for suffix in ("USDTM", "USDT", "USDC", "SWAP", "PERP"):
        if sym.endswith(suffix):
            sym = sym[:-len(suffix)]
            break

    multiplier = 1.0
    m = re.match(r'^(\d{2,9})([A-Z0-9]{2,})$', sym)
    if m:
        mult_val = float(m.group(1))
        base_val = m.group(2)
        if base_val and mult_val >= 10:
            return base_val, mult_val

    if sym.startswith("K") and len(sym) >= 3 and sym[1:2].isupper():
        return sym[1:], 1000.0

    return sym, multiplier

def normalize_symbol(raw_sym):
    base, _ = parse_normalized_symbol(raw_sym)
    return base

def make_venue_key(exchange, market_type="Fut"):
    m_tag = "Spot" if market_type.lower().startswith("spot") else "Fut"
    return f"{exchange} {m_tag}"

def split_venue_key(venue_key):
    parts = venue_key.rsplit(" ", 1)
    if len(parts) == 2 and parts[1] in ("Fut", "Spot"):
        return parts[0], parts[1]
    return venue_key, "Fut"

def is_allowed_venue_pair(min_ex, max_ex):
    """Разрешаем только Fut + Fut и Fut + Spot (исключаем чистый Spot + Spot)."""
    if not min_ex or not max_ex or min_ex == max_ex:
        return False
    _, m1 = split_venue_key(min_ex)
    _, m2 = split_venue_key(max_ex)
    return (m1 == "Fut") or (m2 == "Fut")

# ==================== SECURE REQUESTS & ROTATING HEADERS ====================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
]

def get_random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

def secure_request(url, timeout=12):
    try:
        response = requests.get(url, headers=get_random_headers(), timeout=timeout)
        if response.status_code == 200:
            return response
        else:
            return None
    except Exception:
        return None

# ==================== DIRECT EXCHANGE PRICE ENGINE ====================
def fetch_token_prices_on_demand(sym):
    base_sym, _ = parse_normalized_symbol(sym)
    ex_prices, ex_vols = {}, {}

    def _bin():
        try:
            r = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={base_sym}USDT", timeout=2.5).json()
            if 'price' in r and float(r['price']) >= MIN_VALID_PRICE:
                ex_prices['Binance Fut'] = float(r['price'])
        except: pass
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={base_sym}USDT", timeout=2.5).json()
            if 'price' in r and float(r['price']) >= MIN_VALID_PRICE:
                ex_prices['Binance Spot'] = float(r['price'])
        except: pass

    def _byb():
        try:
            r = requests.get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={base_sym}USDT", timeout=2.5).json().get('result', {}).get('list', [])
            if r and float(r[0]['lastPrice']) >= MIN_VALID_PRICE:
                ex_prices['Bybit Fut'] = float(r[0]['lastPrice'])
                ex_vols['Bybit Fut'] = float(r[0].get('turnover24h', 0))
        except: pass
        try:
            r = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={base_sym}USDT", timeout=2.5).json().get('result', {}).get('list', [])
            if r and float(r[0]['lastPrice']) >= MIN_VALID_PRICE:
                ex_prices['Bybit Spot'] = float(r[0]['lastPrice'])
                ex_vols['Bybit Spot'] = float(r[0].get('turnover24h', 0))
        except: pass

    def _kuc():
        try:
            r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=3).json().get('data', [])
            for item in r:
                s_base, s_mult = parse_normalized_symbol(item.get('symbol', ''))
                if s_base == base_sym and 'lastTradePrice' in item:
                    p_val = float(item['lastTradePrice']) / s_mult
                    if p_val >= MIN_VALID_PRICE:
                        ex_prices['KuCoin Fut'] = p_val
                        ex_vols['KuCoin Fut'] = float(item.get('turnoverOf24h', 0))
                    break
        except: pass
        try:
            r = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={base_sym}-USDT", timeout=2.5).json().get('data', {})
            if isinstance(r, dict) and r.get('price') and float(r['price']) >= MIN_VALID_PRICE:
                ex_prices['KuCoin Spot'] = float(r['price'])
        except: pass

    def _gate():
        try:
            r = requests.get(f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={base_sym}_USDT", timeout=2.5).json()
            if isinstance(r, list) and len(r) > 0 and float(r[0]['last']) >= MIN_VALID_PRICE:
                ex_prices['Gate Fut'] = float(r[0]['last'])
                ex_vols['Gate Fut'] = float(r[0].get('total_size', 0)) * float(r[0]['last'])
        except: pass
        try:
            r = requests.get(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={base_sym}_USDT", timeout=2.5).json()
            if isinstance(r, list) and len(r) > 0 and r[0].get('last') and float(r[0]['last']) >= MIN_VALID_PRICE:
                ex_prices['Gate Spot'] = float(r[0]['last'])
                ex_vols['Gate Spot'] = float(r[0].get('quote_volume', 0))
        except: pass

    def _okx():
        try:
            r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={base_sym}-USDT-SWAP", timeout=2.5).json().get('data', [])
            if r and float(r[0]['last']) >= MIN_VALID_PRICE:
                ex_prices['OKX Fut'] = float(r[0]['last'])
                ex_vols['OKX Fut'] = float(r[0].get('volCcy24h', 0))
        except: pass
        try:
            r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={base_sym}-USDT", timeout=2.5).json().get('data', [])
            if r and float(r[0]['last']) >= MIN_VALID_PRICE:
                ex_prices['OKX Spot'] = float(r[0]['last'])
                ex_vols['OKX Spot'] = float(r[0].get('volCcy24h', 0))
        except: pass

    def _mexc():
        try:
            r = requests.get(f"https://contract.mexc.com/api/v1/contract/ticker?symbol={base_sym}_USDT", timeout=2.5).json().get('data', {})
            if isinstance(r, dict) and 'lastPrice' in r and float(r['lastPrice']) >= MIN_VALID_PRICE:
                ex_prices['MEXC Fut'] = float(r['lastPrice'])
                ex_vols['MEXC Fut'] = float(r.get('amount24h', 0)) * float(r['lastPrice'])
        except: pass
        try:
            r = requests.get(f"https://api.mexc.com/api/v3/ticker/24hr?symbol={base_sym}USDT", timeout=2.5).json()
            if isinstance(r, dict) and r.get('lastPrice') and float(r['lastPrice']) >= MIN_VALID_PRICE:
                ex_prices['MEXC Spot'] = float(r['lastPrice'])
                ex_vols['MEXC Spot'] = float(r.get('quoteVolume', 0))
        except: pass

    def _bitget():
        try:
            r = requests.get(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={base_sym}USDT&productType=USDT-FUTURES", timeout=2.5).json().get('data', [])
            if r and float(r[0]['lastPr']) >= MIN_VALID_PRICE:
                ex_prices['Bitget Fut'] = float(r[0]['lastPr'])
                ex_vols['Bitget Fut'] = float(r[0].get('quoteVolume', 0))
        except: pass
        try:
            r = requests.get(f"https://api.bitget.com/api/v2/spot/market/tickers?symbol={base_sym}USDT", timeout=2.5).json().get('data', [])
            if r and float(r[0]['lastPr']) >= MIN_VALID_PRICE:
                ex_prices['Bitget Spot'] = float(r[0]['lastPr'])
                ex_vols['Bitget Spot'] = float(r[0].get('quoteVolume', 0))
        except: pass

    def _bingx():
        try:
            r = requests.get(f"https://open-api.bingx.com/openApi/swap/v2/quote/ticker?symbol={base_sym}-USDT", timeout=2.5).json().get('data', {})
            if isinstance(r, dict) and r.get('lastPrice') and float(r['lastPrice']) >= MIN_VALID_PRICE:
                ex_prices['BingX Fut'] = float(r['lastPrice'])
                ex_vols['BingX Fut'] = float(r.get('volume', 0))
        except: pass
        try:
            r = requests.get(f"https://open-api.bingx.com/openApi/spot/v1/ticker/24hr?symbol={base_sym}-USDT", timeout=2.5).json().get('data', [])
            if isinstance(r, list) and len(r) > 0 and r[0].get('lastPrice') and float(r[0]['lastPrice']) >= MIN_VALID_PRICE:
                ex_prices['BingX Spot'] = float(r[0]['lastPrice'])
                ex_vols['BingX Spot'] = float(r[0].get('quoteVolume', 0))
        except: pass

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(fn) for fn in (_bin, _byb, _kuc, _gate, _okx, _mexc, _bitget, _bingx)]
        for f in as_completed(futs):
            try: f.result()
            except: pass

    return ex_prices, ex_vols

def fetch_binance_alpha_price(token_query):
    if not token_query:
        return 0.0
    base_target, _ = parse_normalized_symbol(token_query)
    ex_prices, _ = fetch_token_prices_on_demand(base_target)
    valid = [p for p in ex_prices.values() if p >= MIN_VALID_PRICE]
    return valid[0] if valid else 0.0

# ==================== HEALTHCHECK & WEB APP CHART SERVER ====================
@app.route('/')
def health():
    return "OK", 200

@app.route('/api/chart-data')
def chart_data_api():
    symbol = request.args.get('symbol', 'BTCUSDT')
    min_ex = request.args.get('min_ex', 'Long')
    max_ex = request.args.get('max_ex', 'Short')

    key = f"{symbol}_{min_ex}_{max_ex}"
    long_points = price_history_long.get(key, [])
    short_points = price_history_short.get(key, [])

    now_ts = int(time.time())

    current_prices, _ = fetch_token_prices_on_demand(symbol)
    p_long = current_prices.get(min_ex, 0)
    p_short = current_prices.get(max_ex, 0)

    if p_long < MIN_VALID_PRICE or p_short < MIN_VALID_PRICE:
        valid_p = [p for p in current_prices.values() if p >= MIN_VALID_PRICE]
        if len(valid_p) >= 2:
            p_long = min(valid_p)
            p_short = max(valid_p)
        elif len(valid_p) == 1:
            p_long = valid_p[0]
            p_short = valid_p[0] * 1.02
        else:
            p_long, p_short = 10.0, 10.5

    if not long_points:
        long_points = [{"time": now_ts - 60, "value": p_long}, {"time": now_ts, "value": p_long}]
    else:
        if long_points[-1]["value"] != p_long:
            long_points.append({"time": now_ts, "value": p_long})

    if not short_points:
        short_points = [{"time": now_ts - 60, "value": p_short}, {"time": now_ts, "value": p_short}]
    else:
        if short_points[-1]["value"] != p_short:
            short_points.append({"time": now_ts, "value": p_short})

    if len(long_points) > 300: long_points.pop(0)
    if len(short_points) > 300: short_points.pop(0)

    price_history_long[key] = long_points
    price_history_short[key] = short_points

    return jsonify({
        "long_data": long_points,
        "short_data": short_points
    })

@app.route('/chart')
def web_chart():
    symbol = request.args.get('symbol', 'BTCUSDT')
    min_ex = request.args.get('min_ex', 'Long')
    max_ex = request.args.get('max_ex', 'Short')

    key = f"{symbol}_{min_ex}_{max_ex}"
    now_ts = int(time.time())

    current_prices, _ = fetch_token_prices_on_demand(symbol)
    p_long = current_prices.get(min_ex, 0)
    p_short = current_prices.get(max_ex, 0)

    if p_long < MIN_VALID_PRICE or p_short < MIN_VALID_PRICE:
        valid_p = [p for p in current_prices.values() if p >= MIN_VALID_PRICE]
        if len(valid_p) >= 2:
            p_long = min(valid_p)
            p_short = max(valid_p)
        else:
            p_long, p_short = 10.0, 10.5

    long_points = price_history_long.get(key, [])
    short_points = price_history_short.get(key, [])

    if not long_points:
        long_points = [{"time": now_ts - 60, "value": p_long}, {"time": now_ts, "value": p_long}]
    if not short_points:
        short_points = [{"time": now_ts - 60, "value": p_short}, {"time": now_ts, "value": p_short}]

    long_json = json.dumps(long_points)
    short_json = json.dumps(short_points)

    html_template = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>График схождения: {{ symbol }}</title>
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
        <h2>📈 Схождение: {{ symbol }}</h2>
        <div class="subtitle">
            🟢 Long ({{ min_ex }}): <span class="badge badge-long">Линия входа</span> |
            🔴 Short ({{ max_ex }}): <span class="badge badge-short">Линия выхода</span>
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

            const longSeries = chart.addLineSeries({
                color: '#00ff80',
                lineWidth: 2,
                title: 'Long ({{ min_ex }})'
            });

            const shortSeries = chart.addLineSeries({
                color: '#ff4d4d',
                lineWidth: 2,
                title: 'Short ({{ max_ex }})'
            });

            longSeries.setData({{ long_json | safe }});
            shortSeries.setData({{ short_json | safe }});
            chart.timeScale().fitContent();

            setInterval(async () => {
                try {
                    const res = await fetch('/api/chart-data?symbol={{ symbol }}&min_ex={{ min_ex }}&max_ex={{ max_ex }}');
                    const data = await res.json();
                    if (data) {
                        if (data.long_data && data.long_data.length > 0) {
                            const latestLong = data.long_data[data.long_data.length - 1];
                            longSeries.update(latestLong);
                        }
                        if (data.short_data && data.short_data.length > 0) {
                            const latestShort = data.short_data[data.short_data.length - 1];
                            shortSeries.update(latestShort);
                        }
                    }
                } catch (e) {
                    console.error("Error updating convergence chart:", e);
                }
            }, 6000);

            window.addEventListener('resize', () => {
                chart.resize(document.getElementById('chart-container').clientWidth, document.getElementById('chart-container').clientHeight);
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, symbol=symbol, min_ex=min_ex, max_ex=max_ex, long_json=long_json, short_json=short_json)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def get_exchange_url(exchange, symbol="BTCUSDT", market_type="Fut"):
    base_sym, _ = parse_normalized_symbol(symbol)
    ex_name, parsed_m = split_venue_key(exchange)
    m_type = parsed_m if " " in exchange else market_type
    ex_upper = ex_name.upper()
    is_spot = m_type.lower().startswith("spot")

    if is_spot:
        spot_links = {
            "BINANCE": f"https://www.binance.com/en/trade/{base_sym}_USDT",
            "BYBIT": f"https://www.bybit.com/en/trade/spot/{base_sym}/USDT",
            "OKX": f"https://www.okx.com/trade-spot/{base_sym.lower()}-usdt",
            "GATE": f"https://www.gate.io/trade/{base_sym}_USDT",
            "BITGET": f"https://www.bitget.com/spot/{base_sym}USDT",
            "MEXC": f"https://www.mexc.com/exchange/{base_sym}_USDT",
            "BINGX": f"https://bingx.com/en/spot/{base_sym}USDT",
            "KUCOIN": f"https://www.kucoin.com/trade/{base_sym}-USDT"
        }
        return spot_links.get(ex_upper, None)

    fut_links = {
        "BINANCE": f"https://www.binance.com/en/futures/{base_sym}USDT",
        "BYBIT": f"https://www.bybit.com/trade/usdt/{base_sym}USDT",
        "OKX": f"https://www.okx.com/trade-swap/{base_sym.lower()}-usdt-swap",
        "GATE": f"https://www.gate.io/futures/USDT/{base_sym}_USDT",
        "BITGET": f"https://www.bitget.com/futures/usdt/{base_sym}USDT",
        "MEXC": f"https://futures.mexc.com/exchange/{base_sym}_USDT",
        "BINGX": f"https://bingx.com/en/futures/forward/{base_sym}USDT",
        "KUCOIN": f"https://www.kucoin.com/futures/trade/{base_sym}USDTM"
    }
    return fut_links.get(ex_upper, None)

latest_prices_cache = {}

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

def translate_newsmaker_text(text):
    if not OPENROUTER_API_KEY:
        return text
    prompt = f"""
Ты — профессиональный крипто-переводчик. Переведи следующий текст новости крипторынка на русский язык качественно, профессионально, сохранив весь смысл и крипто-терминологию. Сделай текст читаемым и структурированным.

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
        print(f"NewsMaker Translation Error: {e}")
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

def extract_official_web_link(msg_element, fallback_link):
    try:
        buttons = msg_element.find_all('a', class_='tgme_widget_message_inline_button')
        for btn in buttons:
            href = btn.get('href', '')
            if href and any(domain in href.lower() for domain in ['binance.com', 'bybit.com', 'okx.com', 'gate.io', 'gate.com', 'bitget.com', 'mexc.com', 'bingx.com', 'kucoin.com']):
                return href

        text_elem = msg_element.find('div', class_='tgme_widget_message_text')
        if text_elem:
            links = text_elem.find_all('a', href=True)
            for a in links:
                href = a['href']
                if href and any(domain in href.lower() for domain in ['binance.com', 'bybit.com', 'okx.com', 'gate.io', 'gate.com', 'bitget.com', 'mexc.com', 'bingx.com', 'kucoin.com']):
                    return href
    except: pass
    return fallback_link

def process_item(item_id, raw_text, link, default_topic, msg_element=None):
    if item_id in processed_ids:
        return
    processed_ids.add(item_id)

    ai_result = analyze_text(raw_text)
    if "SKIP" in ai_result.upper():
        return

    target_topic = default_topic.upper()
    if target_topic not in TOPICS:
        target_topic = "NEWS"

    official_web_link = None
    if msg_element is not None:
        official_web_link = extract_official_web_link(msg_element, link)
    else:
        official_web_link = link

    if target_topic == "BYBIT" and not official_web_link:
        official_web_link = "https://www.bybit.com"

    exchange_url = get_exchange_url(target_topic) if target_topic in TOPICS and target_topic not in ["NEWS", "SPREAD", "FUNDING", "WEB3", "NEWSMAKER", "ALPHA", "CHAT"] else None

    markup = InlineKeyboardMarkup()
    if official_web_link and official_web_link.startswith("http"):
        markup.add(InlineKeyboardButton("🌐 Официальный сайт / Анонс", url=official_web_link))
    elif exchange_url and exchange_url.startswith("http"):
        markup.add(InlineKeyboardButton(f"🌐 Биржа ({target_topic})", url=exchange_url))

    if link and link.startswith("http") and link != official_web_link:
        markup.add(InlineKeyboardButton("📱 Источник (Telegram)", url=link))

    send_to_topic(target_topic, ai_result, reply_markup=markup)
    time.sleep(1)

def fetch_telegram_channels_promos():
    channels = {
        "BINANCE": {
            "channels": ["Binance_UA_official", "BinanceUkrainian", "binance_announcements", "Binance_Announcements"],
            "web3_channels": ["binanceweb3"],
            "topic": "BINANCE"
        },
        "OKX": {
            "channels": ["okx_ukraine", "okx_ru", "OKXAnnouncements", "okx_campaign_announcement", "OKX_Official"],
            "web3_channels": ["okxwalletannouncement"],
            "topic": "OKX"
        },
        "BYBIT": {
            "channels": ["bybitukrainiannews"],
            "web3_channels": [],
            "topic": "BYBIT"
        },
        "BITGET": {
            "channels": ["BitgetUA", "Bitget_Announcements", "BitgetENOfficial"],
            "web3_channels": ["bitget_wallet"],
            "topic": "BITGET"
        },
        "KUCOIN": {
            "channels": ["Kucoin_Exchange", "Kucoin_News"],
            "web3_channels": ["KuCoin_Web3Wallet", "kucoin_web3"],
            "topic": "KUCOIN"
        },
        "MEXC": {
            "channels": ["MEXCKraineOfficial", "MEXCofficialNews", "MEXCofficial"],
            "web3_channels": [],
            "topic": "MEXC"
        },
        "GATE": {
            "channels": ["GateOfficialNews", "Gate_Ukrainian", "GateCom_EN", "Gateio_NewList_News"],
            "web3_channels": [],
            "topic": "GATE"
        },
        "BINGX": {
            "channels": ["BingXOfficial", "BingXAnnouncement", "BingXEnglish", "BingXRussianAnnouncements"],
            "web3_channels": [],
            "topic": "BINGX"
        }
    }

    while True:
        try:
            for ex_key, data in channels.items():
                target_topic = data["topic"]
                for chan in data["channels"]:
                    url = f"https://t.me/s/{chan}"
                    res = secure_request(url, timeout=8)
                    if not res: continue
                    soup = BeautifulSoup(res.text, 'html.parser')
                    messages = soup.find_all('div', class_='tgme_widget_message')
                    for msg in messages[-1:]:
                        msg_id_attr = msg.get('data-post', '')
                        if not msg_id_attr: continue
                        item_id = f"tg_chan_{msg_id_attr.replace('/', '_')}"
                        text_div = msg.find('div', class_='tgme_widget_message_text')
                        if not text_div: continue
                        raw_text = text_div.get_text(separator='\n', strip=True)
                        post_link = f"https://t.me/{msg_id_attr}"
                        btn = msg.find('a', class_='tgme_widget_message_url')
                        if btn and btn.get('href'): post_link = btn.get('href')
                        full_payload = f"Telegram Channel [{ex_key} / @{chan}]:\n{raw_text}\nLink: {post_link}"
                        process_item(item_id, full_payload, post_link, target_topic, msg_element=msg)

                for chan in data["web3_channels"]:
                    url = f"https://t.me/s/{chan}"
                    res = secure_request(url, timeout=8)
                    if not res: continue
                    soup = BeautifulSoup(res.text, 'html.parser')
                    messages = soup.find_all('div', class_='tgme_widget_message')
                    for msg in messages[-1:]:
                        msg_id_attr = msg.get('data-post', '')
                        if not msg_id_attr: continue
                        item_id = f"tg_web3_{msg_id_attr.replace('/', '_')}"
                        text_div = msg.find('div', class_='tgme_widget_message_text')
                        if not text_div: continue
                        raw_text = text_div.get_text(separator='\n', strip=True)
                        post_link = f"https://t.me/{msg_id_attr}"
                        btn = msg.find('a', class_='tgme_widget_message_url')
                        if btn and btn.get('href'): post_link = btn.get('href')
                        full_payload = f"Web3 Quest & Airdrop [{ex_key} Web3 / @{chan}]:\n{raw_text}\nLink: {post_link}"
                        process_item(item_id, full_payload, post_link, target_topic, msg_element=msg)

            time.sleep(600)
        except Exception as e:
            print(f"Telegram Channels & Web3 Monitor Error: {e}")
            time.sleep(60)

def poll_news_source(channel_username, label_prefix):
    url = f"https://t.me/s/{channel_username}"
    res = secure_request(url, timeout=10)
    if not res: return

    soup = BeautifulSoup(res.text, 'html.parser')
    messages = soup.find_all('div', class_='tgme_widget_message')
    for msg in messages[-1:]:
        msg_id_attr = msg.get('data-post', '')
        if not msg_id_attr: continue

        item_id = f"{label_prefix}_{msg_id_attr.replace('/', '_')}"
        if item_id in processed_ids: continue
        processed_ids.add(item_id)

        text_div = msg.find('div', class_='tgme_widget_message_text')
        raw_text = text_div.get_text(separator='\n', strip=True) if text_div else ""

        photo_url = None
        photo_wrap = msg.find('a', class_='tgme_widget_message_photo_wrap')
        if photo_wrap and photo_wrap.has_attr('style'):
            style_str = photo_wrap['style']
            match = re.search(r"background-image:\s*url\(['\"]?(.*?)['\"]?\)", style_str)
            if match:
                photo_url = match.group(1)

        if not photo_url:
            img_tag = msg.find('img', class_='tgme_widget_message_photo_image')
            if img_tag and img_tag.has_attr('src'):
                photo_url = img_tag['src']

        post_link = f"https://t.me/{msg_id_attr}"
        btn = msg.find('a', class_='tgme_widget_message_url')
        if btn and btn.get('href'): post_link = btn.get('href')

        translated_text = translate_newsmaker_text(raw_text) if raw_text else "📰 Крипто-новость"

        msg_text = (
            f"📰 **Crypto News ({label_prefix})**\n\n"
            f"{translated_text}\n\n"
            f"🔄 _Источник рынка_"
        )

        markup = InlineKeyboardMarkup()
        if post_link and post_link.startswith("http"):
            markup.add(InlineKeyboardButton("📱 Оригинал новости", url=post_link))

        thread_id = TOPICS.get("NEWSMAKER", 4203)

        photo_sent = False
        if photo_url:
            try:
                img_res = requests.get(photo_url, headers=get_random_headers(), timeout=10)
                if img_res.status_code == 200:
                    photo_file = io.BytesIO(img_res.content)
                    photo_file.name = "chart.jpg"
                    bot.send_photo(
                        chat_id=CHAT_ID,
                        message_thread_id=thread_id,
                        photo=photo_file,
                        caption=msg_text,
                        parse_mode="Markdown",
                        reply_markup=markup
                    )
                    photo_sent = True
            except Exception as img_err:
                print(f"❌ Failed to download/send image for {label_prefix}: {img_err}")

        if not photo_sent:
            try:
                bot.send_message(
                    chat_id=CHAT_ID,
                    message_thread_id=thread_id,
                    text=msg_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                    reply_markup=markup
                )
            except Exception as e:
                print(f"❌ Send News Error ({label_prefix}): {e}")

def fetch_newsmaker_channel():
    print("🟢 Dual-Source NewsMaker Monitor (NewsMaker + WatcherGuru) started...")
    while True:
        try:
            poll_news_source("nwsmkr", "newsmaker")
            time.sleep(5)
            poll_news_source("WatcherGuru", "watcherguru")
        except Exception as e:
            print(f"NewsMaker Monitor Error: {e}")
        time.sleep(600)

def fetch_direct_exchange_promos():
    print("🟢 Direct Exchange Websites & APIs Scraper started...")
    while True:
        try:
            binance_apis = [
                ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageNo=1&pageSize=1", "BINANCE"),
                ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=161&pageNo=1&pageSize=1", "BINANCE"),
                ("https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=379&pageNo=1&pageSize=1", "BINANCE")
            ]
            for api_url, top_name in binance_apis:
                res = secure_request(api_url, timeout=8)
                if res:
                    try:
                        data = res.json()
                        if isinstance(data, dict):
                            for art in data.get('data', {}).get('articles', [])[:1]:
                                art_id = f"dir_binance_{art.get('id')}"
                                title = art.get('title', '')
                                code = art.get('code', '')
                                link = f"https://www.binance.com/en/support/announcement/{code}" if code else "https://www.binance.com"
                                raw_text = f"Binance Direct API Promo / Campaign: {title}\nLink: {link}"
                                process_item(art_id, raw_text, link, top_name)
                    except Exception: pass

            mexc_api = "https://www.mexc.com/api/support/list?categoryId=19&page=1&pageSize=1"
            res_mexc = secure_request(mexc_api, timeout=8)
            if res_mexc:
                try:
                    mexc_data = res_mexc.json()
                    if isinstance(mexc_data, dict):
                        for item in mexc_data.get('data', {}).get('result', [])[:1]:
                            item_id = f"dir_mexc_{item.get('id')}"
                            title = item.get('title', '')
                            link = f"https://www.mexc.com/support/articles/{item.get('id')}"
                            raw_text = f"MEXC Direct API Promo / Campaign: {title}\nLink: {link}"
                            process_item(item_id, raw_text, link, "MEXC")
                except Exception: pass
        except Exception as e:
            print(f"Direct Promos Error: {e}")
        time.sleep(600)

def fetch_global_crypto_promos():
    while True:
        try:
            rss_feeds = ["https://cointelegraph.com/rss", "https://cryptopotato.com/feed/"]
            for feed_url in rss_feeds:
                try:
                    feed = feedparser.parse(feed_url)
                    for entry in feed.entries[:1]:
                        entry_id = f"rss_{entry.get('id', entry.get('link'))}"
                        title = entry.get('title', '')
                        summary = entry.get('summary', '')
                        link = entry.get('link', '')
                        raw_text = f"Crypto Aggregator News: {title}\n{summary}\nLink: {link}"
                        process_item(entry_id, raw_text, link, "NEWS")
                except Exception: pass
        except Exception as e:
            print(f"Global RSS Error: {e}")
        time.sleep(900)

# ==================== PARALLEL FUTURES + SPOT MARKET ENGINE ====================
def _record_quote(bids, asks, volumes, sym, venue, bid_p, ask_p, vol_24h, mult=1.0):
    if not sym or mult <= 0:
        return
    b = float(bid_p or 0.0) / mult
    a = float(ask_p or 0.0) / mult
    if b <= 0 and a > 0:
        b = a
    elif a <= 0 and b > 0:
        a = b
    if b < MIN_VALID_PRICE or a < MIN_VALID_PRICE:
        return

    bids.setdefault(sym, {})[venue] = b
    asks.setdefault(sym, {})[venue] = a
    if vol_24h is not None:
        volumes.setdefault(sym, {})[venue] = max(volumes.get(sym, {}).get(venue, 0.0), float(vol_24h or 0.0))

def fetch_futures_data(include_spot=True):
    global latest_prices_cache
    bids, asks, volumes, fundings, funding_times = {}, {}, {}, {}, {}

    def _poll_binance():
        v_fut = make_venue_key("Binance", "Fut")
        try:
            book_map = {}
            r_book = requests.get("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=4).json()
            if isinstance(r_book, list):
                for item in r_book:
                    book_map[item.get('symbol', '')] = (item.get('bidPrice'), item.get('askPrice'))

            r_24 = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=4).json()
            if isinstance(r_24, list):
                for item in r_24:
                    raw_s = item.get('symbol', '')
                    if not raw_s.endswith("USDT"):
                        continue
                    sym, mult = parse_normalized_symbol(raw_s)
                    b_raw, a_raw = book_map.get(raw_s, (item.get('lastPrice'), item.get('lastPrice')))
                    _record_quote(bids, asks, volumes, sym, v_fut, b_raw, a_raw, item.get('quoteVolume', 0.0), mult)
        except Exception: pass

        try:
            r_prem = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=4).json()
            if isinstance(r_prem, list):
                for item in r_prem:
                    sym, _ = parse_normalized_symbol(item.get('symbol', ''))
                    if sym:
                        fundings.setdefault(sym, {})[v_fut] = float(item.get('lastFundingRate', 0.0)) * 100
                        next_time = int(item.get('nextFundingTime', 0)) // 1000
                        if next_time > 0:
                            funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("Binance", "Spot")
            try:
                r_s = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=4).json()
                if isinstance(r_s, list):
                    for item in r_s:
                        raw_s = item.get('symbol', '')
                        if not raw_s.endswith("USDT"):
                            continue
                        sym, mult = parse_normalized_symbol(raw_s)
                        _record_quote(bids, asks, volumes, sym, v_spot, item.get('bidPrice') or item.get('lastPrice'), item.get('askPrice') or item.get('lastPrice'), item.get('quoteVolume', 0.0), mult)
            except Exception: pass

    def _poll_bybit():
        v_fut = make_venue_key("Bybit", "Fut")
        try:
            r = requests.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=4).json().get('result', {}).get('list', [])
            for item in r:
                raw_s = item.get('symbol', '')
                if not raw_s.endswith("USDT"):
                    continue
                sym, mult = parse_normalized_symbol(raw_s)
                lp = item.get('lastPrice')
                _record_quote(bids, asks, volumes, sym, v_fut, item.get('bid1Price') or lp, item.get('ask1Price') or lp, item.get('turnover24h', 0.0), mult)
                if sym and item.get('fundingRate') not in (None, ""):
                    fundings.setdefault(sym, {})[v_fut] = float(item['fundingRate']) * 100
                    next_time = int(item.get('nextFundingTime', 0)) // 1000
                    if next_time > 0:
                        funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("Bybit", "Spot")
            try:
                r = requests.get("https://api.bybit.com/v5/market/tickers?category=spot", timeout=4).json().get('result', {}).get('list', [])
                for item in r:
                    raw_s = item.get('symbol', '')
                    if not raw_s.endswith("USDT"):
                        continue
                    sym, mult = parse_normalized_symbol(raw_s)
                    lp = item.get('lastPrice')
                    _record_quote(bids, asks, volumes, sym, v_spot, item.get('bid1Price') or lp, item.get('ask1Price') or lp, item.get('turnover24h', 0.0), mult)
            except Exception: pass

    def _poll_okx():
        v_fut = make_venue_key("OKX", "Fut")
        try:
            r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=4).json().get('data', [])
            for item in r:
                inst = item.get('instId', '')
                if not inst.endswith("-USDT-SWAP"):
                    continue
                sym, mult = parse_normalized_symbol(inst)
                lp = item.get('last')
                _record_quote(bids, asks, volumes, sym, v_fut, item.get('bidPx') or lp, item.get('askPx') or lp, item.get('volCcy24h', 0.0), mult)
        except Exception: pass

        try:
            r_f = requests.get("https://www.okx.com/api/v5/public/funding-rate-all", timeout=4).json().get('data', [])
            for item in r_f:
                sym, _ = parse_normalized_symbol(item.get('instId', ''))
                if sym and item.get('fundingRate') not in (None, ""):
                    fundings.setdefault(sym, {})[v_fut] = float(item['fundingRate']) * 100
                    next_time = int(item.get('nextFundingTime', 0)) // 1000
                    if next_time > 0:
                        funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("OKX", "Spot")
            try:
                r = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SPOT", timeout=4).json().get('data', [])
                for item in r:
                    inst = item.get('instId', '')
                    if not inst.endswith("-USDT"):
                        continue
                    sym, mult = parse_normalized_symbol(inst)
                    lp = item.get('last')
                    _record_quote(bids, asks, volumes, sym, v_spot, item.get('bidPx') or lp, item.get('askPx') or lp, item.get('volCcy24h', 0.0), mult)
            except Exception: pass

    def _poll_gate():
        v_fut = make_venue_key("Gate", "Fut")
        try:
            r = requests.get("https://api.gateio.ws/api/v4/futures/usdt/tickers", timeout=4).json()
            if isinstance(r, list):
                for item in r:
                    contract = item.get('contract', '')
                    if not contract.endswith("_USDT"):
                        continue
                    sym, mult = parse_normalized_symbol(contract)
                    lp = float(item.get('last') or 0.0)
                    vol_usdt = float(item.get('total_size') or 0.0) * lp
                    _record_quote(bids, asks, volumes, sym, v_fut, item.get('highest_bid') or lp, item.get('lowest_ask') or lp, vol_usdt, mult)
                    if sym and 'funding_rate' in item and item['funding_rate'] is not None:
                        fundings.setdefault(sym, {})[v_fut] = float(item['funding_rate']) * 100
                        next_time = int(item.get('funding_next_time', 0) or 0)
                        if next_time > 0:
                            funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("Gate", "Spot")
            try:
                r = requests.get("https://api.gateio.ws/api/v4/spot/tickers", timeout=4).json()
                if isinstance(r, list):
                    for item in r:
                        pair = item.get('currency_pair', '')
                        if not pair.endswith("_USDT"):
                            continue
                        sym, mult = parse_normalized_symbol(pair)
                        lp = item.get('last')
                        _record_quote(bids, asks, volumes, sym, v_spot, item.get('highest_bid') or lp, item.get('lowest_ask') or lp, item.get('quote_volume', 0.0), mult)
            except Exception: pass

    def _poll_bitget():
        v_fut = make_venue_key("Bitget", "Fut")
        try:
            r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=4).json().get('data', [])
            for item in r:
                raw_s = item.get('symbol', '')
                if not raw_s.endswith("USDT"):
                    continue
                sym, mult = parse_normalized_symbol(raw_s)
                lp = item.get('lastPr')
                _record_quote(bids, asks, volumes, sym, v_fut, item.get('bidPr') or lp, item.get('askPr') or lp, item.get('quoteVolume', 0.0), mult)
                if sym and item.get('fundingRate') not in (None, ""):
                    fundings.setdefault(sym, {})[v_fut] = float(item['fundingRate']) * 100
                    next_time = int(item.get('nextFundingTime', 0) or 0) // 1000
                    if next_time > 0:
                        funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("Bitget", "Spot")
            try:
                r = requests.get("https://api.bitget.com/api/v2/spot/market/tickers", timeout=4).json().get('data', [])
                for item in r:
                    raw_s = item.get('symbol', '')
                    if not raw_s.endswith("USDT"):
                        continue
                    sym, mult = parse_normalized_symbol(raw_s)
                    lp = item.get('lastPr')
                    _record_quote(bids, asks, volumes, sym, v_spot, item.get('bidPr') or lp, item.get('askPr') or lp, item.get('quoteVolume', 0.0), mult)
            except Exception: pass

    def _poll_mexc():
        v_fut = make_venue_key("MEXC", "Fut")
        try:
            r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=4).json().get('data', [])
            if isinstance(r, list):
                for item in r:
                    raw_s = item.get('symbol', '')
                    if not raw_s.endswith("_USDT"):
                        continue
                    sym, mult = parse_normalized_symbol(raw_s)
                    lp = float(item.get('lastPrice') or 0.0)
                    vol_usdt = float(item.get('amount24h') or 0.0) * lp
                    _record_quote(bids, asks, volumes, sym, v_fut, item.get('bid1') or lp, item.get('ask1') or lp, vol_usdt, mult)
                    if sym and 'fundingRate' in item and item['fundingRate'] is not None:
                        fundings.setdefault(sym, {})[v_fut] = float(item['fundingRate']) * 100
                        next_time = int(item.get('nextSettleTime', 0) or 0) // 1000
                        if next_time > 0:
                            funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("MEXC", "Spot")
            try:
                r = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=4).json()
                if isinstance(r, list):
                    for item in r:
                        raw_s = item.get('symbol', '')
                        if not raw_s.endswith("USDT"):
                            continue
                        sym, mult = parse_normalized_symbol(raw_s)
                        lp = item.get('lastPrice')
                        _record_quote(bids, asks, volumes, sym, v_spot, item.get('bidPrice') or lp, item.get('askPrice') or lp, item.get('quoteVolume', 0.0), mult)
            except Exception: pass

    def _poll_bingx():
        v_fut = make_venue_key("BingX", "Fut")
        try:
            r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", timeout=4).json().get('data', [])
            if isinstance(r, list):
                for item in r:
                    raw_s = item.get('symbol', '')
                    if not raw_s.endswith("-USDT"):
                        continue
                    sym, mult = parse_normalized_symbol(raw_s)
                    lp = item.get('lastPrice')
                    _record_quote(bids, asks, volumes, sym, v_fut, item.get('bidPrice') or lp, item.get('askPrice') or lp, item.get('volume', 0.0), mult)
        except Exception: pass

        try:
            r_p = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", timeout=4).json().get('data', [])
            if isinstance(r_p, list):
                for item in r_p:
                    sym, _ = parse_normalized_symbol(item.get('symbol', ''))
                    if sym and 'lastFundingRate' in item and item['lastFundingRate'] is not None:
                        fundings.setdefault(sym, {})[v_fut] = float(item['lastFundingRate']) * 100
                        next_time = int(item.get('nextFundingTime', 0) or 0) // 1000
                        if next_time > 0:
                            funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("BingX", "Spot")
            try:
                r = requests.get("https://open-api.bingx.com/openApi/spot/v1/ticker/24hr", timeout=4).json().get('data', [])
                if isinstance(r, list):
                    for item in r:
                        raw_s = item.get('symbol', '')
                        if not raw_s.endswith("-USDT"):
                            continue
                        sym, mult = parse_normalized_symbol(raw_s)
                        lp = item.get('lastPrice')
                        _record_quote(bids, asks, volumes, sym, v_spot, item.get('bidPrice') or lp, item.get('askPrice') or lp, item.get('quoteVolume', 0.0), mult)
            except Exception: pass

    def _poll_kucoin():
        v_fut = make_venue_key("KuCoin", "Fut")
        try:
            r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=4).json().get('data', [])
            if isinstance(r, list):
                for item in r:
                    raw_s = item.get('symbol', '')
                    if not raw_s.endswith("USDTM"):
                        continue
                    sym, mult = parse_normalized_symbol(raw_s)
                    lp = float(item.get('lastTradePrice') or 0.0)
                    _record_quote(bids, asks, volumes, sym, v_fut, item.get('bestBidPrice') or lp, item.get('bestAskPrice') or lp, item.get('turnoverOf24h', 0.0), mult)
                    if sym and 'fundingFeeRate' in item and item['fundingFeeRate'] is not None:
                        fundings.setdefault(sym, {})[v_fut] = float(item['fundingFeeRate']) * 100
                        next_time = int(item.get('nextFundingRateTime', 0) or 0) // 1000
                        if next_time > 0:
                            funding_times.setdefault(sym, {})[v_fut] = next_time
        except Exception: pass

        if include_spot:
            v_spot = make_venue_key("KuCoin", "Spot")
            try:
                r = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=4).json().get('data', {}).get('ticker', [])
                if isinstance(r, list):
                    for item in r:
                        raw_s = item.get('symbol', '')
                        if not raw_s.endswith("-USDT"):
                            continue
                        sym, mult = parse_normalized_symbol(raw_s)
                        lp = item.get('last')
                        _record_quote(bids, asks, volumes, sym, v_spot, item.get('buy') or lp, item.get('sell') or lp, item.get('volValue', 0.0), mult)
            except Exception: pass

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [
            pool.submit(_poll_binance),
            pool.submit(_poll_bybit),
            pool.submit(_poll_okx),
            pool.submit(_poll_gate),
            pool.submit(_poll_bitget),
            pool.submit(_poll_mexc),
            pool.submit(_poll_bingx),
            pool.submit(_poll_kucoin)
        ]
        for f in as_completed(futs):
            try: f.result()
            except: pass

    for sym, b_dict in bids.items():
        if b_dict:
            latest_prices_cache[sym] = list(b_dict.values())[0]

    return bids, asks, volumes, fundings, funding_times

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

symbol_price_tracker = {}

def filter_stale_quotes(sym, sym_bids, sym_asks, stale_state):
    """
    Отсекает залипшие и аномальные котировки:
    - где цена < MIN_VALID_PRICE или Ask < Bid;
    - где Bid == Ask и при этом цена по бирже стоит без изменений STALE_POLL_LIMIT циклов подряд,
      пока по остальным биржам монеты есть движение;
    - где котировка отклоняется от медианной цены монеты по рынку более чем на MAX_MEDIAN_DEVIATION.
    """
    sym_stale = stale_state.setdefault(sym, {})
    cleaned_bids = {}
    cleaned_asks = {}
    moved_exchanges = 0
    candidate_exchanges = set(sym_bids.keys()).union(set(sym_asks.keys()))

    for ex in candidate_exchanges:
        b = sym_bids.get(ex, 0.0)
        a = sym_asks.get(ex, 0.0)
        if b < MIN_VALID_PRICE or a < MIN_VALID_PRICE or a < b:
            continue

        sig = (b, a)
        prev = sym_stale.get(ex)
        if prev is None or prev["sig"] != sig:
            sym_stale[ex] = {"sig": sig, "unchanged": 0}
            moved_exchanges += 1
        else:
            sym_stale[ex]["unchanged"] += 1

    market_is_moving = moved_exchanges >= 1

    for ex in candidate_exchanges:
        b = sym_bids.get(ex, 0.0)
        a = sym_asks.get(ex, 0.0)
        if b < MIN_VALID_PRICE or a < MIN_VALID_PRICE or a < b:
            continue

        st = sym_stale.get(ex, {"unchanged": 0})
        is_flat_book = (b == a)
        is_stuck_price = is_flat_book and market_is_moving and st["unchanged"] >= STALE_POLL_LIMIT

        if not is_stuck_price:
            if ex in sym_bids:
                cleaned_bids[ex] = b
            if ex in sym_asks:
                cleaned_asks[ex] = a

    all_mids = []
    for ex in set(cleaned_bids.keys()).union(set(cleaned_asks.keys())):
        bp = cleaned_bids.get(ex, 0.0)
        ap = cleaned_asks.get(ex, 0.0)
        if bp >= MIN_VALID_PRICE and ap >= MIN_VALID_PRICE:
            all_mids.append((bp + ap) / 2.0)

    if len(all_mids) >= 2:
        med = statistics.median(all_mids)
        if med > 0:
            cleaned_bids = {
                ex: p for ex, p in cleaned_bids.items()
                if abs(p - med) / med <= MAX_MEDIAN_DEVIATION
            }
            cleaned_asks = {
                ex: p for ex, p in cleaned_asks.items()
                if abs(p - med) / med <= MAX_MEDIAN_DEVIATION
            }

    return cleaned_bids, cleaned_asks

def smooth_spread_value(state_obj, raw_spread):
    """Сглаживает краткосрочные качели спреда по скользящему окну."""
    if raw_spread is None:
        return None
    samples = state_obj.setdefault("spread_samples", [])
    samples.append(raw_spread)
    if len(samples) > SMOOTH_WINDOW:
        samples.pop(0)
    return statistics.median(samples)

def find_best_fut_or_hybrid_pair(valid_bids, valid_asks):
    """
    Находит лучшую связку (min_ex, max_ex), где хотя бы одна сторона — Fut
    (то есть только Fut + Fut или Fut + Spot; чистый Spot + Spot полностью исключён).
    """
    best_pair = None
    best_spread = -1.0

    for b_ex, b_price in valid_bids.items():
        if b_price < MIN_VALID_PRICE:
            continue
        for a_ex, a_price in valid_asks.items():
            if a_price < MIN_VALID_PRICE or b_ex == a_ex:
                continue
            if not is_allowed_venue_pair(b_ex, a_ex):
                continue
            sp = ((a_price - b_price) / b_price) * 100
            if sp > best_spread:
                best_spread = sp
                best_pair = (b_ex, a_ex, b_price, a_price, sp)

    return best_pair

def monitor_spread():
    global active_spreads, price_history_long, price_history_short, sent_alerts_cache, symbol_price_tracker, spread_monitor_enabled
    print("🟢 Smart Spread Monitor initialized (Waiting for /spread_on command)...")

    live_spread_posts = {}
    pending_spreads = {}      # Буфер подтверждения вектора входа
    pair_cooldowns = {}         # Кулдаун на конкретную связку (chart_key) после закрытия
    quote_stale_tracker = {}  # Трекер залипших котировок по (sym -> venue)

    while True:
        if not spread_monitor_enabled:
            if live_spread_posts or pending_spreads:
                live_spread_posts.clear()
                pending_spreads.clear()
            time.sleep(5)
            continue

        try:
            bids, asks, volumes, fundings, _ = fetch_futures_data(include_spot=True)
            curr_time_str = get_kyiv_time()
            now_ts = int(time.time())

            pair_cooldowns = {
                ck: ts for ck, ts in pair_cooldowns.items()
                if (now_ts - ts) < PAIR_COOLDOWN_SECONDS
            }

            all_symbols = set(bids.keys()).union(set(asks.keys()))
            current_detected_spreads = {}
            closed_keys = []

            for chart_key, post_info in list(live_spread_posts.items()):
                sym_name = post_info["sym"]
                long_ex = post_info["min_ex"]
                short_ex = post_info["max_ex"]
                msg_id = post_info["msg_id"]

                if not is_allowed_venue_pair(long_ex, short_ex):
                    del live_spread_posts[chart_key]
                    continue

                raw_b = bids.get(sym_name, {})
                raw_a = asks.get(sym_name, {})
                clean_b, clean_a = filter_stale_quotes(sym_name, raw_b, raw_a, quote_stale_tracker)

                b_val = clean_b.get(long_ex, 0.0)
                a_val = clean_a.get(short_ex, 0.0)

                if b_val >= MIN_VALID_PRICE and a_val >= MIN_VALID_PRICE:
                    post_info["missing_count"] = 0
                    post_info["last_long_p"] = b_val
                    post_info["last_short_p"] = a_val
                    raw_live_spread = ((a_val - b_val) / b_val) * 100
                    live_spread = smooth_spread_value(post_info, raw_live_spread)
                    post_info["last_live_spread"] = live_spread
                    close_reason = "converged"
                else:
                    post_info["missing_count"] = post_info.get("missing_count", 0) + 1
                    post_info["close_confirm_count"] = 0
                    if post_info["missing_count"] < CLOSE_MISSING_LIMIT:
                        p_long_hold = post_info.get("last_long_p", 0.0)
                        p_short_hold = post_info.get("last_short_p", 0.0)
                        sp_hold = post_info.get("last_live_spread", post_info.get("last_spread", SPREAD_HYSTERESIS_THRESHOLD))
                        if p_long_hold >= MIN_VALID_PRICE and p_short_hold >= MIN_VALID_PRICE:
                            sym_vols = volumes.get(sym_name, {})
                            vol_min = sym_vols.get(long_ex, 0) * 0.01
                            vol_max = sym_vols.get(short_ex, 0) * 0.01
                            max_pos_usdt = max(100, int(min(vol_min, vol_max)))
                            current_detected_spreads[chart_key] = {
                                "sym": sym_name,
                                "min_ex": long_ex,
                                "max_ex": short_ex,
                                "min_p": p_long_hold,
                                "max_p": p_short_hold,
                                "spread": sp_hold,
                                "max_pos_usdt": max_pos_usdt,
                                "valid_bids": {k: v for k, v in clean_b.items() if sym_vols.get(k, 0) >= MIN_EXCHANGE_VOL_USDT},
                                "valid_asks": {k: v for k, v in clean_a.items() if sym_vols.get(k, 0) >= MIN_EXCHANGE_VOL_USDT},
                                "sym_vols": sym_vols,
                                "fundings": fundings,
                                "in_hysteresis": True
                            }
                        continue
                    live_spread = None
                    close_reason = "missing_quotes"

                if live_spread is not None and live_spread < SPREAD_CLOSE_THRESHOLD:
                    post_info["close_confirm_count"] = post_info.get("close_confirm_count", 0) + 1
                    close_reason = "converged"
                elif live_spread is None:
                    post_info["close_confirm_count"] = CLOSE_CONFIRM_POLLS
                    close_reason = "missing_quotes"
                else:
                    post_info["close_confirm_count"] = 0

                should_close = (
                    (live_spread is None and post_info.get("missing_count", 0) >= CLOSE_MISSING_LIMIT)
                    or (live_spread is not None and live_spread < SPREAD_CLOSE_THRESHOLD and post_info.get("close_confirm_count", 0) >= CLOSE_CONFIRM_POLLS)
                )

                if should_close:
                    pair_cooldowns[chart_key] = now_ts

                    p_long_close = b_val if b_val >= MIN_VALID_PRICE else post_info.get("last_long_p", 0.0)
                    p_short_close = a_val if a_val >= MIN_VALID_PRICE else post_info.get("last_short_p", 0.0)
                    final_spread_val = live_spread if live_spread is not None else post_info.get("last_live_spread")

                    prices_close_str = ""
                    if p_long_close >= MIN_VALID_PRICE and p_short_close >= MIN_VALID_PRICE:
                        close_sp_line = f" | Текущий спред: `{final_spread_val:.2f}%`" if final_spread_val is not None else ""
                        prices_close_str = (
                            f"\n💵 **Цены при закрытии:**\n"
                            f"🟢 {long_ex}: `${format_price(p_long_close)}` | 🔴 {short_ex}: `${format_price(p_short_close)}`{close_sp_line}\n"
                        )

                    cooldown_mins = PAIR_COOLDOWN_SECONDS // 60
                    if close_reason == "converged":
                        header_text = "🟢 **СПРЕД СОШЕЛСЯ / ЗАКРЫТИЕ СДЕЛКИ**"
                        reason_text = f"🎯 Спред схлопнулся ниже `{SPREAD_CLOSE_THRESHOLD:.2f}%`. Позицию можно закрывать и фиксировать результат!"
                    else:
                        header_text = "⚪ **ЗАКРЫТИЕ ПОСТА (ПОТЕРЯ КОТИРОВОК)**"
                        reason_text = f"⚠️ Актуальные котировки по `{long_ex}` или `{short_ex}` пропали/залипли (`{CLOSE_MISSING_LIMIT}` цикла подряд). Спред ниже `1.00%` не фиксировался — проверь стакан вручную."

                    convergence_text = (
                        f"{header_text}\n"
                        f"🪙 **#{sym_name}** (Long: `{long_ex}` | Short: `{short_ex}`)\n"
                        f"{prices_close_str}\n"
                        f"{reason_text}\n"
                        f"⏸ _Связка поставлена на паузу ({cooldown_mins} мин) от повторных сигналов._\n\n"
                        f"🕒 _Время: {curr_time_str} (Киев)_"
                    )
                    try:
                        bot.send_message(
                            chat_id=CHAT_ID,
                            message_thread_id=TOPICS["SPREAD"],
                            text=convergence_text,
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                            reply_to_message_id=msg_id
                        )
                    except Exception: pass

                    closed_keys.append(chart_key)
                    del live_spread_posts[chart_key]
                    continue

                if live_spread is not None and live_spread < SPREAD_ENTRY_MIN and live_spread >= SPREAD_HYSTERESIS_THRESHOLD:
                    sym_vols = volumes.get(sym_name, {})
                    vol_min = sym_vols.get(long_ex, 0) * 0.01
                    vol_max = sym_vols.get(short_ex, 0) * 0.01
                    max_pos_usdt = max(100, int(min(vol_min, vol_max)))

                    current_detected_spreads[chart_key] = {
                        "sym": sym_name,
                        "min_ex": long_ex,
                        "max_ex": short_ex,
                        "min_p": b_val,
                        "max_p": a_val,
                        "spread": live_spread,
                        "max_pos_usdt": max_pos_usdt,
                        "valid_bids": {k: v for k, v in clean_b.items() if sym_vols.get(k, 0) >= MIN_EXCHANGE_VOL_USDT},
                        "valid_asks": {k: v for k, v in clean_a.items() if sym_vols.get(k, 0) >= MIN_EXCHANGE_VOL_USDT},
                        "sym_vols": sym_vols,
                        "fundings": fundings,
                        "in_hysteresis": True
                    }

            for sym in all_symbols:
                sym_bids = bids.get(sym, {})
                sym_asks = asks.get(sym, {})
                sym_vols = volumes.get(sym, {})

                clean_bids, clean_asks = filter_stale_quotes(sym, sym_bids, sym_asks, quote_stale_tracker)

                valid_bids = {ex: p for ex, p in clean_bids.items() if sym_vols.get(ex, 0) >= MIN_EXCHANGE_VOL_USDT and p >= MIN_VALID_PRICE}
                valid_asks = {ex: p for ex, p in clean_asks.items() if sym_vols.get(ex, 0) >= MIN_EXCHANGE_VOL_USDT and p >= MIN_VALID_PRICE}

                if len(valid_bids) < 2 or len(valid_asks) < 2:
                    continue

                best_pair = find_best_fut_or_hybrid_pair(valid_bids, valid_asks)
                if not best_pair:
                    continue

                min_ex, max_ex, min_p, max_p, raw_spread = best_pair
                if raw_spread <= 0:
                    continue

                chart_key = f"{sym}_{min_ex}_{max_ex}"

                if chart_key in closed_keys:
                    continue

                vol_min = sym_vols.get(min_ex, 0) * 0.01
                vol_max = sym_vols.get(max_ex, 0) * 0.01
                max_pos_usdt = int(min(vol_min, vol_max))
                if max_pos_usdt < 100: max_pos_usdt = 100

                if chart_key in live_spread_posts:
                    spread = smooth_spread_value(live_spread_posts[chart_key], raw_spread)
                else:
                    spread = raw_spread

                in_entry_range = (spread >= SPREAD_ENTRY_MIN) and (SPREAD_ENTRY_MAX is None or spread <= SPREAD_ENTRY_MAX)

                if in_entry_range:
                    if chart_key in live_spread_posts:
                        current_detected_spreads[chart_key] = {
                            "sym": sym, "min_ex": min_ex, "max_ex": max_ex,
                            "min_p": min_p, "max_p": max_p, "spread": spread,
                            "max_pos_usdt": max_pos_usdt, "valid_bids": valid_bids,
                            "valid_asks": valid_asks, "sym_vols": sym_vols, "fundings": fundings,
                            "in_hysteresis": False
                        }
                    else:
                        if chart_key in pair_cooldowns:
                            if chart_key in pending_spreads:
                                del pending_spreads[chart_key]
                            continue

                        if chart_key not in pending_spreads:
                            pending_spreads[chart_key] = {
                                "first_seen": now_ts,
                                "initial_spread": spread
                            }
                        else:
                            elapsed = now_ts - pending_spreads[chart_key]["first_seen"]
                            init_sp = pending_spreads[chart_key]["initial_spread"]

                            if elapsed >= PENDING_BUFFER_SECONDS:
                                if max_pos_usdt >= MIN_ENTRY_POS_USDT and spread >= (init_sp - 0.5):
                                    current_detected_spreads[chart_key] = {
                                        "sym": sym, "min_ex": min_ex, "max_ex": max_ex,
                                        "min_p": min_p, "max_p": max_p, "spread": spread,
                                        "max_pos_usdt": max_pos_usdt, "valid_bids": valid_bids,
                                        "valid_asks": valid_asks, "sym_vols": sym_vols, "fundings": fundings,
                                        "in_hysteresis": False
                                    }
                                    pair_cooldowns[chart_key] = now_ts
                                del pending_spreads[chart_key]
                else:
                    if chart_key in pending_spreads:
                        del pending_spreads[chart_key]

            expired_pending = [k for k, v in pending_spreads.items() if now_ts - v["first_seen"] > 45]
            for k in expired_pending:
                del pending_spreads[k]

            for chart_key, data in current_detected_spreads.items():
                sym = data["sym"]
                min_ex = data["min_ex"]
                max_ex = data["max_ex"]
                min_p = data["min_p"]
                max_p = data["max_p"]
                spread = data["spread"]
                max_pos_usdt = data["max_pos_usdt"]
                valid_bids = data["valid_bids"]
                valid_asks = data["valid_asks"]
                sym_vols = data["sym_vols"]
                fundings = data["fundings"]
                in_hysteresis = data.get("in_hysteresis", False)

                if not is_allowed_venue_pair(min_ex, max_ex):
                    continue

                if sym not in symbol_price_tracker:
                    symbol_price_tracker[sym] = []
                symbol_price_tracker[sym].append((now_ts, min_p))
                symbol_price_tracker[sym] = [item for item in symbol_price_tracker[sym] if now_ts - item[0] <= 60]

                is_momentum = False
                if len(symbol_price_tracker[sym]) >= 2:
                    old_p = symbol_price_tracker[sym][0][1]
                    if old_p > 0:
                        change_pct = abs((min_p - old_p) / old_p) * 100
                        if change_pct >= 2.0:
                            is_momentum = True

                if chart_key not in price_history_long:
                    price_history_long[chart_key] = []
                    price_history_short[chart_key] = []

                price_history_long[chart_key].append({"time": now_ts, "value": round(min_p, 8)})
                price_history_short[chart_key].append({"time": now_ts, "value": round(max_p, 8)})

                if len(price_history_long[chart_key]) > 200:
                    price_history_long[chart_key].pop(0)
                    price_history_short[chart_key].pop(0)

                sym_funds = fundings.get(sym, {})
                min_fund_val = sym_funds.get(min_ex)
                max_fund_val = sym_funds.get(max_ex)
                min_fund_str = f"`{min_fund_val:.2f}%`" if min_fund_val is not None else "`Spot / N/A`"
                max_fund_str = f"`{max_fund_val:.2f}%`" if max_fund_val is not None else "`Spot / N/A`"

                all_valid_exs = set(valid_bids.keys()).union(set(valid_asks.keys()))
                sorted_exs = sorted(all_valid_exs, key=lambda ex: sym_vols.get(ex, 0), reverse=True)
                overview_list = []
                for ex in sorted_exs:
                    bp = format_price(valid_bids.get(ex, 0))
                    ap = format_price(valid_asks.get(ex, 0))
                    v = sym_vols.get(ex, 0)
                    v_str = format_volume(v)
                    url = get_exchange_url(ex, sym)
                    if url:
                        overview_list.append(f"🔹 [{ex}]({url}): Bid: `{bp}` | Ask: `{ap}` ({v_str})")
                    else:
                        overview_list.append(f"🔹 {ex}: Bid: `{bp}` | Ask: `{ap}` ({v_str})")

                overview = "\n".join(overview_list)

                render_url = os.environ.get('RENDER_EXTERNAL_URL', '').strip()
                markup = InlineKeyboardMarkup()
                if render_url:
                    if not render_url.startswith('http'):
                        render_url = f"https://{render_url}"
                    chart_url = f"{render_url}/chart?symbol={sym}&min_ex={min_ex}&max_ex={max_ex}"
                    markup.add(InlineKeyboardButton("📈 График схождения (Live)", url=chart_url))
                else:
                    long_url = get_exchange_url(min_ex, sym)
                    if long_url:
                        markup.add(InlineKeyboardButton("🌐 Биржа Long", url=long_url))

                _, min_m_type = split_venue_key(min_ex)
                _, max_m_type = split_venue_key(max_ex)
                market_mode_label = "Fut + Spot" if (min_m_type != max_m_type) else "Fut + Fut"

                if in_hysteresis:
                    badge = f"⏳ **HOLD / СХОЖДЕНИЕ (ниже 5%, закрытие < {SPREAD_CLOSE_THRESHOLD:.2f}%)**"
                elif is_momentum:
                    badge = "⚡⚡ **MOMENTUM / PUMP SPREAD**"
                elif spread >= 25.0:
                    badge = "🚀🔥 **EXTREME SPREAD (>= 25%)**"
                elif spread >= 15.0:
                    badge = "🔥🔥🔥 **MEGA SPREAD (>= 15%)**"
                elif spread >= 10.0:
                    badge = "🔥 **HIGH SPREAD (>= 10%)**"
                else:
                    badge = "✅ **CONFIRMED SPREAD (>= 5%)** (Вектор подтвержден)"

                min_p_str = format_price(min_p)
                max_p_str = format_price(max_p)

                if chart_key not in live_spread_posts:
                    history_lines = [f"• `{curr_time_str}` — Вход разрешен: **`{spread:.2f}%`**"]

                    msg_text = (
                        f"{badge}\n"
                        f"🪙 **#{sym} | Spread: `{spread:.2f}%`** ({market_mode_label} LIVE)\n\n"
                        f"🟢 **Long Bid ({min_ex}):** `${min_p_str}` (Funding: {min_fund_str})\n"
                        f"🔴 **Short Ask ({max_ex}):** `${max_p_str}` (Funding: {max_fund_str})\n\n"
                        f"📊 **Динамика спреда:**\n" + "\n".join(history_lines) + "\n\n"
                        f"💰 **Объем стакана:** `~${max_pos_usdt:,} USDT`\n\n"
                        f"📝 **Стаканы бирж:**\n{overview}\n\n"
                        f"🔄 _Обновлено: {curr_time_str} (Киев)_"
                    )

                    msg_id = send_to_topic("SPREAD", msg_text, reply_markup=markup)
                    if msg_id:
                        live_spread_posts[chart_key] = {
                            "msg_id": msg_id,
                            "history": history_lines,
                            "min_ex": min_ex,
                            "max_ex": max_ex,
                            "sym": sym,
                            "last_spread": spread,
                            "last_long_p": min_p,
                            "last_short_p": max_p,
                            "last_live_spread": spread,
                            "spread_samples": [spread],
                            "missing_count": 0,
                            "close_confirm_count": 0
                        }
                else:
                    post_info = live_spread_posts[chart_key]
                    msg_id = post_info["msg_id"]
                    history = post_info["history"]

                    if abs(spread - post_info["last_spread"]) >= 0.75:
                        history.append(f"• `{curr_time_str}` — Обновление: **`{spread:.2f}%`**")
                        if len(history) > 6: history.pop(0)
                        post_info["last_spread"] = spread

                    updated_text = (
                        f"{badge}\n"
                        f"🪙 **#{sym} | Spread: `{spread:.2f}%`** ({market_mode_label} LIVE)\n\n"
                        f"🟢 **Long Bid ({min_ex}):** `${min_p_str}` (Funding: {min_fund_str})\n"
                        f"🔴 **Short Ask ({max_ex}):** `${max_p_str}` (Funding: {max_fund_str})\n\n"
                        f"📊 **Динамика спреда:**\n" + "\n".join(history) + "\n\n"
                        f"💰 **Объем стакана:** `~${max_pos_usdt:,} USDT`\n\n"
                        f"📝 **Стаканы бирж:**\n{overview}\n\n"
                        f"🔄 _Обновлено: {curr_time_str} (Киев)_"
                    )

                    try:
                        bot.edit_message_text(
                            chat_id=CHAT_ID,
                            message_id=msg_id,
                            text=updated_text,
                            parse_mode="Markdown",
                            reply_markup=markup,
                            disable_web_page_preview=True
                        )
                    except Exception: pass

        except Exception as e:
            print(f"❌ Advanced Monitor Spread Error: {e}")

        time.sleep(10)

def monitor_funding():
    print("🟢 Funding Monitor started...")
    while True:
        try:
            _, _, volumes, fundings, funding_times = fetch_futures_data(include_spot=False)
            curr_time_str = get_kyiv_time()

            for sym, ex_funds in fundings.items():
                sym_vols = volumes.get(sym, {})
                valid_ex_funds = {ex: rate for ex, rate in ex_funds.items() if sym_vols.get(ex, 0) >= 25_000}
                if len(valid_ex_funds) < 2: continue

                max_ex = max(valid_ex_funds, key=valid_ex_funds.get)
                min_ex = min(valid_ex_funds, key=valid_ex_funds.get)
                funding_spread = abs(valid_ex_funds[max_ex] - valid_ex_funds[min_ex])

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
                        if url:
                            rates_list.append(f"🔹 [{ex}]({url}): `{r:+.2f}%` (⏱ `{countdown}`)")
                        else:
                            rates_list.append(f"🔹 {ex}: `{r:+.2f}%` (⏱ `{countdown}`)")

                    msg_text = (
                        f"🔥 **FUNDING ARBITRAGE (Spread >= 0.5%)**\n"
                        f"🪙 **#{sym} (Spread: `{funding_spread:.2f}%`)**\n\n"
                        f"💰 **Объем:** `~${max_pos_usdt:,} USDT`\n\n"
                        f"📊 **Rates & Timers:**\n" + "\n".join(rates_list) + f"\n\n🔄 _{curr_time_str}_"
                    )
                    send_to_topic("FUNDING", msg_text)
                    time.sleep(2)
        except Exception as e:
            print(f"❌ Funding Monitor Error: {e}")
        time.sleep(1800)

# ==================== BINANCE ALPHA СЕССИЯ ====================
def run_alpha_session(session_key, token_identifier):
    print(f"🚀 [ALPHA DEBUG] Сессия запущена для: {token_identifier} (ключ: {session_key})")

    display_symbol = normalize_symbol(token_identifier) or token_identifier.upper()
    if not display_symbol.endswith("USDT") and not display_symbol.startswith("0X"):
        display_symbol = f"#{display_symbol}USDT"
    elif not display_symbol.startswith("0X"):
        display_symbol = f"#{display_symbol}"

    try:
        bot.send_message(
            chat_id=CHAT_ID,
            message_thread_id=TOPICS["ALPHA"],
            text=f"🚀 **Binance Alpha сессия запущена**\nМонета/Тикер: `{display_symbol}`",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"❌ [ALPHA ERROR] Стартовое сообщение: {e}")

    if session_key not in alpha_price_memory:
        alpha_price_memory[session_key] = []

    while True:
        try:
            session = active_alpha_sessions.get(session_key)
            if not session or session.get("stop"):
                try:
                    bot.send_message(
                        chat_id=CHAT_ID,
                        message_thread_id=TOPICS["ALPHA"],
                        text=f"⏹ **Alpha | `{display_symbol}`**\nСессия остановлена.",
                        parse_mode="Markdown"
                    )
                except: pass
                break

            current_price = fetch_binance_alpha_price(token_identifier)

            if current_price < MIN_VALID_PRICE:
                time.sleep(5)
                continue

            now_ts = time.time()
            history = alpha_price_memory[session_key]
            history.append((now_ts, current_price))

            alpha_price_memory[session_key] = [item for item in history if now_ts - item[0] <= 120]
            history = alpha_price_memory[session_key]

            price_change = 0.0
            trend_icon = "🟢"
            action_advice = "Цена стабильна. Можно безопасно крутить лимитками."

            if len(history) >= 2:
                old_price = history[0][1]
                if old_price > 0:
                    price_change = ((current_price - old_price) / old_price) * 100

            spread_offset = 0.0020
            if abs(price_change) >= 0.30:
                spread_offset = 0.0040

            suggested_buy = current_price * (1 - spread_offset)
            suggested_sell = current_price * (1 + spread_offset)

            buy_str = format_price(suggested_buy)
            sell_str = format_price(suggested_sell)
            curr_p_str = format_price(current_price)

            if price_change <= -0.30:
                trend_icon = "🩸"
                action_advice = "⚠️ **ДАМП / СПОЛЗАНИЕ!** Просадка >= 0.30%. Ордер на продажу может зависнуть — притормози открут!\n🎯 🔴 Шанс на возврат: НЕТ"
            elif price_change >= 0.30:
                trend_icon = "🚀"
                action_advice = "🔥 **ПАМП / РАЗГОН!** Импульс вверх >= 0.30%. Покупать по текущим рискованно, жди отката."
            else:
                action_advice = "Цена стабильна. Можно безопасно крутить лимитками."

            msg_txt = (
                f"{trend_icon} **Alpha** | `{display_symbol}` | ${curr_p_str} (`{price_change:+.2f}%`)\n\n"
                f"📐 **Диапазон ордеров:** Buy `~${buy_str}` | Sell `~${sell_str}`\n"
                f"🎯 **Совет по откруту:**\n{action_advice}"
            )

            try:
                bot.send_message(
                    chat_id=CHAT_ID,
                    message_thread_id=TOPICS["ALPHA"],
                    text=msg_txt,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            except Exception as send_err:
                print(f"❌ [ALPHA SEND ERROR]: {send_err}")

        except Exception as err:
            print(f"❌ [ALPHA ERROR]: {err}")

        time.sleep(30)

# ==================== КОМАНДЫ УПРАВЛЕНИЯ СПРЕДАМИ ====================
@bot.message_handler(commands=['spread_on', 's_on'])
def cmd_spread_on(message):
    global spread_monitor_enabled
    spread_monitor_enabled = True
    bot.reply_to(message, f"🟢 **Мониторинг спредов ЗАПУЩЕН!**\nИщу подтвержденные спреды от `{SPREAD_ENTRY_MIN:.1f}%` (только Fut + Fut и Fut + Spot, вектор {PENDING_BUFFER_SECONDS}с + ликвидность от ${MIN_ENTRY_POS_USDT:,}).", parse_mode="Markdown")
    send_to_topic("SPREAD", "🟢 **Охота за спредами ЗАПУЩЕНА** (режим Fut + Fut и Fut + Spot).")

@bot.message_handler(commands=['spread_off', 's_off'])
def cmd_spread_off(message):
    global spread_monitor_enabled
    spread_monitor_enabled = False
    bot.reply_to(message, "🔴 **Мониторинг спредов ОСТАНОВЛЕН!**\nФлуд в топике Spread отключен до следующего `/spread_on`.", parse_mode="Markdown")
    send_to_topic("SPREAD", "🔴 **Охота за спредами ОСТАНОВЛЕНА** (режим сна).")

# ==================== КОМАНДЫ УПРАВЛЕНИЯ ALPHA ====================
@bot.message_handler(func=lambda msg: msg.text and msg.text.lower().startswith(('/start', '/run', '/alpha')))
def cmd_alpha_start_alt(message):
    text = message.text.strip()
    match = re.search(r'(?:/start|/run|/alpha)\s+([a-zA-Z0-9_-]+)', text)
    if match:
        token_query = match.group(1).strip()
        session_key = f"alpha_{token_query}"
        active_alpha_sessions[session_key] = {"symbol": token_query, "stop": False}
        threading.Thread(target=run_alpha_session, args=(session_key, token_query), daemon=True).start()

        try:
            bot.reply_to(message, f"✅ Предиктивный сканер (30 сек, флуд-режим) запущен в топике Alpha!", parse_mode="Markdown")
        except: pass
        return

    try:
        bot.reply_to(
            message,
            "ℹ️ **Доступные команды:**\n"
            "• `/spread_on` — запустить поиск спредов\n"
            "• `/spread_off` — остановить поиск спредов\n"
            "• `/start [тикер]` — запустить сканер Binance Alpha",
            parse_mode="Markdown"
        )
    except: pass

@bot.message_handler(commands=['stop', 'end'])
def cmd_alpha_stop(message):
    parts = message.text.strip().split()
    if len(parts) >= 2:
        query = parts[1].strip()
        session_key = f"alpha_{query}"
        if session_key in active_alpha_sessions:
            active_alpha_sessions[session_key]["stop"] = True
            bot.reply_to(message, f"⏹ Сессия для `{query}` остановлена.", parse_mode="Markdown")
            return

    for k in active_alpha_sessions:
        active_alpha_sessions[k]["stop"] = True
    bot.reply_to(message, "⏹ Все активные Alpha-сессии остановлены.", parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def handle_chart_screenshots(message):
    if message.message_thread_id not in [TOPICS["ALPHA"], TOPICS["CHAT"]]:
        return

    if not OPENROUTER_API_KEY:
        bot.reply_to(message, "⚠️ API ключ ИИ не настроен на сервере.")
        return

    try:
        bot.reply_to(message, "🧐 Оцениваю график и лимитки...")

        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        import base64
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')

        prompt = """
Проанализируй этот скриншот графика и стакана для торговой сессии Binance Alpha.
Дай ультра-краткий ответ строго по пунктам (без лишней воды):
1. 📊 **Цена vs Ордер:** (где цена относительно лимитки)
2. ⚠️ **Риск уката:** (риск резких движений)
3. 🎯 **Вердикт:** (крутить дальше / ждать отката / переставлять ордер)
"""

        payload = {
            "model": "openai/gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 250
        }

        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=25
        )

        result_text = res.json()['choices'][0]['message']['content'].strip()
        bot.reply_to(message, f"🎯 **Вердикт по ордеру:**\n\n{result_text}", parse_mode="Markdown")

    except Exception as e:
        print(f"❌ Vision Analysis Error: {e}")
        bot.reply_to(message, "❌ Не удалось проанализировать скриншот.")

@bot.message_handler(commands=['vol', 'volume'])
def cmd_vol(message):
    text = message.text.strip().replace(',', '.')
    numbers = re.findall(r'\d+(?:\.\d+)?', text)
    if len(numbers) >= 2:
        try:
            cost = float(numbers[0])
            volume = float(numbers[1])
            if volume < 1000: volume *= 1000
            cost_per_1k = (cost / volume) * 1000
            bot.reply_to(message, f"📊 **Расчет объема:**\n💵 Затраты: `${cost:.2f}`\n📈 Объем: `{volume:,.0f}`\n💎 Цена 1K: `$ {cost_per_1k:.2f}`", parse_mode="Markdown")
            return
        except: pass
    bot.reply_to(message, "ℹ️ Использование: `/vol [затраты] [объем]`", parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_chat_messages(message):
    if not message.text or message.text.startswith('/'): return
    text = message.text.strip()

    calc_match = re.search(r'^([\d.]+)\s*-\s*([\d.]+)$', text)
    if calc_match:
        try:
            val1, val2 = float(calc_match.group(1)), float(calc_match.group(2))
            bot.reply_to(message, f"🧮 {val1} - {val2} = `{val1 - val2:.2f}`", parse_mode="Markdown")
            return
        except: pass

    match_qty = re.search(r'^([\d\s\.,]+)\s+([a-zA-Z0-9_-]+)$', text)
    if match_qty:
        try:
            qty_raw = match_qty.group(1).replace(' ', '').replace(',', '.')
            quantity = float(qty_raw)
            token_query = match_qty.group(2)
        except:
            quantity = 1.0
            token_query = text
    else:
        quantity = 1.0
        token_query = text

    clean_query = token_query.strip()
    if not clean_query:
        return

    sym_prices, sym_vols = fetch_token_prices_on_demand(clean_query)

    if not sym_prices:
        bot.reply_to(message, f"⚠️ Токен по запросу `{clean_query}` не найден на биржах.", parse_mode="Markdown")
        return

    lines = [f"🪙 **Запрос:** `{clean_query}` (Кол-во: `{quantity:,.4f}`)\n"]
    for ex, p in sorted(sym_prices.items(), key=lambda x: x[1]):
        v = format_volume(sym_vols.get(ex, 0))
        total_cost = p * quantity
        lines.append(f"🔹 [{ex}]: `${format_price(p)}` | Общая стоимость: **`${total_cost:,.2f}`** ({v})")

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)

if __name__ == "__main__":
    print("🚀 Bot starting with Direct Exchange API Connector & Prices on Spread Convergence...")
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=fetch_telegram_channels_promos, daemon=True).start()
    threading.Thread(target=fetch_newsmaker_channel, daemon=True).start()
    threading.Thread(target=fetch_direct_exchange_promos, daemon=True).start()
    threading.Thread(target=fetch_global_crypto_promos, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    print("🤖 Telegram bot polling started...")
    bot.infinity_polling(skip_pending=True)
