import time
from datetime import datetime
from managers.persistence import save_to_history_db, save_trades, load_trades, TRADE_LOCK
from managers.common import log_event, get_time_str

def manage_broker_sl(kite, trade, quantity_to_exit=0, cancel_completely=False):
    """
    Modifies or Cancels the Broker Stop Loss Order (SL-M).
    """
    if trade.get('mode') != 'LIVE':
        return

    order_id = trade.get('sl_order_id')
    if not order_id:
        return

    try:
        # 1. CANCEL COMPLETELY (e.g., Target Hit full exit, or Manual Close)
        if cancel_completely:
            try:
                kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
                log_event(trade, "Broker SL Order Cancelled")
            except Exception as e:
                # Ignore if already cancelled/completed
                log_event(trade, f"Broker SL Cancel Failed (Might be closed): {e}")
            
            trade['sl_order_id'] = None
            return

        # 2. PARTIAL EXIT (Reduce SL Quantity)
        if quantity_to_exit > 0:
            current_qty = trade['quantity']
            new_qty = current_qty - quantity_to_exit
            
            if new_qty > 0:
                try:
                    kite.modify_order(
                        variety=kite.VARIETY_REGULAR, 
                        order_id=order_id, 
                        quantity=new_qty
                    )
                    log_event(trade, f"Broker SL Qty Reduced to {new_qty}")
                except Exception as e:
                    log_event(trade, f"Broker SL Mod Failed: {e}")
            else:
                # If new qty is 0 or less, cancel it
                try:
                    kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
                except: pass
                trade['sl_order_id'] = None

    except Exception as e:
        print(f"Manage Broker SL Error: {e}")

def panic_exit_all(kite):
    """
    Emergency Function: Exits all LIVE positions and cancels pending orders.
    """
    with TRADE_LOCK:
        trades = load_trades()
        active_list = []
        
        for t in trades:
            if t['mode'] == 'LIVE':
                # 1. Cancel SL Order
                if t.get('sl_order_id'):
                    try:
                        kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_order_id'])
                    except: pass
                
                # 2. Exit Position (Market Sell)
                if t['status'] != 'PENDING':
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
                        print(f"Panic Exit Fail {t['symbol']}: {e}")
                
                # Move to History immediately to clear Dashboard
                t['exit_time'] = get_time_str()
                t['status'] = "PANIC_EXIT"
                t['exit_price'] = t.get('current_ltp', 0)
                t['pnl'] = (t['exit_price'] - t['entry_price']) * t['quantity']
                
                save_to_history_db(t)
            else:
                # Keep PAPER trades or handle them if needed (currently keeping them)
                active_list.append(t)
        
        save_trades(active_list)

def move_to_history(trade, exit_reason, exit_price):
    """
    Finalizes a trade: calculates PnL, sets timestamps, and moves it to the History DB.
    CRITICAL: Preserves Telegram IDs for 'Delete Thread' functionality.
    """
    trade['status'] = exit_reason
    trade['exit_time'] = get_time_str()
    trade['exit_price'] = float(exit_price)
    
    # Calculate Final PnL
    # For PENDING orders that were cancelled (NOT_ACTIVE), PnL is 0
    if exit_reason == "NOT_ACTIVE":
        trade['pnl'] = 0.0
    else:
        trade['pnl'] = (trade['exit_price'] - trade['entry_price']) * trade['quantity']

    log_event(trade, f"Trade Closed: {exit_reason} @ {exit_price}")
    
    # --- PREPARE DATA FOR HISTORY ---
    # We explicitly ensure Telegram IDs are carried over
    history_entry = {
        "id": trade['id'],
        "symbol": trade['symbol'],
        "exchange": trade['exchange'],
        "mode": trade['mode'],
        "entry_time": trade['entry_time'],
        "exit_time": trade['exit_time'],
        "order_type": trade['order_type'],
        "status": trade['status'],
        "entry_price": trade['entry_price'],
        "exit_price": trade['exit_price'],
        "quantity": trade['quantity'],
        "pnl": trade['pnl'],
        "sl": trade['sl'],
        "targets": trade['targets'],
        "made_high": trade.get('made_high', 0),
        "logs": trade.get('logs', []),
        
        # --- CRITICAL: PRESERVE TELEGRAM DATA ---
        "telegram_msg_id": trade.get('telegram_msg_id'),
        "telegram_update_ids": trade.get('telegram_update_ids', [])
    }
    
    # Save to History DB
    save_to_history_db(history_entry)
