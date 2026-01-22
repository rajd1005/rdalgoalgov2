import pandas as pd
from datetime import datetime, timedelta
import pytz
import re
import os

# Global IST Timezone
IST = pytz.timezone('Asia/Kolkata')

instrument_dump = None 
symbol_map = {} # FAST LOOKUP CACHE

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
    try:
        # 1. Download Contracts (Saves to local CSVs automatically by pya3)
        # FIX: Correct method name is get_contract_master
        alice.get_contract_master("NSE")
        alice.get_contract_master("NFO")
        alice.get_contract_master("MCX")
        
        # 2. Load CSVs into Pandas
        # pya3 usually saves them as 'NSE.csv', 'NFO.csv', 'MCX.csv' in current dir
        dfs = []
        for exch in ['NSE', 'NFO', 'MCX']:
            fname = f"{exch}.csv"
            if os.path.exists(fname):
                # AliceBlue CSV headers are typically:
                # Exchange,Token,LotSize,Symbol,TradingSymbol,ExpiryDate,Instrument,OptionType,StrikePrice
                try:
                    df = pd.read_csv(fname)
                    df['exchange'] = exch
                    dfs.append(df)
                except Exception as e:
                    print(f"⚠️ Error reading {fname}: {e}")
        
        if not dfs:
            print("⚠️ Warning: No contract files found (NSE.csv, etc).")
            return

        instrument_dump = pd.concat(dfs, ignore_index=True)
        
        # 3. Normalize Columns to match existing logic
        # Map AliceBlue cols to standard cols used in this app
        # Expected: name, tradingsymbol, expiry_str, strike, instrument_type, lot_size, token
        
        # Rename columns if they exist (Header names might vary slightly based on pya3 version, using common keys)
        # Common keys: 'Symbol'->name, 'TradingSymbol'->tradingsymbol, 'Token'->instrument_token
        
        col_map = {
            'Symbol': 'name',
            'TradingSymbol': 'tradingsymbol', 
            'Token': 'instrument_token', 
            'LotSize': 'lot_size',
            'StrikePrice': 'strike',
            'ExpiryDate': 'expiry_orig'
        }
        instrument_dump.rename(columns=col_map, inplace=True)
        
        # standardize instrument_type
        # Alice 'OptionType' usually has 'CE', 'PE', 'XX' (for Fut/Eq)
        # Alice 'Instrument' usually has 'OPTIDX', 'FUTIDX', 'EQUITY'
        
        def normalize_inst_type(row):
            itype = str(row.get('Instrument', '')).upper()
            otype = str(row.get('OptionType', '')).upper()
            # FIX: Use the row's exchange, not the loop variable
            exch_val = str(row.get('exchange', ''))
            
            if 'OPT' in itype:
                return otype # CE or PE
            if 'FUT' in itype:
                return 'FUT'
            if 'EQ' in itype or exch_val == 'NSE':
                return 'EQ'
            return 'EQ'

        instrument_dump['instrument_type'] = instrument_dump.apply(normalize_inst_type, axis=1)
        
        # Parse Dates
        # Alice Date format is often timestamp or milliseconds. 
        # But pya3 CSV often writes human readable or epoch.
        # We will attempt generic parsing.
        
        def parse_expiry(val):
            try:
                # Try epoch first (if int/float)
                if pd.api.types.is_number(val):
                    # check if seconds or ms
                    if val > 10000000000: # likely ms
                        return datetime.fromtimestamp(val/1000).date()
                    return datetime.fromtimestamp(val).date()
                
                # Try string parse
                return pd.to_datetime(val).date()
            except:
                return None

        if 'expiry_orig' in instrument_dump.columns:
            instrument_dump['expiry_date'] = instrument_dump['expiry_orig'].apply(parse_expiry)
            instrument_dump['expiry_str'] = instrument_dump['expiry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else None)
        
        # Clean Name (Remove white spaces)
        instrument_dump['name'] = instrument_dump['name'].astype(str).str.strip().str.upper()
        instrument_dump['tradingsymbol'] = instrument_dump['tradingsymbol'].astype(str).str.strip().str.upper()

        # 4. Build Fast Lookup Cache (Symbol -> Instrument Object/Dict)
        print("⚡ Building Fast Lookup Cache...")
        
        # Prioritize exchanges: NFO > MCX > NSE
        exchange_priority = {'NFO': 0, 'MCX': 1, 'NSE': 2, 'BSE': 3}
        instrument_dump['priority'] = instrument_dump['exchange'].map(exchange_priority).fillna(99)
        instrument_dump.sort_values('priority', inplace=True)
        
        # Drop duplicates on tradingsymbol
        unique_symbols = instrument_dump.drop_duplicates(subset=['tradingsymbol'])
        
        # Set index
        symbol_map = unique_symbols.set_index('tradingsymbol').to_dict('index')
        
        print(f"✅ Instruments Indexed. Count: {len(instrument_dump)}")
        
    except Exception as e:
        print(f"❌ Failed to fetch instruments: {e}")
        if instrument_dump is None: instrument_dump = pd.DataFrame()
        symbol_map = {}

def get_alice_instrument(alice, symbol):
    """
    Resolves a string symbol (e.g. 'NFO:NIFTY24JAN...') to an AliceBlue Instrument object.
    Required for placing orders or fetching specific LTP.
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
        # Use AliceBlue SDK method to get instrument by token/symbol
        # alice.get_instrument_by_symbol(exchange, symbol)
        try:
            return alice.get_instrument_by_symbol(row['exchange'], row['tradingsymbol'])
        except: pass
    
    # 3. Try Direct SDK Lookup if map fails
    if exch:
        try:
            return alice.get_instrument_by_symbol(exch, trd_sym)
        except: pass
        
    return None

def get_exchange_name(symbol):
    """
    Determines the exchange (NSE, NFO, MCX) for a given symbol.
    """
    global symbol_map
    if ":" in symbol: return symbol.split(":")[0]
    
    if symbol_map and symbol in symbol_map:
        return symbol_map[symbol]['exchange']
    
    # Fallback
    if "NIFTY" in symbol or "BANKNIFTY" in symbol:
        if any(x in symbol for x in ["FUT", "CE", "PE"]): return "NFO"
    return "NSE"

def get_ltp(alice, symbol):
    """
    Fetches the Last Traded Price (LTP).
    """
    try:
        inst = get_alice_instrument(alice, symbol)
        if not inst: return 0.0
        
        # Get Live Feed
        # alice.get_scrip_info(instrument) returns dict
        quote = alice.get_scrip_info(inst)
        if quote and 'LTP' in quote:
            return float(quote['LTP'])
        return 0.0
    except Exception as e:
        print(f"⚠️ Error fetching LTP for {symbol}: {e}")
        return 0.0

def get_indices_ltp(alice):
    """
    Fetches NIFTY 50, BANKNIFTY, SENSEX.
    AliceBlue index symbols can vary. Assuming standard names or tokens.
    """
    indices = {"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0}
    try:
        # Define Instruments (You might need to adjust 'Nifty 50' based on exact Alice CSV name)
        nifty = alice.get_instrument_by_symbol("NSE", "Nifty 50")
        bank = alice.get_instrument_by_symbol("NSE", "Nifty Bank")
        sensex = alice.get_instrument_by_symbol("BSE", "SENSEX") # If enabled
        
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
    # Normalized name helper
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
    # Make symbol readable (e.g., NIFTY 21500 CE)
    global symbol_map
    if not symbol_map: return tradingsymbol
    
    try:
        data = symbol_map.get(tradingsymbol)
        if data:
            name = data['name']
            inst_type = data['instrument_type']
            expiry_str = data.get('expiry_str', '')
            
            # Format Expiry date to something short like '24 JAN'
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
    """
    Search using local dataframe for speed, or alice search API.
    Local DF is preferred for consistency with filters.
    """
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
            # We don't fetch LTP here to keep search fast, just return name
            # Format: Name (Exch) : Token
            results.append(f"{row['name']} ({row['exchange']})")
            
        return results
    except Exception as e:
        print(f"Search Logic Error: {e}")
        return []

def get_symbol_details(alice, symbol, preferred_exchange=None):
    """
    Get detailed info (LTP, Expiries) for a UI modal.
    """
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: fetch_instruments(alice)
    if instrument_dump is None or instrument_dump.empty: return {}
    
    if "(" in symbol: symbol = symbol.split('(')[0].strip()

    clean = get_zerodha_symbol(symbol)
    today = datetime.now(IST).date()
    
    # Filter DF for this name
    rows = instrument_dump[instrument_dump['name'] == clean]
    if rows.empty: return {}

    # Get LTP for underlying
    ltp = 0
    try:
        # Try finding the equity or index underlying
        # Priority: NSE > BSE
        underlying = rows[rows['instrument_type'] == 'EQ']
        if not underlying.empty:
            # Pick NSE if avail
            u_row = underlying[underlying['exchange']=='NSE'].iloc[0] if not underlying[underlying['exchange']=='NSE'].empty else underlying.iloc[0]
            ltp = get_ltp(alice, f"{u_row['exchange']}:{u_row['tradingsymbol']}")
    except: pass
    
    # If no equity ltp, try Near Month Future
    if ltp == 0:
        try:
            futs = rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today)].sort_values('expiry_date')
            if not futs.empty:
                 f_row = futs.iloc[0]
                 ltp = get_ltp(alice, f"{f_row['exchange']}:{f_row['tradingsymbol']}")
        except: pass

    lot = 1
    # Get Lot Size from first FNO record
    fno_rows = rows[rows['exchange'].isin(['NFO', 'MCX'])]
    if not fno_rows.empty:
        lot = int(fno_rows.iloc[0]['lot_size'])

    # Get Expiries
    f_exp = []
    o_exp = []
    
    if 'expiry_str' in rows.columns:
        f_exp = sorted(rows[(rows['instrument_type'] == 'FUT') & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
        o_exp = sorted(rows[(rows['instrument_type'].isin(['CE', 'PE'])) & (rows['expiry_date'] >= today)]['expiry_str'].unique().tolist())
    
    return {"symbol": clean, "ltp": ltp, "lot_size": lot, "fut_expiries": f_exp, "opt_expiries": o_exp}

def get_chain_data(symbol, expiry_date, option_type, ltp):
    """
    Builds option chain data from local dataframe.
    """
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: return []
    clean = get_zerodha_symbol(symbol)
    
    if 'expiry_str' not in instrument_dump.columns: return []
    
    # Filter
    c = instrument_dump[
        (instrument_dump['name'] == clean) & 
        (instrument_dump['expiry_str'] == expiry_date) & 
        (instrument_dump['instrument_type'] == option_type)
    ]
    if c.empty: return []
    
    strikes = sorted(c['strike'].unique().tolist())
    if not strikes: return []
    
    # Label ITM/OTM/ATM
    # Find ATM
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
    """
    Reconstructs the trading symbol for order placement.
    """
    global instrument_dump
    if instrument_dump is None or instrument_dump.empty: return None
    
    clean = get_zerodha_symbol(symbol)
    
    if option_type == "EQ":
        # Return first EQ match
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
    
    # Get Exchange
    exch = "NFO" # default
    if symbol_map and ts in symbol_map:
        exch = symbol_map[ts]['exchange']
        
    return get_ltp(alice, f"{exch}:{ts}")

def get_instrument_token(tradingsymbol, exchange):
    # Required for Historical Data
    global symbol_map
    if symbol_map and tradingsymbol in symbol_map:
        return symbol_map[tradingsymbol]['instrument_token']
    return None

def fetch_historical_data(alice, token, from_date, to_date, interval='1'):
    # AliceBlue Historical Data
    # Note: alice.get_historical needs an instrument object.
    # token is passed, we need to find the instrument object first.
    # This is complex without the object. We might need to change architecture to pass symbol.
    # For now, return empty as historical isn't strictly used in the main logic (only Replay).
    return []

def get_telegram_symbol(tradingsymbol):
    # Basic formatter for Telegram
    # Example: NIFTY24JAN21500CE -> NIFTY 21500 CE 24JAN
    # Alice symbols might be NIFTY24JAN21500CE
    return get_display_name(tradingsymbol)
