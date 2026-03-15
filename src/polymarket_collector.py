#!/usr/bin/env python3
"""
Polymarket Data Collector
Fetches event probabilities from Polymarket CLOB API
"""

import requests
import sqlite3
import time
import json
from datetime import datetime
from typing import List, Dict, Optional

# Polymarket API endpoints
BASE_URL = "https://clob.polymarket.com"
MARKETS_ENDPOINT = f"{BASE_URL}/markets"

# Database path
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "data", "polymarket_events.db")


def init_database():
    """Initialize SQLite database with schema"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Events table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        title TEXT,
        category TEXT,
        probability REAL,
        volume_24h REAL,
        liquidity REAL,
        timestamp INTEGER,
        raw_data TEXT
    )
    """)
    
    # Probability changes table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS probability_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT,
        old_prob REAL,
        new_prob REAL,
        magnitude REAL,
        timestamp INTEGER,
        FOREIGN KEY (event_id) REFERENCES events(event_id)
    )
    """)
    
    # Index for fast lookups
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_event_timestamp 
    ON events(timestamp DESC)
    """)
    
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_prob_changes_magnitude 
    ON probability_changes(magnitude DESC)
    """)
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")


def fetch_markets(limit: int = 100) -> List[Dict]:
    """
    Fetch active markets from Polymarket
    
    Args:
        limit: Max number of markets to fetch
    
    Returns:
        List of market dictionaries
    """
    try:
        params = {
            "limit": limit,
            "active": "true"  # Only active markets
        }
        
        response = requests.get(MARKETS_ENDPOINT, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # API returns {"data": [...]} or [...] depending on version
        if isinstance(data, dict) and "data" in data:
            markets = data["data"]
        elif isinstance(data, list):
            markets = data
        else:
            print(f"❌ Unexpected response format: {type(data)}")
            return []
        
        print(f"✅ Fetched {len(markets)} markets")
        return markets
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API error: {e}")
        return []


def extract_event_data(market: Dict) -> Optional[Dict]:
    """
    Extract relevant fields from Polymarket market
    
    Args:
        market: Raw market dictionary from API
    
    Returns:
        Cleaned event dictionary
    """
    try:
        # Skip closed/archived markets
        if market.get("closed", False) or market.get("archived", False):
            return None
        
        # Polymarket uses "tokens" array with prices
        tokens = market.get("tokens", [])
        if not tokens:
            return None
        
        # Primary outcome (first token, usually "Yes")
        primary_token = tokens[0]
        probability = float(primary_token.get("price", 0))
        
        # Get tags for category (join multiple tags)
        tags = market.get("tags", [])
        category = ", ".join(tags) if tags else "Unknown"
        
        event = {
            "event_id": market.get("condition_id", ""),
            "title": market.get("question", ""),
            "category": category,
            "probability": probability,
            "volume_24h": 0,  # Not provided in this API version
            "liquidity": 0,   # Not provided in this API version
            "timestamp": int(time.time()),
            "raw_data": json.dumps(market)  # Store full response for debugging
        }
        
        return event
        
    except (KeyError, ValueError, TypeError) as e:
        print(f"⚠️  Parse error for {market.get('question', 'unknown')}: {e}")
        return None


def store_event(conn: sqlite3.Connection, event: Dict):
    """
    Store event in database and detect probability changes
    
    Args:
        conn: Database connection
        event: Event dictionary
    """
    cursor = conn.cursor()
    
    # Check if event exists (get old probability)
    cursor.execute(
        "SELECT probability FROM events WHERE event_id = ?",
        (event["event_id"],)
    )
    result = cursor.fetchone()
    
    if result:
        old_prob = result[0]
        new_prob = event["probability"]
        magnitude = abs(new_prob - old_prob)
        
        # Only log if change is significant (>1%)
        if magnitude > 0.01:
            cursor.execute("""
            INSERT INTO probability_changes 
            (event_id, old_prob, new_prob, magnitude, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """, (
                event["event_id"],
                old_prob,
                new_prob,
                magnitude,
                event["timestamp"]
            ))
            
            print(f"📊 {event['title'][:50]}: {old_prob:.2%} → {new_prob:.2%} ({magnitude:+.2%})")
    
    # Upsert event (update if exists, insert if not)
    cursor.execute("""
    INSERT OR REPLACE INTO events 
    (event_id, title, category, probability, volume_24h, liquidity, timestamp, raw_data)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event["event_id"],
        event["title"],
        event["category"],
        event["probability"],
        event["volume_24h"],
        event["liquidity"],
        event["timestamp"],
        event["raw_data"]
    ))


def collect_snapshot():
    """
    Fetch and store one snapshot of Polymarket events
    """
    print(f"\n{'='*60}")
    print(f"Polymarket Snapshot - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # Fetch markets
    markets = fetch_markets(limit=100)
    if not markets:
        print("❌ No markets fetched")
        return
    
    # Open database
    conn = sqlite3.connect(DB_PATH)
    
    # Process each market
    events_stored = 0
    changes_detected = 0
    
    for market in markets:
        event = extract_event_data(market)
        if event:
            store_event(conn, event)
            events_stored += 1
    
    # Get changes count
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM probability_changes WHERE timestamp >= ?",
        (int(time.time()) - 60,)  # Last minute
    )
    changes_detected = cursor.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Stored {events_stored} events")
    print(f"📊 Detected {changes_detected} probability changes")


def run_continuous(interval_seconds: int = 60):
    """
    Run collector continuously
    
    Args:
        interval_seconds: Time between snapshots
    """
    print(f"🚀 Starting Polymarket collector (interval: {interval_seconds}s)")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            collect_snapshot()
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
            collect_snapshot()
        elif sys.argv[1] == "continuous":
            # Continuous mode
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
            run_continuous(interval)
        else:
            print("Usage:")
            print("  python3 polymarket_collector.py once           # Single snapshot")
            print("  python3 polymarket_collector.py continuous [N] # Run every N seconds")
    else:
        # Default: single snapshot
        collect_snapshot()
