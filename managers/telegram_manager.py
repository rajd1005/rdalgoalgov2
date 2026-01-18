import requests
import json
import time
import settings
import smart_trader
from managers.common import get_time_str
from database import db, TelegramMessage

class TelegramManager:
    def __init__(self):
        self.base_url = "https://api.telegram.org/bot"

    def _get_config(self):
        s = settings.load_settings()
        return s.get('telegram', {})

    def send_message(self, text, reply_to_id=None, override_chat_id=None):
        """
        Sends a message to the configured Telegram Channel.
        Allows overriding the chat_id for specific alerts (like System Alerts).
        Returns the Message ID of the sent message.
        """
        conf = self._get_config()
        if not conf.get('enable_notifications', False):
            return None
        
        token = conf.get('bot_token')
        
        # Use the specific channel if provided, otherwise fallback to the default trade channel
        chat_id = override_chat_id if override_chat_id else conf.get('channel_id')

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
                print(f"❌ Telegram Error (Chat {chat_id}): {resp.text}")
        except Exception as e:
            print(f"❌ Telegram Request Failed: {e}")
        return None

    def notify_system_event(self, event_type, message=""):
        """
        Sends system status alerts (Online, Offline, Login Success/Fail).
        Uses 'system_channel_id' if set, otherwise uses the default 'channel_id'.
        """
        conf = self._get_config()
        sys_channel_id = conf.get('system_channel_id')

        icons = {
            "STARTUP": "🖥️",
            "ONLINE": "🟢",
            "OFFLINE": "🔴",
            "LOGIN_SUCCESS": "✅",
            "LOGIN_FAIL": "⚠️",
            "RESET": "🔄"
        }
        icon = icons.get(event_type, "ℹ️")
        
        # Format the message
        text = f"{icon} <b>SYSTEM ALERT: {event_type}</b>\n{message}\nTime: {get_time_str()}"
        
        # Send immediately using the system channel (if configured) or default
        self.send_message(text, override_chat_id=sys_channel_id)

    def notify_trade_event(self, trade, event_type, extra_data=None):
        """
        Constructs and sends notifications to ALL configured channels based on rules.
        Returns a DICT of Message IDs: {'main': 123, 'vip': 456, ...}
        """
        conf = self._get_config()
        if not conf.get('enable_notifications', False):
            return {}

        raw_symbol = trade.get('symbol', 'Unknown')
        symbol = smart_trader.get_telegram_symbol(raw_symbol)
        
        mode = trade.get('mode', 'PAPER')
        qty = trade.get('quantity', 0)
        entry_price = trade.get('entry_price', 0)
        
        # --- THREAD IDS: Handle Backward Compatibility ---
        # Old trades might have a string ID. New trades use a dict.
        stored_ids = trade.get('telegram_msg_ids', {})
        if not isinstance(stored_ids, dict):
            # If it's a string or legacy 'telegram_msg_id', assume it's for the MAIN channel
            legacy_id = trade.get('telegram_msg_id')
            stored_ids = {'main': legacy_id} if legacy_id else {}

        # --- DETERMINE ACTION TIME ---
        action_time = get_time_str() 
        if isinstance(extra_data, dict) and 'time' in extra_data:
            action_time = extra_data['time']
        elif event_type == "NEW_TRADE" and trade.get('entry_time'):
            action_time = trade.get('entry_time')

        # --- DEFINE TARGET CHANNELS & RULES ---
        all_channels = [
            {'key': 'main', 'id': conf.get('channel_id'), 'allow_all': True},
            {'key': 'vip', 'id': conf.get('vip_channel_id'), 'allow_all': False},
            {'key': 'free', 'id': conf.get('free_channel_id'), 'allow_all': False},
            {'key': 'z2h', 'id': conf.get('z2h_channel_id'), 'allow_all': False, 'custom_name': conf.get('z2h_channel_name')}
        ]
        
        # Rule: Extra channels ONLY get NEW_TRADE, ACTIVE, UPDATE
        allowed_extras = ['NEW_TRADE', 'ACTIVE', 'UPDATE']
        
        # Check if trade has specific target channels defined (Broadcast Selector)
        target_list = trade.get('target_channels') # e.g. ['main', 'vip']

        new_msg_ids = {} # To return

        # Loop through channels
        for ch in all_channels:
            chat_id = ch['id']
            if not chat_id: continue # Skip if not configured
            
            # --- FILTER 1: User Selection ---
            # If target_list exists, skipping channels NOT in the list
            if target_list is not None and ch['key'] not in target_list:
                continue

            # --- FILTER 2: Event Type ---
            # Extra channels (vip/free/z2h) only get specific events unless allow_all is True (Main)
            if not ch['allow_all'] and event_type not in allowed_extras:
                continue
            
            # Get Reply-To ID for this specific channel
            reply_to = stored_ids.get(ch['key'])

            # Logic for NEW_TRADE (Start new thread) vs REPLIES
            if event_type == "NEW_TRADE":
                reply_to = None # Reset for new thread

            # If it's a reply event (not NEW_TRADE) but we don't have a thread ID for this channel, SKIP
            if event_type != "NEW_TRADE" and not reply_to:
                continue

            # --- BUILD MESSAGE CONTENT ---
            msg = ""
            
            if event_type == "NEW_TRADE":
                icon = "🔴" if mode == "LIVE" else "🟡"
                order_type = trade.get('order_type', 'MARKET')
                sl = trade.get('sl', 0)
                targets = trade.get('targets', [])
                
                # Custom Header for Z2H or other channels with custom names
                header = f"{icon} <b>NEW TRADE: {symbol}</b>"
                if ch.get('custom_name'):
                    # Use the custom name (e.g. "Jackpot Calls") in the header
                    header = f"🚀 <b>[{ch['custom_name']}]</b>\n{header}"

                msg = (
                    f"{header}\n"
                    f"Mode: {mode}\n"
                    f"Type: {order_type}\n"
                    f"Qty: {qty}\n"
                    f"Entry: {entry_price}\n"
                    f"SL: {sl}\n"
                    f"Targets: {targets}\n"
                    f"Time: {action_time}"
                )

            elif event_type == "ACTIVE":
                fill_price = extra_data['price'] if isinstance(extra_data, dict) else extra_data
                msg = f"🚀 <b>Order ACTIVATED</b>\nPrice: {fill_price}\nTime: {action_time}"
                
            elif event_type == "UPDATE":
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

            elif event_type == "SL_HIT":
                pnl = extra_data.get('pnl') if isinstance(extra_data, dict) else (extra_data if extra_data else 0)
                exit_price = trade.get('exit_price', 0)
                msg = f"🛑 <b>Stop Loss Hit</b>\nExit Price: {exit_price}\nP/L: {pnl:.2f}\nTime: {action_time}"

            elif event_type == "TARGET_HIT":
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
                
            elif event_type == "HIGH_MADE":
                if isinstance(extra_data, dict): h_price = extra_data.get('price')
                else: h_price = extra_data
                pot_pnl = (h_price - entry_price) * qty
                msg = (
                    f"📈 <b>New High Made: {h_price}</b>\n"
                    f"Max Potential: {pot_pnl:.2f}\n"
                    f"Time: {action_time}"
                )

            # --- SEND & SAVE ---
            if msg:
                sent_id = self.send_message(msg, reply_to_id=reply_to, override_chat_id=chat_id)
                if sent_id:
                    self._save_msg_to_db(trade.get('id'), sent_id, chat_id)
                    
                    # If this was a new trade, record the thread ID for this channel
                    if event_type == "NEW_TRADE":
                        new_msg_ids[ch['key']] = sent_id

        # Return the collected IDs (only useful for NEW_TRADE to update the Trade Record)
        return new_msg_ids

    def _save_msg_to_db(self, trade_id, msg_id, chat_id):
        """Helper to safely save message ID to database"""
        if not trade_id or not msg_id or not chat_id:
            return
            
        try:
            rec = TelegramMessage(trade_id=str(trade_id), message_id=msg_id, chat_id=str(chat_id))
            db.session.add(rec)
            db.session.commit()
        except Exception as e:
            print(f"⚠️ Failed to save Telegram Msg ID: {e}")
            try: db.session.rollback()
            except: pass

    def delete_trade_messages(self, trade_id):
        """
        Deletes all Telegram messages (Thread & Replies) associated with a Trade ID.
        Iterates through the DB records, so it handles ALL channels automatically.
        """
        try:
            # 1. Fetch all message records for this trade (includes Main, VIP, Free, Z2H)
            messages = TelegramMessage.query.filter_by(trade_id=str(trade_id)).all()
            
            if not messages:
                return

            conf = self._get_config()
            token = conf.get('bot_token')
            if not token: 
                return

            delete_url = f"{self.base_url}{token}/deleteMessage"

            # 2. Loop and Delete from Telegram
            for msg in messages:
                try:
                    payload = {"chat_id": msg.chat_id, "message_id": msg.message_id}
                    requests.post(delete_url, json=payload, timeout=2)
                except Exception as req_err:
                    print(f"TG Delete Request Error: {req_err}")

                # 3. Remove from Local DB
                db.session.delete(msg)
            
            db.session.commit()
            print(f"🗑️ Deleted {len(messages)} Telegram messages for Trade {trade_id}")

        except Exception as e:
            print(f"❌ Error deleting Telegram messages: {e}")
            try: db.session.rollback()
            except: pass

# Singleton Instance
bot = TelegramManager()
