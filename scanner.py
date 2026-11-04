import os
import requests
from web3 import Web3

RPC_NODES = {
    "xlayer": "https://rpc.xlayer.tech",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "base": "https://mainnet.base.org"
}

OKX_DEX_ROUTERS = {
    "xlayer": "0x68097d1dfc8ffb097b69352e4a947d1a5814d9a5",
}

def get_web3_connection(chain="xlayer"):
    rpc_url = RPC_NODES.get(chain, RPC_NODES["xlayer"])
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if w3.is_connected():
            return w3
    except Exception as e:
        print(f"❌ Ошибка подключения к RPC ноде {chain}: {e}")
    return None

def fetch_wallet_swap_volume(wallet_address, chain="xlayer", start_block=0):
    w3 = get_web3_connection(chain)
    if not w3:
        return 0.0

    target_wallet = Web3.to_checksum_address(wallet_address)
    router_address = Web3.to_checksum_address(OKX_DEX_ROUTERS.get(chain, OKX_DEX_ROUTERS["xlayer"]))
    
    total_volume_usd = 0.0

    try:
        latest_block = w3.eth.block_number
        scan_window = 5000  
        start_scan = max(latest_block - scan_window, start_block)

        print(f"🔍 Сканируем блокчейн {chain} от блока {start_scan} до {latest_block} для кошелька {target_wallet}...")

        for block_num in range(latest_block, start_scan, -1):
            block = w3.eth.get_block(block_num, full_transactions=True)
            for tx in block.transactions:
                if tx['from'] and tx['from'].lower() == target_wallet.lower():
                    if tx['to'] and tx['to'].lower() == router_address.lower():
                        value_in_eth = w3.from_wei(tx['value'], 'ether')
                        total_volume_usd += float(value_in_eth) * 2600.0  

    except Exception as e:
        print(f"❌ Ошибка при чтении блокчейна: {e}")

    return round(total_volume_usd, 2)

if __name__ == "__main__":
    print("🚀 Блокчейн-сканер OKX Web3 запущен...")
    test_wallet = "0xce99d5ef9f01b5c1f68c848448bc35b885f2a5f0"
    vol = fetch_wallet_swap_volume(test_wallet, chain="xlayer")
    print(f"📊 Наторгованный объем: ${vol}")
