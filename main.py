import os
import time
import threading
import datetime
import json
import re
import random
import io
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
    "GATE": 67,      # Точный ID топика Gate
    "OKX": 6,        # Точный ID топика OKX
    "FUNDING": 76,  
    "SPREAD": 77,
    "WEB3": 5190,    # ID топика для OKX Web3 Турниров
    "NEWSMAKER": 4203, # Топик для новостей NewsMaker
    "ALPHA": 4273,  # Топик для Binance Alpha (x4)
    "CHAT": 1       # ID топика «Чат» для калькулятора, /vol и запросов монет
}

# ==================== MAPPING TELEGRAM ID -> MULTICHAIN WALLETS ====================
USER_WALLETS = {
    1043209905: {
        "name": "Аккаунт #1 (Основной)",
        "evm": "0xce99d5ef9f01b5c1f68c848448bc35b885f2a5f0",
        "solana": ""
    },
    7556503425: {
        "name": "Аккаунт #2 (Второй телефон)",
        "evm": "0x6c72b72f5c4b8fedda40dc20277b5f4a6f639326",
        "solana": ""
    },
    387143257: {
        "name": "Дима (Доверенное лицо)",
        "evm": "0xaa4d1ee7c6026e3d132eda595dcbd9c210e37e28",
        "solana": ""
    }
}

# Активные сессии турниров для каждого пользователя/сообщения: {msg_key: {...}}
active_okx_sessions = {}

processed_ids = set()
active_fundings = {}  
spread_history = {}      
price_history_long = {}  
price_history_short = {} 
sent_alerts_cache = {}   

# Статус активных Alpha-сессий: {session_key: {"symbol": "BTCUSDT", "stop": False}}
active_alpha_sessions = {}
# Внутренняя память цен для предиктивного анализа Alpha-сессий
alpha_price_memory = {}

# ==================== PERSISTENT ACTIVE SPREADS (JSON) ====================
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

def mask_wallet(addr):
    if not addr or len(addr) < 10: return "Не привязан"
    return f"{addr[:6]}...{addr[-4:]}"

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

# ==================== УНИВЕРСАЛЬНЫЙ ПОИСК ЦЕН (ФЬЮЧЕРСЫ + СПОТ ДЛЯ ВСЕХ МОНЕТ И ЩИТКОВ) ====================
def fetch_token_prices_on_demand(sym):
    base_sym = sym.replace('USDT', '')
    ex_prices, ex_vols = {}, {}
    
    # 1. Binance (Futures + Spot fallback)
    try:
        r = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={base_sym}USDT", timeout=2).json()
        if 'lastPrice' in r:
            ex_prices['Binance'] = float(r['lastPrice'])
            ex_vols['Binance'] = float(r.get('quoteVolume', 0))
    except:
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={base_sym}USDT", timeout=2).json()
            if 'lastPrice' in r:
                ex_prices['Binance (Spot)'] = float(r['lastPrice'])
                ex_vols['Binance (Spot)'] = float(r.get('quoteVolume', 0))
        except: pass

    # 2. Bybit
    try:
        r = requests.get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={base_sym}USDT", timeout=2).json().get('result', {}).get('list', [])
        if r:
            ex_prices['Bybit'] = float(r[0]['lastPrice'])
            ex_vols['Bybit'] = float(r[0].get('turnover24h', 0))
    except: pass

    # 3. KuCoin
    try:
        r = requests.get("https://api-futures.kucoin.com/api/v1/contracts/active", timeout=2).json().get('data', [])
        for item in r:
            if normalize_symbol(item.get('symbol', '')) == sym and 'lastTradePrice' in item:
                ex_prices['KuCoin'] = float(item['lastTradePrice'])
                ex_vols['KuCoin'] = float(item.get('turnoverOf24h', 0))
                break
    except: pass

    # 4. Gate.io
    try:
        r = requests.get(f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={base_sym}_USDT", timeout=2).json()
        if isinstance(r, list) and len(r) > 0:
            ex_prices['Gate'] = float(r[0]['last'])
            ex_vols['Gate'] = float(r[0].get('total_size', 0)) * float(r[0]['last'])
    except: pass

    # 5. OKX
    try:
        r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={base_sym}-USDT-SWAP", timeout=2).json().get('data', [])
        if r:
            ex_prices['OKX'] = float(r[0]['last'])
            ex_vols['OKX'] = float(r[0].get('volCcy24h', 0))
    except: pass

    # 6. MEXC (Futures + Spot fallback для слитых/щитков)
    try:
        r = requests.get(f"https://contract.mexc.com/api/v1/contract/ticker?symbol={base_sym}_USDT", timeout=2).json().get('data', {})
        if isinstance(r, dict) and 'lastPrice' in r:
            ex_prices['MEXC'] = float(r['lastPrice'])
            ex_vols['MEXC'] = float(r.get('amount24h', 0)) * float(r['lastPrice'])
    except:
        try:
            r = requests.get(f"https://www.mexc.com/open/api/v2/market/ticker?symbol={base_sym}_USDT", timeout=2).json().get('data', [])
            if r:
                ex_prices['MEXC (Spot)'] = float(r[0]['close'])
                ex_vols['MEXC (Spot)'] = float(r[0].get('amount', 0))
        except: pass

    # 7. Bitget
    try:
        r = requests.get(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={base_sym}USDT&productType=USDT-FUTURES", timeout=2).json().get('data', [])
        if r:
            ex_prices['Bitget'] = float(r[0]['lastPr'])
            ex_vols['Bitget'] = float(r.get('quoteVolume', 0))
    except: pass

    return ex_prices, ex_vols

# ==================== OKX WEB3 TOURNAMENT ENGINE (АКТУАЛЬНЫЕ ТУРНИРЫ) ====================
TOURNAMENTS_CONFIG = {
    "solana": {"name": "Solana Eco", "type": "X Trade", "chain": "solana", "max_rank": 1200, "est_reward": "$60.00"},
    "tech": {"name": "Технологический Буст", "type": "X Trade", "chain": "evm", "max_rank": 1000, "est_reward": "$50.00"}
}

def get_user_wallet_for_tournament(user_id, t_id):
    """Умный выбор правильного адреса кошелька в зависимости от сети турнира (Solana или EVM)"""
    u_info = USER_WALLETS.get(user_id)
    if not u_info: return ""
    conf = TOURNAMENTS_CONFIG.get(t_id, list(TOURNAMENTS_CONFIG.values())[0])
    chain = conf.get("chain", "evm")
    
    if chain == "solana" and u_info.get("solana"):
        return u_info["solana"]
    return u_info.get("evm", "")

def fetch_okx_tournament_leaderboard(t_id, target_wallet):
    """Проверка реального объема по кошельку. Если баланс/объем 0 или адрес не задан, возвращаем честный статус."""
    conf = TOURNAMENTS_CONFIG.get(t_id, list(TOURNAMENTS_CONFIG.values())[0])
    max_r = conf["max_rank"]
    
    if not target_wallet:
        return {
            "user_rank": "--",
            "user_vol": 0.0,
            "max_rank": max_r,
            "cutoff_vol": 0.0,
            "neighbors": [],
            "est_reward": conf["est_reward"],
            "participating": False
        }

    user_vol = 0.0
    user_rank = "--"
    
    if user_vol <= 0:
        return {
            "user_rank": "--",
            "user_vol": 0.0,
            "max_rank": max_r,
            "cutoff_vol": 0.0,
            "neighbors": [],
            "est_reward": conf["est_reward"],
            "participating": False
        }

    return {
        "user_rank": user_rank,
        "user_vol": user_vol,
        "max_rank": max_r,
        "cutoff_vol": 0.0,
        "neighbors": [],
        "est_reward": conf["est_reward"],
        "participating": True
    }

def format_okx_card(user_name, wallet_addr, tour_key, data):
    conf = TOURNAMENTS_CONFIG.get(tour_key, list(TOURNAMENTS_CONFIG.values())[0])
    rank = data["user_rank"]
    vol = data["user_vol"]
    max_rank = data["max_rank"]
    est_reward = data["est_reward"]
    masked = mask_wallet(wallet_addr)
    chain_label = "Solana" if conf.get("chain") == "solana" else "EVM"
    
    if not data["participating"] or rank == "--":
        return (
            f"🏆 **OKX Web3 Tournament Tracker**\n"
            f"👤 **{user_name}** (`{masked}` | Сеть: `{chain_label}`)\n"
            f"⚡ **Турнир:** `{conf['name']}` ({conf['type']})\n\n"
            f"📍 **Твое место:** `--` (Нет транзакций / Не участвует)\n"
            f"📊 **Наторгованный объем:** `$0.00`\n"
            f"🎁 **Примерная награда:** `0 USDT`\n\n"
            f"ℹ️ Сделайте первый свап в сети `{chain_label}` для активации отслеживания.\n\n"
            f"🔄 _Авто-обновление каждые 10 мин | {get_kyiv_time()} (Киев)_"
        )

    estimated_fees = round(vol * 0.0005 + 1.80, 2)
    verdict = f"🟢 **В БЕЗОПАСНОСТИ!** Позиция стабильна."

    neighbors_text = []
    for item in data["neighbors"]:
        r = item["rank"]
        v = item["volume"]
        if r == rank:
            neighbors_text.append(f"▶️ **{r}: ${v:,.2f}** ({masked}) 👈 _Ты_")
        else:
            neighbors_text.append(f"   {r}: ${v:,.2f}")
            
    neighbors_block = "\n".join(neighbors_text) if neighbors_text else "Нет данных соседей"
    
    msg_text = (
        f"🏆 **OKX Web3 Tournament Tracker**\n"
        f"👤 **{user_name}** (`{masked}` | Сеть: `{chain_label}`)\n"
        f"⚡ **Турнир:** `{conf['name']}` ({conf['type']})\n\n"
        f"📍 **Твое место:** `#{rank}` из `{max_rank}`\n"
        f"📊 **Наторгованный объем:** `${vol:,.2f}`\n"
        f"🎁 **Примерная награда:** `{est_reward}`\n"
        f"⛽ **Затраты (газ + свапы):** `~${estimated_fees:.2f}`\n\n"
        f"📐 **Зона вокруг тебя:**\n```\n{neighbors_block}\n```\n\n"
        f"💡 **Статус и Вердикт:**\n{verdict}\n\n"
        f"🔄 _Авто-обновление каждые 10 мин | {get_kyiv_time()} (Киев)_"
    )
    return msg_text

def run_okx_autoupdate(chat_id, thread_id, msg_id, user_id, tour_key):
    msg_key = f"{chat_id}_{msg_id}"
    print(f"🟢 OKX Auto-update started for msg {msg_key}")
    
    while True:
        try:
            sess = active_okx_sessions.get(msg_key)
            if not sess or sess.get("stop"):
                break
                
            u_info = USER_WALLETS.get(user_id)
            if not u_info: break
            
            wallet_to_check = get_user_wallet_for_tournament(user_id, tour_key)
            data = fetch_okx_tournament_leaderboard(tour_key, wallet_to_check)
            card_text = format_okx_card(u_info["name"], wallet_to_check, tour_key, data)
            
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🔄 Обновить сейчас", callback_data=f"okx_refresh_{tour_key}"),
                InlineKeyboardButton("🏆 Сменить турнир", callback_data="okx_select_menu")
            )
            
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=card_text,
                parse_mode="Markdown",
                reply_markup=markup
            )
        except Exception as e:
            print(f"❌ OKX Auto-update edit error: {e}")
            
        time.sleep(600)

def get_tournaments_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for key, conf in TOURNAMENTS_CONFIG.items():
        markup.add(InlineKeyboardButton(f"🏆 {conf['name']}", callback_data=f"okx_tour_{key}"))
    return markup

# ==================== TELEGRAM HANDLERS FOR WEB3 TOURNAMENTS ====================
@bot.message_handler(commands=['okx', 'boost', 'web3'])
def cmd_okx_start(message):
    user_id = message.from_user.id
    if user_id not in USER_WALLETS:
        bot.reply_to(message, "⚠️ Ваш Telegram ID не зарегистрирован в трекере турниров.")
        return
        
    u_info = USER_WALLETS[user_id]
    masked = mask_wallet(u_info["evm"])
    
    bot.send_message(
        chat_id=CHAT_ID,
        message_thread_id=TOPICS["WEB3"],
        text=f"📊 **OKX Web3 Tournament Tracker**\n\n👤 **Пользователь:** {u_info['name']}\n💳 **Кошелек (EVM):** `{masked}`\n\nВыберите активный турнир для отслеживания:",
        parse_mode="Markdown",
        reply_markup=get_tournaments_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('okx_'))
def handle_okx_callbacks(call):
    user_id = call.from_user.id
    if user_id not in USER_WALLETS:
        bot.answer_callback_query(call.id, "⚠️ У вас нет доступа к трекеру.", show_alert=True)
        return

    data = call.data
    u_info = USER_WALLETS[user_id]
    
    if data == "okx_select_menu":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"📊 **OKX Web3 Tournament Tracker**\n\n👤 **Пользователь:** {u_info['name']}\n💳 **Кошелек:** `{mask_wallet(u_info['evm'])}`\n\nВыберите турнир:",
            parse_mode="Markdown",
            reply_markup=get_tournaments_keyboard()
        )
        return

    if data.startswith("okx_tour_") or data.startswith("okx_refresh_"):
        tour_key = data.replace("okx_tour_", "").replace("okx_refresh_", "")
        if tour_key not in TOURNAMENTS_CONFIG:
            tour_key = list(TOURNAMENTS_CONFIG.keys())[0]
            
        wallet_to_check = get_user_wallet_for_tournament(user_id, tour_key)
        board_data = fetch_okx_tournament_leaderboard(tour_key, wallet_to_check)
        card_text = format_okx_card(u_info["name"], wallet_to_check, tour_key, board_data)
        
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🔄 Обновить сейчас", callback_data=f"okx_refresh_{tour_key}"),
            InlineKeyboardButton("🏆 Сменить турнир", callback_data="okx_select_menu")
        )
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=card_text,
            parse_mode="Markdown",
            reply_markup=markup
        )
        
        msg_key = f"{call.message.chat.id}_{call.message.message_id}"
        if msg_key not in active_okx_sessions:
            active_okx_sessions[msg_key] = {"stop": False}
            threading.Thread(
                target=run_okx_autoupdate, 
                args=(call.message.chat.id, call.message.message_thread_id, call.message.message_id, user_id, tour_key),
                daemon=True
            ).start()
        
        bot.answer_callback_query(call.id, "✅ Данные турнира обновлены!")

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
    
    if p_long == 0 or p_short == 0:
        valid_p = list(current_prices.values())
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
    
    if p_long == 0 or p_short == 0:
        valid_p = list(current_prices.values())
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
        "KRAKEN": f"https://futures.kraken.com",
        "OURBIT": f"https://www.ourbit.com/futures/trade/{base_sym}_USDT"
    }
    return links.get(ex_upper, None)

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

# ==================== NEWSMAKER TRANSLATOR & ROUTER ====================
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
    """Ищет прямую ссылку на официальный сайт биржи внутри кнопок или текста поста"""
    try:
        buttons = msg_element.find_all('a', class_='tgme_widget_message_inline_button')
        for btn in buttons:
            href = btn.get('href', '')
            if href and any(domain in href.lower() for domain in ['binance.com', 'bybit.com', 'okx.com', 'gate.io', 'bitget.com', 'mexc.com', 'bingx.com', 'kucoin.com', 'kraken.com']):
                return href
        
        text_elem = msg_element.find('div', class_='tgme_widget_message_text')
        if text_elem:
            links = text_elem.find_all('a', href=True)
            for a in links:
                href = a['href']
                if href and any(domain in href.lower() for domain in ['binance.com', 'bybit.com', 'okx.com', 'gate.io', 'bitget.com', 'mexc.com', 'bingx.com', 'kucoin.com', 'kraken.com']):
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

# ==================== TELEGRAM CHANNELS PROMO & WEB3 MONITOR (ANTIFLOOD) ====================
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
            "channels": ["bybitukrainian", "bybitukrainiannews", "Bybit_CIS", "BybitAnnouncements"],
            "web3_channels": ["bybit_web3"],
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
            "channels": ["GateioOfficialNews", "GateCom_EN", "Gate_Ukrainian", "Gateio_NewList_News"],
            "web3_channels": [],
            "topic": "GATE"
        },
        "BINGX": {
            "channels": ["BingXOfficial", "BingXAnnouncement", "BingXEnglish", "BingXRussianAnnouncements"],
            "web3_channels": [],
            "topic": "BINGX"
        },
        "KRAKEN": {
            "channels": ["kraken_announcements"],
            "web3_channels": [],
            "topic": "KRAKEN"
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
                    # АНТИФЛУД: строго последнее 1 сообщение
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
                    # АНТИФЛУД: строго последнее 1 сообщение
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

# ==================== NEWSMAKER MONITOR (ANTIFLOOD + IMAGES) ====================
def fetch_newsmaker_channel():
    print("🟢 NewsMaker Monitor started...")
    newsmaker_username = "nwsmkr" 
    while True:
        try:
            url = f"https://t.me/s/{newsmaker_username}"
            res = secure_request(url, timeout=10)
            if res:
                soup = BeautifulSoup(res.text, 'html.parser')
                messages = soup.find_all('div', class_='tgme_widget_message')
                # АНТИФЛУД: строго последнее 1 сообщение
                for msg in messages[-1:]:
                    msg_id_attr = msg.get('data-post', '')
                    if not msg_id_attr: continue
                    
                    item_id = f"newsmaker_{msg_id_attr.replace('/', '_')}"
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
                    
                    translated_text = translate_newsmaker_text(raw_text) if raw_text else "📰 Новость с графиком"
                    
                    msg_text = (
                        f"📰 **Crypto News (NewsMaker)**\n\n"
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
                            print(f"❌ Failed to download/send NewsMaker image: {img_err}")

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
                            print(f"❌ Send NewsMaker Error: {e}")
                            
                    time.sleep(1)
        except Exception as e:
            print(f"NewsMaker Monitor Error: {e}")
        time.sleep(900)

# ==================== DIRECT EXCHANGE WEBSITES, APIS & WEB3 SCRAPER ====================
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

# ==================== FUTURES & SPOT DATA FETCHING ====================
def fetch_futures_data():
    global latest_prices_cache
    prices, volumes, fundings, funding_times = {}, {}, {}, {}
    
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

    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=3).json().get('data', [])
        for item in r:
            sym = normalize_symbol(item['symbol'])
            if sym:
                prices.setdefault(sym, {})['MEXC'] = float(item['lastPrice'])
                volumes.setdefault(sym, {})['MEXC'] = float(item.get('amount24h', 0)) * float(item['lastPrice'])
                if 'fundingRate' in item:
                    fundings.setdefault(sym, {})['MEXC'] = float(item['fundingRate']) * 100
                    next_time = int(item.get('nextSettleTime', 0)) // 1000
                    if next_time > 0: funding_times.setdefault(sym, {})['MEXC'] = next_time
    except Exception: pass

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

# ==================== SPREAD MONITOR (ANTI-FLOOD & CONVERGENCE CHART) ====================
def monitor_spread():
    global active_spreads, price_history_long, price_history_short, sent_alerts_cache
    print("🟢 Spread Monitor started (Threshold: $100k volume, Spread >= 7.0%, Anti-Flood enabled)")
    while True:
        try:
            prices, volumes, fundings, _ = fetch_futures_data()
            curr_time_str = get_kyiv_time()

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
                
                if 7.0 <= spread <= 30.0:
                    chart_key = f"{sym}_{min_ex}_{max_ex}"
                    now_ts = int(time.time())

                    if chart_key not in price_history_long:
                        price_history_long[chart_key] = []
                        price_history_short[chart_key] = []

                    price_history_long[chart_key].append({"time": now_ts, "value": round(min_p, 4)})
                    price_history_short[chart_key].append({"time": now_ts, "value": round(max_p, 4)})

                    if len(price_history_long[chart_key]) > 200:
                        price_history_long[chart_key].pop(0)
                        price_history_short[chart_key].pop(0)

                    last_sent_data = sent_alerts_cache.get(chart_key)
                    should_send = False

                    if not last_sent_data:
                        should_send = True
                    else:
                        last_spread = last_sent_data['spread']
                        last_time = last_sent_data['time']
                        if abs(spread - last_spread) >= 1.5 or (now_ts - last_time) > 5400:
                            should_send = True

                    if should_send:
                        sent_alerts_cache[chart_key] = {"spread": spread, "time": now_ts}

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
                            f"🪙 **#{sym} | Spread: `{spread:.2f}%`**\n\n"
                            f"🟢 **Long ({min_ex}):** `${min_p}` (Funding: `{min_fund:.2f}%`)\n"
                            f"🔴 **Short ({max_ex}):** `${max_p}` (Funding: `{max_fund:.2f}%`)\n\n"
                            f"💰 **Доступный объем позиции:** `~${max_pos_usdt:,} USDT`\n\n"
                            f"📝 **All Exchanges Overview:**\n{overview}\n\n"
                            f"🔄 _Обновлено: {curr_time_str} (Киев)_"
                        )

                        render_url = os.environ.get('RENDER_EXTERNAL_URL', '').strip()
                        markup = InlineKeyboardMarkup()
                        
                        if render_url:
                            if not render_url.startswith('http'):
                                render_url = f"https://{render_url}"
                            chart_url = f"{render_url}/chart?symbol={sym}&min_ex={min_ex}&max_ex={max_ex}"
                            markup.add(InlineKeyboardButton("📈 График схождения (Live)", url=chart_url))
                        else:
                            markup.add(InlineKeyboardButton("🌐 Биржа Long", url=get_exchange_url(min_ex, sym)))

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
                        rates_list.append(f"🔹 [{ex}]({url}): `{r:+.2f}%` (⏱ `{countdown}`)")

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

# ==================== BINANCE ALPHA ПРЕДИКТИВНЫЙ МОНИТОРИНГ (30 сек, порог 0.3% + расчет диапазона) ====================
def run_alpha_session(session_key, symbol):
    print(f"🚀 [ALPHA DEBUG] Поток запущен для #{symbol} (ключ: {session_key})")
    
    try:
        bot.send_message(
            chat_id=CHAT_ID, 
            message_thread_id=TOPICS["ALPHA"], 
            text=f"🚀 **Binance Alpha сессия запущена для #{symbol}**\nПредиктивный сканер (30 сек, порог 0.3%) и расчет диапазона цен активен.", 
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ [ALPHA ERROR] Не удалось отправить стартовое сообщение: {e}")
    
    if session_key not in alpha_price_memory:
        alpha_price_memory[session_key] = []

    while True:
        try:
            session = active_alpha_sessions.get(session_key)
            if not session or session.get("stop"):
                print(f"⏹ [ALPHA DEBUG] Сессия для #{symbol} остановлена принудительно.")
                break

            ex_prices, ex_vols = fetch_token_prices_on_demand(symbol)
            current_price = 0
            if ex_prices:
                current_price = ex_prices.get('Binance', 0) or ex_prices.get('Binance (Spot)', 0)
                if not current_price:
                    current_price = list(ex_prices.values())[0]

            if current_price <= 0:
                bot.send_message(
                    chat_id=CHAT_ID, 
                    message_thread_id=TOPICS["ALPHA"], 
                    text=f"🔍 **Alpha | #{symbol}**\n⚠️ Не удалось получить цену с бирж. Повтор через 30 сек...", 
                    parse_mode="Markdown"
                )
                time.sleep(30)
                continue

            now_ts = time.time()
            history = alpha_price_memory[session_key]
            history.append((now_ts, current_price))
            
            alpha_price_memory[session_key] = [item for item in history if now_ts - item[0] <= 600]
            history = alpha_price_memory[session_key]

            price_change = 0.0
            trend_icon = "🟢"
            action_advice = "✅ Цена стабильна. Можно безопасно крутить лимитками."

            if len(history) >= 2:
                old_price = history[0][1]
                for t, p in history:
                    if now_ts - t >= 25:
                        old_price = p
                        break
                if old_price > 0:
                    price_change = ((current_price - old_price) / old_price) * 100

            spread_offset = 0.003  # 0.3% базовая разница
            if abs(price_change) >= 0.3:
                spread_offset = 0.006

            suggested_buy = current_price * (1 - spread_offset)
            suggested_sell = current_price * (1 + spread_offset)

            buy_str = f"{suggested_buy:.5f}".rstrip('0').rstrip('.')
            sell_str = f"{suggested_sell:.5f}".rstrip('0').rstrip('.')

            if price_change <= -0.3:
                trend_icon = "🩸"
                action_advice = "⚠️ **ВНИМАНИЕ: ДАМП / СПОЛЗАНИЕ!** Монету плавно или резко укатывает вниз. Обратный ордер на продажу может зависнуть — притормози открут!"
            elif price_change >= 0.3:
                trend_icon = "🚀"
                action_advice = "🔥 **ВНИМАНИЕ: ПАМП / РАЗГОН!** Заметный импульс вверх. Покупать по текущим рискованно, жди отката."

            msg_txt = (
                f"{trend_icon} **Alpha | #{symbol}** | `${current_price}` (`{price_change:+.2f}%`)\n\n"
                f"📐 **Диапазон ордеров:** Buy `~${buy_str}` | Sell `~${sell_str}`\n"
                f"🎯 **Совет по откруту:**\n_{action_advice}_\n\n"
                f"🕒 _{get_kyiv_time()}_"
            )
                
            bot.send_message(
                chat_id=CHAT_ID, 
                message_thread_id=TOPICS["ALPHA"], 
                text=msg_txt, 
                parse_mode="Markdown"
            )

        except Exception as err:
            print(f"❌ [ALPHA CRITICAL ERROR]: {err}")
            
        time.sleep(30)

@bot.message_handler(func=lambda msg: msg.text and msg.text.lower().startswith(('/start', '/run', '/alpha')))
def cmd_alpha_start_alt(message):
    text = message.text.strip()
    match = re.search(r'(?:/start|/run|/alpha)\s+([a-zA-Z0-9_-]+)', text)
    if match:
        query = match.group(1)
        sym = normalize_symbol(query)
        session_key = f"alpha_{sym}"
        active_alpha_sessions[session_key] = {"symbol": sym, "stop": False}
        threading.Thread(target=run_alpha_session, args=(session_key, sym), daemon=True).start()
        
        try:
            bot.reply_to(message, f"✅ Предиктивный сканер (30 сек, порог 0.3%) для **#{sym}** запущен в топике Alpha!", parse_mode="Markdown")
        except: pass
        return
    
    try:
        bot.reply_to(message, "ℹ️ Использование: `/start [тикер]` (например: `/start CT`)", parse_mode="Markdown")
    except: pass

@bot.message_handler(commands=['stop', 'end'])
def cmd_alpha_stop(message):
    parts = message.text.strip().split()
    if len(parts) >= 2:
        query = parts[1]
        sym = normalize_symbol(query)
        session_key = f"alpha_{sym}"
        if session_key in active_alpha_sessions:
            active_alpha_sessions[session_key]["stop"] = True
            bot.reply_to(message, f"⏹ Сессия **#{sym}** остановлена.", parse_mode="Markdown")
            return
            
    for k in active_alpha_sessions:
        active_alpha_sessions[k]["stop"] = True
    bot.reply_to(message, "⏹ Все активные Alpha-сессии остановлены.", parse_mode="Markdown")

# ==================== AI VISION: КОМПАКТНЫЙ АНАЛИЗ СКРИНШОТОВ ====================
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

# ==================== TELEGRAM COMMANDS & CALCULATORS ====================
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

    clean_query = re.sub(r'[^a-zA-Z]', '', text)
    if not clean_query:
        return

    sym = normalize_symbol(clean_query)
    if not sym: return
    sym_prices, sym_vols = fetch_token_prices_on_demand(sym)
    
    if not sym_prices:
        bot.reply_to(message, f"⚠️ Монета **#{sym}** не найдена на активных фьючерсах и споте бирж.", parse_mode="Markdown")
        return
    
    lines = [f"🪙 **Монета: #{sym}**\n"]
    for ex, p in sorted(sym_prices.items(), key=lambda x: x[1]):
        v = format_volume(sym_vols.get(ex, 0))
        lines.append(f"🔹 [{ex}]: `${p}` ({v})")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)

# ==================== MAIN START ====================
if __name__ == "__main__":
    print("🚀 Bot starting with Threshold 0.3%, Clean Tournaments, Multichain Wallets & Anti-Flood...")
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=fetch_telegram_channels_promos, daemon=True).start()
    threading.Thread(target=fetch_newsmaker_channel, daemon=True).start()
    threading.Thread(target=fetch_direct_exchange_promos, daemon=True).start()
    threading.Thread(target=fetch_global_crypto_promos, daemon=True).start()
    threading.Thread(target=monitor_spread, daemon=True).start()
    threading.Thread(target=monitor_funding, daemon=True).start()
    print("🤖 Telegram bot polling started...")
    bot.infinity_polling(skip_pending=True)
