import json
import threading
from database import db, ActiveTrade, TradeHistory, RiskState

# Global Lock for thread safety
TRADE_LOCK = threading.Lock()

def get_risk_state(mode):
    try:
        record = RiskState.query.filter_by(id=mode).first()
        if record:
            return json.loads(record.data)
    except: pass
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

def load_trades():
    try:
        return [json.loads(r.data) for r in ActiveTrade.query.all()]
    except Exception as e:
        print(f"Load Trades Error: {e}")
        return []

def save_trades(trades):
    try:
        db.session.query(ActiveTrade).delete()
        for t in trades: db.session.add(ActiveTrade(data=json.dumps(t)))
        db.session.commit()
    except Exception as e:
        print(f"Save Trades Error: {e}")
        db.session.rollback()

def load_history():
    try:
        return [json.loads(r.data) for r in TradeHistory.query.order_by(TradeHistory.id.desc()).all()]
    except: return []

def delete_trade_from_db(trade_id):
    with TRADE_LOCK:
        try:
            TradeHistory.query.filter_by(id=int(trade_id)).delete()
            db.session.commit()
            return True
        except:
            db.session.rollback()
            return False

def save_to_history_db(trade_data):
    try:
        db.session.merge(TradeHistory(id=trade_data['id'], data=json.dumps(trade_data)))
        db.session.commit()
    except: db.session.rollback()
