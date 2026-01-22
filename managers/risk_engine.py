import json
import time
import smart_trader
import settings
from datetime import datetime
from database import db, TradeHistory
from managers.persistence import TRADE_LOCK, load_trades, save_trades, load_history, get_risk_state, save_risk_state
from managers.common import IST, log_event
from managers.broker_ops import manage_broker_sl, move_to_history, place_order, modify_order
from managers.telegram_manager import bot as telegram_bot

# --- NEW: End of Day Report Helper (Automated) ---
def send_eod_report(mode):
    """
    Generates and sends two Telegram reports:
    1. Individual Trade Status (Entries, Exits, Highs, Potentials)
    2. Aggregate Summary (Total P/L, Funds, Wins/Losses)
    """
    try:
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        history = load_history()
        
        # Filter for Today's trades in the specific Mode (LIVE/PAPER)
        todays_trades = [t for t in history if t.get('exit_time') and t['exit_time'].startswith(today_str) and t['mode'] == mode]
        
        if not todays_trades:
            return

        # --- REPORT 1: INDIVIDUAL TRADE DETAILS ---
        msg_details = f"📊 <b>{mode} - FINAL TRADE STATUS</b>\n"
        
        total_pnl = 0.0
        total_wins = 0.0
        total_loss = 0.0
        total_funds_used = 0.0
        total_max_potential = 0.0
        
        # Counters
        cnt_not_active = 0
        cnt_direct_sl = 0

        for t in todays_trades:
            raw_symbol = t.get('symbol', 'Unknown')
            symbol = smart_trader.get_telegram_symbol(raw_symbol)
            
            entry = t.get('entry_price', 0)
            sl = t.get('sl', 0)
            targets = t.get('targets', [])
            raw_status = t.get('status', 'CLOSED')
            qty = t.get('quantity', 0)
            pnl = t.get('pnl', 0)
            
            # --- CUSTOM STATUS DISPLAY LOGIC ---
            display_status = raw_status
            is_direct_sl = False 
            
            # 1. Check for "Time_Exit" (Not active trade)
            if raw_status == "NOT_ACTIVE" or (raw_status == "TIME_EXIT" and pnl == 0):
                display_status = "Not Active"
                cnt_not_active += 1
                is_direct_sl = True 
            
            # 2. Check for "SL (Without going T1)"
            elif raw_status == "SL_HIT":
                if not t.get('targets_hit_indices'): # No targets were hit
                    display_status = "Stop-Loss"
                    cnt_direct_sl += 1
                    is_direct_sl = True 
                else:
                    display_status = "SL Hit (After Target)"
            
            # Use made_high if available, else exit price, else entry
            made_high = t.get('made_high', t.get('exit_price', entry))
            
            # --- TRACKING TAG LOGIC ---
            track_tag = "🟢"
            if t.get('virtual_sl_hit'):
                track_tag = "🔴"
            
            # Suppress Potential for Direct SL
            if is_direct_sl:
                made_high = entry 
                max_pot_val = 0.0
                pot_target = "None"
            else:
                # Max Potential Calculation
                max_pot_val = (made_high - entry) * qty
                if max_pot_val < 0: max_pot_val = 0
                
                # Potential Target Logic
                pot_target = "None"
                if len(targets) >= 3:
                    if made_high >= targets[2]: pot_target = "T3 ✅"
                    elif made_high >= targets[1]: pot_target = "T2 ✅"
                    elif made_high >= targets[0]: pot_target = "T1 ✅"

            total_pnl += pnl
            if pnl >= 0: 
                total_wins += pnl
            else: 
                total_loss += pnl
            
            total_max_potential += max_pot_val
            
            # Funds Used
            invested = entry * qty
            total_funds_used += invested
            
            msg_details += (
                f"\n🔹 <b>{symbol}</b>\n"
                f"Entry: {entry}\n"
                f"SL: {sl}\n"
                f"Targets: {targets}\n"
                f"Status: {display_status}\n" 
                f"High Made: {made_high} {track_tag}\n"
                f"Potential Target: {pot_target}\n"
                f"Max Potential: {max_pot_val:.2f}\n"
                f"----------------"
            )

        telegram_bot.send_message(msg_details)

        # --- REPORT 2: AGGREGATE SUMMARY ---
        msg_summary = (
            f"📈 <b>{mode} - EOD SUMMARY</b>\n\n"
            f"💰 <b>Total P/L: ₹ {total_pnl:.2f}</b>\n"
            f"----------------\n"
            f"🟢 Total Wins: ₹ {total_wins:.2f}\n"
            f"🔴 Total Loss: ₹ {total_loss:.2f}\n"
            f"🚀 Max Potential: ₹ {total_max_potential:.2f}\n"
            f"💼 Funds Used: ₹ {total_funds_used:.2f}\n"
            f"📊 Total Trades: {len(todays_trades)}\n"
            f"🚫 Not Active: {cnt_not_active}\n" 
            f"🛑 Direct SL: {cnt_direct_sl}"     
        )
        telegram_bot.send_message(msg_summary)

    except Exception as e:
        print(f"Error generating EOD report: {e}")

# --- NEW: Manual Report Helpers ---

def send_manual_trade_status(mode):
    try:
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        history = load_history()
        todays_trades = [t for t in history if t.get('exit_time') and t['exit_time'].startswith(today_str) and t['mode'] == mode]
        
        if not todays_trades: return {"status": "error", "message": "No trades found."}

        msg_details = f"📊 <b>{mode} - FINAL TRADE STATUS (MANUAL)</b>\n"
        for t in todays_trades:
            symbol = smart_trader.get_telegram_symbol(t.get('symbol', 'Unknown'))
            entry = t.get('entry_price', 0)
            sl = t.get('sl', 0)
            made_high = t.get('made_high', entry)
            
            msg_details += (
                f"\n🔹 <b>{symbol}</b>\n"
                f"Entry: {entry} | SL: {sl}\n"
                f"High: {made_high} | Status: {t.get('status', 'CLOSED')}\n"
                f"----------------"
            )
        telegram_bot.send_message(msg_details)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def send_manual_trade_report(trade_id):
    try:
        history = load_history()
        trade = next((t for t in history if str(t['id']) == str(trade_id)), None)
        if not trade:
            active = load_trades()
            trade = next((t for t in active if str(t['id']) == str(trade_id)), None)
        if not trade: return {"status": "error", "message": "Trade not found"}

        symbol = smart_trader.get_telegram_symbol(trade.get('symbol', 'Unknown'))
        msg = f"🔹 <b>TRADE: {symbol}</b>\nEntry: {trade.get('entry_price')}\nSL: {trade.get('sl')}\nStatus: {trade.get('status')}"
        telegram_bot.send_message(msg)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def send_manual_summary(mode):
    # (Reusing EOD logic for brevity, triggered manually)
    try:
        send_eod_report(mode)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def check_global_exit_conditions(alice, mode, mode_settings):
    with TRADE_LOCK:
        trades = load_trades()
        now = datetime.now(IST)
        exit_time_str = mode_settings.get('universal_exit_time', "15:25")
        today_str = now.strftime("%Y-%m-%d")
        state = get_risk_state(mode)
        
        # 1. TIME EXIT
        try:
            exit_dt = datetime.strptime(exit_time_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            exit_dt = IST.localize(exit_dt.replace(tzinfo=None))
            
            if now >= exit_dt and (now - exit_dt).seconds < 120:
                 if state.get('last_eod_date') != today_str:
                     active_mode = [t for t in trades if t['mode'] == mode]
                     if active_mode:
                         for t in active_mode:
                             exit_reason = "TIME_EXIT"
                             exit_price = t.get('current_ltp', 0)
                             if t['status'] == 'PENDING':
                                 exit_reason = "NOT_ACTIVE"
                                 exit_price = t['entry_price']
                             
                             if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                                manage_broker_sl(alice, t, cancel_completely=True)
                                try: 
                                    place_order(alice, t['symbol'], "SELL", t['quantity'], "MARKET", "MIS", exchange=t['exchange'], tag="TIME_EXIT")
                                except: pass
                             
                             move_to_history(t, exit_reason, exit_price)
                         save_trades([t for t in trades if t['mode'] != mode])
                     
                     send_eod_report(mode)
                     state['last_eod_date'] = today_str
                     save_risk_state(mode, state)
                     return
        except Exception as e: print(f"Time Check Error: {e}")

        # 2. PROFIT LOCKING
        pnl_start = float(mode_settings.get('profit_lock', 0))
        if pnl_start > 0:
            current_total_pnl = 0.0
            for t in load_history():
                if t.get('exit_time') and t['exit_time'].startswith(today_str) and t['mode'] == mode: 
                    current_total_pnl += t.get('pnl', 0)
            
            for t in [x for x in trades if x['mode'] == mode]:
                if t['status'] != 'PENDING':
                    current_total_pnl += (t.get('current_ltp', t['entry_price']) - t['entry_price']) * t['quantity']

            if not state.get('active') and current_total_pnl >= pnl_start:
                state['active'] = True
                state['high_pnl'] = current_total_pnl
                state['global_sl'] = float(mode_settings.get('profit_min', 0))
                save_risk_state(mode, state)
            
            if state.get('active'):
                if current_total_pnl > state['high_pnl']:
                    diff = current_total_pnl - state['high_pnl']
                    trail_step = float(mode_settings.get('profit_trail', 0))
                    if trail_step > 0 and diff >= trail_step:
                         state['global_sl'] += (int(diff / trail_step) * trail_step)
                         state['high_pnl'] = current_total_pnl
                         save_risk_state(mode, state)

                if current_total_pnl <= state['global_sl']:
                    for t in [x for x in trades if x['mode'] == mode]:
                         if t['mode'] == "LIVE" and t['status'] != 'PENDING':
                            manage_broker_sl(alice, t, cancel_completely=True)
                            try: 
                                place_order(alice, t['symbol'], "SELL", t['quantity'], "MARKET", "MIS", exchange=t['exchange'], tag="PROFIT_LOCK")
                            except: pass
                         move_to_history(t, "PROFIT_LOCK", t.get('current_ltp', 0))
                    
                    save_trades([t for t in trades if t['mode'] != mode])
                    state['active'] = False
                    save_risk_state(mode, state)

def update_risk_engine(alice):
    """
    Main Monitoring Loop.
    Uses 'alice' object (AliceBlue).
    IMPROVED: Smart Throttling for AliceBlue Rate Limits (1800 req / 15 min).
    """
    current_settings = settings.load_settings()
    check_global_exit_conditions(alice, "PAPER", current_settings['modes']['PAPER'])
    check_global_exit_conditions(alice, "LIVE", current_settings['modes']['LIVE'])

    with TRADE_LOCK:
        active_trades = load_trades()
        history = load_history()
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        todays_closed = [t for t in history if t.get('exit_time') and t['exit_time'].startswith(today_str)]

        # Unique symbols to fetch
        active_symbols = [f"{t['exchange']}:{t['symbol']}" for t in active_trades]
        closed_symbols = [f"{t['exchange']}:{t['symbol']}" for t in todays_closed]
        all_instruments = list(set(active_symbols + closed_symbols))

        if not all_instruments: 
            return

        # --- ALICEBLUE OPTIMIZED DATA FETCHING ---
        live_prices = {}
        
        # Loop through symbols with throttle to avoid 429 Errors
        # AliceBlue Rate Limit: ~120 requests/minute (2 req/sec)
        for symbol_str in all_instruments:
            try:
                # Resolve Instrument
                inst = smart_trader.get_alice_instrument(alice, symbol_str)
                if inst:
                    # API Call
                    quote = alice.get_scrip_info(inst)
                    if quote and 'LTP' in quote:
                        live_prices[symbol_str] = {
                            'last_price': float(quote['LTP'])
                        }
                
                # THROTTLE: Sleep 0.6s to stay under 2 req/sec limit safe zone
                time.sleep(0.6) 
            except Exception as e:
                print(f"Fetch Error {symbol_str}: {e}")

        if not live_prices:
            return

        # --- 1. Process ACTIVE TRADES ---
        active_list = []
        updated = False
        
        for t in active_trades:
            try:
                inst_key = f"{t['exchange']}:{t['symbol']}"
                if inst_key not in live_prices:
                     active_list.append(t)
                     continue
                     
                ltp = live_prices[inst_key]['last_price']
                
                if t.get('current_ltp') != ltp:
                    t['current_ltp'] = ltp
                    updated = True
                
                # A. PENDING ORDERS
                if t['status'] == "PENDING":
                    condition_met = False
                    if t.get('trigger_dir') == 'BELOW' and ltp <= t['entry_price']: condition_met = True
                    elif t.get('trigger_dir') == 'ABOVE' and ltp >= t['entry_price']: condition_met = True
                    
                    if condition_met:
                        t['status'] = "OPEN"
                        t['highest_ltp'] = t['entry_price']
                        log_event(t, f"Order ACTIVATED @ {ltp}")
                        telegram_bot.notify_trade_event(t, "ACTIVE", ltp)
                        
                        if t['mode'] == 'LIVE':
                            try: 
                                # Market Buy
                                place_order(alice, t['symbol'], "BUY", t['quantity'], "MARKET", "MIS", exchange=t['exchange'])
                                # Place Broker SL
                                try:
                                    sl_id = place_order(alice, t['symbol'], "SELL", t['quantity'], "SL-M", "MIS", price=0.0, trigger_price=t['sl'], exchange=t['exchange'])
                                    t['sl_order_id'] = sl_id
                                except: log_event(t, "Broker SL Fail")
                            except Exception as e: log_event(t, f"Broker Fail: {e}")
                        
                        active_list.append(t)
                    else: active_list.append(t)
                    continue

                # B. ACTIVE ORDERS
                if t['status'] in ['OPEN', 'PROMOTED_LIVE']:
                    current_high = t.get('highest_ltp', 0)
                    if ltp > current_high:
                        t['highest_ltp'] = ltp
                        t['made_high'] = ltp
                        # Notify T3 Cross
                        if (2 in t.get('targets_hit_indices', [])) or (t.get('targets') and len(t['targets']) > 2 and ltp >= t['targets'][2]):
                             telegram_bot.notify_trade_event(t, "HIGH_MADE", ltp)
                    
                    # Trailing Logic
                    if t.get('trailing_sl', 0) > 0:
                        step = t['trailing_sl']
                        if (ltp - (t['sl'] + step)) >= step:
                            t['sl'] += (int((ltp - (t['sl'] + step)) / step) * step)
                            if t['mode'] == 'LIVE' and t.get('sl_order_id'):
                                try: modify_order(alice, t['sl_order_id'], trigger_price=t['sl'])
                                except: pass
                            log_event(t, f"Step Trailing: SL Moved to {t['sl']:.2f}")

                    exit_triggered = False
                    exit_reason = ""
                    
                    if ltp <= t['sl']:
                        exit_triggered = True
                        exit_reason = "SL_HIT"
                    elif t.get('targets'):
                        controls = t.get('target_controls', [{'enabled':True, 'lots':0}]*3)
                        for i, tgt in enumerate(t['targets']):
                            if i not in t.get('targets_hit_indices', []) and ltp >= tgt:
                                t.setdefault('targets_hit_indices', []).append(i)
                                telegram_bot.notify_trade_event(t, "TARGET_HIT", {'t_num': i+1, 'price': tgt})
                                
                                conf = controls[i]
                                if conf.get('trail_to_entry') and t['sl'] < t['entry_price']:
                                    t['sl'] = t['entry_price']
                                    if t['mode'] == 'LIVE': 
                                        try: modify_order(alice, t['sl_order_id'], trigger_price=t['sl'])
                                        except: pass

                                if conf['enabled']:
                                    lot_size = t.get('lot_size') or smart_trader.get_lot_size(t['symbol'])
                                    qty_to_exit = conf.get('lots', 0) * lot_size
                                    if qty_to_exit >= t['quantity']:
                                         exit_triggered = True; exit_reason = "TARGET_HIT"; break
                                    elif qty_to_exit > 0:
                                         if t['mode'] == 'LIVE': manage_broker_sl(alice, t, qty_to_exit)
                                         t['quantity'] -= qty_to_exit
                                         if t['mode'] == 'LIVE':
                                            try: place_order(alice, t['symbol'], "SELL", qty_to_exit, "MARKET", "MIS", exchange=t['exchange'])
                                            except: pass

                    if exit_triggered:
                        if t['mode'] == "LIVE":
                            manage_broker_sl(alice, t, cancel_completely=True)
                            try: place_order(alice, t['symbol'], "SELL", t['quantity'], "MARKET", "MIS", exchange=t['exchange'])
                            except: pass
                        
                        final_price = t['sl'] if exit_reason=="SL_HIT" else (t['targets'][-1] if exit_reason=="TARGET_HIT" else ltp)
                        if exit_reason == "SL_HIT":
                             telegram_bot.notify_trade_event(t, "SL_HIT", (final_price - t['entry_price']) * t['quantity'])
                        move_to_history(t, exit_reason, final_price)
                    else:
                        active_list.append(t)
            except Exception as e:
                print(f"Error processing trade {t.get('symbol')}: {e}")
                active_list.append(t)
        
        if updated: save_trades(active_list)

        # --- 2. Process CLOSED TRADES (Missed Opp. Tracker) ---
        history_updated = False
        for t in todays_closed:
            if t.get('virtual_sl_hit', False): continue
            inst_key = f"{t['exchange']}:{t['symbol']}"
            if inst_key in live_prices:
                ltp = live_prices[inst_key]['last_price']
                t['current_ltp'] = ltp
                
                # Check Virtual SL
                is_dead = (ltp <= t['sl']) if t['entry_price'] > t['sl'] else (ltp >= t['sl'])
                if is_dead:
                    t['virtual_sl_hit'] = True
                else:
                    if ltp > t.get('made_high', t['entry_price']):
                        t['made_high'] = ltp
                        try: telegram_bot.notify_trade_event(t, "HIGH_MADE", ltp)
                        except: pass
                
                db.session.merge(TradeHistory(id=t['id'], data=json.dumps(t)))
                history_updated = True
        
        if history_updated: db.session.commit()
