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
                print(f"❌ Telegram Error: {resp.text}")
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
        Constructs and sends a notification based on the event type.
        Returns the Message ID if a new thread is started (NEW_TRADE).
        Automatically saves the resulting Message ID to the database linked to the Trade ID.
        """
        raw_symbol = trade.get('symbol', 'Unknown')
        # --- FORMAT SYMBOL USING SMART_TRADER ---
        symbol = smart_trader.get_telegram_symbol(raw_symbol)
        
        mode = trade.get('mode', 'PAPER')
        qty = trade.get('quantity', 0)
        entry_price = trade.get('entry_price', 0)
        
        # Determine Thread ID (Reply to the original "Trade Added" message)
        thread_id = trade.get('telegram_msg_id')
        
        # --- DETERMINE ACTION TIME ---
        # Default to current time, but override if 'time' is passed in extra_data
        action_time = get_time_str() 
        
        if isinstance(extra_data, dict) and 'time' in extra_data:
            action_time = extra_data['time']
        elif event_type == "NEW_TRADE" and trade.get('entry_time'):
            # For NEW_TRADE, prefer the trade's specific entry timestamp
            action_time = trade.get('entry_time')

        msg = ""
        
        if event_type == "NEW_TRADE":
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
            # New trades start a new thread, so no reply_id needed
            msg_id = self.send_message(msg)
            
            # --- SAVE MSG ID TO DB ---
            self._save_msg_to_db(trade.get('id'), msg_id)
            return msg_id

        # For updates/exits, we need a thread_id. If missing, we can't reply properly.
        if not thread_id:
            return None

        if event_type == "ACTIVE":
            # Handle float (Live) or Dict (Import)
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
            # Handle float (Live) or Dict (Import)
            pnl = extra_data.get('pnl') if isinstance(extra_data, dict) else (extra_data if extra_data else 0)
            exit_price = trade.get('exit_price', 0)
            msg = f"🛑 <b>Stop Loss Hit</b>\nExit Price: {exit_price}\nP/L: {pnl:.2f}\nTime: {action_time}"

        elif event_type == "TARGET_HIT":
            # extra_data is always a dict for Target Hit
            t_data = extra_data if isinstance(extra_data, dict) else {}
            t_num = t_data.get('t_num', '?')
            t_price = t_data.get('price', 0)
            
            # Calculate Max Potential
            pot_pnl = (t_price - entry_price) * qty
            
            msg = (
                f"🎯 <b>Target {t_num} HIT</b>\n"
                f"Price: {t_price}\n"
                f"Max Potential: {pot_pnl:.2f}\n"
                f"Time: {action_time}"
            )
            
        elif event_type == "HIGH_MADE":
            # Handle float (Live) or Dict (Import)
            if isinstance(extra_data, dict):
                h_price = extra_data.get('price')
            else:
                h_price = extra_data
                
            # Calculate Max Potential
            pot_pnl = (h_price - entry_price) * qty
            
            msg = (
                f"📈 <b>New High Made: {h_price}</b>\n"
                f"Max Potential: {pot_pnl:.2f}\n"
                f"Time: {action_time}"
            )

        if msg:
            msg_id = self.send_message(msg, reply_to_id=thread_id)
            # --- SAVE MSG ID TO DB ---
            self._save_msg_to_db(trade.get('id'), msg_id)
            return msg_id
            
        return None

    def _save_msg_to_db(self, trade_id, msg_id):
        """Helper to safely save message ID to database"""
        if not trade_id or not msg_id:
            return
            
        try:
            # We need the chat_id to delete later
            conf = self._get_config()
            chat_id = conf.get('channel_id')
            
            if chat_id:
                rec = TelegramMessage(trade_id=str(trade_id), message_id=msg_id, chat_id=str(chat_id))
                db.session.add(rec)
                db.session.commit()
        except Exception as e:
            print(f"⚠️ Failed to save Telegram Msg ID: {e}")
            try:
                db.session.rollback()
            except:
                pass

    def delete_trade_messages(self, trade_id):
        """
        Deletes all Telegram messages (Thread & Replies) associated with a Trade ID.
        """
        try:
            # 1. Fetch all message records for this trade
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
            try:
                db.session.rollback()
            except:
                pass

# Singleton Instance
bot = TelegramManager()
