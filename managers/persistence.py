import json
import threading
from database import db, ActiveTrade, TradeHistory, RiskState, TelegramMessage

# Global Lock for thread safety
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
    INCLUDES DEBUG LOGGING AND SESSION RESET.
    """
    try:
        # [DEBUG] Reset session to force fresh read
        db.session.remove() 
        
        raw_rows = ActiveTrade.query.all()
        trades = [json.loads(r.data) for r in raw_rows]
        
        return trades
    except Exception as e:
        print(f"[DEBUG] Load Trades Error: {e}")
        return []

def save_trades(trades):
    """
    OPTIMIZED: Smart Upsert (Update/Insert) instead of Delete-All.
    Reduces DB locking and overhead.
    """
    try:
        # 1. Get IDs of all current DB records
        existing_records = ActiveTrade.query.all()
        existing_map = {r.id: r for r in existing_records}
        
        # 2. Track IDs present in the new list
        new_ids = set()

        for t in trades:
            t_id = int(t['id'])
            new_ids.add(t_id)
            json_data = json.dumps(t)
            
            if t_id in existing_map:
                # Update existing record
                existing_map[t_id].data = json_data
            else:
                # Insert new record
                new_record = ActiveTrade(id=t_id, data=json_data)
                db.session.add(new_record)
        
        # 3. Delete records that are NOT in the new list (trades that were closed/removed)
        for old_id, record in existing_map.items():
            if old_id not in new_ids:
                db.session.delete(record)
        
        db.session.commit()
    except Exception as e:
        print(f"Save Trades Error: {e}")
        db.session.rollback()

# --- Trade History Persistence ---
def load_history():
    try:
        db.session.commit() # Ensure fresh
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
