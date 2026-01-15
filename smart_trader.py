import pandas as pd
from datetime import datetime, timedelta
import pytz

# Global IST Timezone
IST = pytz.timezone('Asia/Kolkata')

instrument_dump = None 

def fetch_instruments(kite):
    global instrument_dump
    if instrument_dump is not None: return

    print("📥 Downloading Instrument List...")
    try:
        instrument_dump = pd.DataFrame(kite.instruments())
        instrument_dump['expiry_str'] = pd.to_datetime(instrument_dump['expiry']).dt.strftime('%Y-%m-%d')
        instrument_dump['expiry_date'] = pd.to_datetime(instrument_dump['expiry']).dt.date
        print("✅ Instruments Downloaded Successfully.")
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")

def get_indices_ltp(kite):
    try:
        q = kite.quote(["NSE:NIFTY 50", "NSE:NIFTY BANK", "BSE:SENSEX"])
        return {
            "NIFTY": q.get("NSE:NIFTY 50", {}).get('last_price', 0),
            "BANKNIFTY": q.get("NSE:NIFTY BANK", {}).get('last_price', 0),
            "SENSEX": q.get("BSE:SENSEX", {}).get('last_price', 0)
        }
    except:
        return {"NIFTY":0, "BANKNIFTY":0, "SENSEX":0}

def get_zerodha_symbol(common_name):
    if not common_name: return ""
    cleaned = common_name
    if "(" in cleaned: cleaned = cleaned.split("(")[0]
    u = cleaned.upper().strip()
    if u in ["BANKNIFTY", "NIFTY BANK", "BANK NIFTY"]: return "BANKNIFTY"
    if u in ["NIFTY", "NIFTY 50", "NIFTY50"]: return "NIFTY"
    if u == "SENSEX": return "SENSEX"
    if u == "FINNIFTY": return "FINNIFTY"
    return u

def get_lot_size(tradingsymbol):
    global instrument_dump
    if instrument_dump is None: return 1
    try:
        row = instrument_dump[instrument_dump['tradingsymbol'] == tradingsymbol]
        if not row.empty:
            return int(row.iloc[0]['lot_size'])
    except: pass
    return 1

def get_display_name(tradingsymbol):
    global instrument_dump
    if instrument_dump is None:
        return tradingsymbol
        
    try:
        row = instrument_dump[instrument_dump['tradingsymbol'] == tradingsymbol]
        if not row.empty:
            data = row.iloc[0]
            name = data['name']
            inst_type = data['instrument_type']
            expiry_dt = data['expiry_date'] 
            expiry_str = expiry_dt.strftime('%d %b').upper()
            
            if inst_type in ["CE", "PE"]:
                strike = int(data['strike'])
                return f"{name} {strike} {inst_type} {expiry_str}"
            elif inst_type == "FUT":
                 return f"{name} FUT {expiry_str}"
            else:
                 return f"{name} {inst_type}"
        return tradingsymbol
    except:
        return tradingsymbol

def search_symbols(kite, keyword, allowed_exchanges=None):
    global instrument_dump
    if instrument_dump is None: return []
    k = keyword.upper()
    
    if allowed_exchanges is None:
        allowed_exchanges = ['NSE', 'NFO', 'MCX', 'CDS', 'BSE', 'BFO']
    
    mask = (instrument_dump['exchange'].isin(allowed_exchanges)) & (instrument_dump['name'].str.startswith(k))
    matches = instrument_dump[mask]
    
    if matches.empty: return []
        
    unique_matches = matches.drop_duplicates(subset=['name', 'exchange']).head(10)
    items_to_quote = [f"{row['exchange']}:{row['tradingsymbol']}" for _, row in unique_matches.iterrows()]
    
    quotes = {}
    try:
        if items_to_quote: quotes = kite.quote(items_to_quote)
    except Exception as e:
        print(f"Search Quote Error: {e}")
    
    results = []
    for _, row in unique_matches.iterrows():
        key = f"{row['exchange']}:{row['tradingsymbol']}"
        ltp = quotes.get(key, {}).get('last_price', 0)
        results.append(f"{row['name']} ({row['exchange']}) : {ltp}")
        
    return results

def adjust_cds_lot_size(symbol, lot_size):
    s = symbol.upper()
    if lot_size == 1:
        if "JPYINR" in s: return 100000
        if any(x in s for x in ["USDINR", "EURINR", "GBPINR", "USDJPY", "EURUSD", "GBPUSD"]): return 1000
    return lot_size

def get_symbol_details(kite, symbol, preferred_exchange=None):
    global instrument_dump
    if instrument_dump is None: fetch_instruments(kite)
    if instrument_dump is None: return {}
    
    if "(" in symbol and ")" in symbol:
        try:
            parts = symbol.split('(')
            if len(parts) > 1: preferred_exchange = parts[1].split(')')[0].strip()
        except: pass

    clean = get_zerodha_symbol(symbol)
    today = datetime.now(IST).date()
    
    rows = instrument_dump[instrument_dump['name'] == clean]
    if rows.empty: return {}

    exchanges = rows['exchange'].unique().tolist()
    exchange_to_use = "NSE"
    
    if preferred_exchange and preferred_exchange in exchanges:
        exchange_to_use = preferred_exchange
    else:
        for p in ['MCX', 'CDS', 'BSE', 'NSE']:
             if p in exchanges: 
                 exchange_to_use = p
                 break
    
    quote_sym = f"{exchange_to_use}:{clean}"
    if clean == "NIFTY": quote_sym = "NSE:NIFTY 50"
    if clean == "BANKNIFTY": quote_sym = "NSE:NIFTY BANK"
    if clean == "SENSEX": quote_sym = "BSE:SENSEX"
    
    ltp = 0
    try:
        q = kite.quote(quote_sym)
        if quote_sym in q: ltp = q[quote_sym]['last_price']
    except: pass
        
    if ltp == 0:
        try:
            fut_exch = 'NFO' if exchange_to_use == 'NSE' else ('BFO' if exchange_to_use == 'BSE' else exchange_to_use)
            futs_all = rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today) & (rows['exchange'] == fut_exch)]
            if not futs_all.empty:
                near_fut = futs_all.sort_values('expiry_date').iloc[0]
                fut_sym = f"{near_fut['exchange']}:{near_fut['tradingsymbol']}"
                ltp = kite.quote(fut_sym)[fut_sym]['last_price']
        except: pass

    lot = 1
    for ex in ['MCX', 'CDS', 'BFO', 'NFO']:
        futs = rows[(rows['exchange'] == ex) & (rows['instrument_type'] == 'FUT')]
        if not futs.empty:
            lot = int(futs.iloc[0]['lot_size'])
            if ex == 'CDS': lot = adjust_cds_lot_size(clean, lot)
            break
            
    f_exp = sorted(rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
    o_exp = sorted(rows[(rows['instrument_type'].isin(['CE', 'PE'])) & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
    
    return {"symbol": clean, "ltp": ltp, "lot_size": lot, "fut_expiries": f_exp, "opt_expiries": o_exp}

def get_chain_data(symbol, expiry_date, option_type, ltp):
    global instrument_dump
    if instrument_dump is None: return []
    clean = get_zerodha_symbol(symbol)
    c = instrument_dump[(instrument_dump['name'] == clean) & (instrument_dump['expiry_str'] == expiry_date) & (instrument_dump['instrument_type'] == option_type)]
    if c.empty: return []
    
    strikes = sorted(c['strike'].unique().tolist())
    if not strikes: return []
    atm = min(strikes, key=lambda x: abs(x - ltp))
    
    res = []
    for s in strikes:
        lbl = "OTM"
        if s == atm: lbl = "ATM"
        elif option_type == "CE": lbl = "ITM" if ltp > s else "OTM"
        elif option_type == "PE": lbl = "ITM" if ltp < s else "OTM"
        res.append({"strike": s, "label": lbl})
    return res

def get_exact_symbol(symbol, expiry, strike, option_type):
    global instrument_dump
    if instrument_dump is None: return None
    if option_type == "EQ": return symbol
    clean = get_zerodha_symbol(symbol)
    
    if option_type == "FUT":
        mask = (instrument_dump['name'] == clean) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
    else:
        try: strike_price = float(strike)
        except: return None
        mask = (instrument_dump['name'] == clean) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == strike_price) & (instrument_dump['instrument_type'] == option_type)
        
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']

def get_specific_ltp(kite, symbol, expiry, strike, inst_type):
    ts = get_exact_symbol(symbol, expiry, strike, inst_type)
    if not ts: return 0
    try:
        global instrument_dump
        exch = "NFO"
        if instrument_dump is not None:
             row = instrument_dump[instrument_dump['tradingsymbol'] == ts]
             if not row.empty: exch = row.iloc[0]['exchange']
        return kite.quote(f"{exch}:{ts}")[f"{exch}:{ts}"]['last_price']
    except: return 0

# --- NEW FUNCTIONS FOR IMPORT/BACKTEST ---
def get_instrument_token(tradingsymbol, exchange):
    global instrument_dump
    if instrument_dump is None: return None
    try:
        row = instrument_dump[(instrument_dump['tradingsymbol'] == tradingsymbol) & (instrument_dump['exchange'] == exchange)]
        if not row.empty:
            return int(row.iloc[0]['instrument_token'])
    except: pass
    return None

def fetch_historical_data(kite, token, from_date, to_date, interval='minute'):
    try:
        # Fetch Data
        data = kite.historical_data(token, from_date, to_date, interval)
        
        # CLEANUP: Convert datetime objects to Strings for JSON serialization
        # This is critical for the Replay feature to save data in the DB
        clean_data = []
        for candle in data:
            c = candle.copy()
            if 'date' in c and hasattr(c['date'], 'strftime'):
                c['date'] = c['date'].strftime('%Y-%m-%d %H:%M:%S')
            clean_data.append(c)
            
        return clean_data
    except Exception as e:
        print(f"History Fetch Error: {e}")
        return []
