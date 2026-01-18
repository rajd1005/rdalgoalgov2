import json
import threading
from database import db, ActiveTrade, TradeHistory, RiskState, TelegramMessage

# Global Lock for thread safety to prevent race conditions during DB saves
TRADE_LOCK = threading.Lock()

# --- Risk State Persistence ---
def get_risk_state(mode):
    try:
        record = RiskState.query.filter_by(id=mode).first()
        if record:
            return json.loads(record.data)
    except Exception as e:
        print(f"Error fetching risk state for {mode}: {e}")
    return {'high_pnl': float('-inf'), 'global_sl': float('-inf'), 'active': False}

def save_risk_state(mode, state):
    try:
        record = RiskState.query.filter_by(id=mode).first()
        if not record:
            record = RiskState(id=mode, data=json.dumps(state))
            db.session.add(record)
        else:
            record.data = json.dumps(state)
        db.session.commit()
    except Exception as e:
        print(f"Risk State Save Error: {e}")
        db.session.rollback()

# --- Active Trades Persistence ---
def load_trades():
    """
    Loads all currently active trades from the database.
    UPDATED: Forces a session commit to ensure we see the latest writes.
    """
    try:
        # [CRITICAL FIX] Force refresh to avoid stale reads within the same request
        # This line is REQUIRED for Shadow mode to work correctly.
        db.session.commit() 
        
        return [json.loads(r.data) for r in ActiveTrade.query.all()]
    except Exception as e:
        print(f"Load Trades Error: {e}")
        return []

def save_trades(trades):
    """
    Overwrites the ActiveTrade table with the provided list of trades.
    """
    try:
        db.session.query(ActiveTrade).delete()
        for t in trades: 
            db.session.add(ActiveTrade(data=json.dumps(t)))
        db.session.commit()
    except Exception as e:
        print(f"Save Trades Error: {e}")
        db.session.rollback()

# --- Trade History Persistence ---
def load_history():
    try:
        return [json.loads(r.data) for r in TradeHistory.query.order_by(TradeHistory.id.desc()).all()]
    except Exception as e:
        print(f"Load History Error: {e}")
        return []

def delete_trade(trade_id):
    from managers.telegram_manager import bot as telegram_bot
    with TRADE_LOCK:
        try:
            telegram_bot.delete_trade_messages(trade_id)
            TradeHistory.query.filter_by(id=int(trade_id)).delete()
            db.session.commit()
            return True
        except Exception as e:
            print(f"Delete Trade Error: {e}")
            db.session.rollback()
            return False

def save_to_history_db(trade_data):
    try:
        db.session.merge(TradeHistory(id=trade_data['id'], data=json.dumps(trade_data)))
        db.session.commit()
    except Exception as e:
        print(f"Save History DB Error: {e}")
        db.session.rollback()
