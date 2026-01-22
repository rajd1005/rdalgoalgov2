# mock_broker.py
import datetime
import random
import threading
import time
import re

# --- Global Data ---
MOCK_MARKET_DATA = {
    "NSE:NIFTY 50": 22000.0,
    "NSE:NIFTY BANK": 48000.0,
    "BSE:SENSEX": 72000.0,
    "NSE:RELIANCE": 2400.0,
}

# Configuration
SIM_CONFIG = {
    "active": False,
    "volatility": 0.05,
    "speed": 1.0,
    "trend": "SIDEWAYS"
}

def get_mock_expiry():
    return datetime.date.today().strftime("%Y-%m-%d")

CURRENT_EXPIRY = get_mock_expiry()

# --- OPTION PRICING ENGINE ---
def calculate_option_price(spot_price, strike_price, option_type):
    intrinsic = 0.0
    if option_type == "CE": intrinsic = max(0.0, spot_price - strike_price)
    else: intrinsic = max(0.0, strike_price - spot_price)
    distance = abs(spot_price - strike_price)
    time_value = 150 * (0.995 ** distance) 
    noise = random.uniform(-2, 2)
    return round(max(0.05, intrinsic + time_value + noise), 2)

# --- Background Market Simulator ---
def _market_heartbeat():
    print(f"💓 [MOCK MARKET] Simulation Heartbeat Started. Expiry: {CURRENT_EXPIRY}", flush=True)
    while True:
        if SIM_CONFIG["active"]:
            trend = SIM_CONFIG["trend"]
            vol = SIM_CONFIG["volatility"]
            
            # 1. Update INDICES
            indices = ["NSE:NIFTY 50", "NSE:NIFTY BANK", "BSE:SENSEX", "NSE:RELIANCE"]
            for sym in indices:
                curr = MOCK_MARKET_DATA.get(sym, 10000)
                bias = 0
                if trend == "BULLISH": bias = vol * 0.5
                elif trend == "BEARISH": bias = -vol * 0.5
                change = random.uniform(-vol, vol) + bias
                MOCK_MARKET_DATA[sym] = round(curr * (1 + change/100.0), 2)

            # 2. Update FUTURES & OPTIONS
            keys = list(MOCK_MARKET_DATA.keys())
            for sym in keys:
                if "FUT" in sym:
                    idx_key = "NSE:NIFTY 50"
                    if "BANK" in sym: idx_key = "NSE:NIFTY BANK"
                    if idx_key in MOCK_MARKET_DATA:
                        MOCK_MARKET_DATA[sym] = round(MOCK_MARKET_DATA[idx_key] + 10, 2)

                if ("NIFTY" in sym or "BANKNIFTY" in sym) and ("CE" in sym or "PE" in sym):
                    try:
                        match = re.search(r'(CE|PE)(\d+(\.\d+)?)', sym)
                        if match:
                            type_ = match.group(1)
                            strike = float(match.group(2))
                            spot = MOCK_MARKET_DATA["NSE:NIFTY 50"]
                            if "BANKNIFTY" in sym: spot = MOCK_MARKET_DATA["NSE:NIFTY BANK"]
                            MOCK_MARKET_DATA[sym] = calculate_option_price(spot, strike, type_)
                    except: pass
        time.sleep(SIM_CONFIG["speed"])

t = threading.Thread(target=_market_heartbeat, daemon=True)
t.start()

# --- MOCK ALICEBLUE CLASS ---
class MockAliceBlue:
    def __init__(self, user_id=None, api_key=None, **kwargs):
        print(f"⚠️ [MOCK ALICEBLUE] Initialized. Expiry Set To: {CURRENT_EXPIRY}", flush=True)
        self.mock_instruments = self._generate_instruments()
        # Enums for compatibility
        self.TransactionType = type('Enum', (), {'Buy': 'BUY', 'Sell': 'SELL'})
        self.OrderType = type('Enum', (), {'Market': 'MARKET', 'Limit': 'LIMIT', 'StopLossLimit': 'SL', 'StopLossMarket': 'SL-M'})
        self.ProductType = type('Enum', (), {'Intraday': 'MIS', 'Delivery': 'CNC'})

    def get_session_id(self):
        return {"stat": "Ok", "sessionID": "mock_session_123"}

    def get_master_contract(self, exchange):
        # In real pya3, this downloads a file. Here we do nothing, assumes smart_trader loads simulated data or skips.
        print(f"[Mock] Downloaded Master Contract for {exchange}")
        return True

    def get_instrument_by_symbol(self, exchange, symbol):
        # Find in mock list
        for i in self.mock_instruments:
            if i['exchange'] == exchange and i['tradingsymbol'] == symbol:
                return i
        # If not found, create a dummy one on the fly for simulation flexibility
        return {"exchange": exchange, "tradingsymbol": symbol, "token": random.randint(10000, 99999), "symbol": symbol}

    def get_scrip_info(self, instrument):
        # Return Quote in AliceBlue Format
        sym_key = f"{instrument['exchange']}:{instrument['tradingsymbol']}"
        
        # Determine fallback if key missing
        if sym_key not in MOCK_MARKET_DATA:
            MOCK_MARKET_DATA[sym_key] = 100.0
            
        ltp = MOCK_MARKET_DATA[sym_key]
        return {'stat': 'Ok', 'LTP': ltp, 'TSym': instrument['tradingsymbol']}

    def place_order(self, **kwargs):
        # AliceBlue place_order returns dict with NessjID on success
        print(f"✅ [MOCK ALICE] Order: {kwargs.get('transaction_type')} {kwargs.get('quantity')} {kwargs.get('instrument', {}).get('tradingsymbol')}", flush=True)
        return {'stat': 'Ok', 'NessjID': f"ORD_{random.randint(10000,99999)}"}

    def modify_order(self, **kwargs):
        print(f"✏️ [MOCK ALICE] Modify Order {kwargs.get('order_id')}", flush=True)
        return {'stat': 'Ok'}

    def cancel_order(self, order_id):
        print(f"❌ [MOCK ALICE] Cancel Order {order_id}", flush=True)
        return {'stat': 'Ok'}

    def get_daywise_positions(self):
        # Return empty list or mock positions
        return []

    def get_order_book(self):
        return []

    def get_order_history(self, order_id):
        # Required for modification logic in broker_ops
        return [{'Exchange':'NFO', 'Trsym':'MOCK', 'Trantype':'B', 'PrdType':'I', 'Qty':50}]

    def search_instruments(self, exchange, keyword):
        # Simple search in mock instruments
        return [i for i in self.mock_instruments if keyword.upper() in i['tradingsymbol']]

    def _generate_instruments(self):
        # Same generator as before but adapted keys if needed
        inst_list = []
        inst_list.append({"token": "256265", "tradingsymbol": "NIFTY 50", "symbol": "NIFTY 50", "exchange": "NSE", "lot_size": 1})
        inst_list.append({"token": "260105", "tradingsymbol": "NIFTY BANK", "symbol": "NIFTY BANK", "exchange": "NSE", "lot_size": 1})
        
        # ... (Include futures/options generation similar to previous, simplified here)
        return inst_list

    # Mock Methods
    def login_url(self): return "/mock-login-trigger"
    def generate_session(self, request_token, api_secret): return {"access_token": "mock_token_123", "user_id": "DEMO_USER"}
    def set_access_token(self, access_token): pass
    def instruments(self, exchange=None): return self.mock_instruments

    def quote(self, instruments):
        if isinstance(instruments, str): instruments = [instruments]
        res = {}
        for x in instruments:
            if x not in MOCK_MARKET_DATA: MOCK_MARKET_DATA[x] = 100.0
            p = MOCK_MARKET_DATA[x]
            res[x] = {"last_price": p, "ohlc": {"open": p, "high": p, "low": p, "close": p}}
        return res

    def ltp(self, instruments): return self.quote(instruments)

    def place_order(self, **kwargs): 
        print(f"✅ [MOCK] Order: {kwargs.get('transaction_type')} {kwargs.get('quantity')} {kwargs.get('tradingsymbol')}", flush=True)
        return f"ORD_{random.randint(10000,99999)}"

    def historical_data(self, *args, **kwargs): return []
