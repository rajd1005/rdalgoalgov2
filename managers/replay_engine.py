from datetime import datetime
import time
import smart_trader
import settings
from managers.common import IST, get_exchange, log_event
from managers.persistence import TRADE_LOCK, load_trades, save_trades
from managers.broker_ops import move_to_history

def import_past_trade(kite, symbol, entry_dt_str, qty, entry_price, sl_price, targets, trailing_sl, sl_to_entry, exit_multiplier, target_controls):
    """
    Simulates a trade based on historical data.
    1. Fetches minute-level data from the Entry Time up to Now.
    2. Interpolates ticks (OHLC) to simulate price movement.
    3. Checks for Entry Trigger, SL Hit, Target Hits, and Time Exits.
    4. Saves the result as either an Active Paper Trade (if still open) or History (if closed).
    """
    try:
        # 1. Parse Input & Initialize Data
        entry_time = datetime.strptime(entry_dt_str, "%Y-%m-%dT%H:%M") 
        try: 
            entry_time = IST.localize(entry_time)
        except: pass

        # Get Universal Exit Time from Settings (default to PAPER setting)
        try:
            s_cfg = settings.load_settings()
            exit_time_conf = s_cfg['modes']['PAPER'].get('universal_exit_time', "15:25")
            exit_H, exit_M = map(int, exit_time_conf.split(':'))
        except:
            exit_H, exit_M = 15, 25

        now = datetime.now(IST)
        exchange = get_exchange(symbol)
        
        token = smart_trader.get_instrument_token(symbol, exchange)
        if not token: 
            return {"status": "error", "message": "Symbol Token not found"}
        
        # Fetch Data (Up to 'Now')
        hist_data = smart_trader.fetch_historical_data(kite, token, entry_time, now, "minute")
        if not hist_data: 
            return {"status": "error", "message": "No historical data found"}
        
        # Determine Trigger Direction
        first_open = hist_data[0]['open']
        trigger_dir = "ABOVE" if first_open < entry_price else "BELOW"

        status = "PENDING"
        current_sl = float(sl_price)
        current_qty = int(qty)
        highest_ltp = float(entry_price)
        targets_hit_indices = []
        t_list = [float(x) for x in targets]
        
        logs = [f"[{entry_time.strftime('%Y-%m-%d %H:%M:%S')}] 📋 Replay Import Started. Entry: {entry_price}. Trigger: {trigger_dir}"]
        
        final_status = "PENDING"
        exit_reason = ""
        final_exit_price = 0.0
        
        # 3. Candle-by-Candle Simulation (Interpolated Ticks)
        for idx, candle in enumerate(hist_data):
            c_date_str = candle['date'] # "YYYY-MM-DD HH:MM:SS"
            
            # --- Check Universal Time Exit ---
            try:
                c_dt = datetime.strptime(c_date_str, "%Y-%m-%d %H:%M:%S")
                if c_dt.hour > exit_H or (c_dt.hour == exit_H and c_dt.minute >= exit_M):
                    if status == "OPEN":
                        final_status = "TIME_EXIT"
                        exit_reason = "TIME_EXIT"
                        final_exit_price = candle['open']
                        logs.append(f"[{c_date_str}] ⏰ Universal Time Exit @ {final_exit_price}")
                        current_qty = 0
                        break
            except: pass

            O, H, L, C = candle['open'], candle['high'], candle['low'], candle['close']
            
            # Interpolate Tick sequence based on candle color
            if C >= O: ticks = [O, L, H, C]
            else: ticks = [O, H, L, C]

            # Process Each Tick
            for ltp in ticks:
                
                # --- PHASE 1: ACTIVATION ---
                if status == "PENDING":
                    activated = False
                    if trigger_dir == "ABOVE" and ltp >= entry_price: activated = True
                    elif trigger_dir == "BELOW" and ltp <= entry_price: activated = True
                    
                    if activated:
                        status = "OPEN"
                        fill_price = entry_price 
                        highest_ltp = max(fill_price, ltp) 
                        logs.append(f"[{c_date_str}] 🚀 Order ACTIVATED @ {fill_price}")
                        continue 

                # --- PHASE 2: SIMULATION (Risk Engine) ---
                if status == "OPEN":
                    if ltp > highest_ltp:
                        highest_ltp = ltp
                        t_sl = float(trailing_sl) if trailing_sl else 0
                        
                        # Trailing Logic
                        if t_sl > 0:
                            step = t_sl
                            diff = highest_ltp - (current_sl + step)
                            if diff >= step:
                                steps_to_move = int(diff / step)
                                new_sl = current_sl + (steps_to_move * step)
                                
                                # Trailing Limits
                                limit_val = float('inf')
                                mode = int(sl_to_entry)
                                if mode == 1: limit_val = entry_price
                                elif mode == 2 and len(t_list)>0: limit_val = t_list[0]
                                elif mode == 3 and len(t_list)>1: limit_val = t_list[1]
                                elif mode == 4 and len(t_list)>2: limit_val = t_list[2]
                                
                                if mode > 0: new_sl = min(new_sl, limit_val)
                                
                                if new_sl > current_sl:
                                    current_sl = new_sl
                                    logs.append(f"[{c_date_str}] 📈 Trailing SL Moved: {current_sl:.2f} (LTP: {ltp})")

                    # Check SL
                    if ltp <= current_sl:
                        final_status = "SL_HIT"
                        exit_reason = "SL_HIT"
                        final_exit_price = current_sl
                        logs.append(f"[{c_date_str}] 🛑 SL Hit @ {current_sl}. Exited {current_qty} Qty.")
                        current_qty = 0
                        break

                    # Check Targets
                    for i, tgt in enumerate(t_list):
                        if i in targets_hit_indices: continue 
                        if ltp >= tgt:
                            targets_hit_indices.append(i)
                            conf = target_controls[i]
                            
                            # Trail to Entry
                            if conf.get('trail_to_entry') and current_sl < entry_price:
                                current_sl = entry_price
                                logs.append(f"[{c_date_str}] 🎯 Target {i+1} Hit: SL Trailed to Entry ({current_sl})")
                                
                            if conf['enabled']:
                                lot_size = smart_trader.get_lot_size(symbol)
                                exit_qty = conf['lots'] * lot_size
                                
                                # Check for Full Exit or Bulk Exit
                                if exit_qty >= current_qty or exit_qty >= 1000:
                                    final_status = "TARGET_HIT"
                                    exit_reason = f"TARGET_{i+1}_HIT"
                                    final_exit_price = tgt
                                    logs.append(f"[{c_date_str}] 🎯 Target {i+1} Hit ({tgt}). Full Exit.")
                                    current_qty = 0
                                    break 
                                else:
                                    current_qty -= exit_qty
                                    logs.append(f"[{c_date_str}] 🎯 Target {i+1} Hit ({tgt}). Partial Exit {exit_qty} Qty. Rem: {current_qty}")
                    
                    if current_qty == 0:
                         if final_status == "PENDING": final_status = "TARGET_HIT"
                         if not exit_reason: exit_reason = "TARGET_HIT"
                         final_exit_price = ltp
                         break 

            if current_qty == 0:
                # Post-Exit Scan: Check if market went higher after exit
                skip_scan = (final_status == "SL_HIT" and len(targets_hit_indices) > 0)
                
                if not skip_scan:
                    remaining_candles = hist_data[idx+1:]
                    if remaining_candles:
                        try:
                            max_rest = max([float(c['high']) for c in remaining_candles])
                            if max_rest > highest_ltp:
                                highest_ltp = max_rest
                                logs.append(f"[{remaining_candles[-1]['date']}] ℹ️ Post-Exit High Detected: {highest_ltp}")
                        except: pass
                break 

        # 4. Finalize & Save
        with TRADE_LOCK:
            current_ltp = entry_price
            
            # SCENARIO A: Trade is still OPEN (Active)
            if final_status in ["OPEN", "PENDING"]:
                try: 
                    q = kite.quote(f"{exchange}:{symbol}")
                    current_ltp = q[f"{exchange}:{symbol}"]['last_price']
                except: 
                    if hist_data: current_ltp = hist_data[-1]['close']
                
                record = {
                    "id": int(time.time()), 
                    "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"), 
                    "symbol": symbol, "exchange": exchange,
                    "mode": "PAPER", 
                    "order_type": "MARKET", "status": final_status, 
                    "entry_price": entry_price, 
                    "quantity": current_qty if final_status == "OPEN" else qty,
                    "sl": current_sl, "targets": t_list, 
                    "target_controls": target_controls,
                    "lot_size": smart_trader.get_lot_size(symbol), 
                    "trailing_sl": float(trailing_sl), "sl_to_entry": int(sl_to_entry), "exit_multiplier": int(exit_multiplier), 
                    "sl_order_id": None,
                    "targets_hit_indices": targets_hit_indices, 
                    "highest_ltp": highest_ltp, "made_high": highest_ltp, 
                    "current_ltp": current_ltp, 
                    "trigger_dir": trigger_dir,
                    "logs": logs,
                    "is_replay": True,
                    "last_update_time": hist_data[-1]['date'] if hist_data else get_time_str()
                }
                trades = load_trades()
                trades.append(record)
                save_trades(trades)
                return {"status": "success", "message": f"Simulation Complete. Trade Still Active as {final_status}."}
                
            else:
                # SCENARIO B: Trade CLOSED (History)
                last_time = logs[-1].split(']')[0].replace('[', '')
                pnl_calc = (final_exit_price - entry_price) * qty
                if "Closed:" not in logs[-1]:
                    logs.append(f"[{last_time}] Closed: {final_status} @ {final_exit_price} | P/L ₹ {pnl_calc:.2f}")

                record = {
                    "id": int(time.time()), 
                    "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"), 
                    "symbol": symbol, "exchange": exchange,
                    "mode": "PAPER", 
                    "order_type": "MARKET", "status": final_status, 
                    "entry_price": entry_price, "quantity": qty,
                    "sl": current_sl, "targets": t_list, 
                    "target_controls": target_controls,
                    "lot_size": smart_trader.get_lot_size(symbol), 
                    "trailing_sl": float(trailing_sl), "sl_to_entry": int(sl_to_entry), "exit_multiplier": int(exit_multiplier), 
                    "sl_order_id": None,
                    "targets_hit_indices": targets_hit_indices, 
                    "highest_ltp": highest_ltp, "made_high": highest_ltp, 
                    "current_ltp": final_exit_price, "trigger_dir": trigger_dir, 
                    "logs": logs,
                    "is_replay": True
                }
                move_to_history(record, exit_reason, final_exit_price)
                return {"status": "success", "message": f"Simulation Complete. Closed: {exit_reason} @ {final_exit_price}"}

    except Exception as e: 
        return {"status": "error", "message": str(e)}
