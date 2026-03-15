# Quick Start Guide

Get up and running with cross-market signal detection in 5 minutes.

---

## Setup (2 minutes)

### 1. Install dependencies
```bash
cd ~/.openclaw/workspace/projects/cross-market-signals
pip3 install -r requirements.txt
```

### 2. Create data directory
```bash
mkdir -p data
```

### 3. Test Polymarket collector
```bash
cd src
python3 polymarket_collector.py once
```

Expected output:
```
✅ Database initialized
✅ Fetched 100 markets
✅ Stored 100 events
📊 Detected 0 probability changes (first run)
```

### 4. Test Hyperliquid collector
```bash
python3 hyperliquid_collector.py once
```

Expected output:
```
✅ Database initialized
✅ Fetched funding data for 200+ markets
🔍 Filtered to 5 symbols
✅ Stored 5 perps
📊 Detected 0 funding rate changes (first run)
```

---

## Data Collection (ongoing)

### Option 1: Manual snapshots
```bash
# Polymarket (1-minute intervals recommended)
python3 src/polymarket_collector.py once

# Hyperliquid (10-second intervals recommended)
python3 src/hyperliquid_collector.py once
```

### Option 2: Continuous mode (terminal)
```bash
# Polymarket (60-second loop)
python3 src/polymarket_collector.py continuous 60

# Hyperliquid (10-second loop)
python3 src/hyperliquid_collector.py continuous 10
```

Run each in a separate terminal/tmux pane.

### Option 3: Cron jobs (automated)
Add to crontab (`crontab -e`):

```cron
# Polymarket: every minute
* * * * * cd ~/.openclaw/workspace/projects/cross-market-signals/src && /usr/local/bin/python3 polymarket_collector.py once >> ../logs/polymarket.log 2>&1

# Hyperliquid: every 10 seconds (via 6 staggered jobs)
* * * * * cd ~/.openclaw/workspace/projects/cross-market-signals/src && /usr/local/bin/python3 hyperliquid_collector.py once >> ../logs/hyperliquid.log 2>&1
* * * * * sleep 10; cd ~/.openclaw/workspace/projects/cross-market-signals/src && /usr/local/bin/python3 hyperliquid_collector.py once >> ../logs/hyperliquid.log 2>&1
* * * * * sleep 20; cd ~/.openclaw/workspace/projects/cross-market-signals/src && /usr/local/bin/python3 hyperliquid_collector.py once >> ../logs/hyperliquid.log 2>&1
* * * * * sleep 30; cd ~/.openclaw/workspace/projects/cross-market-signals/src && /usr/local/bin/python3 hyperliquid_collector.py once >> ../logs/hyperliquid.log 2>&1
* * * * * sleep 40; cd ~/.openclaw/workspace/projects/cross-market-signals/src && /usr/local/bin/python3 hyperliquid_collector.py once >> ../logs/hyperliquid.log 2>&1
* * * * * sleep 50; cd ~/.openclaw/workspace/projects/cross-market-signals/src && /usr/local/bin/python3 hyperliquid_collector.py once >> ../logs/hyperliquid.log 2>&1
```

---

## Query Data (SQLite)

### Polymarket

```bash
cd data
sqlite3 polymarket_events.db
```

**Example queries:**

```sql
-- Top 10 most liquid markets
SELECT title, probability, volume_24h, liquidity 
FROM events 
ORDER BY liquidity DESC 
LIMIT 10;

-- Recent probability spikes (>10% change)
SELECT 
    e.title,
    pc.old_prob,
    pc.new_prob,
    pc.magnitude,
    datetime(pc.timestamp, 'unixepoch') as time
FROM probability_changes pc
JOIN events e ON pc.event_id = e.event_id
WHERE pc.magnitude > 0.10
ORDER BY pc.timestamp DESC
LIMIT 10;

-- Markets by category
SELECT category, COUNT(*) as count, AVG(probability) as avg_prob
FROM events
GROUP BY category
ORDER BY count DESC;
```

### Hyperliquid

```bash
cd data
sqlite3 hyperliquid_perps.db
```

**Example queries:**

```sql
-- Latest snapshot (all symbols)
SELECT symbol, mark_price, funding_rate, open_interest
FROM perps
WHERE timestamp = (SELECT MAX(timestamp) FROM perps)
ORDER BY open_interest DESC;

-- BTC funding rate history (last hour)
SELECT 
    datetime(timestamp, 'unixepoch') as time,
    funding_rate,
    open_interest
FROM perps
WHERE symbol = 'BTC-USD'
AND timestamp > strftime('%s', 'now', '-1 hour')
ORDER BY timestamp DESC;

-- Funding rate changes (last 24h)
SELECT 
    symbol,
    old_rate,
    new_rate,
    magnitude,
    datetime(timestamp, 'unixepoch') as time
FROM funding_changes
WHERE timestamp > strftime('%s', 'now', '-24 hours')
ORDER BY magnitude DESC
LIMIT 20;
```

---

## Check System Health

### Database sizes
```bash
ls -lh data/*.db
```

Expect:
- `polymarket_events.db`: ~100 KB per hour
- `hyperliquid_perps.db`: ~50 KB per hour

### Log files
```bash
tail -20 logs/polymarket.log
tail -20 logs/hyperliquid.log
```

### Data freshness
```bash
# Polymarket (should be <60 seconds ago)
sqlite3 data/polymarket_events.db "SELECT datetime(MAX(timestamp), 'unixepoch') FROM events;"

# Hyperliquid (should be <10 seconds ago)
sqlite3 data/hyperliquid_perps.db "SELECT datetime(MAX(timestamp), 'unixepoch') FROM perps;"
```

---

## Next Steps

Once you have **24+ hours of data** collected:

1. **Phase 2:** Build signal detector (`src/signal_detector.py`)
   - Map Polymarket events → Hyperliquid assets
   - Calculate signal strength
   - Generate alerts

2. **Phase 3:** Backtest signals (`src/backtester.py`)
   - Measure historical hit rate
   - Calculate average lag time
   - Validate profitability

3. **Phase 4:** Live paper trading
   - Real-time signal monitoring
   - Log predicted moves vs actual moves
   - Refine thresholds

---

## Troubleshooting

### "No module named 'requests'"
```bash
pip3 install -r requirements.txt
```

### "Database is locked"
Stop any running collectors (Ctrl+C in all terminals), then retry.

### "API error: 429 Too Many Requests"
You're hitting rate limits. Increase polling interval:
- Polymarket: 60s → 120s
- Hyperliquid: 10s → 30s

### Database growing too large
**Prune old data** (keep last 7 days):

```bash
# Polymarket
sqlite3 data/polymarket_events.db "DELETE FROM events WHERE timestamp < strftime('%s', 'now', '-7 days');"
sqlite3 data/polymarket_events.db "VACUUM;"

# Hyperliquid
sqlite3 data/hyperliquid_perps.db "DELETE FROM perps WHERE timestamp < strftime('%s', 'now', '-7 days');"
sqlite3 data/hyperliquid_perps.db "VACUUM;"
```

---

## Expected Timeline

| Day | Activity | Data Size |
|-----|----------|-----------|
| 1 | Start collectors | ~5 MB |
| 2-7 | Let data accumulate | ~100 MB |
| 7 | Build signal detector | - |
| 14 | Backtest + validate | - |
| 21 | Launch paper trading | - |

---

## Stop Collectors

### Terminal mode
Press `Ctrl+C`

### Cron mode
```bash
crontab -e
# Comment out the collector lines (add # at start)
# Save and exit
```

---

**You're ready! Start collecting data and come back in 24 hours to build the signal detector.** 🚀
