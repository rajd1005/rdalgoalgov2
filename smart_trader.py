import pandas as pd
from datetime import datetime, timedelta
import pytz
import re
import os
import requests
from pandas.api.types import is_number

# Global IST Timezone
IST = pytz.timezone('Asia/Kolkata')

instrument_dump = None 
symbol_map = {} # FAST LOOKUP CACHE

def manual_download_contract(exchange):
    """
    Fallback method to download contract master if the library fails.
    """
    try:
        url = f"https://v2api.aliceblueonline.com/restmodelapi/scm/{exchange}.csv"
        print(f"🔄 Attempting manual download for {exchange} from {url}...")
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            with open(f"{exchange}.csv", "wb") as f:
                f.write(response.content)
            print(f"✅ Manually downloaded {exchange}.csv")
            return True
        else:
            print(f"❌ Manual download failed for {exchange}: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Manual download error for {exchange}: {e}")
        return False

def fetch_instruments(alice):
    """
    Downloads AliceBlue master contracts (NSE, NFO, MCX),
    merges them into a single DataFrame, and builds a fast lookup map.
    """
    global instrument_dump, symbol_map
    
    # If already loaded and map exists, skip to save bandwidth
    if instrument_dump is not None and not instrument_dump.empty and symbol_map: 
        return

    print("📥 Downloading AliceBlue Master Contracts...")
    
    # 1. Download Contracts (Try Library First, then Fallback)
    for exch in ["NSE", "NFO", "MCX"]:
        success = False
        try:
            # Attempt to use the library method
            alice.get_contract_master(exch)
            success = True
        except Exception as e:
            print(f"⚠️ Library method failed for {exch}: {e}")
        
        if not success:
            # Fallback to manual download
            manual_download_contract(exch)
        
    try:
        # 2. Load CSVs into Pandas
        dfs = []
        for exch in ['NSE', 'NFO', 'MCX']:
            fname = f"{exch}.csv"
            if os.path.exists(fname):
                try:
                    # Low_memory=False to prevent mixed type warnings on large files
                    df = pd.read_csv(fname, low_memory=False)
                    df['exchange'] = exch
                    # Clean Headers (Strip whitespace)
                    df.columns = df.columns.str.strip()
                    dfs.append(df)
                except Exception as e:
                    print(f"⚠️ Error reading {fname}: {e}")
        
        if not dfs:
            print("⚠️ Warning: No contract files found (NSE.csv, etc).")
            return

        instrument_dump = pd.concat(dfs, ignore_index=True)
        # De-fragment frame to improve performance and stop warnings
        instrument_dump = instrument_dump.copy()
        
        # 3. Robust Column Renaming
        # Define possible aliases for standard columns found in AliceBlue CSVs
        column_aliases = {
            'name': ['Symbol', 'symbol', 'SYMBOL'],
            'tradingsymbol': ['TradingSymbol', 'tradingsymbol', 'TrdSym', 'TRDSYM'],
            'instrument_token': ['Token', 'token', 'TOKEN', 'ScripCode'],
            'lot_size': ['LotSize', 'lot_size', 'Lot', 'LOT'],
            'strike': ['StrikePrice', 'strike', 'Strike', 'STRIKE'],
            'expiry_orig': ['ExpiryDate', 'expiry', 'Expiry'],
            'inst_type_raw': ['Instrument', 'instrument', 'INST'],
            'opt_type_raw': ['OptionType', 'option_type', 'OPTTYPE']
        }

        # Find and rename matching columns
        rename_dict = {}
        for target_col, aliases in column_aliases.items():
            for alias in aliases:
                if alias in instrument_dump.columns:
                    rename_dict[alias] = target_col
                    break # Use the first match found
        
        instrument_dump.rename(columns=rename_dict, inplace=True)

        # Critical Check for Required Columns
        if 'name' not in instrument_dump.columns:
            print(f"❌ Error: 'name' column missing. Available columns: {list(instrument_dump.columns)}")
            # Fallback: create name from tradingsymbol if possible
            if 'tradingsymbol' in instrument_dump.columns:
                print("⚠️ Auto-fixing: Using 'tradingsymbol' as 'name'")
                instrument_dump['name'] = instrument_dump['tradingsymbol']
            else:
                return # Cannot proceed

        # 4. Standardize Instrument Type (Optimized)
        # We calculate this using list comprehension to avoid DataFrame fragmentation
        
        # Get columns safely
        inst_col = instrument_dump['inst_type_raw'].astype(str).str.upper() if 'inst_type_raw' in instrument_dump.columns else pd.Series([""] * len(instrument_dump))
        opt_col = instrument_dump['opt_type_raw'].astype(str).str.upper() if 'opt_type_raw' in instrument_dump.columns else pd.Series([""] * len(instrument_dump))
        exch_col = instrument_dump['exchange'].astype(str)
        
        types = []
        # Vectorized logic is hard here due to mixed conditions, using fast loop
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
                types.append('EQ') # Default
        
        instrument_dump['instrument_type'] = types
        
        # 5. Parse Dates (Optimized)
        def parse_expiry(val):
            try:
                if is_number(val):
                    # Check if milliseconds (13 digits) or seconds (10 digits)
                    if val > 10000000000: 
                        return datetime.fromtimestamp(val/1000).date()
                    return datetime.fromtimestamp(val).date()
                return pd.to_datetime(val).date()
            except:
                return None

        if 'expiry_orig' in instrument_dump.columns:
            instrument_dump['expiry_date'] = instrument_dump['expiry_orig'].apply(parse_expiry)
            instrument_dump['expiry_str'] = instrument_dump['expiry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else None)
        
        # Clean Strings
        instrument_dump['name'] = instrument_dump['name'].astype(str).str.strip().str.upper()
        if 'tradingsymbol' in instrument_dump.columns:
            instrument_dump['tradingsymbol'] = instrument_dump['tradingsymbol'].astype(str).str.strip().str.upper()

        # 6. Build Fast Lookup Cache
        print("⚡ Building Fast Lookup Cache...")
        
        exchange_priority = {'NFO': 0, 'MCX': 1, 'NSE': 2, 'BSE': 3}
        instrument_dump['priority'] = instrument_dump['exchange'].map(exchange_priority).fillna(99)
        instrument_dump.sort_values('priority', inplace=True)
        
        if 'tradingsymbol' in instrument_dump.columns:
            unique_symbols = instrument_dump.drop_duplicates(subset=['tradingsymbol'])
            symbol_map = unique_symbols.set_index('tradingsymbol').to_dict('index')
            print(f"✅ Instruments Indexed. Count: {len(instrument_dump)}")
        else:
            print("❌ Error: 'tradingsymbol' column missing, cannot build map.")
            symbol_map = {}
        
    except Exception as e:
        print(f"❌ Failed to fetch/process instruments: {e}")
        import traceback
        traceback.print_exc()
        if instrument_dump is None: instrument_dump = pd.DataFrame()
        symbol_map = {}

def get_alice_instrument(alice, symbol):
    """
    Resolves a string symbol (e.g. 'NFO:NIFTY24JAN...') to an AliceBlue Instrument object.
    """
    global symbol_map
    
    # 1. Parse Exchange
    exch = None
    trd_sym = symbol
    if ":" in symbol:
        parts = symbol.split(":")
        exch = parts[0]
        trd_sym = parts[1]
    
    # 2. Try Map Lookup first (Fastest)
    if symbol_map and trd_sym in symbol_map:
        row = symbol_map[trd_sym]
        try:
            return alice.get_instrument_by_symbol(row['exchange'], row['tradingsymbol'])
        except: pass
    
    # 3. Try Direct SDK Lookup
    if exch:
        try:
            return alice.get_instrument_by_symbol(exch, trd_sym)
        except: pass
        
    return None

def get_exchange_name(symbol):
    global symbol_map
    if ":" in symbol: return symbol.split(":")[0]
    if symbol_map and symbol in symbol_map:
        return symbol_map[symbol]['exchange']
    
    # Fallback
    if "NIFTY" in symbol or "BANKNIFTY" in symbol:
        if any(x in symbol for x in ["FUT", "CE", "PE"]): return "NFO"
    return "NSE"

def get_ltp(alice, symbol):
    try:
        inst = get_alice_instrument(alice, symbol)
        if not inst: return 0.0
        
        quote = alice.get_scrip_info(inst)
        if quote and 'LTP' in quote:
            return float(quote['LTP'])
        return 0.0
    except Exception as e:
        print(f"⚠️ Error fetching LTP for {symbol}: {e}")
        return 0.0

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
    cleaned = common_name
    if "(" in cleaned: cleaned = cleaned.split("(")[0]
    u = cleaned.upper().strip()
    if u in ["BANKNIFTY", "NIFTY BANK", "BANK NIFTY"]: return "BANKNIFTY"
    if u in ["NIFTY", "NIFTY 50", "NIFTY50"]: return "NIFTY"
    return u

def get_lot_size(tradingsymbol):
    global symbol_map
    if not symbol_map: return 1
    data = symbol_map.get(tradingsymbol)
    if data:
        return int(data.get('lot_size', 1))
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
                try:
                    dt = datetime.strptime(expiry_str, '%Y-%m-%d')
                    expiry_str = dt.strftime('%d %b').upper()
                except: pass

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

def search_symbols(alice, keyword, allowed_exchanges=None):
    global instrument_dump
    
    if instrument_dump is None or instrument_dump.empty: 
        fetch_instruments(alice)
        if instrument_dump is None or instrument_dump.empty: return []

    k = keyword.upper()
    if not allowed_exchanges: 
        allowed_exchanges = ['NSE', 'NFO', 'MCX']
    
    try:
        # Filter Logic
        mask = (instrument_dump['exchange'].isin(allowed_exchanges)) & (instrument_dump['name'].str.startswith(k, na=False))
        matches = instrument_dump[mask]
        
        if matches.empty: return []
            
        unique_matches = matches.drop_duplicates(subset=['name', 'exchange']).head(10)
        
        results = []
        for _, row in unique_matches.iterrows():
            results.append(f"{row['name']} ({row['exchange']})")
            
        return results
    except Exception as e:
        print(f"Search Logic Error: {e}")
        return []

def get_symbol_details(alice, symbol, preferred_exchange=None):
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: fetch_instruments(alice)
    if instrument_dump is None or instrument_dump.empty: return {}
    
    if "(" in symbol: symbol = symbol.split('(')[0].strip()

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
    if not fno_rows.empty:
        lot = int(fno_rows.iloc[0]['lot_size'])

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
        lbl = "OTM"
        if s == atm: lbl = "ATM"
        elif option_type == "CE": lbl = "ITM" if ltp > s else "OTM"
        elif option_type == "PE": lbl = "ITM" if ltp < s else "OTM"
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
        mask = (
            (instrument_dump['name'] == clean) & 
            (instrument_dump['expiry_str'] == expiry) & 
            (instrument_dump['strike'] == strike_price) & 
            (instrument_dump['instrument_type'] == option_type)
        )
        
    if not mask.any(): return None
    return instrument_dump[mask].iloc[0]['tradingsymbol']

def get_specific_ltp(alice, symbol, expiry, strike, inst_type):
    ts = get_exact_symbol(symbol, expiry, strike, inst_type)
    if not ts: return 0.0
    
    exch = "NFO" 
    if symbol_map and ts in symbol_map:
        exch = symbol_map[ts]['exchange']
        
    return get_ltp(alice, f"{exch}:{ts}")

def get_instrument_token(tradingsymbol, exchange):
    global symbol_map
    if symbol_map and tradingsymbol in symbol_map:
        return symbol_map[tradingsymbol]['instrument_token']
    return None

def fetch_historical_data(alice, token, from_date, to_date, interval='1'):
    return []

def get_telegram_symbol(tradingsymbol):
    return get_display_name(tradingsymbol)
