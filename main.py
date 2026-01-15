import os
import json
import threading
import time
import gc 
from flask import Flask, render_template, request, redirect, flash, jsonify
from kiteconnect import KiteConnect
import config
# --- REFACTORED IMPORTS ---
from managers import persistence, trade_manager, risk_engine, replay_engine, common, broker_ops
# --------------------------
import smart_trader
import settings
from database import db
import auto_login 

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.from_object(config)

db.init_app(app)
with app.app_context():
    db.create_all()

kite = KiteConnect(api_key=config.API_KEY)

# --- GLOBAL STATE MANAGEMENT ---
bot_active = False
login_state = "IDLE" 
login_error_msg = None 

def run_auto_login_process():
    global bot_active, login_state, login_error_msg
    
    if not config.ZERODHA_USER_ID or not config.TOTP_SECRET:
        login_state = "FAILED"
        login_error_msg = "Missing Credentials in Config"
        return

    login_state = "WORKING"
    login_error_msg = None
    
    try:
        # Pass the kite instance to get the login URL
        token, error = auto_login.perform_auto_login(kite)
        gc.collect() # Cleanup memory after selenium usage
        
        # REMOVED SKIP_SESSION Check to force token capture
        
        if token:
            try:
                data = kite.generate_session(token, api_secret=config.API_SECRET)
                kite.set_access_token(data["access_token"])
                
                # Fetch instruments immediately after login
                smart_trader.fetch_instruments(kite)
                
                bot_active = True
                login_state = "IDLE"
                gc.collect()
                print("✅ Session Generated Successfully & Instruments Fetched")
            except Exception as e:
                # Specific check for token expiry during generation (e.g. reused token)
                if "Token is invalid" in str(e):
                    print("⚠️ Generated Token Expired or Invalid. Retrying...")
                    login_state = "FAILED" 
                else:
                    print(f"❌ Session Generation Error: {e}")
                    login_state = "FAILED"
                    login_error_msg = str(e)
        else:
            # FIX: Check if the callback route successfully logged us in meanwhile
            if bot_active:
                print("✅ Auto-Login: Handled via Callback Route. System Online.")
                login_state = "IDLE"
            else:
                print(f"❌ Auto-Login Failed: {error}")
                login_state = "FAILED"
                login_error_msg = error
            
    except Exception as e:
        print(f"❌ Critical Session Error: {e}")
        login_state = "FAILED"
        login_error_msg = str(e)

def background_monitor():
    global bot_active, login_state
    print("🖥️ Background Monitor Started")
    time.sleep(5) # Allow Flask to start up
    
    while True:
        with app.app_context():
            try:
                # 1. Active Bot Check
                if bot_active:
                    try:
                        if not kite.access_token: 
                            raise Exception("No Access Token Found")
                        
                        # Run Strategy Logic (Risk Engine)
                        risk_engine.update_risk_engine(kite)
                        
                    except Exception as e:
                        err = str(e)
                        # Detect session expiry or network issues
                        # "Token is invalid" is the key error from Zerodha when session expires
                        if "Token is invalid" in err or "Network" in err or "No Access Token" in err or "access_token" in err:
                            print(f"⚠️ Connection Lost: {err}")
                            bot_active = False # This forces the logic below to run
                        else:
                            print(f"⚠️ Risk Loop Warning: {err}")

                # 2. Reconnection Logic (Only if Bot is NOT active)
                if not bot_active:
                    if login_state == "IDLE":
                        print("🔄 Monitor: System Offline. Initiating Auto-Login...")
                        run_auto_login_process()
                    
                    elif login_state == "FAILED":
                        # Wait 60s before trying again to avoid spamming
                        print("⚠️ Auto-Login previously failed. Retrying in 60s...")
                        time.sleep(60)
                        login_state = "IDLE" # Reset state to trigger retry
                        
            except Exception as e:
                print(f"❌ Monitor Loop Critical Error: {e}")
            finally:
                db.session.remove()
        
        time.sleep(3) # Pulse interval

@app.route('/')
def home():
    global bot_active, login_state
    if bot_active:
        # UPDATED: Use persistence module
        trades = persistence.load_trades()
        for t in trades: 
            t['symbol'] = smart_trader.get_display_name(t['symbol'])
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
    bot_active = False
    login_state = "IDLE"
    flash("🔄 Connection Reset. Login Monitor will retry.")
    return redirect('/')

@app.route('/callback')
def callback():
    global bot_active
    t = request.args.get("request_token")
    if t:
        try:
            data = kite.generate_session(t, api_secret=config.API_SECRET)
            kite.set_access_token(data["access_token"])
            bot_active = True
            smart_trader.fetch_instruments(kite)
            gc.collect()
            flash("✅ System Online")
        except Exception as e:
            flash(f"Login Error: {e}")
    return redirect('/')

@app.route('/api/settings/load')
def api_settings_load():
    return jsonify(settings.load_settings())

@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    if settings.save_settings_file(request.json):
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/positions')
def api_positions():
    # UPDATED: Use persistence module
    trades = persistence.load_trades()
    for t in trades:
        t['lot_size'] = smart_trader.get_lot_size(t['symbol'])
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/closed_trades')
def api_closed_trades():
    # UPDATED: Use persistence module
    trades = persistence.load_history()
    for t in trades:
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/delete_trade/<trade_id>', methods=['POST'])
def api_delete_trade(trade_id):
    # UPDATED: Use persistence module
    if persistence.delete_trade(trade_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/update_trade', methods=['POST'])
def api_update_trade():
    data = request.json
    try:
        # UPDATED: Use trade_manager module
        if trade_manager.update_trade_protection(kite, data['id'], data['sl'], data['targets'], data.get('trailing_sl', 0), data.get('entry_price'), data.get('target_controls'), data.get('sl_to_entry', 0), data.get('exit_multiplier', 1)):
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Trade not found"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manage_trade', methods=['POST'])
def api_manage_trade():
    data = request.json
    trade_id = data.get('id')
    action = data.get('action')
    lots = int(data.get('lots', 0))
    
    # UPDATED: Use persistence and trade_manager
    trades = persistence.load_trades()
    t = next((x for x in trades if str(x['id']) == str(trade_id)), None)
    if t and lots > 0:
        lot_size = smart_trader.get_lot_size(t['symbol'])
        if trade_manager.manage_trade_position(kite, trade_id, action, lot_size, lots):
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Action Failed"})

@app.route('/api/indices')
def api_indices():
    if not bot_active:
        return jsonify({"NIFTY":0, "BANKNIFTY":0, "SENSEX":0})
    return jsonify(smart_trader.get_indices_ltp(kite))

@app.route('/api/search')
def api_search():
    current_settings = settings.load_settings()
    allowed = current_settings.get('exchanges', None)
    return jsonify(smart_trader.search_symbols(kite, request.args.get('q', ''), allowed))

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
    if not bot_active:
        return jsonify({"status": "error", "message": "Bot not connected"})
    # UPDATED: Use broker_ops module
    if broker_ops.panic_exit_all(kite):
        flash("🚨 PANIC MODE EXECUTED. ALL TRADES CLOSED.")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Failed to execute panic mode"})

@app.route('/api/import_trade', methods=['POST'])
def api_import_trade():
    if not bot_active: return jsonify({"status": "error", "message": "Bot not connected"})
    data = request.json
    try:
        final_sym = smart_trader.get_exact_symbol(data['symbol'], data['expiry'], data['strike'], data['type'])
        if not final_sym: return jsonify({"status": "error", "message": "Invalid Symbol/Strike"})
        
        # UPDATED: Use replay_engine module
        result = replay_engine.import_past_trade(
            kite, final_sym, data['entry_time'], 
            int(data['qty']), float(data['price']), 
            float(data['sl']), [float(t) for t in data['targets']],
            data.get('trailing_sl', 0), data.get('sl_to_entry', 0),
            data.get('exit_multiplier', 1), data.get('target_controls')
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/simulate_scenario', methods=['POST'])
def api_simulate_scenario():
    if not bot_active: return jsonify({"status": "error", "message": "Bot offline"})
    data = request.json
    trade_id = data.get('trade_id')
    config = data.get('config')
    
    # Call the new engine function
    result = replay_engine.simulate_trade_scenario(kite, trade_id, config)
    return jsonify(result)

@app.route('/trade', methods=['POST'])
def place_trade():
    if not bot_active: return redirect('/')
    try:
        sym = request.form['index']
        type_ = request.form['type']
        mode = request.form['mode']
        qty = int(request.form['qty'])
        order_type = request.form['order_type']
        
        limit_price = float(request.form.get('limit_price') or 0)
        sl_points = float(request.form.get('sl_points', 0))
        trailing_sl = float(request.form.get('trailing_sl') or 0)
        sl_to_entry = int(request.form.get('sl_to_entry', 0))
        exit_multiplier = int(request.form.get('exit_multiplier', 1))
        
        t1 = float(request.form.get('t1_price', 0))
        t2 = float(request.form.get('t2_price', 0))
        t3 = float(request.form.get('t3_price', 0))
        
        # UPDATED: Use common module
        can_trade, reason = common.can_place_order(mode)
        if not can_trade:
            flash(f"⛔ Trade Blocked: {reason}")
            return redirect('/')
        
        custom_targets = [t1, t2, t3] if t1 > 0 else []
        
        target_controls = []
        for i in range(1, 4):
            enabled = request.form.get(f't{i}_active') == 'on'
            lots = int(request.form.get(f't{i}_lots') or 0)
            trail_cost = request.form.get(f't{i}_cost') == 'on'
            if i == 3 and lots == 0: lots = 1000 
            target_controls.append({'enabled': enabled, 'lots': lots, 'trail_to_entry': trail_cost})
        
        final_sym = smart_trader.get_exact_symbol(sym, request.form.get('expiry'), request.form.get('strike', 0), type_)
        if not final_sym:
            flash("❌ Symbol Generation Failed")
            return redirect('/')

        # UPDATED: Use trade_manager module
        res = trade_manager.create_trade_direct(kite, mode, final_sym, qty, sl_points, custom_targets, order_type, limit_price, target_controls, trailing_sl, sl_to_entry, exit_multiplier)
        
        if res['status'] == 'success':
            flash(f"✅ Order Placed: {final_sym}")
        else:
            flash(f"❌ Error: {res['message']}")
            
    except Exception as e:
        flash(f"Error: {e}")
    return redirect('/')

@app.route('/promote/<trade_id>')
def promote(trade_id):
    # UPDATED: Use trade_manager module
    if trade_manager.promote_to_live(kite, trade_id):
        flash("✅ Promoted!")
    else:
        flash("❌ Error")
    return redirect('/')

@app.route('/close_trade/<trade_id>')
def close_trade(trade_id):
    # UPDATED: Use trade_manager module
    if trade_manager.close_trade_manual(kite, trade_id):
        flash("✅ Closed")
    else:
        flash("❌ Error")
    return redirect('/')

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    t = threading.Thread(target=background_monitor, daemon=True)
    t.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
