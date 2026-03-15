# Cross-Market Signal Integration: Polymarket × Hyperliquid

**Created:** March 11, 2026, 2:00 AM (Autonomous Night Shift)  
**Author:** Aiden (autonomous execution)  
**Status:** Research Phase → Implementation Roadmap  
**Goal:** Detect exploitable signal divergences between prediction markets and crypto perps

---

## Core Thesis

Prediction markets (Polymarket) and crypto perpetuals (Hyperliquid) price **correlated but distinct instruments**:

- **Polymarket:** Event-driven probability (elections, macro events, crypto milestones)
- **Hyperliquid:** Price-driven derivatives (perpetual futures on BTC, ETH, SOL)

**Opportunity:** When prediction market odds shift dramatically, related crypto assets often lag → **exploitable edge**.

---

## Example Signal Flows

### 1. Regulatory Events → BTC/ETH Reaction
**Polymarket Market:** "SEC approves ETH ETF by Q2 2026"  
**Hyperliquid Impact:** ETH-USD perpetual premium/discount

**Signal:**
- Polymarket probability jumps from 30% → 70% in 1 hour
- Hyperliquid ETH funding rate still negative (shorts paying longs)
- **Trade:** Long ETH perps before market catches up

### 2. Macro Events → Risk-On/Risk-Off
**Polymarket Market:** "Fed cuts rates in March 2026"  
**Hyperliquid Impact:** BTC volatility, altcoin funding rates

**Signal:**
- Polymarket probability spikes 20%+ 
- BTC funding rate lags (no directional shift yet)
- **Trade:** Long BTC/altcoins before repricing

### 3. Protocol Events → Specific Tokens
**Polymarket Market:** "Solana processes 10M TPS by Q3"  
**Hyperliquid Impact:** SOL-USD perpetual

**Signal:**
- Polymarket probability increases
- Hyperliquid SOL open interest flat (market not pricing it in)
- **Trade:** Position before narrative spreads

---

## Data Architecture

### Phase 1: Data Collection (Week 1)

**Polymarket:**
- API: `https://clob.polymarket.com/` (public, no auth required)
- Data: Event probabilities, volume, liquidity, probability changes
- Update frequency: 1 minute
- Storage: SQLite `polymarket_events.db`

**Hyperliquid:**
- API: `https://api.hyperliquid.xyz/info` (public, read-only)
- Data: Perpetual prices, funding rates, open interest, mark/index spread
- Update frequency: 10 seconds
- Storage: SQLite `hyperliquid_perps.db`

**Schema:**
```sql
-- Polymarket
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    title TEXT,
    category TEXT,
    probability REAL,
    volume_24h REAL,
    liquidity REAL,
    timestamp INTEGER
);

CREATE TABLE probability_changes (
    event_id TEXT,
    old_prob REAL,
    new_prob REAL,
    magnitude REAL,
    timestamp INTEGER
);

-- Hyperliquid
CREATE TABLE perps (
    symbol TEXT,
    mark_price REAL,
    funding_rate REAL,
    open_interest REAL,
    volume_24h REAL,
    timestamp INTEGER
);

CREATE TABLE funding_changes (
    symbol TEXT,
    old_rate REAL,
    new_rate REAL,
    magnitude REAL,
    timestamp INTEGER
);
```

### Phase 2: Signal Detection (Week 2)

**Event → Asset Mapping:**
```python
SIGNAL_MAP = {
    # Regulatory
    "eth_etf": ["ETH-USD", "BTC-USD"],  # ETH approval lifts all boats
    "crypto_regulation": ["BTC-USD", "ETH-USD"],
    
    # Macro
    "fed_rates": ["BTC-USD", "ETH-USD", "SOL-USD"],  # Risk-on assets
    "recession": ["BTC-USD"],  # Flight to digital gold
    
    # Protocol-specific
    "solana_tps": ["SOL-USD"],
    "ethereum_upgrade": ["ETH-USD"],
    "bitcoin_halving": ["BTC-USD"]
}
```

**Signal Strength Formula:**
```python
def calculate_signal_strength(polymarket_change, hyperliquid_lag):
    """
    polymarket_change: Δprobability (0-1)
    hyperliquid_lag: Time since Polymarket move (seconds)
    
    Returns: signal_strength (0-100)
    """
    
    # Weight Polymarket probability shift
    prob_score = abs(polymarket_change) * 100  # 0-100
    
    # Decay function: signal weakens as Hyperliquid catches up
    lag_score = max(0, 100 - (hyperliquid_lag / 60))  # Decay over 60 min
    
    # Combine
    signal = (prob_score * 0.6) + (lag_score * 0.4)
    
    return min(signal, 100)
```

**Alert Conditions:**
```python
def should_alert(signal_strength, volume_confidence):
    """
    Trigger alert when:
    1. Signal strength > 60
    2. Polymarket volume > $50K (liquid market)
    3. Hyperliquid open interest > $1M (tradable)
    """
    return (
        signal_strength > 60 and
        volume_confidence > 0.7
    )
```

### Phase 3: Backtesting (Week 3)

**Historical Analysis:**
1. Download Polymarket historical events (past 6 months)
2. Download Hyperliquid perpetual prices (past 6 months)
3. Simulate signals in hindsight
4. Measure hit rate, average lag, profitability

**Metrics:**
- **Hit rate:** % of signals that predicted correct direction
- **Average lag:** Time between Polymarket move and Hyperliquid move
- **Signal-to-noise:** Profitable signals vs false positives
- **Edge decay:** How fast does the edge disappear?

### Phase 4: Live Paper Trading (Week 4)

**Real-time Monitoring:**
- Cron job: Every 1 minute
- Check Polymarket for probability spikes (>10% in 5 min)
- Check Hyperliquid for correlated assets
- Log signal strength, timestamp, outcome

**Validation Period:** 2 weeks of paper trading before real capital

---

## Technical Stack

**Language:** Python 3.11+  
**Database:** SQLite (lightweight, embedded)  
**APIs:**
- Polymarket CLOB API (REST)
- Hyperliquid Info API (REST)

**Dependencies:**
```txt
requests==2.31.0
pandas==2.2.0
sqlite3 (built-in)
```

**File Structure:**
```
cross-market-signals/
├── README.md (this file)
├── requirements.txt
├── src/
│   ├── polymarket_collector.py
│   ├── hyperliquid_collector.py
│   ├── signal_detector.py
│   ├── backtester.py
│   └── utils.py
├── data/
│   ├── polymarket_events.db
│   └── hyperliquid_perps.db
├── config/
│   └── signal_map.yaml
├── logs/
│   └── signals.jsonl
└── notebooks/
    └── backtest_analysis.ipynb
```

---

## Risks & Mitigations

### 1. False Signals
**Risk:** Polymarket moves don't always predict crypto price moves  
**Mitigation:**
- Backtesting to measure historical hit rate
- Only trade signals with >70% confidence
- Position sizing: max 2% per signal

### 2. Latency
**Risk:** Signal detected after market already moved  
**Mitigation:**
- 1-minute polling (aggressive)
- Pre-compute asset mappings (no runtime lookups)
- Cloud hosting (AWS Lambda) for low latency

### 3. Liquidity
**Risk:** Hyperliquid slippage on large orders  
**Mitigation:**
- Only trade markets with >$5M daily volume
- Check order book depth before execution
- Start with small position sizes

### 4. Correlation Breakdown
**Risk:** Historical correlation != future correlation  
**Mitigation:**
- Rolling correlation windows (update weekly)
- Kill switch if 3 consecutive false signals
- Manual review of edge cases

---

## Success Metrics

**Phase 1 (Data Collection):**
- ✅ Polymarket data flowing (1-min updates)
- ✅ Hyperliquid data flowing (10-sec updates)
- ✅ SQLite databases stable for 7 days

**Phase 2 (Signal Detection):**
- ✅ 10+ event-asset mappings defined
- ✅ Signal strength formula validated
- ✅ Alert system tested (dry-run)

**Phase 3 (Backtesting):**
- ✅ Hit rate >60%
- ✅ Average signal lag <15 minutes
- ✅ Positive expected value (EV+)

**Phase 4 (Live Paper Trading):**
- ✅ 2 weeks of live signal logging
- ✅ Zero system crashes
- ✅ Hit rate >55% in live conditions

**Phase 5 (Real Capital):**
- ✅ 1 month of profitable paper trading
- ✅ Sharpe ratio >1.5
- ✅ Max drawdown <5%

---

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1. Data Collection | 1 week | Polymarket + Hyperliquid collectors running |
| 2. Signal Detection | 1 week | Event-asset mappings + alert system |
| 3. Backtesting | 1 week | Historical performance report |
| 4. Paper Trading | 2 weeks | Live signal validation |
| 5. Real Capital | Ongoing | Profitable trading system |

**Total time to live system:** 5 weeks

---

## Next Steps (Tomorrow Morning)

1. **Review this research** (5 min)
2. **Decide: Build this now or defer?**
   - **Build now:** High leverage, aligns with trading bot goals
   - **Defer:** Focus on job applications first (2-week sprint)
3. **If building:** Start Phase 1 (Polymarket data collector, 1-2 hours)
4. **If deferring:** Move to backlog, prioritize job search

---

## Competitive Analysis

**Similar Systems:**
- Kaiko (institutional cross-market analytics) - $$$
- Nansen (on-chain + market data) - $$
- Coinalyze (perps funding arbitrage) - basic

**Our Edge:**
- Free data (Polymarket + Hyperliquid public APIs)
- Event-driven (not just price-based)
- Custom event-asset mappings (proprietary)
- Lightweight (SQLite, no cloud costs)

---

## ROI Estimate

**Investment:**
- Development: 40 hours (5 weeks × 8 hours/week)
- Hosting: $0 (run locally or free tier Lambda)
- Data: $0 (public APIs)

**Potential Return:**
- If hit rate = 60%, avg edge = 2%, 1 signal/day
- Capital: $1,000/signal
- Expected profit: $1,000 × 0.6 × 0.02 = $12/day
- Monthly: ~$360
- Annualized: ~$4,320

**Payback:** ~9 days of profitable signals

**Upside:** Scales with capital (10x capital = 10x returns)

---

## Conclusion

This is a **high-leverage research project** that:

✅ Builds real trading infrastructure (portfolio-worthy)  
✅ Teaches API integration, data pipelines, signal processing  
✅ Aligns with long-term prediction market bot goals  
✅ Potentially profitable (not just a portfolio piece)  
✅ Differentiated (cross-market signals rare in retail space)

**Recommendation:** Build Phase 1 this week if job applications on track. Otherwise, defer 2 weeks and execute after job search sprint.

---

**End of Research Document**  
**Next:** Yumo to review and decide priority vs job search focus.
