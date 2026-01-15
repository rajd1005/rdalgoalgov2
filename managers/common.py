from datetime import datetime
import pytz
import settings
from managers.persistence import load_history, load_trades

IST = pytz.timezone('Asia/Kolkata')

def get_time_str(): 
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    if 'logs' not in trade: trade['logs'] = []
    trade['logs'].append(f"[{get_time_str()}] {message}")

def get_exchange(symbol):
    s = symbol.upper()
    if any(x in s for x in ['CRUDEOIL', 'GOLD', 'SILVER', 'COPPER', 'NATURALGAS']): return "MCX"
    if any(x in s for x in ['USDINR', 'EURINR', 'GBPINR', 'JPYINR']): return "CDS"
    if "SENSEX" in s or "BANKEX" in s: return "BFO" if any(char.isdigit() for char in s) else "BSE"
    if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol: return "NFO"
    return "NSE"

def get_day_pnl(mode):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    total = 0.0
    history = load_history()
    for t in history:
        if t['exit_time'].startswith(today_str) and t['mode'] == mode: total += t.get('pnl', 0)
    active = load_trades()
    for t in active:
        if t['mode'] == mode and t['status'] != 'PENDING':
            total += (t.get('current_ltp', t['entry_price']) - t['entry_price']) * t['quantity']
    return total

def can_place_order(mode):
    current_settings = settings.load_settings()
    mode_conf = current_settings['modes'][mode]
    max_loss_limit = float(mode_conf.get('max_loss', 0))
    if max_loss_limit > 0:
        limit = -abs(max_loss_limit)
        current_pnl = get_day_pnl(mode)
        if current_pnl <= limit: return False, f"Max Daily Loss Reached ({current_pnl:.2f} <= {limit})"
    return True, "OK"
