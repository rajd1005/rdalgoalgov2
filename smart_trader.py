import pandas as pd
from datetime import datetime, timedelta
import pytz
import re
import os
import requests
import zipfile
import io
import urllib.request
import urllib.error
from pandas.api.types import is_number
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global IST Timezone
IST = pytz.timezone('Asia/Kolkata')

instrument_dump = None 
symbol_map = {} # FAST LOOKUP CACHE

def create_emergency_instruments():
    """
    Creates a minimal set of instruments to allow the system to boot
    even if Master Contract download fails completely.
    """
    print("⚠️ GENERATING EMERGENCY INSTRUMENT DATA (Offline/Recovery Mode)")
    data = [
        # Indices
        {"name": "NIFTY", "tradingsymbol": "Nifty 50", "instrument_token": "26000", "lot_size": 1, "exchange": "NSE", "instrument_type": "EQ", "tick_size": 0.05},
        {"name": "BANKNIFTY", "tradingsymbol": "Nifty Bank", "instrument_token": "26009", "lot_size": 1, "exchange": "NSE", "instrument_type": "EQ", "tick_size": 0.05},
        {"name": "SENSEX", "tradingsymbol": "SENSEX", "instrument_token": "1", "lot_size": 1, "exchange": "BSE", "instrument_type": "EQ", "tick_size": 0.05},
        {"name": "INDIA VIX", "tradingsymbol": "INDIA VIX", "instrument_token": "26017", "lot_size": 1, "exchange": "NSE", "instrument_type": "EQ", "tick_size": 0.05},
    ]
    
    df = pd.DataFrame(data)
    # Add missing columns with defaults
    defaults = {
        'expiry_date': None, 'expiry_str': None, 'strike': 0, 
        'inst_type_raw': 'EQ', 'opt_type_raw': 'XX', 'expiry_orig': None
    }
    for col, val in defaults.items():
        df[col] = val
        
    print(f"✅ Created {len(df)} emergency instruments.")
    return df

def manual_download_contract(exchange):
    """
    Robust fallback to download contract master.
    Uses Requests AND Urllib.
    """
    urls = [
        f"https://v2api.aliceblueonline.com/restmodelapi/scm/{exchange}.csv",
        f"https://aliceblueonline.com/api/scm/{exchange}.csv",
        f"https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/ScripMaster/getScripMasterCsv/{exchange}",
        f"https://files.aliceblueonline.com/global/content/scm/{exchange}.csv"
    ]
    
    # Variations: Upper, Lower, ZIP
    variations = []
    # Add original URL
    for u in urls: variations.append((u, False))
    # Add ZIP version
    for u in urls: variations.append((u.replace(".csv", ".zip"), True))
    # Add lowercase version
    for u in urls: variations.append((u.replace(exchange, exchange.lower()), False))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive"
    }

    for url, is_zip in variations:
        print(f"🔄 Trying: {url} ...")
        
        # METHOD 1: REQUESTS
        try:
            response = requests.get(url, headers=headers, timeout=10, verify=False)
            if response.status_code == 200:
                content = response.content
                if validate_and_save(content, exchange, is_zip): return True
            else:
                print(f"   ❌ HTTP {response.status_code}")
        except Exception as e:
            print(f"   ❌ Requests Error: {str(e)}")

        # METHOD 2: URLLIB (Backup)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                content = r.read()
                if validate_and_save(content, exchange, is_zip): return True
        except Exception as e:
            print(f"   ❌ Urllib Error: {str(e)}")
            
    print(f"🚫 All download attempts failed for {exchange}")
    return False

def validate_and_save(content, exchange, is_zip):
    if not content: return False
    
    # HTML Check
    if content.strip().startswith(b"<!DOCTYPE") or content.strip().startswith(b"<html"):
        print("   ⚠️ Content is HTML (Invalid)")
        return False
        
    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                csv_name = z.namelist()[0]
                with open(f"{exchange}.csv", "wb") as f:
                    f.write(z.read(csv_name))
            print(f"   ✅ ZIP Downloaded & Extracted")
            return True
        except: return False
    else:
        # CSV Check (Looking for commas)
        if b"," in content[:200]:
            with open(f"{exchange}.csv", "wb") as f:
                f.write(content)
            print(f"   ✅ CSV Downloaded")
            return True
    return False

def fetch_instruments(alice):
    global instrument_dump, symbol_map
    
    if instrument_dump is not None and not instrument_dump.empty and symbol_map: 
        return

    print("📥 Downloading AliceBlue Master Contracts...")
    
    # 1. Attempt Download
    for exch in ["NSE", "NFO", "MCX"]:
        success = False
        # Library Method
        try:
            if hasattr(alice, 'get_contract_master'):
                alice.get_contract_master(exch)
                if os.path.exists(f"{exch}.csv") and os.path.getsize(f"{exch}.csv") > 1024:
                    success = True
        except: pass
        
        # Manual Fallback
        if not success:
            manual_download_contract(exch)
        
    # 2. Load into Pandas
    dfs = []
    try:
        for exch in ['NSE', 'NFO', 'MCX']:
            fname = f"{exch}.csv"
            if os.path.exists(fname) and os.path.getsize(fname) > 0:
                try:
                    # Quick Validity Check
                    with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                        if "<html" in f.readline(): continue
                        
                    df = pd.read_csv(fname, low_memory=False, encoding='utf-8', on_bad_lines='skip')
                    df['exchange'] = exch
                    df.columns = df.columns.str.strip()
                    dfs.append(df)
                except Exception as e:
                    print(f"⚠️ Error reading {fname}: {e}")
    except: pass
    
    # 3. Process Data
    if not dfs:
        print("⚠️ Warning: No valid contract files found. Using Emergency Data.")
        instrument_dump = create_emergency_instruments()
    else:
        instrument_dump = pd.concat(dfs, ignore_index=True)
        
    instrument_dump = instrument_dump.copy()
    
    # 4. Column Normalization
    column_aliases = {
        'name': ['Symbol', 'symbol', 'SYMBOL', 'Symbol Name'],
        'tradingsymbol': ['TradingSymbol', 'tradingsymbol', 'TrdSym', 'TRDSYM'],
        'instrument_token': ['Token', 'token', 'TOKEN', 'ScripCode'],
        'lot_size': ['LotSize', 'lot_size', 'Lot', 'LOT'],
        'strike': ['StrikePrice', 'strike', 'Strike', 'STRIKE'],
        'expiry_orig': ['ExpiryDate', 'expiry', 'Expiry'],
        'inst_type_raw': ['Instrument', 'instrument', 'INST'],
        'opt_type_raw': ['OptionType', 'option_type', 'OPTTYPE']
    }

    rename_dict = {}
    for target_col, aliases in column_aliases.items():
        for alias in aliases:
            if alias in instrument_dump.columns:
                rename_dict[alias] = target_col
                break
    
    instrument_dump.rename(columns=rename_dict, inplace=True)

    # 5. Defaults & Calculations
    if 'name' not in instrument_dump.columns and 'tradingsymbol' in instrument_dump.columns:
         instrument_dump['name'] = instrument_dump['tradingsymbol']

    defaults = {'inst_type_raw': 'EQ', 'opt_type_raw': 'XX', 'expiry_orig': None, 'strike': 0, 'lot_size': 1, 'instrument_token': 0}
    for col, val in defaults.items():
        if col not in instrument_dump.columns: instrument_dump[col] = val

    # Type Logic
    inst_col = instrument_dump['inst_type_raw'].astype(str).str.upper()
    opt_col = instrument_dump['opt_type_raw'].astype(str).str.upper()
    
    instrument_dump['instrument_type'] = 'EQ'
    instrument_dump.loc[inst_col.str.contains('OPT'), 'instrument_type'] = opt_col.loc[inst_col.str.contains('OPT')]
    instrument_dump.loc[inst_col.str.contains('FUT'), 'instrument_type'] = 'FUT'
    
    # Expiry Parsing
    def parse_expiry(val):
        try:
            if pd.isna(val) or val == '': return None
            if is_number(val):
                v = float(val)
                if v > 10000000000: return datetime.fromtimestamp(v/1000).date()
                return datetime.fromtimestamp(v).date()
            return pd.to_datetime(val).date()
        except: return None

    instrument_dump['expiry_date'] = instrument_dump['expiry_orig'].apply(parse_expiry)
    instrument_dump['expiry_str'] = instrument_dump['expiry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else None)
    
    # String Cleaning
    for col in ['name', 'tradingsymbol']:
        if col in instrument_dump.columns:
            instrument_dump[col] = instrument_dump[col].astype(str).str.strip().str.upper()

    # 6. Build Cache
    print("⚡ Building Fast Lookup Cache...")
    exchange_priority = {'NFO': 0, 'MCX': 1, 'NSE': 2, 'BSE': 3}
    instrument_dump['priority'] = instrument_dump['exchange'].map(exchange_priority).fillna(99)
    instrument_dump.sort_values('priority', inplace=True)
    
    if 'tradingsymbol' in instrument_dump.columns:
        unique_symbols = instrument_dump.drop_duplicates(subset=['tradingsymbol'])
        symbol_map = unique_symbols.set_index('tradingsymbol').to_dict('index')
        print(f"✅ Instruments Indexed. Count: {len(instrument_dump)}")
    else:
        print("❌ Error: 'tradingsymbol' missing in Data.")
        symbol_map = {}

def get_alice_instrument(alice, symbol):
    global symbol_map
    exch = None
    trd_sym = symbol
    if ":" in symbol:
        parts = symbol.split(":")
        exch = parts[0]
        trd_sym = parts[1]
    
    if symbol_map and trd_sym in symbol_map:
        row = symbol_map[trd_sym]
        try: return alice.get_instrument_by_symbol(row['exchange'], row['tradingsymbol'])
        except: pass
    
    if exch:
        try: return alice.get_instrument_by_symbol(exch, trd_sym)
        except: pass
    return None

def get_exchange_name(symbol):
    global symbol_map
    if ":" in symbol: return symbol.split(":")[0]
    if symbol_map and symbol in symbol_map: return symbol_map[symbol]['exchange']
    if "NIFTY" in symbol or "BANKNIFTY" in symbol:
        if any(x in symbol for x in ["FUT", "CE", "PE"]): return "NFO"
    return "NSE"

def get_ltp(alice, symbol):
    try:
        inst = get_alice_instrument(alice, symbol)
        if not inst: return 0.0
        quote = alice.get_scrip_info(inst)
        if quote and 'LTP' in quote: return float(quote['LTP'])
        return 0.0
    except: return 0.0

def get_indices_ltp(alice):
    indices = {"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0}
    try:
        nifty = alice.get_instrument_by_symbol("NSE", "Nifty 50")
        bank = alice.get_instrument_by_symbol("NSE", "Nifty Bank")
        sensex = alice.get_instrument_by_symbol("BSE", "SENSEX")
        if nifty:
            q = alice.get_scrip_info(nifty)
            if q: indices["NIFTY"] = float(q.get('LTP', 0))
        if bank:
            q = alice.get_scrip_info(bank)
            if q: indices["BANKNIFTY"] = float(q.get('LTP', 0))
        if sensex:
             q = alice.get_scrip_info(sensex)
             if q: indices["SENSEX"] = float(q.get('LTP', 0))
    except: pass
    return indices

def get_zerodha_symbol(common_name):
    if not common_name: return ""
    cleaned = common_name.split("(")[0].upper().strip()
    if cleaned in ["BANKNIFTY", "NIFTY BANK", "BANK NIFTY"]: return "BANKNIFTY"
    if cleaned in ["NIFTY", "NIFTY 50", "NIFTY50"]: return "NIFTY"
    return cleaned

def get_lot_size(tradingsymbol):
    global symbol_map
    if symbol_map and tradingsymbol in symbol_map:
        return int(symbol_map[tradingsymbol].get('lot_size', 1))
    return 1

def get_display_name(tradingsymbol):
    global symbol_map
    if not symbol_map: return tradingsymbol
    try:
        data = symbol_map.get(tradingsymbol)
        if data:
            name = data['name']
            inst_type = data['instrument_type']
            expiry_str = data.get('expiry_str', '')
            if expiry_str:
                try: expiry_str = datetime.strptime(expiry_str, '%Y-%m-%d').strftime('%d %b').upper()
                except: pass
            if inst_type in ["CE", "PE"]:
                return f"{name} {int(data['strike'])} {inst_type} {expiry_str}"
            elif inst_type == "FUT":
                 return f"{name} FUT {expiry_str}"
            else:
                 return f"{name} {inst_type}"
        return tradingsymbol
    except: return tradingsymbol

def search_symbols(alice, keyword, allowed_exchanges=None):
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: 
        fetch_instruments(alice)
        if instrument_dump is None or instrument_dump.empty: return []

    k = keyword.upper()
    if not allowed_exchanges: allowed_exchanges = ['NSE', 'NFO', 'MCX']
    
    try:
        mask = (instrument_dump['exchange'].isin(allowed_exchanges)) & (instrument_dump['name'].str.startswith(k, na=False))
        matches = instrument_dump[mask]
        if matches.empty: return []
        unique = matches.drop_duplicates(subset=['name', 'exchange']).head(10)
        return [f"{row['name']} ({row['exchange']})" for _, row in unique.iterrows()]
    except: return []

def get_symbol_details(alice, symbol, preferred_exchange=None):
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: fetch_instruments(alice)
    if instrument_dump is None or instrument_dump.empty: return {}
    
    clean = get_zerodha_symbol(symbol)
    today = datetime.now(IST).date()
    rows = instrument_dump[instrument_dump['name'] == clean]
    if rows.empty: return {}

    ltp = 0
    try:
        underlying = rows[rows['instrument_type'] == 'EQ']
        if not underlying.empty:
            u_row = underlying[underlying['exchange']=='NSE'].iloc[0] if not underlying[underlying['exchange']=='NSE'].empty else underlying.iloc[0]
            ltp = get_ltp(alice, f"{u_row['exchange']}:{u_row['tradingsymbol']}")
    except: pass
    
    if ltp == 0:
        try:
            futs = rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today)].sort_values('expiry_date')
            if not futs.empty:
                 f_row = futs.iloc[0]
                 ltp = get_ltp(alice, f"{f_row['exchange']}:{f_row['tradingsymbol']}")
        except: pass

    lot = 1
    fno_rows = rows[rows['exchange'].isin(['NFO', 'MCX'])]
    if not fno_rows.empty: lot = int(fno_rows.iloc[0]['lot_size'])

    f_exp = []
    o_exp = []
    if 'expiry_str' in rows.columns:
        f_exp = sorted(rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
        o_exp = sorted(rows[(rows['instrument_type'].isin(['CE', 'PE'])) & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
    
    return {"symbol": clean, "ltp": ltp, "lot_size": lot, "fut_expiries": f_exp, "opt_expiries": o_exp}

def get_chain_data(symbol, expiry_date, option_type, ltp):
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: return []
    clean = get_zerodha_symbol(symbol)
    if 'expiry_str' not in instrument_dump.columns: return []
    
    c = instrument_dump[
        (instrument_dump['name'] == clean) & 
        (instrument_dump['expiry_str'] == expiry_date) & 
        (instrument_dump['instrument_type'] == option_type)
    ]
    if c.empty: return []
    
    strikes = sorted(c['strike'].unique().tolist())
    if not strikes: return []
    atm = min(strikes, key=lambda x: abs(x - ltp))
    
    res = []
    for s in strikes:
        lbl = "ATM" if s == atm else ("ITM" if (option_type == "CE" and ltp > s) or (option_type == "PE" and ltp < s) else "OTM")
        res.append({"strike": s, "label": lbl})
    return res

def get_exact_symbol(symbol, expiry, strike, option_type):
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: return None
    clean = get_zerodha_symbol(symbol)
    
    if option_type == "EQ":
        mask = (instrument_dump['name'] == clean) & (instrument_dump['instrument_type'] == 'EQ')
        if mask.any(): return instrument_dump[mask].iloc[0]['tradingsymbol']
        return symbol

    if 'expiry_str' not in instrument_dump.columns: return None

    if option_type == "FUT":
        mask = (instrument_dump['name'] == clean) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['instrument_type'] == "FUT")
    else:
        try: strike_price = float(strike)
        except: return None
        mask = (instrument_dump['name'] == clean) & (instrument_dump['expiry_str'] == expiry) & (instrument_dump['strike'] == strike_price) & (instrument_dump['instrument_type'] == option_type)
        
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']

def get_specific_ltp(alice, symbol, expiry, strike, inst_type):
    ts = get_exact_symbol(symbol, expiry, strike, inst_type)
    if not ts: return 0.0
    exch = "NFO"
    if symbol_map and ts in symbol_map: exch = symbol_map[ts]['exchange']
    return get_ltp(alice, f"{exch}:{ts}")

def get_instrument_token(tradingsymbol, exchange):
    global symbol_map
    if symbol_map and tradingsymbol in symbol_map: return symbol_map[tradingsymbol]['instrument_token']
    return None

def fetch_historical_data(alice, token, from_date, to_date, interval='1'):
    return []

def get_telegram_symbol(tradingsymbol):
    return get_display_name(tradingsymbol)
