import os
import json
import threading
import time
import gc 
import secrets
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, flash, jsonify, url_for
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from kiteconnect import KiteConnect
from sqlalchemy import text 
import config

# --- REFACTORED IMPORTS ---
from managers import persistence, trade_manager, risk_engine, replay_engine, common, broker_ops
from managers.telegram_manager import bot as telegram_bot
# --------------------------
import smart_trader
import settings
from database import db, AppSetting, User
# Auto-login import removed

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.from_object(config)

# Initialize Database & Apply Fixes
db.init_app(app)
with app.app_context():
    db.create_all()
    
    # --- [CRITICAL FIX] AUTO-UPDATE DATABASE SCHEMA ---
    try:
        db.session.execute(text('ALTER TABLE "user" ALTER COLUMN password TYPE VARCHAR(255)'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
    # --------------------------------------------------

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- GLOBAL SESSION STORAGE (Multi-User) ---
user_sessions = {}

def get_user_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {'kite': None, 'active': False, 'state': 'OFFLINE', 'error': None}
    return user_sessions[user_id]

# --- USER SPECIFIC LOGIN LOGIC ---
def start_user_session(user_id):
    """
    Initializes the Kite Object for manual login.
    AUTO-LOGIN REMOVED: This function no longer triggers Selenium.
    """
    with app.app_context():
        user = User.query.get(user_id)
        if not user: return

        session = get_user_session(user_id)
        creds = user.get_creds()

        # 1. Check Credentials
        if not creds or not creds.get('user_id'):
            session['state'] = 'SETUP'
            session['error'] = 'Credentials Missing'
            return

        # 2. Init Kite Object (Required for generating Manual Login URL)
        try:
            k = KiteConnect(api_key=creds['api_key'])
            session['kite'] = k 
            session['state'] = 'OFFLINE' # Ready for manual login
            session['error'] = None
            print(f"✅ User {user.username}: Kite Object Initialized (Waiting for Manual Login)")

        except Exception as e:
            session['state'] = 'FAILED'
            session['error'] = f"Kite Init Error: {str(e)}"
            print(f"❌ User {user.username} Critical Error: {e}")

def stop_user_session(user_id):
    if user_id in user_sessions:
        user_sessions[user_id]['active'] = False
        user_sessions[user_id]['state'] = 'PAUSED'

# --- BACKGROUND MONITOR (MULTI-USER) ---
def background_monitor():
    with app.app_context():
        print("🖥️ Multi-User Background Monitor Started (Manual Mode)")
        time.sleep(5)
        
        while True:
            active_ids = list(user_sessions.keys())
            
            for uid in active_ids:
                session = user_sessions[uid]
                
                # Only monitor ACTIVE sessions
                if not session['active']:
                    continue

                if session['kite']:
                    try:
                        if not hasattr(session['kite'], "mock_instruments"):
                            if not session['kite'].access_token: raise Exception("No Token")
                        
                        risk_engine.update_risk_engine(session['kite'], user_id=uid)
                        
                    except Exception as e:
                        err = str(e)
                        if "Token is invalid" in err or "access_token" in err:
                            print(f"⚠️ User {uid} Connection Lost: {err}")
                            session['active'] = False
                            session['state'] = 'OFFLINE' # Reset to Offline
                        else:
                            print(f"⚠️ User {uid} Risk Loop Warning: {err}")

            time.sleep(1)

# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == "admin" and password == config.ADMIN_PASSWORD:
            user = User.query.filter_by(username="admin").first()
            if not user:
                hashed = generate_password_hash(config.ADMIN_PASSWORD)
                user = User(username="admin", password=hashed, is_admin=True)
                db.session.add(user)
                db.session.commit()
            login_user(user)
            return redirect(url_for('home'))

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            if not user.is_active_sub:
                flash("❌ Subscription/Trial Expired. Contact Admin.")
            else:
                login_user(user)
                return redirect(url_for('home'))
        else:
            flash("❌ Invalid Credentials")
            
    return render_template('login.html') 

@app.route('/logout')
@login_required
def logout():
    stop_user_session(current_user.id)
    logout_user()
    flash("Logged Out")
    return redirect(url_for('login'))

@app.route('/magic_login/<token>/<int:uid>')
def magic_login(token, uid):
    user = User.query.get(uid)
    if user:
        login_user(user)
        return redirect(url_for('home'))
    return "Invalid Link"

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin: return "Access Denied", 403
    users = User.query.all()
    return render_template('admin.html', users=users)

@app.route('/admin/add_user', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin: return "Access Denied", 403
    
    username = request.form['username']
    password = request.form['password']
    days = int(request.form.get('days', 7))
    is_trial = request.form.get('is_trial') == 'on'
    
    if User.query.filter_by(username=username).first():
        flash("User already exists")
        return redirect('/admin')
        
    hashed = generate_password_hash(password)
    expiry = datetime.now() + timedelta(days=days)
    
    new_user = User(username=username, password=hashed, subscription_end=expiry, is_trial=is_trial)
    db.session.add(new_user)
    db.session.commit()
    
    flash(f"User {username} created!")
    return redirect('/admin')

@app.route('/admin/generate_link/<int:uid>')
@login_required
def generate_link(uid):
    if not current_user.is_admin: return "Access Denied", 403
    token = secrets.token_urlsafe(16)
    link = url_for('magic_login', token=token, uid=uid, _external=True)
    return jsonify({"link": link})

@app.route('/admin/reset_password', methods=['POST'])
@login_required
def admin_reset_password():
    if not current_user.is_admin: return "Access Denied", 403
    
    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')
    
    user = User.query.get(user_id)
    if user:
        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash(f"✅ Password updated for {user.username}")
    else:
        flash("❌ User not found")
        
    return redirect('/admin')

@app.route('/')
@login_required
def home():
    session = get_user_session(current_user.id)
    
    # Check if we need to initialize the session (first load)
    if not session['kite'] and not session['error']:
        start_user_session(current_user.id)
        session = get_user_session(current_user.id)

    if session['active'] and session['kite']:
        trades = persistence.load_trades(user_id=current_user.id)
        for t in trades: 
            t['symbol'] = smart_trader.get_display_name(t['symbol'])
        active_trades = [t for t in trades if t['status'] in ['OPEN', 'PROMOTED_LIVE', 'PENDING', 'MONITORING']]
        
        return render_template('dashboard.html', 
                               is_active=True, 
                               trades=active_trades,
                               username=current_user.username,
                               expiry=current_user.subscription_end)
    
    creds = current_user.get_creds() or {}
    form_creds = {
        "user_id": creds.get('user_id', ''),
        "password": creds.get('password', ''),
        "totp": creds.get('totp', ''),
        "api_key": creds.get('api_key', ''),
        "api_secret": creds.get('api_secret', '')
    }
    
    login_url = session['kite'].login_url() if session['kite'] else "#"
    return render_template('dashboard.html', 
                           is_active=False, 
                           state=session['state'], 
                           error=session['error'], 
                           login_url=login_url, 
                           creds=form_creds,
                           username=current_user.username)

@app.route('/api/save_credentials', methods=['POST'])
@login_required
def api_save_credentials():
    data = request.json
    try:
        current_user.set_creds(
            api_key=data.get("api_key"),
            api_secret=data.get("api_secret"),
            totp=data.get("totp"),
            uid=data.get("user_id"),
            pwd=data.get("password")
        )
        db.session.commit()
        
        # Re-initialize Kite object with new credentials
        start_user_session(current_user.id)
        
        flash("✅ Credentials Saved! Please click Login.")
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/status')
@login_required
def api_status():
    session = get_user_session(current_user.id)
    login_url = session['kite'].login_url() if session['kite'] else "#"
    return jsonify({"active": session['active'], "state": session['state'], "login_url": login_url})

@app.route('/reset_connection')
@login_required
def reset_connection():
    stop_user_session(current_user.id)
    flash("⏸️ System Paused. Edit Credentials or Resume.")
    return redirect('/')

@app.route('/api/resume_login')
@login_required
def resume_login():
    session = get_user_session(current_user.id)
    session['state'] = 'OFFLINE'
    return jsonify({"status": "success"})

@app.route('/callback')
def callback():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
        
    t = request.args.get("request_token")
    if t:
        try:
            session = get_user_session(current_user.id)
            creds = current_user.get_creds()
            
            if not session['kite']:
                session['kite'] = KiteConnect(api_key=creds['api_key'])
                
            data = session['kite'].generate_session(t, api_secret=creds['api_secret'])
            session['kite'].set_access_token(data["access_token"])
            
            session['active'] = True
            session['state'] = 'IDLE'
            smart_trader.fetch_instruments(session['kite'])
            
            flash("✅ System Online")
        except Exception as e:
            flash(f"Login Error: {e}")
    return redirect('/')

# --- SETTINGS & TRADING ROUTES ---

@app.route('/api/settings/load')
@login_required
def api_settings_load():
    s = settings.load_settings()
    try:
        today_str = time.strftime("%Y-%m-%d")
        trades = persistence.load_trades(user_id=current_user.id)
        history = persistence.load_history(user_id=current_user.id)
        count = 0
        if trades:
            for t in trades:
                if t.get('entry_time', '').startswith(today_str): count += 1
        if history:
            for t in history:
                if t.get('entry_time', '').startswith(today_str): count += 1
        s['is_first_trade'] = (count == 0)
    except:
        s['is_first_trade'] = False
    return jsonify(s)

@app.route('/api/settings/save', methods=['POST'])
@login_required
def api_settings_save():
    if settings.save_settings_file(request.json):
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/positions')
@login_required
def api_positions():
    trades = persistence.load_trades(user_id=current_user.id)
    for t in trades:
        t['lot_size'] = smart_trader.get_lot_size(t['symbol'])
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/closed_trades')
@login_required
def api_closed_trades():
    trades = persistence.load_history(user_id=current_user.id)
    for t in trades:
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    return jsonify(trades)

@app.route('/api/delete_trade/<trade_id>', methods=['POST'])
@login_required
def api_delete_trade(trade_id):
    if persistence.delete_trade(trade_id, user_id=current_user.id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/api/update_trade', methods=['POST'])
@login_required
def api_update_trade():
    session = get_user_session(current_user.id)
    data = request.json
    try:
        if trade_manager.update_trade_protection(session['kite'], data['id'], data['sl'], data['targets'], data.get('trailing_sl', 0), data.get('entry_price'), data.get('target_controls'), data.get('sl_to_entry', 0), data.get('exit_multiplier', 1), user_id=current_user.id):
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Trade not found"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manage_trade', methods=['POST'])
@login_required
def api_manage_trade():
    session = get_user_session(current_user.id)
    data = request.json
    trade_id = data.get('id')
    action = data.get('action')
    lots = int(data.get('lots', 0))
    trades = persistence.load_trades(user_id=current_user.id)
    t = next((x for x in trades if str(x['id']) == str(trade_id)), None)
    if t and lots > 0:
        lot_size = smart_trader.get_lot_size(t['symbol'])
        if trade_manager.manage_trade_position(session['kite'], trade_id, action, lot_size, lots, user_id=current_user.id):
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Action Failed"})

@app.route('/api/indices')
@login_required
def api_indices():
    session = get_user_session(current_user.id)
    if not session['active']:
        return jsonify({"NIFTY":0, "BANKNIFTY":0, "SENSEX":0})
    return jsonify(smart_trader.get_indices_ltp(session['kite']))

@app.route('/api/search')
@login_required
def api_search():
    session = get_user_session(current_user.id)
    current_settings = settings.load_settings()
    allowed = current_settings.get('exchanges', None)
    return jsonify(smart_trader.search_symbols(session['kite'], request.args.get('q', ''), allowed))

@app.route('/api/details')
@login_required
def api_details():
    session = get_user_session(current_user.id)
    return jsonify(smart_trader.get_symbol_details(session['kite'], request.args.get('symbol', '')))

@app.route('/api/chain')
@login_required
def api_chain():
    return jsonify(smart_trader.get_chain_data(request.args.get('symbol'), request.args.get('expiry'), request.args.get('type'), float(request.args.get('ltp', 0))))

@app.route('/api/specific_ltp')
@login_required
def api_s_ltp():
    session = get_user_session(current_user.id)
    return jsonify({"ltp": smart_trader.get_specific_ltp(session['kite'], request.args.get('symbol'), request.args.get('expiry'), request.args.get('strike'), request.args.get('type'))})

@app.route('/api/panic_exit', methods=['POST'])
@login_required
def api_panic_exit():
    session = get_user_session(current_user.id)
    if not session['active']:
        return jsonify({"status": "error", "message": "Bot not connected"})
    if broker_ops.panic_exit_all(session['kite']):
        flash("🚨 PANIC MODE EXECUTED. ALL TRADES CLOSED.")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Failed to execute panic mode"})

@app.route('/api/manual_trade_report', methods=['POST'])
@login_required
def api_manual_trade_report():
    trade_id = request.json.get('trade_id')
    if not trade_id: return jsonify({"status": "error", "message": "Trade ID missing"})
    result = risk_engine.send_manual_trade_report(trade_id, user_id=current_user.id)
    return jsonify(result)

@app.route('/api/manual_summary', methods=['POST'])
@login_required
def api_manual_summary():
    mode = request.json.get('mode', 'PAPER')
    result = risk_engine.send_manual_summary(mode, user_id=current_user.id)
    return jsonify(result)

@app.route('/api/manual_trade_status', methods=['POST'])
@login_required
def api_manual_trade_status():
    mode = request.json.get('mode', 'PAPER')
    result = risk_engine.send_manual_trade_status(mode, user_id=current_user.id)
    return jsonify(result)

@app.route('/api/test_telegram', methods=['POST'])
def test_telegram():
    token = request.form.get('token')
    chat = request.form.get('chat_id')
    if not token or not chat: return jsonify({"status": "error", "message": "Missing credentials"})
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": "✅ <b>RD Algo Terminal:</b> Test Message Received!", "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200: return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": f"Telegram API Error: {r.text}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/import_trade', methods=['POST'])
@login_required
def api_import_trade():
    session = get_user_session(current_user.id)
    if not session['active']: return jsonify({"status": "error", "message": "Bot not connected"})
    data = request.json
    try:
        final_sym = smart_trader.get_exact_symbol(data['symbol'], data['expiry'], data['strike'], data['type'])
        if not final_sym: return jsonify({"status": "error", "message": "Invalid Symbol/Strike"})
        selected_channel = data.get('target_channel', 'main')
        target_channels = [selected_channel] 
        result = replay_engine.import_past_trade(
            session['kite'], final_sym, data['entry_time'], int(data['qty']), float(data['price']), 
            float(data['sl']), [float(t) for t in data['targets']],
            data.get('trailing_sl', 0), data.get('sl_to_entry', 0),
            data.get('exit_multiplier', 1), data.get('target_controls'),
            target_channels=target_channels, user_id=current_user.id
        )
        queue = result.get('notification_queue', [])
        trade_ref = result.get('trade_ref', {})
        if queue and trade_ref:
            def send_seq_notifications(uid):
                with app.app_context():
                    msg_ids = telegram_bot.notify_trade_event(trade_ref, "NEW_TRADE")
                    if msg_ids:
                        from managers.persistence import load_trades, save_trades, save_to_history_db
                        trade_id = trade_ref['id']
                        updated_ref = False
                        if isinstance(msg_ids, dict):
                            ids_dict = msg_ids
                            main_id = msg_ids.get(selected_channel) or msg_ids.get('main')
                        else:
                            ids_dict = {'main': msg_ids}
                            main_id = msg_ids
                        trades = load_trades(user_id=uid)
                        for t in trades:
                            if str(t['id']) == str(trade_id):
                                t['telegram_msg_ids'] = ids_dict
                                t['telegram_msg_id'] = main_id 
                                save_trades(trades, user_id=uid)
                                updated_ref = True
                                break
                        if not updated_ref:
                            trade_ref['telegram_msg_ids'] = ids_dict
                            trade_ref['telegram_msg_id'] = main_id
                            save_to_history_db(trade_ref, user_id=uid)
                            trade_ref['telegram_msg_ids'] = ids_dict
                            trade_ref['telegram_msg_id'] = main_id
                    for item in queue:
                        evt = item['event']
                        if evt == 'NEW_TRADE': continue
                        time.sleep(1.0)
                        dat = item.get('data')
                        t_obj = item.get('trade', trade_ref).copy() 
                        if 'id' not in t_obj: t_obj['id'] = trade_ref['id']
                        t_obj['telegram_msg_ids'] = trade_ref.get('telegram_msg_ids')
                        t_obj['telegram_msg_id'] = trade_ref.get('telegram_msg_id')
                        telegram_bot.notify_trade_event(t_obj, evt, dat)
            t = threading.Thread(target=send_seq_notifications, args=(current_user.id,))
            t.start()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/simulate_scenario', methods=['POST'])
@login_required
def api_simulate_scenario():
    session = get_user_session(current_user.id)
    if not session['active']: return jsonify({"status": "error", "message": "Bot offline"})
    data = request.json
    trade_id = data.get('trade_id')
    config = data.get('config')
    result = replay_engine.simulate_trade_scenario(session['kite'], trade_id, config)
    return jsonify(result)

@app.route('/api/sync', methods=['POST'])
@login_required
def api_sync():
    session = get_user_session(current_user.id)
    login_url = session['kite'].login_url() if session['kite'] else "#"
    response = {
        "status": {"active": session['active'], "state": session['state'], "login_url": login_url}, 
        "indices": {"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0}, 
        "positions": [], "closed_trades": [], "specific_ltp": 0
    }
    if session['active']:
        try: response["indices"] = smart_trader.get_indices_ltp(session['kite'])
        except: pass
    trades = persistence.load_trades(user_id=current_user.id)
    for t in trades:
        t['lot_size'] = smart_trader.get_lot_size(t['symbol'])
        t['symbol'] = smart_trader.get_display_name(t['symbol'])
    response["positions"] = trades
    if request.json.get('include_closed'):
        history = persistence.load_history(user_id=current_user.id)
        for t in history:
            t['symbol'] = smart_trader.get_display_name(t['symbol'])
        response["closed_trades"] = history
    req_ltp = request.json.get('ltp_req')
    if session['active'] and req_ltp and req_ltp.get('symbol'):
        try:
            response["specific_ltp"] = smart_trader.get_specific_ltp(session['kite'], req_ltp['symbol'], req_ltp['expiry'], req_ltp['strike'], req_ltp['type'])
        except: pass
    return jsonify(response)

@app.route('/trade', methods=['POST'])
@login_required
def place_trade():
    session = get_user_session(current_user.id)
    if not session['active']: return redirect('/')
    try:
        raw_mode = request.form['mode']
        mode_input = raw_mode.strip().upper()
        sym = request.form['index']
        type_ = request.form['type']
        input_qty = int(request.form['qty'])
        order_type = request.form['order_type']
        limit_price = float(request.form.get('limit_price') or 0)
        sl_points = float(request.form.get('sl_points', 0))
        trailing_sl = float(request.form.get('trailing_sl') or 0)
        sl_to_entry = int(request.form.get('sl_to_entry', 0))
        exit_multiplier = int(request.form.get('exit_multiplier', 1))
        t1 = float(request.form.get('t1_price', 0))
        t2 = float(request.form.get('t2_price', 0))
        t3 = float(request.form.get('t3_price', 0))
        target_channels = ['main']
        selected_channel = request.form.get('target_channel')
        if selected_channel in ['vip', 'free', 'z2h']: target_channels.append(selected_channel)
        can_trade, reason = common.can_place_order("LIVE" if mode_input == "LIVE" else "PAPER")
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
        app_settings = settings.load_settings()
        def execute(ex_mode, ex_qty, ex_channels, overrides=None):
            use_sl_points = sl_points
            use_target_controls = target_controls
            use_custom_targets = custom_targets 
            use_ratios = None
            if overrides:
                use_trail = float(overrides.get('trailing_sl', trailing_sl))
                use_sl_entry = int(overrides.get('sl_to_entry', sl_to_entry))
                use_exit_mult = int(overrides.get('exit_multiplier', exit_multiplier))
                if 'sl_points' in overrides: use_sl_points = float(overrides['sl_points'])
                if 'target_controls' in overrides: use_target_controls = overrides['target_controls']
                if 'ratios' in overrides: use_ratios = overrides['ratios']
                if 'custom_targets' in overrides: use_custom_targets = overrides['custom_targets']
            else:
                use_trail = trailing_sl
                use_sl_entry = sl_to_entry
                use_exit_mult = exit_multiplier
            return trade_manager.create_trade_direct(session['kite'], ex_mode, final_sym, ex_qty, use_sl_points, use_custom_targets, order_type, limit_price, use_target_controls, use_trail, use_sl_entry, use_exit_mult, target_channels=ex_channels, risk_ratios=use_ratios, user_id=current_user.id)
        target_mode_conf = "LIVE" if mode_input == "SHADOW" else mode_input
        mode_conf = app_settings['modes'].get(target_mode_conf, {})
        clean_sym = sym.split(':')[0].strip().upper()
        symbol_override = {}
        if 'symbol_sl' in mode_conf and clean_sym in mode_conf['symbol_sl']:
            s_data = mode_conf['symbol_sl'][clean_sym]
            if isinstance(s_data, (int, float)):
                symbol_override['sl_points'] = float(s_data)
            elif isinstance(s_data, dict):
                s_sl = float(s_data.get('sl', 0))
                if s_sl > 0:
                    symbol_override['sl_points'] = s_sl
                    t_points = s_data.get('targets', [])
                    if len(t_points) == 3:
                        new_ratios = [t / s_sl for t in t_points]
                        symbol_override['ratios'] = new_ratios
                        symbol_override['custom_targets'] = []
        if mode_input == "SHADOW":
            can_live, reason = common.can_place_order("LIVE")
            if not can_live:
                flash(f"❌ Shadow Blocked: LIVE Mode is Disabled/Blocked ({reason})")
                return redirect('/')
            try:
                val = request.form.get('live_qty')
                live_qty = int(val) if val else input_qty
            except (ValueError, TypeError): live_qty = input_qty
            live_controls = []
            for i in range(1, 4):
                enabled = request.form.get(f'live_t{i}_active') == 'on'
                try: lots = int(request.form.get(f'live_t{i}_lots'))
                except: lots = 0
                full = request.form.get(f'live_t{i}_full') == 'on'
                cost = request.form.get(f'live_t{i}_cost') == 'on'
                if full: lots = 1000
                live_controls.append({'enabled': enabled, 'lots': lots, 'trail_to_entry': cost})
            try: live_sl_points = float(request.form.get('live_sl_points'))
            except: live_sl_points = sl_points
            try: live_trail = float(request.form.get('live_trailing_sl'))
            except: live_trail = trailing_sl 
            try: live_entry_sl = int(request.form.get('live_sl_to_entry'))
            except: live_entry_sl = sl_to_entry
            try: live_exit_mult = int(request.form.get('live_exit_multiplier'))
            except: live_exit_mult = exit_multiplier
            try:
                lt1 = float(request.form.get('live_t1_price', 0))
                lt2 = float(request.form.get('live_t2_price', 0))
                lt3 = float(request.form.get('live_t3_price', 0))
                live_custom_targets = [lt1, lt2, lt3]
            except: live_custom_targets = custom_targets
            live_overrides = {'trailing_sl': live_trail, 'sl_to_entry': live_entry_sl, 'exit_multiplier': live_exit_mult, 'sl_points': live_sl_points, 'target_controls': live_controls, 'custom_targets': live_custom_targets, 'ratios': None}
            res_live = execute("LIVE", live_qty, [], overrides=live_overrides)
            if res_live['status'] != 'success':
                flash(f"❌ Shadow Failed: LIVE Execution Error ({res_live['message']})")
                return redirect('/')
            time.sleep(1)
            paper_qty = input_qty
            res_paper = execute("PAPER", paper_qty, target_channels, overrides=None)
            if res_paper['status'] == 'success': flash(f"👻 Shadow Executed: ✅ LIVE | ✅ PAPER")
            else: flash(f"⚠️ Shadow Partial: ✅ LIVE | ❌ PAPER Failed ({res_paper['message']})")
        else:
            can_trade, reason = common.can_place_order(mode_input)
            if not can_trade:
                flash(f"⛔ Trade Blocked: {reason}")
                return redirect('/')
            final_qty = input_qty
            std_overrides = None
            if symbol_override: std_overrides = symbol_override.copy()
            res = execute(mode_input, final_qty, target_channels, overrides=std_overrides)
            if res['status'] == 'success': flash(f"✅ Order Placed: {final_sym}")
            else: flash(f"❌ Error: {res['message']}")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect('/')

@app.route('/promote/<trade_id>')
@login_required
def promote(trade_id):
    session = get_user_session(current_user.id)
    if trade_manager.promote_to_live(session['kite'], trade_id, user_id=current_user.id): flash("✅ Promoted!")
    else: flash("❌ Error")
    return redirect('/')

@app.route('/close_trade/<trade_id>')
@login_required
def close_trade(trade_id):
    session = get_user_session(current_user.id)
    if trade_manager.close_trade_manual(session['kite'], trade_id, user_id=current_user.id): flash("✅ Closed")
    else: flash("❌ Error")
    return redirect('/')

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    t = threading.Thread(target=background_monitor, daemon=True)
    t.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
