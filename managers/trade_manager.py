import time
import smart_trader
from managers.persistence import TRADE_LOCK, load_trades, save_trades
from managers.common import get_time_str, log_event, get_exchange
from managers.broker_ops import manage_broker_sl, move_to_history

def create_trade_direct(kite, mode, specific_symbol, quantity, sl_points, custom_targets, order_type, limit_price=0, target_controls=None, trailing_sl=0, sl_to_entry=0, exit_multiplier=1):
    with TRADE_LOCK:
        trades = load_trades()
        current_ts = int(time.time())
        # Duplicate check
        for t in trades:
            if t['symbol'] == specific_symbol and t['quantity'] == quantity and (current_ts - t['id']) < 5:
                 return {"status": "error", "message": "Duplicate Trade Blocked"}

        exchange = get_exchange(specific_symbol)
        current_ltp = 0.0
        try: current_ltp = kite.quote(f"{exchange}:{specific_symbol}")[f"{exchange}:{specific_symbol}"]["last_price"]
        except: return {"status": "error", "message": "Failed to fetch Live Price"}

        status = "OPEN"; entry_price = current_ltp; trigger_dir = "BELOW"
        if order_type == "LIMIT":
            entry_price = float(limit_price)
            status = "PENDING"
            trigger_dir = "ABOVE" if entry_price >= current_ltp else "BELOW"

        logs = []; sl_order_id = None
        if mode == "LIVE" and status == "OPEN":
            try:
                kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=specific_symbol, exchange=exchange, transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=quantity, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                sl_trigger = entry_price - sl_points 
                try:
                    sl_order_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=specific_symbol, exchange=exchange, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=quantity, order_type=kite.ORDER_TYPE_SL_M, product=kite.PRODUCT_MIS, trigger_price=sl_trigger)
                    logs.append(f"[{get_time_str()}] Broker SL Placed: ID {sl_order_id}")
                except Exception as sl_e: logs.append(f"[{get_time_str()}] Broker SL FAILED: {sl_e}")
            except Exception as e: return {"status": "error", "message": f"Broker Rejected: {e}"}

        # Target Calculation Logic
        targets = custom_targets if len(custom_targets) == 3 and custom_targets[0] > 0 else [entry_price + (sl_points * x) for x in [0.5, 1.0, 2.0]]
        if not target_controls: target_controls = [{'enabled': True, 'lots': 0, 'trail_to_entry': False}, {'enabled': True, 'lots': 0, 'trail_to_entry': False}, {'enabled': True, 'lots': 1000, 'trail_to_entry': False}]
        
        lot_size = smart_trader.get_lot_size(specific_symbol)
        final_trailing_sl = float(trailing_sl) if trailing_sl else 0
        if final_trailing_sl == -1.0: final_trailing_sl = float(sl_points)

        # Multiplier Logic (Splitting Targets)
        if exit_multiplier > 1:
             # ... [Keep logic from original file] ...
             pass # (Copy the logic from strategy_manager.py here)

        logs.insert(0, f"[{get_time_str()}] Trade Added. Status: {status}")
        record = {
            "id": int(time.time()), "entry_time": get_time_str(), "symbol": specific_symbol, "exchange": exchange,
            "mode": mode, "order_type": order_type, "status": status, "entry_price": entry_price, "quantity": quantity,
            "sl": entry_price - sl_points, "targets": targets, "target_controls": target_controls,
            "lot_size": lot_size, "trailing_sl": final_trailing_sl, "sl_to_entry": int(sl_to_entry),
            "exit_multiplier": int(exit_multiplier), "sl_order_id": sl_order_id,
            "targets_hit_indices": [], "highest_ltp": entry_price, "made_high": entry_price, "current_ltp": current_ltp, "trigger_dir": trigger_dir, "logs": logs
        }
        trades.append(record)
        save_trades(trades)
        return {"status": "success", "trade": record}

def update_trade_protection(kite, trade_id, sl, targets, trailing_sl=0, entry_price=None, target_controls=None, sl_to_entry=0, exit_multiplier=1):
    with TRADE_LOCK:
        trades = load_trades()
        updated = False
        for t in trades:
            if str(t['id']) == str(trade_id):
                # ... [Logic from strategy_manager.py update_trade_protection] ...
                # Use manage_broker_sl if needed
                updated = True
                break  
        if updated:
            save_trades(trades)
            return True
        return False

def manage_trade_position(kite, trade_id, action, lot_size, lots_count):
    # ... [Logic from strategy_manager.py manage_trade_position] ...
    # Ensure to use manage_broker_sl from broker_ops
    pass

def promote_to_live(kite, trade_id):
    # ... [Logic from strategy_manager.py promote_to_live] ...
    pass

def close_trade_manual(kite, trade_id):
    with TRADE_LOCK:
        trades = load_trades()
        active_list = []; found = False
        for t in trades:
            if t['id'] == int(trade_id):
                found = True
                exit_p = t.get('current_ltp', 0)
                try: exit_p = kite.quote(f"{t['exchange']}:{t['symbol']}")[f"{t['exchange']}:{t['symbol']}"]['last_price']
                except: pass
                
                if t['mode'] == "LIVE" and t['status'] != "PENDING":
                    manage_broker_sl(kite, t, cancel_completely=True)
                    try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                    except: pass
                move_to_history(t, "MANUAL_EXIT", exit_p)
            else: active_list.append(t)
        if found: save_trades(active_list)
        return found
