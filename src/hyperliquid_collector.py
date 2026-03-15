#!/usr/bin/env python3
"""
Hyperliquid Data Collector
Fetches perpetual futures data from Hyperliquid Info API
"""

import requests
import sqlite3
import time
import json
from datetime import datetime
from typing import List, Dict, Optional

# Hyperliquid API
INFO_URL = "https://api.hyperliquid.xyz/info"

# Database path
DB_PATH = "../data/hyperliquid_perps.db"

# Target symbols (major crypto perps)
TARGET_SYMBOLS = [
    "BTC-USD",
    "ETH-USD", 
    "SOL-USD",
    "AVAX-USD",
    "MATIC-USD"
]


def init_database():
    """Initialize SQLite database with schema"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Perps table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS perps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        mark_price REAL,
        index_price REAL,
        funding_rate REAL,
        open_interest REAL,
        volume_24h REAL,
        timestamp INTEGER,
        raw_data TEXT
    )
    """)
    
    # Funding changes table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS funding_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        old_rate REAL,
        new_rate REAL,
        magnitude REAL,
        timestamp INTEGER
    )
    """)
    
    # Indexes
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_perps_symbol_timestamp 
    ON perps(symbol, timestamp DESC)
    """)
    
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_funding_changes_magnitude 
    ON funding_changes(magnitude DESC)
    """)
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")


def fetch_meta() -> Optional[Dict]:
    """
    Fetch market metadata from Hyperliquid
    
    Returns:
        Metadata dictionary with all available markets
    """
    try:
        payload = {"type": "meta"}
        response = requests.post(INFO_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"✅ Fetched metadata for {len(data.get('universe', []))} markets")
        return data
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API error: {e}")
        return None


def fetch_all_mids() -> Optional[Dict]:
    """
    Fetch all mid prices (mark prices) from Hyperliquid
    
    Returns:
        Dictionary mapping symbol → mid price
    """
    try:
        payload = {"type": "allMids"}
        response = requests.post(INFO_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Convert to dict for easy lookup
        mids = {item["coin"]: float(item["mid"]) for item in data.get("mids", [])}
        print(f"✅ Fetched {len(mids)} mid prices")
        return mids
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API error: {e}")
        return None


def fetch_funding_rates() -> Optional[List[Dict]]:
    """
    Fetch funding rates for all perpetuals
    
    Returns:
        List of funding rate data
    """
    try:
        payload = {"type": "metaAndAssetCtxs"}
        response = requests.post(INFO_URL, json=payload, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Extract funding info
        funding_data = []
        for ctx in data.get("assetCtxs", []):
            funding_data.append({
                "symbol": ctx.get("coin", ""),
                "funding_rate": float(ctx.get("funding", 0)),
                "open_interest": float(ctx.get("openInterest", 0)),
                "volume_24h": float(ctx.get("dayNtlVlm", 0)),
                "mark_price": float(ctx.get("markPx", 0)),
                "oracle_price": float(ctx.get("oraclePx", 0))
            })
        
        print(f"✅ Fetched funding data for {len(funding_data)} markets")
        return funding_data
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API error: {e}")
        return None


def extract_perp_data(funding_info: Dict) -> Optional[Dict]:
    """
    Extract relevant fields from funding data
    
    Args:
        funding_info: Raw funding dictionary
    
    Returns:
        Cleaned perp dictionary
    """
    try:
        # Normalize symbol format (Hyperliquid uses "BTC" not "BTC-USD")
        symbol = funding_info["symbol"]
        if not symbol.endswith("-USD"):
            symbol = f"{symbol}-USD"
        
        perp = {
            "symbol": symbol,
            "mark_price": funding_info["mark_price"],
            "index_price": funding_info["oracle_price"],
            "funding_rate": funding_info["funding_rate"],
            "open_interest": funding_info["open_interest"],
            "volume_24h": funding_info["volume_24h"],
            "timestamp": int(time.time()),
            "raw_data": json.dumps(funding_info)
        }
        
        return perp
        
    except (KeyError, ValueError, TypeError) as e:
        print(f"⚠️  Parse error: {e}")
        return None


def store_perp(conn: sqlite3.Connection, perp: Dict):
    """
    Store perp data in database and detect funding rate changes
    
    Args:
        conn: Database connection
        perp: Perp dictionary
    """
    cursor = conn.cursor()
    
    # Check last funding rate for this symbol
    cursor.execute("""
    SELECT funding_rate FROM perps 
    WHERE symbol = ? 
    ORDER BY timestamp DESC LIMIT 1
    """, (perp["symbol"],))
    
    result = cursor.fetchone()
    
    if result:
        old_rate = result[0]
        new_rate = perp["funding_rate"]
        magnitude = abs(new_rate - old_rate)
        
        # Log if change is significant (>0.001% = 0.00001)
        if magnitude > 0.00001:
            cursor.execute("""
            INSERT INTO funding_changes 
            (symbol, old_rate, new_rate, magnitude, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """, (
                perp["symbol"],
                old_rate,
                new_rate,
                magnitude,
                perp["timestamp"]
            ))
            
            print(f"📊 {perp['symbol']}: {old_rate:.6f} → {new_rate:.6f} ({magnitude:+.6f})")
    
    # Insert perp snapshot
    cursor.execute("""
    INSERT INTO perps 
    (symbol, mark_price, index_price, funding_rate, open_interest, volume_24h, timestamp, raw_data)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        perp["symbol"],
        perp["mark_price"],
        perp["index_price"],
        perp["funding_rate"],
        perp["open_interest"],
        perp["volume_24h"],
        perp["timestamp"],
        perp["raw_data"]
    ))


def collect_snapshot(symbols_filter: Optional[List[str]] = None):
    """
    Fetch and store one snapshot of Hyperliquid perps
    
    Args:
        symbols_filter: List of symbols to track (None = all)
    """
    print(f"\n{'='*60}")
    print(f"Hyperliquid Snapshot - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # Fetch funding data
    funding_data = fetch_funding_rates()
    if not funding_data:
        print("❌ No funding data fetched")
        return
    
    # Filter symbols if requested
    if symbols_filter:
        funding_data = [
            item for item in funding_data 
            if item["symbol"] in symbols_filter or f"{item['symbol']}-USD" in symbols_filter
        ]
        print(f"🔍 Filtered to {len(funding_data)} symbols")
    
    # Open database
    conn = sqlite3.connect(DB_PATH)
    
    # Process each market
    perps_stored = 0
    changes_detected = 0
    
    for funding_info in funding_data:
        perp = extract_perp_data(funding_info)
        if perp:
            store_perp(conn, perp)
            perps_stored += 1
    
    # Get changes count
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM funding_changes WHERE timestamp >= ?",
        (int(time.time()) - 60,)  # Last minute
    )
    changes_detected = cursor.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Stored {perps_stored} perps")
    print(f"📊 Detected {changes_detected} funding rate changes")


def run_continuous(interval_seconds: int = 10, symbols_filter: Optional[List[str]] = None):
    """
    Run collector continuously
    
    Args:
        interval_seconds: Time between snapshots
        symbols_filter: Symbols to track (None = all)
    """
    print(f"🚀 Starting Hyperliquid collector (interval: {interval_seconds}s)")
    if symbols_filter:
        print(f"🔍 Tracking: {', '.join(symbols_filter)}")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            collect_snapshot(symbols_filter)
            print(f"\n💤 Sleeping {interval_seconds}s...\n")
            time.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Collector stopped")


if __name__ == "__main__":
    import sys
    
    # Initialize DB on first run
    init_database()
    
    # Parse arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "once":
            # Single snapshot
            symbols = TARGET_SYMBOLS if len(sys.argv) == 2 else None
            collect_snapshot(symbols)
        elif sys.argv[1] == "continuous":
            # Continuous mode
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            run_continuous(interval, TARGET_SYMBOLS)
        else:
            print("Usage:")
            print("  python3 hyperliquid_collector.py once           # Single snapshot (major symbols)")
            print("  python3 hyperliquid_collector.py continuous [N] # Run every N seconds")
    else:
        # Default: single snapshot
        collect_snapshot(TARGET_SYMBOLS)
