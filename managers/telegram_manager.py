import requests
import threading
import time
import settings
import smart_trader
from managers.common import get_time_str

class TelegramManager:
    def __init__(self):
        self.base_url = "https://api.telegram.org/bot"
        self.app = None 

    def init_app(self, app):
        self.app = app

    def _get_config(self):
        s = settings.load_settings()
        return s.get('telegram', {})

    def _send_http_request(self, text, reply_to_id=None):
        conf = self._get_config()
        if not conf.get('enable_notifications', False): return None
        token = conf.get('bot_token')
        chat_id = conf.get('channel_id')
        if not token or not chat_id: return None
        url = f"{self.base_url}{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_to_id: payload["reply_to_message_id"] = reply_to_id
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
        from managers.persistence import load_trades, save_trades, load_history, save_to_history_db, TRADE_LOCK
        try:
            with TRADE_LOCK:
                trades = load_trades()
                found = False
                for t in trades:
                    # Strict string comparison to avoid int/str mismatch
                    if str(t['id']) == str(trade_id):
                        if update_type == 'SET_MAIN_ID': t['telegram_msg_id'] = msg_id
                        else:
                            if 'telegram_update_ids' not in t: t['telegram_update_ids'] = []
                            t['telegram_update_ids'].append(msg_id)
                        found = True
                        break
                
                if found:
                    save_trades(trades)
                    return

                if not found:
                    history = load_history()
                    target = next((t for t in history if str(t['id']) == str(trade_id)), None)
                    if target:
                        if update_type == 'SET_MAIN_ID': target['telegram_msg_id'] = msg_id
                        else:
                            if 'telegram_update_ids' not in target: target['telegram_update_ids'] = []
                            target['telegram_update_ids'].append(msg_id)
                        save_to_history_db(target)
        except Exception as e:
            print(f"⚠️ Telegram BG Update Error: {e}")

    def send_message(self, text, reply_to_id=None):
        def task(): self._send_http_request(text, reply_to_id)
        threading.Thread(target=task).start()

    def delete_message(self, message_id):
        def task():
            conf = self._get_config()
            token = conf.get('bot_token')
            chat_id = conf.get('channel_id')
            if token and chat_id and message_id:
                try:
                    url = f"{self.base_url}{token}/deleteMessage"
                    requests.post(url, json={"chat_id": chat_id, "message_id": message_id}, timeout=5)
                except Exception as e: print(f"Delete Error: {e}")
        threading.Thread(target=task).start()

    def notify_trade_event(self, trade, event_type, extra_data=None):
        try:
            raw_symbol = trade.get('symbol', 'Unknown')
            symbol = smart_trader.get_telegram_symbol(raw_symbol)
            mode = trade.get('mode', 'PAPER')
            qty = trade.get('quantity', 0)
            entry_price = trade.get('entry_price', 0)
            trade_id = trade.get('id')
            thread_id = trade.get('telegram_msg_id')
            
            action_time = get_time_str()
            if isinstance(extra_data, dict) and 'time' in extra_data: action_time = extra_data['time']
            elif event_type == "NEW_TRADE" and trade.get('entry_time'): action_time = trade.get('entry_time')

            msg = ""
            update_type = "APPEND_UPDATE_ID" 

            if event_type == "NEW_TRADE":
                update_type = "SET_MAIN_ID"
                icon = "🔴" if mode == "LIVE" else "🟡"
                order_type = trade.get('order_type', 'MARKET')
                sl = trade.get('sl', 0)
                targets = trade.get('targets', [])
                msg = (f"{icon} <b>NEW TRADE: {symbol}</b>\nMode: {mode}\nType: {order_type}\nQty: {qty}\n"
                       f"Entry: {entry_price}\nSL: {sl}\nTargets: {targets}\nTime: {action_time}")
                thread_id = None 

            elif event_type == "ACTIVE" and thread_id:
                fill_price = extra_data['price'] if isinstance(extra_data, dict) else extra_data
                msg = f"🚀 <b>Order ACTIVATED</b>\nPrice: {fill_price}\nTime: {action_time}"
                
            elif event_type == "UPDATE" and thread_id:
                update_text = extra_data if extra_data else ""
                if update_text: msg = f"✏️ <b>Trade Update</b>\n{update_text}\nTime: {action_time}"
                else: msg = (f"✏️ <b>Protection Updated</b>\nNew SL: {trade.get('sl')}\nTrailing: {trade.get('trailing_sl')}\nTargets: {trade.get('targets')}\nTime: {action_time}")

            elif event_type == "SL_HIT" and thread_id:
                pnl = extra_data.get('pnl') if isinstance(extra_data, dict) else (extra_data if extra_data else 0)
                exit_price = trade.get('exit_price', 0)
                msg = f"🛑 <b>Stop Loss Hit</b>\nExit Price: {exit_price}\nP/L: {pnl:.2f}\nTime: {action_time}"

            elif event_type == "TARGET_HIT" and thread_id:
                t_data = extra_data if isinstance(extra_data, dict) else {}
                t_num = t_data.get('t_num', '?')
                t_price = t_data.get('price', 0)
                pot_pnl = (t_price - entry_price) * qty
                msg = (f"🎯 <b>Target {t_num} HIT</b>\nPrice: {t_price}\nMax Potential: {pot_pnl:.2f}\nTime: {action_time}")
                
            elif event_type == "HIGH_MADE" and thread_id:
                h_price = extra_data.get('price') if isinstance(extra_data, dict) else extra_data
                pot_pnl = (h_price - entry_price) * qty
                msg = (f"📈 <b>New High Made: {h_price}</b>\nMax Potential: {pot_pnl:.2f}\nTime: {action_time}")

            if msg:
                app_ref = self.app
                def task():
                    def run_logic():
                        mid = self._send_http_request(msg, thread_id)
                        if mid: self._bg_update_db(trade_id, mid, update_type)
                    if app_ref:
                        with app_ref.app_context(): run_logic()
                    else: run_logic()
                threading.Thread(target=task).start()
        except Exception as e: print(f"Notify Error: {e}")

bot = TelegramManager()
