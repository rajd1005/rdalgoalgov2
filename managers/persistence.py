import json
import threading
from database import db, ActiveTrade, TradeHistory, RiskState

# Global Lock for thread safety to prevent race conditions during DB saves
# This lock should be acquired by other managers before performing read-modify-write operations on trades.
TRADE_LOCK = threading.Lock()

# --- Risk State Persistence ---
def get_risk_state(mode):
    """
    Retrieves the persistent risk state (Profit Locking, High PnL) for a specific mode.
    """
    try:
        record = RiskState.query.filter_by(id=mode).first()
        if record:
            return json.loads(record.data)
    except Exception as e:
        print(f"Error fetching risk state for {mode}: {e}")
    # Default state if not found
    return {'high_pnl': float('-inf'), 'global_sl': float('-inf'), 'active': False}

def save_risk_state(mode, state):
    """
    Saves or updates the risk state for a specific mode.
    """
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
    """
    try:
        return [json.loads(r.data) for r in ActiveTrade.query.all()]
    except Exception as e:
        print(f"Load Trades Error: {e}")
        return []

def save_trades(trades):
    """
    Overwrites the ActiveTrade table with the provided list of trades.
    Note: The caller is responsible for acquiring TRADE_LOCK if necessary.
    """
    try:
        # Clear existing active trades and replace with new list
        db.session.query(ActiveTrade).delete()
        for t in trades: 
            db.session.add(ActiveTrade(data=json.dumps(t)))
        db.session.commit()
    except Exception as e:
        print(f"Save Trades Error: {e}")
        db.session.rollback()

# --- Trade History Persistence ---
def load_history():
    """
    Loads closed trade history, ordered by ID (timestamp) descending.
    """
    try:
        return [json.loads(r.data) for r in TradeHistory.query.order_by(TradeHistory.id.desc()).all()]
    except Exception as e:
        print(f"Load History Error: {e}")
        return []

def delete_trade(trade_id):
    """
    Deletes a specific trade from history by ID. Thread-safe.
    """
    with TRADE_LOCK:
        try:
            TradeHistory.query.filter_by(id=int(trade_id)).delete()
            db.session.commit()
            return True
        except Exception as e:
            print(f"Delete Trade Error: {e}")
            db.session.rollback()
            return False

def save_to_history_db(trade_data):
    """
    Saves or updates a trade record in the TradeHistory table.
    """
    try:
        # Use merge to handle both insert and update (e.g., updating 'made_high')
        db.session.merge(TradeHistory(id=trade_data['id'], data=json.dumps(trade_data)))
        db.session.commit()
    except Exception as e:
        print(f"Save History DB Error: {e}")
        db.session.rollback()
