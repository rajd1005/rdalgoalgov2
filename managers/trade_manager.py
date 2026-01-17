import logging
import time
from datetime import datetime
from managers import common, persistence, broker_ops
import smart_trader

def create_trade_direct(kite, mode, symbol, qty, sl_points, targets, order_type, limit_price, target_controls, trailing_sl, sl_to_entry, exit_multiplier):
    """
    Creates a new trade (LIVE or PAPER) with all protection parameters.
    This function is called directly from the Dashboard 'Add Trade' form.
    """
    try:
        # 1. Validate Input
        if qty <= 0:
            return {"status": "error", "message": "Quantity must be > 0"}
        
        # 2. Get Current Market Price (LTP) if not provided (for SL calculation)
        ltp = smart_trader.get_ltp(kite, symbol)
        if ltp == 0:
            return {"status": "error", "message": "Could not fetch LTP for Symbol"}

        entry_price = ltp
        if order_type == 'LIMIT' and limit_price > 0:
            entry_price = limit_price

        # 3. Calculate Stop Loss Price
        # If sl_points is provided, use it. Otherwise, assume direct SL price (logic can be adjusted)
        # Here we assume sl_points is the distance from entry.
        # Determine direction based on Targets (if provided) or standard logic?
        # For simplicity in this terminal, we assume LONG trades for now, or infer from SL.
        
        # NOTE: The dashboard logic usually implies LONG if targets > entry.
        # But 'sl_points' is a distance. Let's assume LONG for simple placement, 
        # or we could add a 'direction' field in the form. 
        # For now, let's assume LONG.
        direction = "LONG"
        sl_price = entry_price - sl_points
        
        # 4. LIVE MODE EXECUTION
        sl_order_id = None
        
        if mode == "LIVE":
            # Place the Main Entry Order
            try:
                order_id = broker_ops.place_order(
                    kite, 
                    symbol=symbol, 
                    transaction_type=kite.TRANSACTION_TYPE_BUY, 
                    quantity=qty, 
                    order_type=order_type, 
                    price=limit_price if order_type == 'LIMIT' else 0,
                    tag="RD_ALGO_ENTRY"
                )
                if not order_id:
                     return {"status": "error", "message": "Broker Rejected Entry Order"}
                     
                # Place SL-M Order (Broker Side Protection)
                # We place a separate SL-M order for safety
                sl_order_id = broker_ops.place_order(
                    kite,
                    symbol=symbol,
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=qty,
                    order_type=kite.ORDER_TYPE_SLM,
                    trigger_price=sl_price,
                    tag="RD_ALGO_SL"
                )
                
            except Exception as e:
                return {"status": "error", "message": f"Broker Error: {str(e)}"}

        # 5. Construct Trade Record
        # We save this to our internal DB for tracking (Risk Engine)
        trade_record = {
            "id": int(time.time()),
            "entry_time": common.get_time_str(),
            "symbol": symbol,
            "mode": mode,
            "status": "OPEN" if mode == "PAPER" else "MONITORING", # LIVE trades start as MONITORING
            "order_type": order_type,
            "quantity": qty,
            "entry_price": entry_price,
            "sl": sl_price,
            "targets": targets, # List of target prices
            "target_controls": target_controls, # List of dicts [{'enabled': T, 'lots': 0, 'trail': F}, ...]
            "trailing_sl": trailing_sl,
            "sl_to_entry": sl_to_entry,
            "exit_multiplier": exit_multiplier,
            "sl_order_id": sl_order_id,
            "targets_hit_indices": [],
            "highest_ltp": entry_price,
            "logs": [f"Trade Added in {mode} Mode. Entry: {entry_price}, SL: {sl_price}"]
        }

        # 6. Save to Persistence
        trades = persistence.load_trades()
        trades.append(trade_record)
        persistence.save_trades(trades)
        
        # 7. Notify Telegram (Async handled by risk engine loop or here)
        from managers.telegram_manager import bot
        bot.notify_trade_event(trade_record, "NEW_TRADE")

        return {"status": "success", "message": "Trade Created Successfully"}

    except Exception as e:
        logging.error(f"Create Trade Error: {e}")
        return {"status": "error", "message": str(e)}

def update_trade_protection(kite, trade_id, new_sl, new_targets, trailing_sl, entry_price, target_controls, sl_to_entry, exit_multiplier):
    """
    Updates the protection parameters (SL, Targets, Trailing) for an existing trade.
    """
    with persistence.TRADE_LOCK:
        trades = persistence.load_trades()
        trade = next((t for t in trades if str(t['id']) == str(trade_id)), None)
        
        if not trade:
            return False

        # Update Logic
        trade['sl'] = float(new_sl)
        trade['targets'] = [float(t) for t in new_targets]
        trade['trailing_sl'] = float(trailing_sl)
        if entry_price:
             trade['entry_price'] = float(entry_price)
        
        if target_controls:
            trade['target_controls'] = target_controls
            
        trade['sl_to_entry'] = int(sl_to_entry)
        trade['exit_multiplier'] = int(exit_multiplier)
        
        trade['logs'].append(f"[{common.get_time_str()}] ✏️ Manual Update: SL={new_sl}, Targets={new_targets}")

        # If LIVE, update the broker SL-M order if it exists
        if trade['mode'] == 'LIVE' and trade.get('sl_order_id'):
            try:
                broker_ops.modify_order(
                    kite, 
                    order_id=trade['sl_order_id'], 
                    trigger_price=float(new_sl)
                )
                trade['logs'].append(f"[{common.get_time_str()}] ✅ Broker SL Modified to {new_sl}")
            except Exception as e:
                trade['logs'].append(f"[{common.get_time_str()}] ⚠️ Broker SL Modify Failed: {e}")

        persistence.save_trades(trades)
        
        from managers.telegram_manager import bot
        bot.notify_trade_event(trade, "UPDATE", "Protection Parameters Updated via Dashboard")
        
        return True

def manage_trade_position(kite, trade_id, action, lot_size, lots_to_act):
    """
    Handles Partial Exit or Full Exit manual commands.
    """
    with persistence.TRADE_LOCK:
        trades = persistence.load_trades()
        trade = next((t for t in trades if str(t['id']) == str(trade_id)), None)
        
        if not trade: return False
        
        qty_to_reduce = lots_to_act * lot_size
        current_qty = trade['quantity']
        
        if action == "EXIT":
            # FULL EXIT
            reason = "MANUAL_EXIT"
            exit_price = smart_trader.get_ltp(kite, trade['symbol'])
            
            if trade['mode'] == 'LIVE':
                 broker_ops.place_order(kite, trade['symbol'], kite.TRANSACTION_TYPE_SELL, current_qty, tag="MANUAL_EXIT")
                 # Cancel SL
                 if trade.get('sl_order_id'):
                     try: kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=trade['sl_order_id'])
                     except: pass
            
            # Close internally
            trade['status'] = "CLOSED"
            trade['exit_price'] = exit_price
            trade['logs'].append(f"[{common.get_time_str()}] 🛑 Manual Full Exit @ {exit_price}")
            
            # Move to history logic is handled by risk_engine cleanup or we do it here
            # For simplicity, risk engine picks up CLOSED trades and archives them.
            
        elif action == "PARTIAL_EXIT":
            if qty_to_reduce >= current_qty:
                return False # Use full exit instead
                
            if trade['mode'] == 'LIVE':
                 broker_ops.place_order(kite, trade['symbol'], kite.TRANSACTION_TYPE_SELL, qty_to_reduce, tag="PARTIAL_EXIT")
            
            trade['quantity'] -= qty_to_reduce
            trade['logs'].append(f"[{common.get_time_str()}] 📉 Manual Partial Exit: {qty_to_reduce} Qty")
            
        persistence.save_trades(trades)
        return True

def promote_to_live(kite, trade_id):
    """
    Promotes a Paper trade to Live execution (Experimental).
    """
    with persistence.TRADE_LOCK:
        trades = persistence.load_trades()
        trade = next((t for t in trades if str(t['id']) == str(trade_id)), None)
        
        if not trade or trade['mode'] != 'PAPER':
            return False
            
        # 1. Place Broker Order
        try:
            order_id = broker_ops.place_order(
                kite, 
                symbol=trade['symbol'], 
                transaction_type=kite.TRANSACTION_TYPE_BUY, 
                quantity=trade['quantity'], 
                tag="PROMOTE_LIVE"
            )
            
            if order_id:
                trade['mode'] = 'LIVE'
                trade['status'] = 'MONITORING'
                trade['logs'].append(f"[{common.get_time_str()}] 🆙 Promoted to LIVE. Order ID: {order_id}")
                
                # Try placing SL
                try:
                    sl_id = broker_ops.place_order(
                        kite,
                        symbol=trade['symbol'],
                        transaction_type=kite.TRANSACTION_TYPE_SELL,
                        quantity=trade['quantity'],
                        order_type=kite.ORDER_TYPE_SLM,
                        trigger_price=trade['sl'],
                        tag="RD_ALGO_SL"
                    )
                    trade['sl_order_id'] = sl_id
                except:
                    trade['logs'].append("⚠️ Failed to place Broker SL during promotion")

                persistence.save_trades(trades)
                return True
        except Exception as e:
            print(f"Promotion Failed: {e}")
            return False

def close_trade_manual(kite, trade_id):
    """
    Force closes a trade from the dashboard.
    """
    return manage_trade_position(kite, trade_id, "EXIT", 1, 99999)
