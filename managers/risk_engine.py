import json
import smart_trader
import settings
from datetime import datetime
from database import db, TradeHistory
from managers.persistence import TRADE_LOCK, load_trades, save_trades, load_history, get_risk_state, save_risk_state
from managers.common import IST, log_event
from managers.broker_ops import manage_broker_sl, move_to_history
from managers.telegram_manager import bot as telegram_bot

def check_global_exit_conditions(kite, mode, mode_settings):
    """
    Checks and executes global risk rules:
    1. Universal Square-off Time (e.g., 15:25)
    2. Profit Locking (Global PnL Trailing)
    """
    # This function modifies trades, so it must use lock internally
    with TRADE_LOCK:
        trades = load_trades()
        now = datetime.now(IST)
        exit_time_str = mode_settings.get('universal_exit_time', "15:25")
        
        # --- 1. TIME BASED EXIT ---
        try:
            exit_dt = datetime.strptime(exit_time_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            exit_dt = IST.localize(exit_dt.replace(tzinfo=None))
            
            # Trigger within 2 minutes of the time
            if now >= exit_dt and (now - exit_dt).seconds < 120:
                 active_mode = [t for t in trades if t['mode'] == mode]
                 if active_mode:
                     for t in active_mode:
                         if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                            manage_broker_sl(kite, t, cancel_completely=True)
                            try: 
                                kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            except: pass
                         
                         move_to_history(t, "TIME_EXIT", t.get('current_ltp', 0))
                     
                     # Save remaining trades (those not in the current mode)
                     remaining = [t for t in trades if t['mode'] != mode]
                     save_trades(remaining)
                     return
        except Exception as e: 
            print(f"Time Check Error: {e}")

        # --- 2. PROFIT LOCKING (Global Trailing) ---
        pnl_start = float(mode_settings.get('profit_lock', 0))
        if pnl_start > 0:
            current_total_pnl = 0.0
            
            # Calculate PnL consistency (Realized + Unrealized)
            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            history = load_history()
            for t in history:
                if t.get('exit_time') and t['exit_time'].startswith(today_str) and t['mode'] == mode: 
                    current_total_pnl += t.get('pnl', 0)
            
            active = [t for t in trades if t['mode'] == mode]
            for t in active:
                if t['status'] != 'PENDING':
                    current_total_pnl += (t.get('current_ltp', t['entry_price']) - t['entry_price']) * t['quantity']

            state = get_risk_state(mode)
            
            # Activation: Reach minimum threshold
            if not state['active'] and current_total_pnl >= pnl_start:
                state['active'] = True
                state['high_pnl'] = current_total_pnl
                state['global_sl'] = float(mode_settings.get('profit_min', 0))
                save_risk_state(mode, state)
            
            if state['active']:
                # Trail the Global SL up
                if current_total_pnl > state['high_pnl']:
                    diff = current_total_pnl - state['high_pnl']
                    trail_step = float(mode_settings.get('profit_trail', 0))
                    
                    if trail_step > 0 and diff >= trail_step:
                         steps = int(diff / trail_step)
                         state['global_sl'] += (steps * trail_step)
                         state['high_pnl'] = current_total_pnl
                         save_risk_state(mode, state)

                # Breach: Global SL Hit
                if current_total_pnl <= state['global_sl']:
                    active_mode = [t for t in trades if t['mode'] == mode]
                    for t in active_mode:
                         if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                            manage_broker_sl(kite, t, cancel_completely=True)
                            try: 
                                kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            except: pass
                         
                         move_to_history(t, "PROFIT_LOCK", t.get('current_ltp', 0))
                    
                    remaining = [t for t in trades if t['mode'] != mode]
                    save_trades(remaining)
                    
                    # Reset State
                    state['active'] = False
                    save_risk_state(mode, state)

def update_risk_engine(kite):
    """
    The main monitoring loop called by the background thread.
    Updates prices, checks SL/Target hits, and triggers exits.
    """
    # Check Global Conditions first
    current_settings = settings.load_settings()
    check_global_exit_conditions(kite, "PAPER", current_settings['modes']['PAPER'])
    check_global_exit_conditions(kite, "LIVE", current_settings['modes']['LIVE'])

    with TRADE_LOCK:
        active_trades = load_trades()
        
        # Load Today's Closed Trades for Missed Opportunity Tracking
        history = load_history()
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        todays_closed = [t for t in history if t.get('exit_time') and t['exit_time'].startswith(today_str)]

        # Combine Active Symbols AND Closed Symbols for Data Fetching
        active_symbols = [f"{t['exchange']}:{t['symbol']}" for t in active_trades]
        closed_symbols = [f"{t['exchange']}:{t['symbol']}" for t in todays_closed]
        
        all_instruments = list(set(active_symbols + closed_symbols))

        if not all_instruments: 
            return

        # Fetch Live Prices
        try: 
            live_prices = kite.quote(all_instruments)
        except: 
            return

        # --- 1. Process ACTIVE TRADES ---
        active_list = []
        updated = False
        
        for t in active_trades:
            inst_key = f"{t['exchange']}:{t['symbol']}"
            if inst_key not in live_prices:
                 active_list.append(t)
                 continue
                 
            ltp = live_prices[inst_key]['last_price']
            t['current_ltp'] = ltp
            updated = True
            
            # A. PENDING ORDERS (Activation Logic)
            if t['status'] == "PENDING":
                condition_met = False
                if t.get('trigger_dir') == 'BELOW':
                    if ltp <= t['entry_price']: condition_met = True
                elif t.get('trigger_dir') == 'ABOVE':
                    if ltp >= t['entry_price']: condition_met = True
                
                if condition_met:
                    t['status'] = "OPEN"
                    t['highest_ltp'] = t['entry_price']
                    log_event(t, f"Order ACTIVATED @ {ltp}")
                    
                    # --- TELEGRAM NOTIFICATION: ACTIVE ---
                    telegram_bot.notify_trade_event(t, "ACTIVE", ltp)
                    
                    if t['mode'] == 'LIVE':
                        try: 
                            # Place Market Buy
                            kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_BUY, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            
                            # Place SL-M
                            try:
                                sl_id = kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_SL_M, product=kite.PRODUCT_MIS, trigger_price=t['sl'])
                                t['sl_order_id'] = sl_id
                            except: 
                                log_event(t, "Broker SL Fail")
                        except Exception as e: 
                            log_event(t, f"Broker Fail: {e}")
                    
                    active_list.append(t)
                else: 
                    active_list.append(t)
                continue

            # B. ACTIVE ORDERS
            if t['status'] in ['OPEN', 'PROMOTED_LIVE']:
                current_high = t.get('highest_ltp', 0)
                if ltp > current_high:
                    t['highest_ltp'] = ltp
                    t['made_high'] = ltp
                    
                    # --- TELEGRAM NOTIFICATION: HIGH MADE ---
                    # Only if T3 (index 2) is already hit
                    if 2 in t.get('targets_hit_indices', []):
                         telegram_bot.notify_trade_event(t, "HIGH_MADE", ltp)
                
                # --- Step Trailing Logic ---
                if t.get('trailing_sl', 0) > 0:
                    step = t['trailing_sl']
                    current_sl = t['sl']
                    diff = ltp - (current_sl + step)
                    
                    if diff >= step:
                        steps_to_move = int(diff / step)
                        new_sl = current_sl + (steps_to_move * step)
                        
                        # Trailing Limits (Cap SL to Entry/Targets)
                        sl_limit = float('inf')
                        mode = int(t.get('sl_to_entry', 0))
                        if mode == 1: sl_limit = t['entry_price']
                        elif mode == 2 and t['targets']: sl_limit = t['targets'][0]
                        elif mode == 3 and len(t['targets']) > 1: sl_limit = t['targets'][1]
                        
                        if mode > 0: 
                            new_sl = min(new_sl, sl_limit)
                        
                        if new_sl > t['sl']:
                            t['sl'] = new_sl
                            # Sync Broker
                            if t['mode'] == 'LIVE' and t.get('sl_order_id'):
                                try: 
                                    kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_order_id'], trigger_price=new_sl)
                                except: pass
                            log_event(t, f"Step Trailing: SL Moved to {t['sl']:.2f} (LTP {ltp})")

                exit_triggered = False
                exit_reason = ""
                
                # --- Check SL Hit ---
                if ltp <= t['sl']:
                    exit_triggered = True
                    exit_reason = "SL_HIT"
                    
                # --- Check Target Hits ---
                elif not exit_triggered:
                    controls = t.get('target_controls', [{'enabled':True, 'lots':0}]*3)
                    
                    for i, tgt in enumerate(t['targets']):
                        if i not in t.get('targets_hit_indices', []) and ltp >= tgt:
                            t.setdefault('targets_hit_indices', []).append(i)
                            conf = controls[i]
                            
                            # --- TELEGRAM NOTIFICATION: TARGET HIT ---
                            telegram_bot.notify_trade_event(t, "TARGET_HIT", {'t_num': i+1, 'price': tgt})

                            # Feature: Trail SL to Entry on Target Hit
                            if conf.get('trail_to_entry') and t['sl'] < t['entry_price']:
                                t['sl'] = t['entry_price']
                                log_event(t, f"Target {i+1} Hit: SL Trailed to Entry ({t['sl']})")
                                if t['mode'] == 'LIVE' and t.get('sl_order_id'):
                                    try: 
                                        kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_order_id'], trigger_price=t['sl'])
                                    except: pass

                            if not conf['enabled']: 
                                continue
                            
                            lot_size = t.get('lot_size') or smart_trader.get_lot_size(t['symbol'])
                            qty_to_exit = conf.get('lots', 0) * lot_size
                            
                            # Full Exit vs Partial Exit
                            if qty_to_exit >= t['quantity']:
                                 exit_triggered = True
                                 exit_reason = "TARGET_HIT"
                                 break
                            elif qty_to_exit > 0:
                                 # Partial Exit
                                 if t['mode'] == 'LIVE': 
                                     manage_broker_sl(kite, t, qty_to_exit)
                                 
                                 t['quantity'] -= qty_to_exit
                                 log_event(t, f"Target {i+1} Hit. Exited {qty_to_exit} Qty")
                                 
                                 if t['mode'] == 'LIVE':
                                    try: 
                                        kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty_to_exit, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                                    except: pass

                # --- Execute Exit ---
                if exit_triggered:
                    if t['mode'] == "LIVE":
                        manage_broker_sl(kite, t, cancel_completely=True)
                        try: 
                            kite.place_order(variety=kite.VARIETY_REGULAR, tradingsymbol=t['symbol'], exchange=t['exchange'], transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=t['quantity'], order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                        except: pass
                    
                    final_price = t['sl'] if exit_reason=="SL_HIT" else (t['targets'][-1] if exit_reason=="TARGET_HIT" else ltp)
                    
                    # --- TELEGRAM NOTIFICATION: SL HIT (Exit) ---
                    if exit_reason == "SL_HIT":
                        trade_snap = t.copy()
                        trade_snap['exit_price'] = final_price
                        pnl_realized = (final_price - t['entry_price']) * t['quantity']
                        telegram_bot.notify_trade_event(trade_snap, "SL_HIT", pnl_realized)
                    
                    move_to_history(t, exit_reason, final_price)
                else:
                    active_list.append(t)
        
        if updated: 
            save_trades(active_list)

        # --- 2. Process CLOSED TRADES (Missed Opportunity Tracker) ---
        history_updated = False
        for t in todays_closed:
            # Skip tracker if SL was hit AFTER hitting some targets (logic: trade was successful partially, no need to track infinite potential)
            if t['status'] == 'SL_HIT' and t.get('targets_hit_indices'):
                continue

            inst_key = f"{t['exchange']}:{t['symbol']}"
            if inst_key in live_prices:
                ltp = live_prices[inst_key]['last_price']
                
                # Check if current price is higher than the recorded high
                current_high = t.get('made_high', t['entry_price'])
                if ltp > current_high:
                    t['made_high'] = ltp
                    # Direct DB merge for efficiency (updating historical record)
                    db.session.merge(TradeHistory(id=t['id'], data=json.dumps(t)))
                    history_updated = True
        
        if history_updated: 
            db.session.commit()
