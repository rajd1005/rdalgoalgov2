from managers.common import log_event, get_time_str
from managers.persistence import TRADE_LOCK, load_trades, save_trades, save_to_history_db
import smart_trader

def place_order(kite, symbol, transaction_type, quantity, order_type="MARKET", product="MIS", price=0, trigger_price=0, exchange=None, tag="RD_ALGO"):
    """
    Wrapper for placing orders with automatic exchange detection if missing.
    """
    try:
        # Determine exchange if not provided
        if not exchange:
            exchange = smart_trader.get_exchange_name(symbol)
            
        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            product=product,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            tag=tag
        )
        return order_id
    except Exception as e:
        print(f"❌ Order Placement Failed: {e}")
        raise e

def modify_order(kite, order_id, quantity=None, price=None, trigger_price=None):
    try:
        kite.modify_order(
            variety=kite.VARIETY_REGULAR,
            order_id=order_id,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price
        )
        return True
    except Exception as e:
        print(f"❌ Order Modification Failed: {e}")
        raise e

def move_to_history(trade, final_status, exit_price, user_id=None):
    """
    Finalizes a trade, calculates PnL, logs the closure, and moves it to the history database.
    """
    real_pnl = 0
    was_active = trade['status'] != 'PENDING'
    
    # Respect Pre-Calculated P/L (for Replay/Partial Exits)
    if 'pnl' in trade and trade['pnl'] is not None:
         real_pnl = trade['pnl']
    elif was_active:
        # Standard calculation (Exit - Entry) * Qty
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
        
    trade['pnl'] = real_pnl if was_active else 0
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    trade['exit_type'] = final_status
    
    # Avoid duplicate logging if called multiple times (sanity check)
    if "Closed:" not in str(trade.get('logs', [])):
         log_event(trade, f"Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}")
    
    save_to_history_db(trade, user_id=user_id)

def manage_broker_sl(kite, trade, qty_to_remove=0, cancel_completely=False, user_id=None):
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

def panic_exit_all(kite, user_id=None):
    """
    Emergency Function: Immediately closes all active positions for the specific user.
    """
    with TRADE_LOCK:
        trades = load_trades(user_id=user_id)
        if not trades: 
            return True
            
        print(f"🚨 PANIC MODE TRIGGERED (User {user_id}): Closing {len(trades)} positions.")
        
        for t in trades:
            # Handle LIVE trades on the broker side
            if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                # First, cancel the protection SL to avoid double execution
                manage_broker_sl(kite, t, cancel_completely=True, user_id=user_id)
                
                # Then place the exit order
                try: 
                    place_order(
                        kite,
                        symbol=t['symbol'], 
                        exchange=t['exchange'], 
                        transaction_type=kite.TRANSACTION_TYPE_SELL, 
                        quantity=t['quantity'], 
                        order_type=kite.ORDER_TYPE_MARKET, 
                        product=kite.PRODUCT_MIS,
                        tag="PANIC_EXIT"
                    )
                except Exception as e: 
                    print(f"Panic Broker Fail {t['symbol']}: {e}")
            
            # Move to internal history
            exit_p = t.get('current_ltp', t['entry_price'])
            move_to_history(t, "PANIC_EXIT", exit_p, user_id=user_id)
        
        # Clear active trades list for this user
        save_trades([], user_id=user_id)
        return True
