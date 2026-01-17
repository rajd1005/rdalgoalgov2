import pandas as pd
from datetime import datetime, timedelta
import threading

# Global variables to store instrument data
instrument_dump = None
symbol_map = {}

# LOCK to prevent crashes when updating instruments while Risk Engine is reading
INSTRUMENT_LOCK = threading.Lock()

def fetch_instruments(kite):
    """
    Downloads and indexes the instrument list from Kite.
    Protected by a thread lock to ensure safe concurrency.
    """
    global instrument_dump, symbol_map
    try:
        print("📥 Downloading Instrument List...")
        instruments = kite.instruments()
        
        with INSTRUMENT_LOCK:
            instrument_dump = pd.DataFrame(instruments)
            
            # Create a fast lookup map: 'TRADINGSYMBOL' -> Row Data
            # We map the tradingsymbol to the dictionary record for fast O(1) access
            unique_symbols = instrument_dump.drop_duplicates(subset=['tradingsymbol'])
            symbol_map = unique_symbols.set_index('tradingsymbol').to_dict('index')
            
        print(f"✅ Instruments Downloaded & Indexed. Count: {len(symbol_map)}")
        return True
    except Exception as e:
        print(f"❌ Error fetching instruments: {e}")
        return False

def get_instrument_token(symbol, exchange):
    """
    Returns the instrument token for a given symbol and exchange.
    Uses the fast hash map first, then falls back to dataframe search.
    """
    try:
        # Use the map for instant lookup instead of filtering DataFrame
        with INSTRUMENT_LOCK:
            if symbol in symbol_map:
                item = symbol_map[symbol]
                if item['exchange'] == exchange:
                    return item['instrument_token']
        
        # Fallback to slower dataframe search if map fails (rare case)
        with INSTRUMENT_LOCK:
            if instrument_dump is not None:
                res = instrument_dump[(instrument_dump['tradingsymbol'] == symbol) & (instrument_dump['exchange'] == exchange)]
                if not res.empty:
                    return res.iloc[0]['instrument_token']
    except Exception as e:
        print(f"Token Lookup Error for {symbol}: {e}")
    return None

def get_lot_size(tradingsymbol):
    """
    Returns lot size. Defaults to 1 if not found or if Equity.
    """
    try:
        with INSTRUMENT_LOCK:
            if tradingsymbol in symbol_map:
                return int(symbol_map[tradingsymbol].get('lot_size', 1))
    except:
        pass
    return 1

def get_display_name(tradingsymbol):
    """
    Returns the friendly name of the symbol if available.
    """
    try:
        with INSTRUMENT_LOCK:
            if tradingsymbol in symbol_map:
                return symbol_map[tradingsymbol].get('name', tradingsymbol)
    except:
        pass
    return tradingsymbol

def search_symbols(kite, query, allowed_exchanges=None):
    """
    Searches for symbols matching the query string.
    Returns a list of matching dictionaries.
    """
    if not query or len(query) < 2: return []
    
    results = []
    try:
        with INSTRUMENT_LOCK:
            if instrument_dump is not None:
                # Filter by string match (Case insensitive)
                mask = instrument_dump['tradingsymbol'].str.contains(query.upper(), na=False)
                
                if allowed_exchanges:
                    mask = mask & instrument_dump['exchange'].isin(allowed_exchanges)
                
                # Limit results to top 20 for performance
                df_res = instrument_dump[mask].head(20)
                
                for _, row in df_res.iterrows():
                    results.append({
                        "symbol": row['tradingsymbol'],
                        "exchange": row['exchange'],
                        "type": row['instrument_type'],
                        "expiry": str(row['expiry']) if row['expiry'] else ""
                    })
    except Exception as e:
        print(f"Search Error: {e}")
    return results

def get_symbol_details(kite, symbol):
    """
    Get detailed info for a symbol (Lot size, Expiry, Tick Size, etc.)
    """
    try:
        with INSTRUMENT_LOCK:
            if symbol in symbol_map:
                row = symbol_map[symbol]
                return {
                    "lot_size": row.get('lot_size', 1),
                    "expiry": str(row.get('expiry', '')),
                    "tick_size": row.get('tick_size', 0.05),
                    "segment": row.get('segment', '')
                }
    except: pass
    return {}

def get_indices_ltp(kite):
    """
    Fetches LTP for major indices (NIFTY 50, BANKNIFTY, SENSEX).
    Hardcoded tokens are used for stability, but names are preferred if mapped.
    """
    tokens = {
        "256265": "NIFTY",       # NIFTY 50 (NSE)
        "260105": "BANKNIFTY",   # NIFTY BANK (NSE)
        "264969": "SENSEX"       # BSE SENSEX
    }
    res = {"NIFTY": 0, "BANKNIFTY": 0, "SENSEX": 0}
    try:
        q = kite.quote(list(tokens.keys()))
        for t, name in tokens.items():
            if t in q:
                res[name] = q[t]['last_price']
    except: pass
    return res

def get_chain_data(symbol, expiry, type_, atm_price):
    """
    Helper to filter option chain data from the instrument dump.
    Returns nearest 10 strikes to the ATM price.
    """
    try:
        with INSTRUMENT_LOCK:
            if instrument_dump is None: return []
            
            # Filter 1: Exchange NFO/BFO/MCX
            mask = instrument_dump['exchange'].isin(['NFO', 'BFO', 'MCX'])
            
            # Filter 2: Name match (Underlying)
            mask = mask & (instrument_dump['name'] == symbol)
            
            # Filter 3: Expiry
            if expiry:
                mask = mask & (instrument_dump['expiry'] == expiry)
            
            # Filter 4: Option Type (CE/PE)
            if type_:
                mask = mask & (instrument_dump['instrument_type'] == type_)
                
            df = instrument_dump[mask].copy()
            
            # Calculate distance from ATM to sort by nearest strikes
            df['dist'] = abs(df['strike'] - atm_price)
            df = df.sort_values('dist').head(10) # Get nearest 10
            
            chain = []
            for _, row in df.iterrows():
                chain.append({
                    "symbol": row['tradingsymbol'],
                    "strike": row['strike'],
                    "type": row['instrument_type'],
                    "expiry": str(row['expiry'])
                })
            return chain
    except Exception as e:
        print(f"Chain Data Error: {e}")
    return []

def get_specific_ltp(kite, symbol, expiry, strike, type_):
    """
    Constructs symbol based on parameters and fetches its LTP.
    Ex: NIFTY 23OCT 19500 CE
    """
    try:
        # --- FIX: Validate inputs before converting to float ---
        if not strike or not expiry or not type_:
            return 0
        
        # Check if strike is a valid number, otherwise return 0 (handles 'Select Type First')
        try:
            strike_val = float(strike)
        except (ValueError, TypeError):
            return 0
        # --- END FIX ---

        with INSTRUMENT_LOCK:
            if instrument_dump is None: return 0
            
            mask = (instrument_dump['name'] == symbol) & \
                   (instrument_dump['strike'] == strike_val) & \
                   (instrument_dump['instrument_type'] == type_) & \
                   (instrument_dump['expiry'] == expiry)
                   
            res = instrument_dump[mask]
            if not res.empty:
                tsym = res.iloc[0]['tradingsymbol']
                exch = res.iloc[0]['exchange']
                q = kite.quote(f"{exch}:{tsym}")
                return q[f"{exch}:{tsym}"]['last_price']
    except Exception as e:
        print(f"Spec LTP Error: {e}")
    return 0

def get_exact_symbol(name, expiry, strike, type_):
    """
    Finds the exact Tradingsymbol based on Option parameters.
    """
    try:
        with INSTRUMENT_LOCK:
            if instrument_dump is None: return None
            
            mask = (instrument_dump['name'] == name) & \
                   (instrument_dump['strike'] == float(strike)) & \
                   (instrument_dump['instrument_type'] == type_) & \
                   (instrument_dump['expiry'] == expiry)
            
            res = instrument_dump[mask]
            if not res.empty:
                return res.iloc[0]['tradingsymbol']
    except: pass
    return None

def fetch_historical_data(kite, token, from_date, to_date, interval):
    """
    Wrapper for Kite's historical data API.
    """
    try:
        return kite.historical_data(token, from_date, to_date, interval)
    except Exception as e:
        print(f"Hist Data Error: {e}")
        return []
        
def get_telegram_symbol(raw_symbol):
    """
    Formats symbol for Telegram messages to look cleaner.
    Example: NIFTY23OCT19500CE -> NIFTY 19500 CE
    """
    try:
        # Simple cleanup to make it readable
        # This is a basic implementation; can be enhanced with Regex if needed
        if "NIFTY" in raw_symbol or "BANKNIFTY" in raw_symbol:
            return raw_symbol 
    except: pass
    return raw_symbol
