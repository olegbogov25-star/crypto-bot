import os
import requests

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = "-1004451728851"
WEB3_TOPIC_ID = 5190

# Твои аккаунты с привязкой к Telegram ID
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

# Список турниров и связанных сетей
OKX_TOURNAMENTS = {
    "bsc": {"id": "akedo", "name": "Akedo (BSC / Aketo)", "chain": "evm", "max_rank": 3000, "est_reward": "320 USDT"},
    "xlayer": {"id": "tech", "name": "Технологический Буст (X Layer)", "chain": "evm", "max_rank": 3000, "est_reward": "$50.00"},
    "solana": {"id": "solana", "name": "Solana Eco (Solana)", "chain": "solana", "max_rank": 3000, "est_reward": "$60.00"}
}

def mask_wallet(addr):
    if not addr or len(addr) < 10: return "Не привязан"
    return f"{addr[:6]}...{addr[-4:]}"

def fetch_okx_leaderboard_api(campaign_id, wallet_address):
    """Запрос к официальному API OKX для получения реального места, объема и соседей"""
    if not wallet_address:
        return None
    try:
        url = f"https://www.okx.com/priapi/v1/web3/growth/campaign/leaderboard?campaignId={campaign_id}&walletAddress={wallet_address}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            return res.json().get("data", {})
    except Exception as e:
        print(f"❌ OKX API Error: {e}")
    return None
