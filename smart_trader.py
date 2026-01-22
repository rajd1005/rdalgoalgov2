import pandas as pd
from datetime import datetime, timedelta
import pytz
import re
import os
import requests
from pandas.api.types import is_number
import io

# Global IST Timezone
IST = pytz.timezone('Asia/Kolkata')

instrument_dump = None 
symbol_map = {} # FAST LOOKUP CACHE

def manual_download_contract(exchange):
    """
    Fallback method to download contract master if the library fails.
    Implements multiple mirrors and content validation.
    """
    # List of possible URLs for Master Contracts
    urls = [
        f"https://v2api.aliceblueonline.com/restmodelapi/scm/{exchange}.csv",
        f"https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/ScripMaster/getScripMasterCsv/{exchange}",
        f"https://files.aliceblueonline.com/global/content/scm/{exchange}.csv"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/csv,application/csv,text/plain",
        "Referer": "https://ant.aliceblueonline.com/"
    }

    for url in urls:
        try:
            print(f"🔄 Attempting manual download for {exchange} from {url}...")
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                content = response.content
                # VALIDATION: Check if content is HTML (Error Page)
                if content.strip().startswith(b"<!DOCTYPE") or content.strip().startswith(b"<html"):
                    print(f"⚠️ Invalid content (HTML) received from {url}")
                    continue
                
                # VALIDATION: Check if content looks like CSV (has commas)
                if b"," not in content[:100]:
                    print(f"⚠️ Invalid content (Not CSV) received from {url}")
                    continue

                with open(f"{exchange}.csv", "wb") as f:
                    f.write(content)
                print(f"✅ Manually downloaded {exchange}.csv")
                return True
            else:
                print(f"❌ HTTP {response.status_code} from {url}")
        except Exception as e:
            print(f"❌ Download error for {url}: {e}")
            
    print(f"🚫 All download attempts failed for {exchange}")
    return False

def fetch_instruments(alice):
    """
    Downloads AliceBlue master contracts (NSE, NFO, MCX),
    merges them into a single DataFrame, and builds a fast lookup map.
    """
    global instrument_dump, symbol_map
    
    if instrument_dump is not None and not instrument_dump.empty and symbol_map: 
        return

    print("📥 Downloading AliceBlue Master Contracts...")
    
    # 1. Download Contracts
    for exch in ["NSE", "NFO", "MCX"]:
        success = False
        # Try Library First (if it works)
        try:
            if hasattr(alice, 'get_contract_master'):
                alice.get_contract_master(exch)
                # Verify file exists and is not empty
                if os.path.exists(f"{exch}.csv") and os.path.getsize(f"{exch}.csv") > 1024:
                    success = True
        except: pass
        
        # Fallback to Manual
        if not success:
            manual_download_contract(exch)
        
    try:
        # 2. Load CSVs into Pandas
        dfs = []
        for exch in ['NSE', 'NFO', 'MCX']:
            fname = f"{exch}.csv"
            if os.path.exists(fname) and os.path.getsize(fname) > 0:
                try:
                    # Read only first few lines to check validity before full load
                    with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                        first_line = f.readline()
                        if "DOCTYPE" in first_line or "<html" in first_line:
                            print(f"⚠️ Skipping invalid/HTML file: {fname}")
                            continue

                    df = pd.read_csv(fname, low_memory=False, encoding='utf-8', on_bad_lines='skip')
                    df['exchange'] = exch
                    df.columns = df.columns.str.strip()
                    dfs.append(df)
                except Exception as e:
                    print(f"⚠️ Error reading {fname}: {e}")
        
        if not dfs:
            print("⚠️ Warning: No valid contract files found.")
            return

        instrument_dump = pd.concat(dfs, ignore_index=True)
        instrument_dump = instrument_dump.copy()
        
        # 3. Robust Column Renaming
        column_aliases = {
            'name': ['Symbol', 'symbol', 'SYMBOL', 'Symbol Name'],
            'tradingsymbol': ['TradingSymbol', 'tradingsymbol', 'TrdSym', 'TRDSYM', 'Trading Symbol'],
            'instrument_token': ['Token', 'token', 'TOKEN', 'ScripCode', 'Instrument Token'],
            'lot_size': ['LotSize', 'lot_size', 'Lot', 'LOT', 'Lot Size'],
            'strike': ['StrikePrice', 'strike', 'Strike', 'STRIKE', 'Strike Price'],
            'expiry_orig': ['ExpiryDate', 'expiry', 'Expiry', 'Expiry Date'],
            'inst_type_raw': ['Instrument', 'instrument', 'INST', 'Instrument Type'],
            'opt_type_raw': ['OptionType', 'option_type', 'OPTTYPE', 'Option Type']
        }

        rename_dict = {}
        for target_col, aliases in column_aliases.items():
            for alias in aliases:
                if alias in instrument_dump.columns:
                    rename_dict[alias] = target_col
                    break
        
        instrument_dump.rename(columns=rename_dict, inplace=True)

        # 4. Critical Column Checks & Fallbacks
        if 'name' not in instrument_dump.columns:
            if 'tradingsymbol' in instrument_dump.columns:
                print("⚠️ 'name' column missing. Using 'tradingsymbol'.")
                instrument_dump['name'] = instrument_dump['tradingsymbol']
            else:
                print(f"❌ CRITICAL: Missing 'name' and 'tradingsymbol'. Columns: {list(instrument_dump.columns)}")
                return

        # Ensure other required cols exist to avoid KeyErrors later
        required_defaults = {
            'inst_type_raw': 'EQ',
            'opt_type_raw': 'XX',
            'expiry_orig': None,
            'strike': 0,
            'lot_size': 1,
            'instrument_token': 0
        }
        for col, default in required_defaults.items():
            if col not in instrument_dump.columns:
                instrument_dump[col] = default

        # 5. Standardize Instrument Type
        inst_col = instrument_dump['inst_type_raw'].astype(str).str.upper()
        opt_col = instrument_dump['opt_type_raw'].astype(str).str.upper()
        exch_col = instrument_dump['exchange'].astype(str)
        
        types = []
        for i in range(len(instrument_dump)):
            itype = inst_col.iloc[i]
            otype = opt_col.iloc[i]
            exch = exch_col.iloc[i]
            
            if 'OPT' in itype:
                types.append(otype) # CE or PE
            elif 'FUT' in itype:
                types.append('FUT')
            elif 'EQ' in itype or exch == 'NSE':
                types.append('EQ')
            else:
                types.append('EQ')
        
        instrument_dump['instrument_type'] = types
        
        # 6. Parse Dates
        def parse_expiry(val):
            try:
                if pd.isna(val) or val == '': return None
                if is_number(val):
                    v = float(val)
                    if v > 10000000000: return datetime.fromtimestamp(v/1000).date()
                    return datetime.fromtimestamp(v).date()
                return pd.to_datetime(val).date()
            except:
                return None

        instrument_dump['expiry_date'] = instrument_dump['expiry_orig'].apply(parse_expiry)
        instrument_dump['expiry_str'] = instrument_dump['expiry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else None)
        
        # Clean Strings
        instrument_dump['name'] = instrument_dump['name'].astype(str).str.strip().str.upper()
        if 'tradingsymbol' in instrument_dump.columns:
            instrument_dump['tradingsymbol'] = instrument_dump['tradingsymbol'].astype(str).str.strip().str.upper()

        # 7. Build Cache
        print("⚡ Building Fast Lookup Cache...")
        exchange_priority = {'NFO': 0, 'MCX': 1, 'NSE': 2, 'BSE': 3}
        instrument_dump['priority'] = instrument_dump['exchange'].map(exchange_priority).fillna(99)
        instrument_dump.sort_values('priority', inplace=True)
        
        if 'tradingsymbol' in instrument_dump.columns:
            unique_symbols = instrument_dump.drop_duplicates(subset=['tradingsymbol'])
            symbol_map = unique_symbols.set_index('tradingsymbol').to_dict('index')
            print(f"✅ Instruments Indexed. Count: {len(instrument_dump)}")
        else:
            print("❌ Error: 'tradingsymbol' column missing.")
            symbol_map = {}
        
    except Exception as e:
        print(f"❌ Failed to process instruments: {e}")
        import traceback
        traceback.print_exc()
        if instrument_dump is None: instrument_dump = pd.DataFrame()
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
