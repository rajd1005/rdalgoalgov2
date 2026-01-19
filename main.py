import os
import json
import threading
import time
import gc 
import requests
from flask import Flask, render_template, request, redirect, flash, jsonify, url_for
from kiteconnect import KiteConnect
import config

# --- REFACTORED IMPORTS ---
from managers import persistence, trade_manager, risk_engine, replay_engine, common, broker_ops
from managers.telegram_manager import bot as telegram_bot
# --------------------------
import smart_trader
import settings
from database import db, AppSetting
import auto_login 

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.from_object(config)

# Initialize Database
db.init_app(app)
with app.app_context():
    db.create_all()

kite = KiteConnect(api_key=config.API_KEY)

# --- GLOBAL STATE MANAGEMENT ---
bot_active = False
login_state = "IDLE" 
login_error_msg = None 

# --- TOKEN PERSISTENCE HELPERS ---
def save_token_to_db(access_token):
    """Saves the active access token to the database to survive restarts."""
    try:
        with app.app_context():
            setting_rec = AppSetting.query.first()
            if not setting_rec:
                data = {"access_token": access_token}
                setting_rec = AppSetting(data=json.dumps(data))
                db.session.add(setting_rec)
            else:
                data = json.loads(setting_rec.data)
                data["access_token"] = access_token
                setting_rec.data = json.dumps(data)
            db.session.commit()
            print("💾 Access Token persisted to DB.")
    except Exception as e:
        print(f"❌ Failed to save token: {e}")

def load_token_from_db():
    """Restores session from DB if memory is empty."""
    global bot_active
    try:
        if not kite.access_token:
            with app.app_context():
                setting_rec = AppSetting.query.first()
                if setting_rec:
                    data = json.loads(setting_rec.data)
                    token = data.get("access_token")
                    if token:
                        print("♻️ Restoring Session from Database...")
                        kite.set_access_token(token)
                        bot_active = True
                        # Async fetch instruments if missing
                        if not smart_trader.symbol_map:
                            threading.Thread(target=smart_trader.fetch_instruments, args=(kite,)).start()
    except Exception as e:
        print(f"⚠️ Token Restore Warning: {e}")

# Ensure token is loaded before processing requests
@app.before_request
def ensure_token_state():
    if not bot_active:
        load_token_from_db()

# --- LOGIN & MONITORING ---

def run_auto_login_process():
    global bot_active, login_state, login_error_msg
    
    if not config.ZERODHA_USER_ID or not config.TOTP_SECRET:
        login_state = "FAILED"
        login_error_msg = "Missing Credentials in Config"
        return

    login_state = "WORKING"
    login_error_msg = None
    
    try:
        token, error = auto_login.perform_auto_login(kite)
        gc.collect() 
        
        if token:
            try:
                data = kite.generate_session(token, api_secret=config.API_SECRET)
                access_token = data["access_token"]
                
                kite.set_access_token(access_token)
                save_token_to_db(access_token) # Persist
                
                smart_trader.fetch_instruments(kite)
                
                bot_active = True
                login_state = "IDLE"
                gc.collect()
                
                telegram_bot.notify_system_event("LOGIN_SUCCESS", "Auto-Login Successful. Session Saved.")
                print("✅ Session Generated & Saved")
                
            except Exception as e:
                telegram_bot.notify_system_event("LOGIN_FAIL", f"Session Gen Failed: {str(e)}")
                print(f"❌ Session Generation Error: {e}")
                login_state = "FAILED"
                login_error_msg = str(e)
        else:
            # Check if callback handled it in parallel
            if bot_active:
                print("✅ Auto-Login: Handled via Callback Route.")
                login_state = "IDLE"
            else:
                telegram_bot.notify_system_event("LOGIN_FAIL", f"Auto-Login Failed: {error}")
                print(f"❌ Auto-Login Failed: {error}")
                login_state = "FAILED"
                login_error_msg = error
            
    except Exception as e:
        telegram_bot.notify_system_event("LOGIN_FAIL", f"Critical Login Error: {str(e)}")
        print(f"❌ Critical Session Error: {e}")
        login_state = "FAILED"
        login_error_msg = str(e)

def background_monitor():
    global bot_active, login_state
    
    with app.app_context():
        try:
            telegram_bot.notify_system_event("STARTUP", "Server Deployed & Monitor Started.")
            print("🖥️ Background Monitor Started")
        except: pass
    
    time.sleep(5)
    
    while True:
        with app.app_context():
            try:
                # Attempt Restore if offline
                if not bot_active:
                    load_token_from_db()

                if bot_active:
                    try:
                        # Validate Token (Skip if Mock)
                        if not hasattr(kite, "mock_instruments"):
                            if not kite.access_token: raise Exception("No Access Token")
                            # Lightweight check
                            # kite.profile() 
                        
                        risk_engine.update_risk_engine(kite)
                        
                    except Exception as e:
                        err = str(e)
                        if "Token" in err or "Network" in err or "Access Token" in err:
                            print(f"⚠️ Connection Lost: {err}")
                            if bot_active: telegram_bot.notify_system_event("OFFLINE", f"Connection Lost: {err}")
                            bot_active = False 
                        else:
                            print(f"⚠️ Risk Loop Warning: {err}")

                if not bot_active:
                    if hasattr(kite, "mock_instruments"):
                        bot_active = True
                        continue

                    if login_state == "IDLE":
                        print("🔄 Monitor: System Offline. Initiating Auto-Login...")
                        run_auto_login_process()
                    
                    elif login_state == "FAILED":
                        print("⚠️ Auto-Login previously failed. Retrying in 60s...")
                        time.sleep(60)
                        login_state = "IDLE" 
                        
            except Exception as e:
                print(f"❌ Monitor Loop Critical Error: {e}")
            finally:
                db.session.remove()
        
        time.sleep(0.5) 

# --- ROUTES ---

@app.route('/')
def home():
    if bot_active:
        trades = persistence.load_trades()
        for t in trades: t['symbol'] = smart_trader.get_display_name(t['symbol'])
        active = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING', 'MONITORING']]
        return render_template('dashboard.html', is_active=True, trades=active)
    return render_template('dashboard.html', is_active=False, state=login_state, error=login_error_msg, login_url=kite.login_url())

@app.route('/secure', methods=['GET', 'POST'])
def secure_login_page():
    if request.method == 'POST':
        if request.form.get('password') == config.ADMIN_PASSWORD:
            return redirect(kite.login_url())
        else:
            return render_template('secure_login.html', error="Invalid Password! Access Denied.")
    return render_template('secure_login.html')

@app.route('/api/status')
def api_status():
    return jsonify({"active": bot_active, "state": login_state, "login_url": kite.login_url()})

@app.route('/reset_connection')
def reset_connection():
    global bot_active, login_state
    telegram_bot.notify_system_event("RESET", "Manual Connection Reset.")
    
    # Clear DB Token
    try:
        with app.app_context():
            setting = AppSetting.query.first()
            if setting:
                d = json.loads(setting.data)
                if "access_token" in d: del d["access_token"]
                setting.data = json.dumps(d)
                db.session.commit()
    except: pass

    bot_active = False
    login_state = "IDLE"
    flash("🔄 Connection Reset.")
    return redirect('/')

@app.route('/callback')
def callback():
    global bot_active
    t = request.args.get("request_token")
    if t:
        try:
            data = kite.generate_session(t, api_secret=config.API_SECRET)
            access_token = data["access_token"]
            kite.set_access_token(access_token)
            save_token_to_db(access_token)
            
            bot_active = True
            smart_trader.fetch_instruments(kite)
            gc.collect()
            telegram_bot.notify_system_event("LOGIN_SUCCESS", "Manual Login (Callback) Successful.")
            flash("✅ System Online")
        except Exception as e:
            flash(f"Login Error: {e}")
    return redirect('/')

# --- DATA & SETTINGS API ---

@app.route('/api/settings/load')
def api_settings_load(): return jsonify(settings.load_settings())

@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    if settings.save_settings_file(request.json): return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/positions')
def api_positions():
    trades = persistence.load_trades()
    for t in trades:
        t['lot_size'] = smart_trader.get_lot_size(t['symbol'])
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/closed_trades')
def api_closed_trades():
    trades = persistence.load_history()
    for t in trades: t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/delete_trade/<trade_id>', methods=['POST'])
def api_delete_trade(trade_id):
    if persistence.delete_trade(trade_id): return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/update_trade', methods=['POST'])
def api_update_trade():
    data = request.json
    try:
        if trade_manager.update_trade_protection(kite, data['id'], data['sl'], data['targets'], data.get('trailing_sl', 0), data.get('entry_price'), data.get('target_controls'), data.get('sl_to_entry', 0), data.get('exit_multiplier', 1)):
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Trade not found"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manage_trade', methods=['POST'])
def api_manage_trade():
    data = request.json
    trade_id, action, lots = data.get('id'), data.get('action'), int(data.get('lots', 0))
    t = next((x for x in persistence.load_trades() if str(x['id']) == str(trade_id)), None)
    if t and lots > 0:
        if trade_manager.manage_trade_position(kite, trade_id, action, smart_trader.get_lot_size(t['symbol']), lots):
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Action Failed"})

@app.route('/api/indices')
def api_indices():
    if not bot_active: return jsonify({"NIFTY":0, "BANKNIFTY":0, "SENSEX":0})
    return jsonify(smart_trader.get_indices_ltp(kite))

@app.route('/api/search')
def api_search():
    return jsonify(smart_trader.search_symbols(kite, request.args.get('q', ''), settings.load_settings().get('exchanges', None)))

@app.route('/api/details')
def api_details():
    return jsonify(smart_trader.get_symbol_details(kite, request.args.get('symbol', '')))

@app.route('/api/chain')
def api_chain():
    return jsonify(smart_trader.get_chain_data(request.args.get('symbol'), request.args.get('expiry'), request.args.get('type'), float(request.args.get('ltp', 0))))

@app.route('/api/specific_ltp')
def api_s_ltp():
    return jsonify({"ltp": smart_trader.get_specific_ltp(kite, request.args.get('symbol'), request.args.get('expiry'), request.args.get('strike'), request.args.get('type'))})

@app.route('/api/panic_exit', methods=['POST'])
def api_panic_exit():
    if not bot_active: return jsonify({"status": "error", "message": "Bot not connected"})
    if broker_ops.panic_exit_all(kite):
        flash("🚨 PANIC MODE EXECUTED.")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Failed"})

@app.route('/get_ltp')
def route_get_ltp():
    sym = request.args.get('symbol')
    if not sym: return jsonify({'ltp': 0})
    return jsonify({'ltp': smart_trader.get_ltp(kite, sym)})

# --- CORE UPDATE ROUTE (Corrected for LTP) ---
@app.route('/update_data')
def update_data():
    try:
        active_trades = persistence.load_trades()
        active_trades = [t for t in active_trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING', 'MONITORING']]
        
        for t in active_trades:
            t['symbol'] = smart_trader.get_display_name(t['symbol'])
            
        # Get LTP for requested symbol
        symbol_to_track = request.args.get('symbol')
        
        # Fallback to first trade if none selected
        if not symbol_to_track and active_trades:
            symbol_to_track = active_trades[0]['symbol']
            
        ltp = 0.0
        if symbol_to_track:
            ltp = smart_trader.get_ltp(kite, symbol_to_track)
            
        return jsonify({'trades': active_trades, 'ltp': ltp, 'status': 'success'})
    except Exception as e:
        print(f"Update Data Error: {e}")
        return jsonify({'trades': [], 'ltp': 0, 'status': 'error'})

# --- TELEGRAM & IMPORT ---

@app.route('/api/test_telegram', methods=['POST'])
def test_telegram():
    token, chat = request.form.get('token'), request.form.get('chat_id')
    if not token or not chat: return jsonify({"status": "error"})
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": "✅ Test Success", "parse_mode": "HTML"}, timeout=5)
        return jsonify({"status": "success" if r.status_code == 200 else "error", "message": r.text})
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manual_trade_report', methods=['POST'])
def api_manual_trade_report():
    return jsonify(risk_engine.send_manual_trade_report(request.json.get('trade_id')))

@app.route('/api/manual_summary', methods=['POST'])
def api_manual_summary():
    return jsonify(risk_engine.send_manual_summary(request.json.get('mode', 'PAPER')))

@app.route('/api/manual_trade_status', methods=['POST'])
def api_manual_trade_status():
    return jsonify(risk_engine.send_manual_trade_status(request.json.get('mode', 'PAPER')))

@app.route('/api/import_trade', methods=['POST'])
def api_import_trade():
    if not bot_active: return jsonify({"status": "error", "message": "Bot not connected"})
    data = request.json
    try:
        final_sym = smart_trader.get_exact_symbol(data['symbol'], data['expiry'], data['strike'], data['type'])
        if not final_sym: return jsonify({"status": "error", "message": "Invalid Symbol"})
        
        result = replay_engine.import_past_trade(
            kite, final_sym, data['entry_time'], int(data['qty']), float(data['price']), float(data['sl']), 
            [float(t) for t in data['targets']], data.get('trailing_sl', 0), data.get('sl_to_entry', 0),
            data.get('exit_multiplier', 1), data.get('target_controls')
        )
        
        queue = result.get('notification_queue', [])
        trade_ref = result.get('trade_ref', {})
        if queue and trade_ref:
            def send_seq():
                with app.app_context():
                    msg_ids = telegram_bot.notify_trade_event(trade_ref, "NEW_TRADE")
                    if msg_ids:
                        trade_ref['telegram_msg_ids'] = msg_ids if isinstance(msg_ids, dict) else {'main': msg_ids}
                        persistence.save_to_history_db(trade_ref) 
                    
                    for item in queue:
                        if item['event'] == 'NEW_TRADE': continue
                        time.sleep(1.0)
                        t_obj = item.get('trade', trade_ref).copy()
                        if 'id' not in t_obj: t_obj['id'] = trade_ref['id']
                        t_obj['telegram_msg_ids'] = trade_ref.get('telegram_msg_ids')
                        telegram_bot.notify_trade_event(t_obj, item['event'], item.get('data'))
            threading.Thread(target=send_seq).start()
        
        return jsonify(result)
    except Exception as e: return jsonify({"status": "error", "message": str(e)})

@app.route('/api/simulate_scenario', methods=['POST'])
def api_simulate_scenario():
    if not bot_active: return jsonify({"status": "error"})
    return jsonify(replay_engine.simulate_trade_scenario(kite, request.json.get('trade_id'), request.json.get('config')))

@app.route('/api/sync', methods=['POST'])
def api_sync():
    res = { "status": {"active": bot_active, "state": login_state}, "indices": {}, "positions": [] }
    if bot_active:
        res["indices"] = smart_trader.get_indices_ltp(kite)
        trades = persistence.load_trades()
        for t in trades:
            t['lot_size'] = smart_trader.get_lot_size(t['symbol'])
            t['symbol'] = smart_trader.get_display_name(t['symbol'])
        res["positions"] = trades
    return jsonify(res)

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active: return redirect('/')
    try:
        mode_input = request.form['mode'].strip().upper()
        sym = request.form['index']
        type_ = request.form['type']
        input_qty = int(request.form['qty'])
        order_type = request.form['order_type']
        limit_price = float(request.form.get('limit_price') or 0)
        
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        if not final_sym:
            flash("❌ Symbol Generation Failed"); return redirect('/')

        tc = []
        for i in range(1, 4):
            l = int(request.form.get(f't{i}_lots') or 0)
            if i == 3 and l == 0: l = 1000
            tc.append({'enabled': request.form.get(f't{i}_active')=='on', 'lots': l, 'trail_to_entry': request.form.get(f't{i}_cost')=='on'})
        
        channels = ['main']
        for k in ['vip', 'free', 'z2h']: 
            if request.form.get(f'pub_{k}'): channels.append(k)

        # Shadow Logic (Overrides)
        if mode_input == "SHADOW":
            if not common.can_place_order("LIVE")[0]:
                flash("❌ Shadow Blocked: LIVE Mode Disabled"); return redirect('/')
            
            s = settings.load_settings()['modes']['LIVE']
            overrides = {
                'trailing_sl': s.get('trailing_sl', 0), 'sl_to_entry': s.get('sl_to_entry', 0),
                'exit_multiplier': s.get('exit_multiplier', 1), 'target_controls': tc, 
                'ratios': s.get('ratios', [0.5,1,1.5]), 'custom_targets': [],
                'sl_points': float(request.form.get('sl_points', 0))
            }
            
            r1 = trade_manager.create_trade_direct(kite, "LIVE", final_sym, input_qty, float(request.form.get('sl_points',0)), [], order_type, limit_price, tc, 0, 0, 1, [], overrides=overrides)
            if r1['status'] != 'success':
                flash(f"❌ Shadow Live Failed: {r1['message']}"); return redirect('/')
            
            time.sleep(1)
            r2 = trade_manager.create_trade_direct(kite, "PAPER", final_sym, input_qty, float(request.form.get('sl_points',0)), [float(request.form.get(f't{i}_price',0)) for i in range(1,4)], order_type, limit_price, tc, float(request.form.get('trailing_sl',0)), int(request.form.get('sl_to_entry',0)), int(request.form.get('exit_multiplier',1)), target_channels=channels)
            
            flash(f"👻 Shadow: LIVE {r1['status']} | PAPER {r2['status']}")
        else:
            if not common.can_place_order(mode_input)[0]:
                flash(f"⛔ Blocked: {mode_input} disabled"); return redirect('/')
            
            r = trade_manager.create_trade_direct(
                kite, mode_input, final_sym, input_qty, 
                float(request.form.get('sl_points', 0)), 
                [float(request.form.get(f't{i}_price', 0)) for i in range(1,4)],
                order_type, limit_price, tc,
                float(request.form.get('trailing_sl') or 0),
                int(request.form.get('sl_to_entry', 0)),
                int(request.form.get('exit_multiplier', 1)),
                target_channels=channels
            )
            flash(f"✅ {r['status']}: {r.get('message', 'Done')}")

    except Exception as e:
        flash(f"Error: {e}")
    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    if trade_manager.promote_to_live(kite, trade_id): flash("✅ Promoted!"); 
    else: flash("❌ Error")
    return redirect('/')

@app.route('/close_trade/<trade_id>')
def close_trade(trade_id):
    if trade_manager.close_trade_manual(kite, trade_id): flash("✅ Closed"); 
    else: flash("❌ Error")
    return redirect('/')

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    t = threading.Thread(target=background_monitor, daemon=True)
    t.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
