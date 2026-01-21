import json
import threading
from database import db, ActiveTrade, TradeHistory, RiskState, TelegramMessage

# Global Lock for thread safety
TRADE_LOCK = threading.Lock()

# --- Risk State Persistence (Multi-User) ---
def get_risk_state(mode, user_id):
    """
    Fetches risk state using a composite key (user_id_mode)
    to separate data between users.
    """
    db_key = f"{user_id}_{mode}"
    try:
        record = RiskState.query.filter_by(id=db_key).first()
        if record:
            return json.loads(record.data)
    except Exception as e:
        print(f"Error fetching risk state for {mode} (User {user_id}): {e}")
    return {'high_pnl': float('-inf'), 'global_sl': float('-inf'), 'active': False}

def save_risk_state(mode, state, user_id):
    """
    Saves risk state with user isolation.
    """
    db_key = f"{user_id}_{mode}"
    try:
        record = RiskState.query.filter_by(id=db_key).first()
        if not record:
            record = RiskState(id=db_key, data=json.dumps(state))
            db.session.add(record)
        else:
            record.data = json.dumps(state)
        db.session.commit()
    except Exception as e:
        print(f"Risk State Save Error (User {user_id}): {e}")
        db.session.rollback()

# --- Active Trades Persistence (Multi-User) ---
def load_trades(user_id):
    """
    Loads active trades ONLY for the specified user.
    """
    try:
        # [DEBUG] Reset session to force fresh read
        db.session.remove() 
        
        raw_rows = ActiveTrade.query.all()
        user_trades = []
        
        for r in raw_rows:
            try:
                t_data = json.loads(r.data)
                # Filter: Only return trades belonging to this user
                if str(t_data.get('user_id')) == str(user_id):
                    user_trades.append(t_data)
            except:
                continue
        
        return user_trades
    except Exception as e:
        print(f"[DEBUG] Load Trades Error (User {user_id}): {e}")
        return []

def save_trades(trades, user_id):
    """
    Overwrites the ActiveTrade table intelligently.
    1. Reads ALL trades.
    2. Keeps trades belonging to OTHER users.
    3. Merges with NEW trades for CURRENT user.
    4. Saves everything back.
    
    This ensures User A doesn't wipe User B's trades.
    """
    with TRADE_LOCK:
        try:
            # 1. Fetch current DB state
            all_rows = ActiveTrade.query.all()
            preserved_trades = []
            
            # 2. Preserve other users' data
            for r in all_rows:
                try:
                    t_data = json.loads(r.data)
                    if str(t_data.get('user_id')) != str(user_id):
                        preserved_trades.append(t_data)
                except:
                    continue 
            
            # 3. Prepare current user's trades (Ensure ID is stamped)
            for t in trades:
                t['user_id'] = user_id
                
            # 4. Combine
            final_list = preserved_trades + trades
            
            # 5. Atomic Wipe & Replace
            db.session.query(ActiveTrade).delete()
            for t in final_list: 
                db.session.add(ActiveTrade(data=json.dumps(t)))
            
            db.session.commit()
        except Exception as e:
            print(f"[DEBUG] Save Trades Error (User {user_id}): {e}")
            db.session.rollback()

# --- Trade History Persistence (Multi-User) ---
def load_history(user_id):
    """
    Loads trade history filtered by user_id.
    """
    try:
        db.session.commit() # Ensure fresh
        
        # Load all history (TradeHistory ID is unique per trade, but we need to check contents)
        all_records = TradeHistory.query.order_by(TradeHistory.id.desc()).all()
        user_history = []
        
        for r in all_records:
            try:
                data = json.loads(r.data)
                if str(data.get('user_id')) == str(user_id):
                    user_history.append(data)
            except:
                pass
                
        return user_history
    except Exception as e:
        print(f"Load History Error (User {user_id}): {e}")
        return []

def delete_trade(trade_id, user_id):
    """
    Deletes a closed trade if it belongs to the user.
    """
    from managers.telegram_manager import bot as telegram_bot
    with TRADE_LOCK:
        try:
            row = TradeHistory.query.filter_by(id=int(trade_id)).first()
            if row:
                data = json.loads(row.data)
                # Security Check: Does trade belong to user?
                if str(data.get('user_id')) == str(user_id):
                    telegram_bot.delete_trade_messages(trade_id)
                    db.session.delete(row)
                    db.session.commit()
                    return True
                else:
                    print(f"⚠️ Unauthorized delete attempt: User {user_id} tried to delete Trade {trade_id}")
            return False
        except Exception as e:
            print(f"Delete Trade Error: {e}")
            db.session.rollback()
            return False

def save_to_history_db(trade_data, user_id):
    """
    Saves a closed trade to history, ensuring user_id is attached.
    """
    try:
        # Stamp ownership
        trade_data['user_id'] = user_id
        
        db.session.merge(TradeHistory(id=trade_data['id'], data=json.dumps(trade_data)))
        db.session.commit()
    except Exception as e:
        print(f"Save History DB Error: {e}")
        db.session.rollback()
