from managers.common import log_event
from managers.persistence import TRADE_LOCK, load_trades, save_trades, save_to_history_db

# Helper to move trade to history (Placed here to avoid circular imports in core_logic)
def move_to_history(trade, final_status, exit_price):
    real_pnl = 0
    was_active = trade['status'] != 'PENDING'
    if was_active:
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    trade['pnl'] = real_pnl if was_active else 0
    trade['status'] = final_status; trade['exit_price'] = exit_price
    trade['exit_time'] = str(datetime.now()); trade['exit_type'] = final_status
    
    if "Closed:" not in str(trade['logs']):
         log_event(trade, f"Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}")
    
    save_to_history_db(trade)

def manage_broker_sl(kite, trade, qty_to_remove=0, cancel_completely=False):
    sl_id = trade.get('sl_order_id')
    if not sl_id or trade['mode'] != 'LIVE': return

    try:
        if cancel_completely or qty_to_remove >= trade['quantity']:
            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=sl_id)
            log_event(trade, f"Broker SL Cancelled (ID: {sl_id})")
            trade['sl_order_id'] = None 
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
    with TRADE_LOCK:
        trades = load_trades()
        if not trades: return True
        print(f"🚨 PANIC MODE TRIGGERED: Closing {len(trades)} positions.")
        for t in trades:
            if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                manage_broker_sl(kite, t, cancel_completely=True)
                try: kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                except Exception as e: print(f"Panic Broker Fail {t['symbol']}: {e}")
            move_to_history(t, "PANIC_EXIT", t.get('current_ltp', t['entry_price']))
        save_trades([])
        return True
