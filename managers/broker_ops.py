from managers.common import log_event, get_time_str
from managers.persistence import save_to_history_db
import smart_trader
import time

def place_order(alice, symbol, transaction_type, quantity, order_type="MARKET", product="MIS", price=0.0, trigger_price=0.0, exchange=None, tag="RD_ALGO"):
    """
    Places an order using AliceBlue SDK.
    Requires fetching the specific Instrument object first.
    """
    try:
        # 1. Fetch Instrument Object (Required for AliceBlue)
        inst = smart_trader.get_alice_instrument(alice, symbol)
        if not inst:
            raise Exception(f"Instrument not found for symbol: {symbol}")

        # 2. Map Parameters to AliceBlue Enums
        # Transaction Type
        t_type = alice.TransactionType.Buy if transaction_type == "BUY" else alice.TransactionType.Sell
        
        # Product Type
        p_type = alice.ProductType.Intraday # Default MIS
        if product in ["NRML", "CNC"]:
            p_type = alice.ProductType.Delivery
        
        # Order Type
        o_type = alice.OrderType.Market
        if order_type == "LIMIT": 
            o_type = alice.OrderType.Limit
        elif order_type == "SL": 
            o_type = alice.OrderType.StopLossLimit
        elif order_type == "SL-M": 
            o_type = alice.OrderType.StopLossMarket

        # 3. Place Order
        # Note: Prices must be floats. Quantity must be int.
        res = alice.place_order(
            transaction_type=t_type,
            instrument=inst,
            quantity=int(quantity),
            order_type=o_type,
            product_type=p_type,
            price=float(price),
            trigger_price=float(trigger_price),
            stop_loss=None,
            square_off=None,
            trailing_sl=None,
            is_amo=False,
            order_tag=tag
        )

        # 4. Handle Response
        # Success response example: {'stat': 'Ok', 'NessjID': '123456'}
        if res and isinstance(res, dict) and res.get('stat') == 'Ok':
            return res.get('NessjID')
        else:
            err_msg = res.get('emsg', 'Unknown Error') if res else "No Response"
            raise Exception(f"Broker Error: {err_msg}")

    except Exception as e:
        print(f"❌ Order Placement Failed: {e}")
        raise e

def modify_order(alice, order_id, quantity=None, price=0.0, trigger_price=0.0, order_type="SL-M"):
    """
    Modifies an order. 
    AliceBlue requires Instrument, TransactionType, and ProductType to modify.
    We must fetch these from the order history if we only have the order_id.
    """
    try:
        if not order_id: return False

        # 1. Fetch Order Context (History)
        # We need to know what we are modifying (Buy/Sell? Instrument?)
        history = alice.get_order_history(order_id)
        if not history:
            raise Exception("Order History not found, cannot modify.")
        
        # Get the latest state (usually the last item or the first depending on API, assuming standard list)
        # Inspecting typical structure: List of dicts. We take the one that defines the order.
        curr_order = history[0] if isinstance(history, list) and len(history) > 0 else history
        
        # Extract Context
        exch = curr_order.get('Exchange')
        tr_sym = curr_order.get('Trsym')
        tr_type_str = curr_order.get('Trantype') # 'B' or 'S'
        prod_str = curr_order.get('PrdType') # 'I' or 'D' (Intraday/Delivery)
        
        # Reconstruct Objects
        inst = alice.get_instrument_by_symbol(exch, tr_sym)
        if not inst: raise Exception(f"Instrument reconstruction failed for {tr_sym}")
        
        # Map Strings back to Enums
        t_type = alice.TransactionType.Buy if tr_type_str in ['B', 'BUY'] else alice.TransactionType.Sell
        
        p_type = alice.ProductType.Intraday
        if prod_str in ['D', 'CNC', 'NRML', 'DELIVERY']:
            p_type = alice.ProductType.Delivery

        # Determine Order Type
        # If trigger price is > 0 and price > 0 -> SL Limit
        # If trigger price > 0 and price = 0 -> SL Market (Market doesn't take price)
        o_type = alice.OrderType.StopLossMarket
        if order_type == "LIMIT": o_type = alice.OrderType.Limit
        elif order_type == "SL": o_type = alice.OrderType.StopLossLimit
        
        # Use existing quantity if not provided
        qty_to_use = int(quantity) if quantity else int(curr_order.get('Qty', 0))

        # 2. Call Modify
        res = alice.modify_order(
            transaction_type=t_type,
            instrument=inst,
            product_type=p_type,
            order_id=str(order_id),
            order_type=o_type,
            quantity=qty_to_use,
            price=float(price),
            trigger_price=float(trigger_price)
        )
        
        if res and isinstance(res, dict) and res.get('stat') == 'Ok':
            return True
        else:
            print(f"Modify Error Response: {res}")
            return False

    except Exception as e:
        print(f"❌ Order Mod Failed: {e}")
        raise e

def cancel_order(alice, order_id):
    """
    Cancels an order using AliceBlue SDK.
    """
    try:
        if not order_id: return
        alice.cancel_order(order_id)
        return True
    except Exception as e:
        print(f"❌ Cancel Failed: {e}")
        return False

def manage_broker_sl(alice, trade, qty_to_remove=0, cancel_completely=False):
    """
    Adjusts or Cancels the Broker-side Stop Loss order.
    """
    sl_id = trade.get('sl_order_id')
    if not sl_id or trade.get('mode') != 'LIVE': 
        return

    try:
        if cancel_completely or (qty_to_remove >= trade['quantity']):
            # Cancel the SL Order
            if cancel_order(alice, sl_id):
                log_event(trade, f"Broker SL Cancelled ({sl_id})")
                trade['sl_order_id'] = None 
        
        elif qty_to_remove > 0:
            # Modify the SL Order Quantity
            current_qty = int(trade['quantity'])
            new_qty = current_qty - int(qty_to_remove)
            
            if new_qty > 0:
                # We assume SL-M for modifications usually, but preserving price 0.0 implies Market
                # If the original was SL-Limit, we might lose that info here unless we store it.
                # Defaulting to SL-M for safety in reducing positions.
                if modify_order(alice, sl_id, quantity=new_qty, price=0.0, trigger_price=float(trade['sl']), order_type="SL-M"):
                    log_event(trade, f"Broker SL Modified to Qty: {new_qty}")
                else:
                    log_event(trade, "Failed to Modify Broker SL")
            else:
                cancel_order(alice, sl_id)
                trade['sl_order_id'] = None
                
    except Exception as e:
        log_event(trade, f"Broker SL Error: {e}")

def panic_exit_all(alice):
    """
    Critical function to:
    1. Cancel all Pending Orders
    2. Square off all Open Positions (Netwise)
    """
    try:
        print("🚨 INITIATING PANIC EXIT (AliceBlue)...")
        
        # 1. Cancel All Open Orders
        orders = alice.get_order_book()
        if orders and isinstance(orders, list):
            for o in orders:
                if o.get('Status') in ['OPEN', 'TRIGGER PENDING', 'modify pending']:
                    oid = o.get('NessjID')
                    if oid:
                        print(f"🚫 Panic: Cancelling Order {oid}")
                        alice.cancel_order(oid)
        
        # 2. Square Off Positions
        # We fetch Daywise/Netwise positions
        positions = alice.get_daywise_positions()
        
        if positions and isinstance(positions, list):
            for p in positions:
                # Calculate Net Quantity
                # AliceBlue keys: 'Bqty', 'Sqty', or 'Netqty' directly
                net_qty = int(p.get('Netqty', 0))
                
                if net_qty != 0:
                    symbol = p.get('Trsym')
                    exch = p.get('Exchange')
                    token = p.get('Token')
                    
                    # Determine Exit Transaction Type
                    trans_type = "SELL" if net_qty > 0 else "BUY"
                    exit_qty = abs(net_qty)
                    
                    print(f"🏃 Panic: Squaring off {symbol} ({net_qty}) via {trans_type}")
                    
                    try:
                        # Reconstruct Instrument for placement
                        inst = alice.get_instrument_by_symbol(exch, symbol)
                        if inst:
                             place_order(
                                alice, 
                                symbol=f"{exch}:{symbol}", # Format expected by our wrapper
                                transaction_type=trans_type,
                                quantity=exit_qty,
                                order_type="MARKET",
                                product="MIS", # Assuming Intraday for panic
                                tag="PANIC_EXIT"
                            )
                    except Exception as e:
                        print(f"❌ Panic Error for {symbol}: {e}")
                        
        return True
    except Exception as e:
        print(f"❌ Panic Execution Failed: {e}")
        return False

def move_to_history(trade, final_status, exit_price):
    """
    Moves a trade to history by updating its status/PnL and saving to DB.
    """
    real_pnl = 0
    was_active = trade['status'] != 'PENDING'
    
    # Calculate PnL
    if was_active:
        real_pnl = round((exit_price - trade['entry_price']) * trade['quantity'], 2)
    
    trade['pnl'] = real_pnl if was_active else 0
    trade['status'] = final_status
    trade['exit_price'] = exit_price
    trade['exit_time'] = get_time_str()
    trade['exit_type'] = final_status
    
    # Log if not already logged
    # Check if the last log is a Close log to avoid duplicates
    logs_str = str(trade.get('logs', []))
    if "Closed:" not in logs_str:
         log_event(trade, f"Closed: {final_status} @ {exit_price} | P/L ₹ {real_pnl:.2f}")
    
    # Save to History DB via Persistence layer
    save_to_history_db(trade)
