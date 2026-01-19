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

    def edit_message(self, text, message_id, chat_id):
        """
        Updates an existing message with new text.
        Used for the 'Live Dashboard' feature to avoid spamming new messages.
        """
        conf = self._get_config()
        token = conf.get('bot_token')
        
        if not token or not message_id or not chat_id:
            return None

        url = f"{self.base_url}{token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }

        try:
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code != 200:
                # Ignore 'message is not modified' error (happens if data is same)
                if "message is not modified" not in resp.text:
                    print(f"❌ Telegram Edit Error: {resp.text}")
        except Exception as e:
            print(f"❌ Telegram Edit Failed: {e}")

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

    def _generate_live_card(self, trade, event_type=None, extra_data=None):
        """
        Generates the 'Live Scoreboard' message content.
        This serves as the 'Place Holder' that gets updated in real-time.
        """
        raw_symbol = trade.get('symbol', 'Unknown')
        symbol = smart_trader.get_telegram_symbol(raw_symbol)
        mode = trade.get('mode', 'PAPER')
        
        # Determine Status Header
        status = trade.get('status', 'OPEN')
        status_icon = "🚀"
        header_note = ""

        if event_type == "SL_HIT":
            status = "STOP LOSS HIT"
            status_icon = "🛑"
        elif event_type == "TARGET_HIT":
            status = "TARGET HIT"
            status_icon = "🎯"
        elif event_type == "TIME_EXIT":
            status = "TIME EXIT"
            status_icon = "⏰"
        elif status == "PENDING":
            status = "PENDING ORDER"
            status_icon = "⏳"
        
        # Calculate Data
        entry = trade.get('entry_price', 0)
        ltp = trade.get('current_ltp', entry)
        qty = trade.get('quantity', 0)
        
        # PnL Logic
        if status == "PENDING":
            pnl = 0.0
        elif event_type == "SL_HIT" and extra_data:
            # If extra_data is the realized PnL passed from risk_engine
            pnl = extra_data if isinstance(extra_data, (int, float)) else 0.0
        else:
            pnl = (ltp - entry) * qty
            
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        
        # Format Targets
        targets = trade.get('targets', [])
        hit_indices = trade.get('targets_hit_indices', [])
        target_lines = []
        for i, t in enumerate(targets):
            mark = "✅" if i in hit_indices else "⏳"
            target_lines.append(f"T{i+1}: {t} {mark}")
        target_str = " | ".join(target_lines)

        # Build Message
        msg = (
            f"{status_icon} <b>{symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Status: {status}</b>\n"
            f"<i>Mode: {mode}</i>\n\n"
            f"🔹 <b>Entry:</b> {entry}\n"
            f"🔹 <b>LTP:</b> {ltp}\n"
            f"🔹 <b>SL:</b> {trade.get('sl', 0)}\n\n"
            f"🎯 <b>Targets:</b>\n{target_str}\n\n"
            f"{pnl_emoji} <b>P/L: ₹ {pnl:.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Last Update: {get_time_str()}</i>"
        )
        return msg

    def notify_trade_event(self, trade, event_type, extra_data=None):
        """
        Constructs and sends notifications to ALL configured channels.
        Supports two modes based on settings:
        1. Edit Mode (Live Dashboard): Updates the original message.
        2. Threaded Mode (Default): Sends new reply messages for events.
        """
        conf = self._get_config()
        if not conf.get('enable_notifications', False):
            return {}

        # Check Edit Mode Toggle
        edit_mode = conf.get('edit_mode', False)

        raw_symbol = trade.get('symbol', 'Unknown')
        symbol = smart_trader.get_telegram_symbol(raw_symbol)
        
        mode = trade.get('mode', 'PAPER')
        qty = trade.get('quantity', 0)
        entry_price = trade.get('entry_price', 0)
        
        # --- THREAD IDS ---
        if 'telegram_msg_ids' not in trade or not isinstance(trade['telegram_msg_ids'], dict):
            trade['telegram_msg_ids'] = {}
            legacy_id = trade.get('telegram_msg_id')
            if legacy_id:
                trade['telegram_msg_ids']['main'] = legacy_id
        
        stored_ids = trade['telegram_msg_ids']

        # --- DETERMINE ACTION TIME ---
        action_time = get_time_str() 
        if isinstance(extra_data, dict) and 'time' in extra_data:
            action_time = extra_data['time']
        elif event_type == "NEW_TRADE" and trade.get('entry_time'):
            action_time = trade.get('entry_time')
            
        entry_time_str = trade.get('entry_time', action_time)

        # --- DEFINE CHANNELS ---
        all_channels = [
            {'key': 'main', 'id': conf.get('channel_id'), 'allow_all': True},
            {'key': 'vip', 'id': conf.get('vip_channel_id'), 'allow_all': False},
            {'key': 'free', 'id': conf.get('free_channel_id'), 'allow_all': False},
            {'key': 'z2h', 'id': conf.get('z2h_channel_id'), 'allow_all': False, 'custom_name': conf.get('z2h_channel_name')}
        ]
        
        # Event Categories
        result_events = ['TARGET_HIT', 'HIGH_MADE', 'SL_HIT']
        
        # User Selection
        target_list = trade.get('target_channels') 

        new_msg_ids = {} 

        # Loop through channels
        for ch in all_channels:
            key = ch['key']
            chat_id = ch['id']
            if not chat_id: continue 
            
            # --- FILTER 1: User Selection & Premium Spillover ---
            is_allowed = True
            if target_list is not None:
                if key in target_list:
                    is_allowed = True
                else:
                    # Spillover Logic
                    is_premium_trade = any(x in target_list for x in ['vip', 'z2h'])
                    if key == 'free' and is_premium_trade and event_type in result_events:
                        is_allowed = True
                    else:
                        is_allowed = False
            
            if not is_allowed:
                continue

            # --- FILTER 2: Event Type Segmentation ---
            if key in ['vip', 'z2h']:
                allowed_vip = ['NEW_TRADE', 'ACTIVE', 'UPDATE']
                # In Edit Mode, we want to allow updates to the dashboard for Results too
                if not edit_mode and event_type not in allowed_vip:
                    continue
            
            elif key == 'free':
                allowed_free = ['NEW_TRADE', 'ACTIVE', 'UPDATE', 'TARGET_HIT', 'HIGH_MADE']
                if not edit_mode and event_type not in allowed_free:
                    continue

            # --- MSG MANAGEMENT (EDIT vs SEND) ---
            reply_to = stored_ids.get(key)
            msg_sent_id = None
            
            # ---------------------------------------------------------
            # PATH A: EDIT MODE (Live Dashboard)
            # ---------------------------------------------------------
            if edit_mode:
                # If we have an existing message, we EDIT it.
                if reply_to:
                    # Generate the Live Card
                    card_text = self._generate_live_card(trade, event_type, extra_data)
                    self.edit_message(card_text, reply_to, chat_id)
                else:
                    # No message yet (New Trade OR Spillover start)
                    # We must SEND a new message to start the dashboard.
                    card_text = self._generate_live_card(trade, event_type, extra_data)
                    
                    # Add Header for Spillover
                    if key == 'free' and event_type != "NEW_TRADE":
                         header_prefix = (
                            f"🔔 <b>{symbol}</b>\n"
                            f"Added Time: {entry_time_str}\n"
                            f"➖➖➖➖➖➖➖➖\n"
                        )
                         card_text = header_prefix + card_text

                    msg_sent_id = self.send_message(card_text, override_chat_id=chat_id)

            # ---------------------------------------------------------
            # PATH B: STANDARD MODE (Threaded Replies)
            # ---------------------------------------------------------
            else:
                is_new_thread_start = False
                if event_type == "NEW_TRADE":
                    reply_to = None 
                if key == 'free' and not reply_to:
                    is_new_thread_start = True

                if event_type != "NEW_TRADE" and not reply_to and not is_new_thread_start:
                    continue

                # Build Standard Message
                msg = ""
                if event_type == "NEW_TRADE":
                    icon = "🔴" if mode == "LIVE" else "🟡"
                    order_type = trade.get('order_type', 'MARKET')
                    sl = trade.get('sl', 0)
                    targets = trade.get('targets', [])
                    
                    header = f"{icon} <b>NEW TRADE: {symbol}</b>"
                    if ch.get('custom_name'):
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

                if is_new_thread_start and key == 'free' and event_type != "NEW_TRADE" and msg:
                    header_prefix = (
                        f"🔔 <b>{symbol}</b>\n"
                        f"Added Time: {entry_time_str}\n"
                        f"➖➖➖➖➖➖➖➖\n"
                    )
                    msg = header_prefix + msg

                if msg:
                    msg_sent_id = self.send_message(msg, reply_to_id=reply_to, override_chat_id=chat_id)

            # --- SAVE ID IF NEW MESSAGE SENT ---
            if msg_sent_id:
                self._save_msg_to_db(trade.get('id'), msg_sent_id, chat_id)
                
                # If it's a new thread start (Edit Mode First Msg OR Threaded Mode First Msg)
                # We save it to the trade object so subsequent events know what to Reply/Edit.
                if event_type == "NEW_TRADE" or (key == 'free' and not reply_to):
                    new_msg_ids[key] = msg_sent_id
                    trade['telegram_msg_ids'][key] = msg_sent_id

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
        try:
            messages = TelegramMessage.query.filter_by(trade_id=str(trade_id)).all()
            if not messages: return

            conf = self._get_config()
            token = conf.get('bot_token')
            if not token: return

            delete_url = f"{self.base_url}{token}/deleteMessage"

            for msg in messages:
                try:
                    payload = {"chat_id": msg.chat_id, "message_id": msg.message_id}
                    requests.post(delete_url, json=payload, timeout=2)
                except Exception as req_err:
                    print(f"TG Delete Request Error: {req_err}")
                db.session.delete(msg)
            
            db.session.commit()
            print(f"🗑️ Deleted {len(messages)} Telegram messages for Trade {trade_id}")

        except Exception as e:
            print(f"❌ Error deleting Telegram messages: {e}")
            try: db.session.rollback()
            except: pass

# Singleton Instance
bot = TelegramManager()
