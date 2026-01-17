from managers.common import log_event, get_time_str
from managers.persistence import TRADE_LOCK, load_trades, save_trades, save_to_history_db

def move_to_history(trade, final_status, exit_price):
    """
    Finalizes a trade, calculates PnL, logs the closure, and moves it to the history database.
    """
    real_pnl = 0
    was_active = trade['status'] != 'PENDING'
    
    # --- FIX START: Respect Pre-Calculated P/L (for Replay/Partial Exits) ---
    # If the trade already has a calculated 'pnl' (e.g. from Replay Engine), use it.
    if 'pnl' in trade and trade['pnl'] is not None:
         real_pnl = trade['pnl']
    # --- FIX END ---
    elif was_active:
        # Standard calculation (Exit - Entry) * Qty
        # Used for standard Live/Paper trades that don't track cumulative P/L yet
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
        
    trade['pnl'] = real_pnl if was_active else 0
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    trade['exit_type'] = final_status
    
    # Avoid duplicate logging if called multiple times (sanity check)
    if "Closed:" not in str(trade.get('logs', [])):
         log_event(trade, f"Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}")
    
    save_to_history_db(trade)

def manage_broker_sl(kite, trade, qty_to_remove=0, cancel_completely=False):
    """
    Manages the physical Stop Loss order on the Broker (Zerodha) side.
    Can cancel the SL completely or modify the quantity (for partial exits).
    """
    sl_id = trade.get('sl_order_id')
    # Only proceed if there is an SL Order ID and the mode is LIVE
    if not sl_id or trade['mode'] != 'LIVE': 
        return

    try:
        # Scenario 1: Cancel SL completely (Full Exit or Panic)
        if cancel_completely or qty_to_remove >= trade['quantity']:
            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=sl_id)
            log_event(trade, f"Broker SL Cancelled (ID: {sl_id})")
            trade['sl_order_id'] = None 
            
        # Scenario 2: Reduce SL Quantity (Partial Exit)
        elif qty_to_remove > 0:
            new_qty = trade['quantity'] - qty_to_remove
            if new_qty > 0:
                kite.modify_order(
                    variety=kite.VARIETY_REGULAR,
                    order_id=sl_id,
                    quantity=new_qty
                )
                log_event(trade, f"Broker SL Qty Modified to {new_qty}")
                
    except Exception as e:
        log_event(trade, f"⚠️ Broker SL Update Failed: {e}")

def panic_exit_all(kite):
    """
    Emergency Function: Immediately closes all active positions.
    1. Cancels pending Broker SL orders.
    2. Places Market Sell orders for all open quantities.
    3. Moves all trades to history with status 'PANIC_EXIT'.
    """
    with TRADE_LOCK:
        trades = load_trades()
        if not trades: 
            return True
            
        print(f"🚨 PANIC MODE TRIGGERED: Closing {len(trades)} positions.")
        
        for t in trades:
            # Handle LIVE trades on the broker side
            if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                # First, cancel the protection SL to avoid double execution
                manage_broker_sl(kite, t, cancel_completely=True)
                
                # Then place the exit order
                try: 
                    kite.place_order(
                        variety=kite.VARIETY_REGULAR, 
                        tradingsymbol=t['symbol'], 
                        exchange=t['exchange'], 
                        transaction_type=kite.TRANSACTION_TYPE_SELL, 
                        quantity=t['quantity'], 
                        order_type=kite.ORDER_TYPE_MARKET, 
                        product=kite.PRODUCT_MIS
                    )
                except Exception as e: 
                    print(f"Panic Broker Fail {t['symbol']}: {e}")
            
            # Move to internal history
            # Use current_ltp if available, else fallback to entry (neutral exit logic for panic if data missing)
            exit_p = t.get('current_ltp', t['entry_price'])
            move_to_history(t, "PANIC_EXIT", exit_p)
        
        # Clear active trades list
        save_trades([])
        return True
