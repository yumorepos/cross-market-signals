#!/usr/bin/env python3
"""
Cross-Market Signal Detector
Identifies exploitable divergences between Polymarket events and Hyperliquid perps
"""

import sqlite3
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

# Event → Asset Mapping
# Maps Polymarket event keywords to Hyperliquid perpetual symbols
SIGNAL_MAP = {
    # Crypto-specific events
    "bitcoin": ["BTC-USD"],
    "btc": ["BTC-USD"],
    "ethereum": ["ETH-USD"],
    "eth": ["ETH-USD", "BTC-USD"],  # ETH events often lift all boats
    "solana": ["SOL-USD"],
    "sol": ["SOL-USD"],
    
    # Regulatory events (broad crypto impact)
    "sec": ["BTC-USD", "ETH-USD", "SOL-USD"],
    "regulation": ["BTC-USD", "ETH-USD"],
    "etf": ["BTC-USD", "ETH-USD"],
    "ban": ["BTC-USD", "ETH-USD"],
    
    # Macro events (risk-on/risk-off)
    "fed": ["BTC-USD", "ETH-USD"],
    "rates": ["BTC-USD"],
    "recession": ["BTC-USD"],
    "inflation": ["BTC-USD"],
    
    # Protocol events
    "upgrade": [],  # Will be dynamically matched (e.g., "solana upgrade" → SOL-USD)
    "hack": [],     # Will be dynamically matched to affected asset
    "halving": ["BTC-USD"],
}


def get_probability_changes(
    conn: sqlite3.Connection,
    since_minutes: int = 5,
    min_magnitude: float = 0.10  # 10% probability shift
) -> List[Dict]:
    """
    Get recent significant probability changes from Polymarket
    
    Args:
        conn: Database connection
        since_minutes: Look back this many minutes
        min_magnitude: Minimum probability change to consider
    
    Returns:
        List of probability change dictionaries
    """
    cursor = conn.cursor()
    
    since_timestamp = int(time.time()) - (since_minutes * 60)
    
    cursor.execute("""
    SELECT 
        pc.event_id,
        e.title,
        e.category,
        pc.old_prob,
        pc.new_prob,
        pc.magnitude,
        pc.timestamp,
        e.volume_24h,
        e.liquidity
    FROM probability_changes pc
    JOIN events e ON pc.event_id = e.event_id
    WHERE pc.timestamp >= ?
      AND pc.magnitude >= ?
    ORDER BY pc.magnitude DESC
    """, (since_timestamp, min_magnitude))
    
    changes = []
    for row in cursor.fetchall():
        changes.append({
            "event_id": row[0],
            "title": row[1],
            "category": row[2],
            "old_prob": row[3],
            "new_prob": row[4],
            "magnitude": row[5],
            "timestamp": row[6],
            "volume_24h": row[7],
            "liquidity": row[8],
        })
    
    return changes


def match_event_to_assets(event_title: str) -> List[str]:
    """
    Match Polymarket event title to Hyperliquid perpetual symbols
    
    Args:
        event_title: Polymarket event title (e.g., "Bitcoin hits $100K by June")
    
    Returns:
        List of Hyperliquid symbols (e.g., ["BTC-USD"])
    """
    title_lower = event_title.lower()
    assets = []
    
    for keyword, symbols in SIGNAL_MAP.items():
        if keyword in title_lower:
            assets.extend(symbols)
    
    # Deduplicate
    return list(set(assets))


def calculate_signal_strength(
    prob_change: Dict,
    lag_seconds: int
) -> float:
    """
    Calculate signal strength (0-100)
    
    High signal = large probability shift + short time lag
    
    Args:
        prob_change: Probability change dictionary
        lag_seconds: Seconds since Polymarket move
    
    Returns:
        Signal strength (0-100)
    """
    # Weight probability magnitude (0-100)
    prob_score = abs(prob_change["magnitude"]) * 100
    
    # Decay function: signal weakens over time
    # Full strength for first 5 minutes, decays to 0 over 60 minutes
    max_lag = 60 * 60  # 60 minutes
    lag_score = max(0, 100 - (lag_seconds / max_lag * 100))
    
    # Combine (60% probability shift, 40% time decay)
    signal = (prob_score * 0.6) + (lag_score * 0.4)
    
    return min(signal, 100)


def calculate_confidence(prob_change: Dict) -> float:
    """
    Calculate confidence in signal quality (0-1)
    
    High confidence = high volume + high liquidity
    
    Args:
        prob_change: Probability change dictionary
    
    Returns:
        Confidence score (0-1)
    """
    volume = prob_change.get("volume_24h", 0)
    liquidity = prob_change.get("liquidity", 0)
    
    # Thresholds (conservative)
    min_volume = 50_000  # $50K daily volume
    min_liquidity = 10_000  # $10K liquidity
    
    volume_score = min(volume / min_volume, 1.0)
    liquidity_score = min(liquidity / min_liquidity, 1.0)
    
    # Average
    confidence = (volume_score + liquidity_score) / 2
    
    return confidence


def should_alert(signal_strength: float, confidence: float) -> bool:
    """
    Determine if signal is strong enough to alert/trade
    
    Args:
        signal_strength: Signal strength (0-100)
        confidence: Confidence score (0-1)
    
    Returns:
        True if signal meets alert thresholds
    """
    # Conservative thresholds
    min_strength = 60  # Strong probability shift + recent
    min_confidence = 0.7  # Liquid market
    
    return (signal_strength >= min_strength and confidence >= min_confidence)


def detect_signals(polymarket_db_path: str) -> List[Dict]:
    """
    Detect cross-market signals
    
    Args:
        polymarket_db_path: Path to Polymarket SQLite database
    
    Returns:
        List of signal dictionaries
    """
    print(f"\n{'='*60}")
    print(f"Signal Detection - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # Connect to Polymarket database
    conn = sqlite3.connect(polymarket_db_path)
    
    # Get recent probability changes
    prob_changes = get_probability_changes(conn, since_minutes=60, min_magnitude=0.10)
    
    print(f"📊 Found {len(prob_changes)} significant probability changes (last 60 min)\n")
    
    if not prob_changes:
        print("No signals detected.\n")
        conn.close()
        return []
    
    # Analyze each change
    signals = []
    
    for change in prob_changes:
        # Match event to Hyperliquid assets
        assets = match_event_to_assets(change["title"])
        
        if not assets:
            continue  # No relevant crypto assets
        
        # Calculate signal metrics
        lag_seconds = int(time.time()) - change["timestamp"]
        signal_strength = calculate_signal_strength(change, lag_seconds)
        confidence = calculate_confidence(change)
        
        # Build signal
        signal = {
            "event_title": change["title"],
            "event_id": change["event_id"],
            "category": change["category"],
            "prob_old": change["old_prob"],
            "prob_new": change["new_prob"],
            "prob_change": change["magnitude"],
            "hyperliquid_assets": assets,
            "signal_strength": signal_strength,
            "confidence": confidence,
            "lag_seconds": lag_seconds,
            "timestamp": change["timestamp"],
            "alert": should_alert(signal_strength, confidence),
        }
        
        signals.append(signal)
    
    # Sort by signal strength (strongest first)
    signals.sort(key=lambda s: s["signal_strength"], reverse=True)
    
    # Print results
    alert_count = sum(1 for s in signals if s["alert"])
    print(f"✅ Detected {len(signals)} potential signals")
    print(f"🚨 {alert_count} signals meet alert thresholds\n")
    
    for i, signal in enumerate(signals[:10], 1):  # Top 10
        icon = "🚨" if signal["alert"] else "📊"
        print(f"{icon} Signal #{i}")
        print(f"   Event: {signal['event_title'][:60]}")
        print(f"   Probability: {signal['prob_old']:.1%} → {signal['prob_new']:.1%} "
              f"({signal['prob_change']:+.1%})")
        print(f"   Assets: {', '.join(signal['hyperliquid_assets'])}")
        print(f"   Strength: {signal['signal_strength']:.1f}/100")
        print(f"   Confidence: {signal['confidence']:.0%}")
        print(f"   Lag: {signal['lag_seconds'] // 60} min")
        print()
    
    conn.close()
    return signals


def log_signals(signals: List[Dict], log_path: str):
    """
    Log signals to JSONL file
    
    Args:
        signals: List of signal dictionaries
        log_path: Path to log file
    """
    with open(log_path, "a") as f:
        for signal in signals:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                **signal
            }
            f.write(json.dumps(log_entry) + "\n")
    
    print(f"✅ Logged {len(signals)} signals to {log_path}\n")


if __name__ == "__main__":
    import sys
    import os
    
    # Get project root
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
    
    POLYMARKET_DB = os.path.join(PROJECT_ROOT, "data", "polymarket_events.db")
    LOG_PATH = os.path.join(PROJECT_ROOT, "logs", "signals.jsonl")
    
    # Ensure log directory exists
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    
    # Detect signals
    signals = detect_signals(POLYMARKET_DB)
    
    # Log results
    if signals:
        log_signals(signals, LOG_PATH)
    
    print(f"{'='*60}\n")
