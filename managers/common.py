import pytz
import logging
from datetime import datetime, time

# Define Timezone (Critical for Algo)
IST = pytz.timezone('Asia/Kolkata')

def get_time_str():
    """Returns current IST time as string"""
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

def get_today_date_str():
    return datetime.now(IST).strftime("%Y-%m-%d")

def log_event(trade, message):
    """
    Appends a log message to the trade's log list.
    """
    timestamp = get_time_str()
    log_entry = f"[{timestamp}] {message}"
    
    if 'logs' not in trade:
        trade['logs'] = []
    
    # Insert at top (newest first)
    trade['logs'].insert(0, log_entry)
    print(f"📝 {trade.get('symbol', 'TRADE')}: {message}")

def get_exchange(symbol):
    """
    Helper to guess exchange from symbol string if not provided.
    AliceBlue symbols often look like 'NSE:RELIANCE' or just 'RELIANCE'
    """
    if ":" in symbol:
        return symbol.split(":")[0]
    
    # Heuristic for AliceBlue/General Indian Markets
    s = symbol.upper()
    if "NIFTY" in s or "BANKNIFTY" in s or "FINNIFTY" in s or "SENSEX" in s:
        if "FUT" in s or "CE" in s or "PE" in s:
            if "SENSEX" in s: return "BFO" # BSE F&O
            return "NFO" # NSE F&O
    
    if s.endswith(".BO"): return "BSE"
    if s.endswith("-BL"): return "BSE" # Sometimes used
    
    return "NSE" # Default to NSE Equity

def can_place_order(mode):
    """
    Global Safety Check.
    Returns: (Boolean, Reason)
    """
    # 1. Check Mode
    if mode not in ["LIVE", "PAPER"]:
        return False, f"Invalid Mode: {mode}"
    
    # 2. Check Time (Optional Safety - Block trades after 3:30 PM)
    now = datetime.now(IST).time()
    market_open = time(9, 15)
    market_close = time(15, 30)
    
    # Uncomment to enforce market hours strictness
    # if mode == "LIVE" and (now < market_open or now > market_close):
    #     return False, "Market Closed"

    return True, "OK"

def parse_broker_error(e):
    """
    AliceBlue specific error parsing.
    """
    err_str = str(e)
    # AliceBlue often returns errors in 'emsg' key if it's a dict
    if "emsg" in err_str:
        return err_str # It's already descriptive
    
    if "NetworkException" in err_str:
        return "Network Error - Check Internet"
        
    return err_str
