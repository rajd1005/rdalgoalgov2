import json
from database import db, AppSetting

def get_defaults():
    # Define default settings for a mode
    default_mode_settings = {
        "qty_mult": 1, 
        "ratios": [0.5, 1.0, 1.5], 
        "symbol_sl": {}, 
        "trailing_sl": 0,
        "sl_to_entry": 0,
        "order_type": "MARKET",
        "exit_multiplier": 1,
        "universal_exit_time": "15:25", 
        "max_loss": 0,       
        "profit_lock": 0,    
        "profit_min": 0,     
        "profit_trail": 0    
    }
    
    return {
        # --- NEW: 1st Trade Critical Setting ---
        "first_trade_critical": False,
        # ---------------------------------------
        "default_trade_mode": "PAPER",
        "exchanges": ["NSE", "NFO", "MCX", "CDS", "BSE", "BFO"],
        "watchlist": [],
        "broadcast_defaults": ["vip", "free", "z2h"], 
        "modes": {
            "LIVE": default_mode_settings.copy(),
            "PAPER": default_mode_settings.copy(),
            "SHADOW": default_mode_settings.copy()
        },
        "import_config": {
            "enable_history_check": True,
            "default_interval": "minute"
        },
        "telegram": {
            "bot_token": "",
            "enable_notifications": False,
            
            # 1. Main Channel (Receives ALL updates)
            "channel_id": "", 
            "system_channel_id": "",
            
            # 2. VIP Channel (New/Active/Update Only)
            "vip_channel_id": "",
            
            # 3. Free Channel (New/Active/Update Only)
            "free_channel_id": "",
            
            # 4. ZeroToHero Channel (New/Active/Update Only + Custom Name)
            "z2h_channel_id": "",
            "z2h_channel_name": "Zero To Hero", # Default Name

            # --- Event Toggles (Individual On/Off) ---
            "event_toggles": {
                "NEW_TRADE": True,
                "ACTIVE": True,
                "UPDATE": True,
                "SL_HIT": True,
                "TARGET_HIT": True,
                "HIGH_MADE": True,
                "EXIT": True
            },

            # --- Message Templates (With Placeholders) ---
            "templates": {
                "FREE_HEADER": "🔔 <b>{symbol}</b>\nAdded Time: {entry_time}\n➖➖➖➖➖➖➖➖\n",
                "NEW_TRADE": "{icon} <b>NEW TRADE: {symbol}</b>\nMode: {mode}\nType: {order_type}\nQty: {qty}\nEntry: {entry}\nSL: {sl}\nTargets: {targets}\nTime: {time}",
                "ACTIVE": "🚀 <b>Order ACTIVATED</b>\nPrice: {price}\nTime: {time}",
                "UPDATE": "✏️ <b>Trade Update</b>\n{update_text}\nTime: {time}",
                "SL_HIT": "🛑 <b>Stop Loss Hit</b>\nExit Price: {exit_price}\nP/L: {pnl}\nTime: {time}",
                "TARGET_HIT": "🎯 <b>Target {t_num} HIT</b>\nPrice: {price}\nMax Potential: {pot_pnl}\nTime: {time}",
                "HIGH_MADE": "📈 <b>New High Made: {price}</b>\nMax Potential: {pot_pnl}\nTime: {time}",
                "EXIT": "🚪 <b>Trade Closed</b>\nReason: {reason}\nPrice: {exit_price}\nP/L: {pnl}\nTime: {time}"
            }
        }
    }

def load_settings():
    defaults = get_defaults()
    try:
        setting = AppSetting.query.first()
        if setting:
            saved = json.loads(setting.data)
            
            # Integrity Check
            if "modes" not in saved:
                old_mult = saved.get("qty_mult", 1)
                old_ratios = saved.get("ratios", [0.5, 1.0, 1.5])
                old_sl = saved.get("symbol_sl", {})
                saved["modes"] = {
                    "LIVE": {"qty_mult": old_mult, "ratios": old_ratios, "symbol_sl": old_sl.copy()},
                    "PAPER": {"qty_mult": old_mult, "ratios": old_ratios, "symbol_sl": old_sl.copy()}
                }

            # Merge Modes (Ensure LIVE, PAPER, SHADOW exist)
            for m in ["LIVE", "PAPER", "SHADOW"]:
                if m in saved["modes"]:
                    for key, val in defaults["modes"][m].items():
                        if key not in saved["modes"][m]: saved["modes"][m][key] = val
                    if "symbol_sl" not in saved["modes"][m]: saved["modes"][m]["symbol_sl"] = {}
                else: 
                    saved["modes"][m] = defaults["modes"][m].copy()

            if "exchanges" not in saved: saved["exchanges"] = defaults["exchanges"]
            if "watchlist" not in saved: saved["watchlist"] = []
            
            # --- MERGE NEW KEYS ---
            if "default_trade_mode" not in saved: saved["default_trade_mode"] = defaults["default_trade_mode"]
            if "first_trade_critical" not in saved: saved["first_trade_critical"] = defaults["first_trade_critical"]
            if "broadcast_defaults" not in saved: saved["broadcast_defaults"] = defaults["broadcast_defaults"]
            
            if "import_config" not in saved: saved["import_config"] = defaults["import_config"]

            # Merge Telegram (Recursive merge for new keys & templates)
            if "telegram" not in saved: 
                saved["telegram"] = defaults["telegram"]
            else:
                for k, v in defaults["telegram"].items():
                    if k not in saved["telegram"]:
                        saved["telegram"][k] = v
                    elif isinstance(v, dict) and isinstance(saved["telegram"][k], dict):
                        # Deep merge for templates and toggles
                        for sub_k, sub_v in v.items():
                            if sub_k not in saved["telegram"][k]:
                                saved["telegram"][k][sub_k] = sub_v

            return saved
    except Exception as e: print(f"Error loading settings: {e}")
    return defaults

def save_settings_file(data):
    try:
        setting = AppSetting.query.first()
        if not setting:
            setting = AppSetting(data=json.dumps(data))
            db.session.add(setting)
        else: setting.data = json.dumps(data)
        db.session.commit()
        return True
    except Exception as e:
        print(f"Settings Save Error: {e}")
        db.session.rollback()
        return False
