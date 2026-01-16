import requests
import threading
import time
import settings
import smart_trader
from managers.common import get_time_str

class TelegramManager:
    def __init__(self):
        self.base_url = "https://api.telegram.org/bot"
        self.app = None # Hold reference to Flask App

    def init_app(self, app):
        """
        Initialize with Flask app to allow DB access in background threads.
        """
        self.app = app

    def _get_config(self):
        s = settings.load_settings()
        return s.get('telegram', {})

    def _send_http_request(self, text, reply_to_id=None):
        """
        Internal blocking method to send HTTP request.
        """
        conf = self._get_config()
        if not conf.get('enable_notifications', False):
            return None
        
        token = conf.get('bot_token')
        chat_id = conf.get('channel_id')

        if not token or not chat_id:
            return None

        url = f"{self.base_url}{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_to_id:
            payload["reply_to_message_id"] = reply_to_id

        try:
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                return resp.json().get('result', {}).get('message_id')
            else:
                print(f"❌ Telegram Error: {resp.text}")
        except Exception as e:
            print(f"❌ Telegram Request Failed: {e}")
        return None

    def _bg_update_db(self, trade_id, msg_id, update_type):
        """
        Background worker to update DB with the new Message ID.
        update_type: 'SET_MAIN_ID' (for New Trade) or 'APPEND_UPDATE_ID' (for Updates)
        """
        # Local import to prevent circular dependency
        from managers.persistence import load_trades, save_trades, load_history, save_to_history_db, TRADE_LOCK
        
        try:
            with TRADE_LOCK:
                # 1. Try Active Trades
                trades = load_trades()
                found = False
                for t in trades:
                    if str(t['id']) == str(trade_id):
                        if update_type == 'SET_MAIN_ID':
                            t['telegram_msg_id'] = msg_id
                        else:
                            if 'telegram_update_ids' not in t: t['telegram_update_ids'] = []
                            t['telegram_update_ids'].append(msg_id)
                        found = True
                        break
                
                if found:
                    save_trades(trades)
                    return

                # 2. Try History (if trade closed fast)
                if not found:
                    history = load_history()
                    target = next((t for t in history if str(t['id']) == str(trade_id)), None)
                    if target:
                        # Need to parse JSON, update, and re-serialize
                        if update_type == 'SET_MAIN_ID':
                            target['telegram_msg_id'] = msg_id
                        else:
                            if 'telegram_update_ids' not in target: target['telegram_update_ids'] = []
                            target['telegram_update_ids'].append(msg_id)
                        save_to_history_db(target)
        except Exception as e:
            print(f"⚠️ Telegram BG Update Error: {e}")

    # --- PUBLIC API ---

    def send_message(self, text, reply_to_id=None):
        """
        Sends a generic message asynchronously.
        """
        def task():
            self._send_http_request(text, reply_to_id)
        
        threading.Thread(target=task).start()

    def delete_message(self, message_id):
        """
        Deletes a message asynchronously.
        """
        def task():
            conf = self._get_config()
            token = conf.get('bot_token')
            chat_id = conf.get('channel_id')
            if token and chat_id and message_id:
                try:
                    url = f"{self.base_url}{token}/deleteMessage"
                    requests.post(url, json={"chat_id": chat_id, "message_id": message_id}, timeout=5)
                except Exception as e:
                    print(f"Delete Error: {e}")
        
        threading.Thread(target=task).start()

    def notify_trade_event(self, trade, event_type, extra_data=None):
        """
        Constructs message and sends it in a BACKGROUND THREAD.
        Does NOT block the caller. Returns None immediately.
        """
        try:
            # 1. Prepare Data (Fast, In-Memory)
            raw_symbol = trade.get('symbol', 'Unknown')
            symbol = smart_trader.get_telegram_symbol(raw_symbol)
            mode = trade.get('mode', 'PAPER')
            qty = trade.get('quantity', 0)
            entry_price = trade.get('entry_price', 0)
            trade_id = trade.get('id')
            
            # Determine Thread ID (Reply to)
            thread_id = trade.get('telegram_msg_id')
            
            action_time = get_time_str()
            if isinstance(extra_data, dict) and 'time' in extra_data:
                action_time = extra_data['time']
            elif event_type == "NEW_TRADE" and trade.get('entry_time'):
                action_time = trade.get('entry_time')

            msg = ""
            update_type = "APPEND_UPDATE_ID" # Default

            if event_type == "NEW_TRADE":
                update_type = "SET_MAIN_ID"
                icon = "🔴" if mode == "LIVE" else "🟡"
                order_type = trade.get('order_type', 'MARKET')
                sl = trade.get('sl', 0)
                targets = trade.get('targets', [])
                
                msg = (
                    f"{icon} <b>NEW TRADE: {symbol}</b>\n"
                    f"Mode: {mode}\n"
                    f"Type: {order_type}\n"
                    f"Qty: {qty}\n"
                    f"Entry: {entry_price}\n"
                    f"SL: {sl}\n"
                    f"Targets: {targets}\n"
                    f"Time: {action_time}"
                )
                # New trades start new threads, no reply needed
                thread_id = None 

            elif event_type == "ACTIVE" and thread_id:
                fill_price = extra_data['price'] if isinstance(extra_data, dict) else extra_data
                msg = f"🚀 <b>Order ACTIVATED</b>\nPrice: {fill_price}\nTime: {action_time}"
                
            elif event_type == "UPDATE" and thread_id:
                update_text = extra_data if extra_data else ""
                if update_text:
                    msg = f"✏️ <b>Trade Update</b>\n{update_text}\nTime: {action_time}"
                else:
                    msg = (
                        f"✏️ <b>Protection Updated</b>\n"
                        f"New SL: {trade.get('sl')}\n"
                        f"Trailing: {trade.get('trailing_sl')}\n"
                        f"Targets: {trade.get('targets')}\n"
                        f"Time: {action_time}"
                    )

            elif event_type == "SL_HIT" and thread_id:
                pnl = extra_data.get('pnl') if isinstance(extra_data, dict) else (extra_data if extra_data else 0)
                exit_price = trade.get('exit_price', 0)
                msg = f"🛑 <b>Stop Loss Hit</b>\nExit Price: {exit_price}\nP/L: {pnl:.2f}\nTime: {action_time}"

            elif event_type == "TARGET_HIT" and thread_id:
                t_data = extra_data if isinstance(extra_data, dict) else {}
                t_num = t_data.get('t_num', '?')
                t_price = t_data.get('price', 0)
                pot_pnl = (t_price - entry_price) * qty
                msg = (
                    f"🎯 <b>Target {t_num} HIT</b>\n"
                    f"Price: {t_price}\n"
                    f"Max Potential: {pot_pnl:.2f}\n"
                    f"Time: {action_time}"
                )
                
            elif event_type == "HIGH_MADE" and thread_id:
                h_price = extra_data.get('price') if isinstance(extra_data, dict) else extra_data
                pot_pnl = (h_price - entry_price) * qty
                msg = (
                    f"📈 <b>New High Made: {h_price}</b>\n"
                    f"Max Potential: {pot_pnl:.2f}\n"
                    f"Time: {action_time}"
                )

            # 2. Spawn Background Task if message exists
            if msg:
                # Capture Flask App Reference for the thread
                app_ref = self.app

                def task():
                    # Helper to run the logic
                    def run_logic():
                        mid = self._send_http_request(msg, thread_id)
                        if mid:
                            self._bg_update_db(trade_id, mid, update_type)

                    # Wrap in App Context if available (Fixes DB Update)
                    if app_ref:
                        with app_ref.app_context():
                            run_logic()
                    else:
                        run_logic()

                threading.Thread(target=task).start()

        except Exception as e:
            print(f"Notify Error: {e}")

# Singleton Instance
bot = TelegramManager()
