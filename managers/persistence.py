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
    Loads active trades ONLY for the specified user via DB filtering.
    """
    try:
        # [DEBUG] Reset session to force fresh read
        db.session.remove() 
        
        # Efficient DB-side filtering
        rows = ActiveTrade.query.filter_by(user_id=user_id).all()
        user_trades = []
        
        for r in rows:
            try:
                t_data = json.loads(r.data)
                user_trades.append(t_data)
            except:
                continue
        
        return user_trades
    except Exception as e:
        print(f"[DEBUG] Load Trades Error (User {user_id}): {e}")
        return []

def save_trades(trades, user_id):
    """
    Saves trades ONLY for the current user safely.
    Deletes existing rows for this user ID and inserts the new list.
    Does NOT affect other users' data.
    """
    with TRADE_LOCK:
        try:
            # 1. Delete ONLY this user's active trades
            ActiveTrade.query.filter_by(user_id=user_id).delete()
            
            # 2. Insert the updated list
            for t in trades:
                t['user_id'] = user_id # Ensure ID is stamped in JSON too
                
                # Insert with user_id column populated
                new_row = ActiveTrade(user_id=user_id, data=json.dumps(t))
                db.session.add(new_row)
            
            db.session.commit()
        except Exception as e:
            print(f"[DEBUG] Save Trades Error (User {user_id}): {e}")
            db.session.rollback()

# --- Trade History Persistence (OPTIMIZED) ---
def load_history(user_id):
    """
    Loads trade history efficiently using DB Index.
    Filters by user_id at the database level to prevent memory overload.
    """
    try:
        db.session.commit() # Ensure fresh data
        
        # [FIX] Filter by user_id column directly in DB query
        # Added limit(200) to prevent memory overflow on huge histories
        records = TradeHistory.query.filter_by(user_id=user_id)\
                                      .order_by(TradeHistory.id.desc())\
                                      .limit(200).all()
        
        return [json.loads(r.data) for r in records]
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
                # Security Check: Verify ownership via Column OR JSON (Backwards compatibility)
                is_owner = False
                if row.user_id is not None:
                    is_owner = (str(row.user_id) == str(user_id))
                else:
                    # Fallback for old records without column data
                    data = json.loads(row.data)
                    is_owner = (str(data.get('user_id')) == str(user_id))

                if is_owner:
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
    Saves a closed trade to history, ensuring user_id is populated in Column AND JSON.
    """
    try:
        trade_data['user_id'] = user_id
        
        # [FIX] Populate user_id column for indexed searching
        record = TradeHistory(
            id=trade_data['id'], 
            user_id=user_id, 
            data=json.dumps(trade_data)
        )
        db.session.merge(record)
        db.session.commit()
    except Exception as e:
        print(f"Save History DB Error: {e}")
        db.session.rollback()
