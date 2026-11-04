import os
import time
import requests
from web3 import Web3

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = "-1004451728851"
WEB3_TOPIC_ID = 5190

USER_WALLETS = {
    "Аккаунт #1 (Основной)": "0xce99d5ef9f01b5c1f68c848448bc35b885f2a5f0",
    "Аккаунт #2 (Второй телефон)": "0x6c72b72f5c4b8fedda40dc20277b5f4a6f639326",
    "Дима (Доверенное лицо)": "0xaa4d1ee7c6026e3d132eda595dcbd9c210e37e28"
}

RPC_NODES = {
    "xlayer": "https://rpc.xlayer.tech",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "base": "https://mainnet.base.org",
    "optimism": "https://mainnet.optimism.io",
    "polygon": "https://polygon-rpc.com",
    "bsc": "https://bsc-dataseed.binance.org",
    "ethereum": "https://eth.llamarpc.com",
    "blast": "https://rpc.blast.io",
    "scroll": "https://rpc.scroll.io",
    "linea": "https://rpc.linea.build"
}

DEX_ROUTERS = {
    "xlayer": "0x68097d1dfc8ffb097b69352e4a947d1a5814d9a5",
    "arbitrum": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "base": "0x2626664c2603336e57b271c5c0b26f421741e481",
    "optimism": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "polygon": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "bsc": "0x10ed43c718714eb63d5aa57b78b54704e256024e",
    "ethereum": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "blast": "0x1d69dc0d1e345b88ce8d89e02c6101ec9b07efcf",
    "scroll": "0x569ee73bce4f17789f21f1da83e60a37b3f46f4b",
    "linea": "0x1d69dc0d1e345b88ce8d89e02c6101ec9b07efcf"
}

def get_web3_connection(chain):
    rpc_url = RPC_NODES.get(chain)
    if not rpc_url: return None
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 3}))
        if w3.is_connected():
            return w3
    except Exception:
        pass
    return None

def fetch_wallet_volume_single_chain(wallet_address, chain):
    """Сканирует объем конкретного кошелька строго в одной выбранной сети для молниеносного ответа"""
    if not wallet_address or len(wallet_address) < 10:
        return 0.0

    w3 = get_web3_connection(chain)
    if not w3: return 0.0
    
    router = DEX_ROUTERS.get(chain)
    if not router: return 0.0
    
    target_wallet = Web3.to_checksum_address(wallet_address)
    router_address = Web3.to_checksum_address(router)
    
    chain_vol = 0.0
    try:
        latest_block = w3.eth.block_number
        scan_window = 400  # Оптимальный срез блоков для скорости
        start_scan = max(latest_block - scan_window, 0)

        for block_num in range(latest_block, start_scan, -1):
            try:
                block = w3.eth.get_block(block_num, full_transactions=True)
                for tx in block.transactions:
                    if tx.get('from') and tx['from'].lower() == target_wallet.lower():
                        if tx.get('to') and tx['to'].lower() == router_address.lower():
                            value_in_native = w3.from_wei(tx.get('value', 0), 'ether')
                            multiplier = 2600.0 if chain in ["ethereum", "arbitrum", "optimism", "base", "blast", "scroll", "linea", "xlayer"] else (600.0 if chain == "bsc" else 0.5)
                            chain_vol += float(value_in_native) * multiplier
            except Exception:
                continue
    except Exception:
        pass
        
    return round(chain_vol, 2)

def send_single_chain_report(chain_key):
    """Отправляет отчет по конкретной выбранной сети"""
    if not TELEGRAM_TOKEN:
        return

    chain_name = chain_key.upper()
    lines = [f"🌐 **Мультичейн-трекер: сеть `{chain_name}`**\n"]
    
    for name, wallet in USER_WALLETS.items():
        masked = f"{wallet[:6]}...{wallet[-4:]}"
        vol = fetch_wallet_volume_single_chain(wallet, chain_key)
        lines.append(f"👤 **{name}** (`{masked}`)\n📊 Объем в `{chain_name}`: **`${vol:,.2f}`**\n")

    lines.append(f"🔄 _Точечный сканирование сети {chain_name} завершено._")
    message_text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "message_thread_id": WEB3_TOPIC_ID,
        "text": message_text,
        "parse_mode": "Markdown"
    }

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Ошибка отправки отчета по сети: {e}")
