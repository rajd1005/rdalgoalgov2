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
        Allows overriding the chat_id for specific alerts (like System Alerts or Extra Channels).
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
        Supports multiple channels (Main + 3 Extra) with event filtering.
        Updates the trade's `telegram_msg_ids` dictionary with the new message IDs.
        Returns the Main Channel Message ID for backward compatibility.
        """
        conf = self._get_config()
        
        # 1. Determine Target Channels
        # Default to 'main' if not specified in trade
        target_channels = trade.get('notify_channels', ['main'])
        
        # 2. Build Channel Map (Internal Key -> Chat ID)
        channel_map = {'main': conf.get('channel_id')}
        
        # Add Extra Channels from Settings if they exist
        if 'extra_channels' in conf:
            for ch in conf['extra_channels']:
                if ch.get('enabled') and ch.get('chat_id'):
                    channel_map[ch['id']] = ch['chat_id']

        # 3. Prepare Message Content
        raw_symbol = trade.get('symbol', 'Unknown')
        symbol = smart_trader.get_telegram_symbol(raw_symbol)
        mode = trade.get('mode', 'PAPER')
        qty = trade.get('quantity', 0)
        entry_price = trade.get('entry_price', 0)
        
        # Default Action Time
        action_time = get_time_str()
        if isinstance(extra_data, dict) and 'time' in extra_data:
            action_time = extra_data['time']
        elif event_type == "NEW_TRADE" and trade.get('entry_time'):
            action_time = trade.get('entry_time')

        msg = ""

        # --- MESSAGE CONSTRUCTION ---
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
            h_price = extra_data.get('price') if isinstance(extra_data, dict) else extra_data
            pot_pnl = (h_price - entry_price) * qty
            msg = (
                f"📈 <b>New High Made: {h_price}</b>\n"
                f"Max Potential: {pot_pnl:.2f}\n"
                f"Time: {action_time}"
            )

        if not msg:
            return None

        # 4. SEND TO CHANNELS
        sent_main_id = None
        
        # Ensure telegram_msg_ids dictionary exists in trade object
        if 'telegram_msg_ids' not in trade or not isinstance(trade['telegram_msg_ids'], dict):
            trade['telegram_msg_ids'] = {}
            # Backward compatibility check
            if trade.get('telegram_msg_id'):
                trade['telegram_msg_ids']['main'] = trade['telegram_msg_id']

        for ch_key in target_channels:
            chat_id = channel_map.get(ch_key)
            if not chat_id: 
                continue

            # --- EVENT FILTERING ---
            # Main Channel gets ALL events.
            # Extra Channels get ONLY: NEW_TRADE, ACTIVE, UPDATE
            if ch_key != 'main' and event_type not in ['NEW_TRADE', 'ACTIVE', 'UPDATE']:
                continue

            # --- THREADING LOGIC ---
            # Get the thread ID for this specific channel
            reply_to = trade['telegram_msg_ids'].get(ch_key)

            # New Trades start a thread, so reply_to is None
            if event_type == "NEW_TRADE":
                reply_to = None
            
            # If not New Trade and we don't have a thread ID for this channel, we can't reply
            if event_type != "NEW_TRADE" and not reply_to:
                continue

            # Send Message
            msg_id = self.send_message(msg, reply_to_id=reply_to, override_chat_id=chat_id)
            
            if msg_id:
                # Update Trade Record
                trade['telegram_msg_ids'][ch_key] = msg_id
                
                # Save Main ID for return
                if ch_key == 'main':
                    sent_main_id = msg_id
                
                # Save to Database for Deletion
                self._save_msg_to_db(trade.get('id'), msg_id, chat_id)

        return sent_main_id

    def _save_msg_to_db(self, trade_id, msg_id, chat_id=None):
        """Helper to safely save message ID to database with specific Chat ID"""
        if not trade_id or not msg_id:
            return
            
        try:
            # If chat_id not provided, default to main channel config (Backward Comp)
            if not chat_id:
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
        Works across all channels because Chat IDs are stored in the DB.
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
