import settings
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')

def get_time_str():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

def log_event(trade, message):
    log_entry = f"[{get_time_str()}] {message}"
    if 'logs' not in trade:
        trade['logs'] = []
    trade['logs'].insert(0, log_entry)
    
def get_exchange(symbol):
    # Basic exchange detection based on symbol suffix or name
    if 'SENSEX' in symbol or 'BSE' in symbol: return 'BFO'
    if 'NIFTY' in symbol or 'BANKNIFTY' in symbol: return 'NFO'
    if 'MCX' in symbol: return 'MCX'
    return 'NSE'

def can_place_order(mode, user_id=None):
    """
    Checks global risk limits (Max Loss) based on the specific USER'S settings.
    """
    try:
        # 1. Load Settings for this specific User
        s = settings.load_settings(user_id=user_id)
        mode_conf = s['modes'].get(mode, {})
        
        # 2. Check Max Loss Limit
        max_loss = float(mode_conf.get('max_loss', 0))
        
        if max_loss > 0:
            # Import here to avoid circular dependency
            from managers.persistence import load_history
            
            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            total_loss = 0.0
            
            # Calculate Realized Loss from History for the specific User
            history = load_history(user_id=user_id)
            for t in history:
                # Check if trade was exited TODAY and matches the mode (LIVE/PAPER)
                if t.get('exit_time') and t['exit_time'].startswith(today_str) and t['mode'] == mode:
                    if t.get('pnl', 0) < 0:
                        total_loss += abs(t['pnl'])
            
            if total_loss >= max_loss:
                return False, f"Max Loss Limit Reached (Limit: ₹{max_loss}, Today's Loss: ₹{total_loss:.2f})"

        return True, "OK"

    except Exception as e:
        print(f"Risk Check Error (User {user_id}): {e}")
        # Fail safe: Allow trade if check fails, but log error
        return True, "Error bypassed"
