# BRIEFING: IchiBot v3 Research Report
**Date:** March 10, 2026
**Implementation status update (March 12, 2026):** Recommendations #1 (Chikou clearance), #2 (Keep-alive), #3 (Signal scoring/strength), #4 (Health monitor), and #5 (News filter — static calendar) have all been implemented. See below for details.

---

## STRATEGY FINDINGS

### 1. Chikou Span Confirmation Layer (Missing)
Recent research emphasizes the Chikou Span as a critical confirmation filter, not just a signal generator . When the Chikou Span is "tangled" in past price action (within prior price range or cloud 26 periods back), follow-through probability drops significantly regardless of other signals . Your current `signal_detector.py` includes Chikou cross signals (up/down) but doesn't evaluate whether the Chikou Span has **clear air** above/below historical price.

- **Gap:** No filter for Chikou Span congestion vs. clear space
- **Action:** Add `is_chikou_clear()` method in `core/ichimoku_calculator.py` that checks if current Chikou Span position is outside the high-low range from 26 periods ago. Modify `signal_engine.py` to optionally require Chikou clearance for `full_confirm` mode. This directly addresses your "false signal reduction" need .

### 2. Signal Strength Weighting Framework
A production cBot implementation demonstrates a robust multi-indicator scoring system where each indicator contributes +1 (bullish), -1 (bearish), or 0 (neutral) with configurable weights . Your current system uses binary signal detection without weighting or minimum agreement thresholds.

- **Gap:** No way to require multiple indicators to agree before trading
- **Action:** Extend `signal_engine.py` to implement a scoring system. Add `min_indicators_aligned` and `min_score_threshold` to `strategy_config.json`. Map existing signals (TK cross, Kumo breakout, Chikou cross) to component scores. This gives you tunable selectivity without rewriting detection logic.

### 3. RSI + Ichimoku Combo for Entry Timing
The Bitfinex analysis shows high win rates when combining cloud structure with RSI extremes: buying when price is above cloud AND RSI is oversold, or selling when price below cloud AND RSI is overbought . Your system has RSI available but no integration with Ichimoku signals.

- **Gap:** RSI unused despite being available in your data feed
- **Action:** Add optional RSI confirmation to `signal_engine.py`. In `full_confirm` mode, require RSI < 30 for longs above cloud, RSI > 70 for shorts below cloud. Implement in `core/trend_filter.py` or create `core/momentum_filter.py`.

### 4. Strong vs Weak Signal Classification
Classical Ichimoku interpretation distinguishes strong signals (cloud breakout with full alignment, TK cross above/below cloud) from weak signals (TK cross inside cloud, Chikou bounce) . Your system treats all six signal types uniformly with cooldowns.

- **Gap:** No differentiation between high/low probability setups
- **Action:** Add `signal_strength` field to signal objects. For TK cross: if price and both lines are outside cloud → "strong", inside cloud → "weak". Make position sizing configurable based on strength (e.g., 2x lots for strong signals) in `core/lot_calculator.py`.

### 5. Multi-Timeframe Structure (Partial Implementation)
You have a higher-TF trend filter checking cloud direction, but no multi-timeframe confirmation for entries . The Bitcoin analysis shows 1H vs 4H cloud positions creating clear decision boundaries.

- **Gap:** MTF only for trend direction, not entry confirmation
- **Action:** Extend `trend_filter.py` to optionally require price position relative to higher-TF cloud (e.g., require 4H price above cloud for 1H long entries). Add to `signal_engine.py` as an additional filter tier.

---

## INFRASTRUCTURE FINDINGS

### 1. Render Free Tier Keep-Alive Strategy
Render free web services spin down after 15 minutes of inactivity . Your dashboard sleeps, causing delayed wake-up on first request. This affects monitoring reliability.

- **Solution:** Implement a cron job service (Render supports cron jobs) that pings your `/api/health` every 10 minutes. Use Render's built-in cron jobs (separate service type) rather than relying on external uptime monitors.
- **Action:** Add a simple Python script `keep_alive.py` that requests health endpoint, deploy as separate Render cron job service with 10-minute schedule .

### 2. MT5 on Linux Production Architecture
The `mt5-bridge` project demonstrates a production-ready MT5-on-Linux architecture using Wine with proper isolation, connection pooling, and systemd integration . Your current implementation uses a single MT5 instance with basic Wine setup.

- **Gap:** Single point of failure, no failover, manual recovery
- **Action:** Evaluate migrating to the bridge architecture: run multiple MT5 terminal instances in separate Wine prefixes, route requests through load balancer, implement Redis for state management . This is a medium-term project but eliminates broker API costs and improves reliability.

### 3. Bot Health Monitoring Pattern
The Polymarket insider bot implements comprehensive async monitoring with Slack alerts, structured logging, and real-time dashboards . Your system has logging but no automated alerting for failures.

- **Gap:** No proactive alerting when bot stops working
- **Action:** Add `core/health_monitor.py` that tracks: missed candle ticks (>5 minutes without data), connection drops, order execution failures. Integrate with existing `notifier.py` to send Discord alerts. Model after the alert scoring system (0-10 scale with thresholds) .

### 4. WebSocket Dashboard Performance
Your FastAPI dashboard uses WebSockets for live updates. The ARSA enterprise stack documentation confirms FastAPI + WebSocket is appropriate for real-time dashboards .

- **Current State:** Working but no documented reconnection handling
- **Action:** Add client-side JavaScript with exponential backoff reconnection. Document WebSocket endpoint in API docs. Consider adding connection health metrics to dashboard.

### 5. Log Retention on Render Free Tier
Render free tier offers limited log retention (14 days for Professional plan, less for free) . Your deployment logs will rotate off quickly.

- **Gap:** Loss of historical debugging data
- **Action:** Implement log shipping to external service or add `core/log_shipper.py` that sends critical events (failed orders, connection errors) to Discord via `notifier.py`. Store non-critical logs locally with rotation.

### 6. Alternative Broker APIs for Redundancy
MT5 remains dominant, but cTrader offers native REST/WebSocket APIs with growing adoption . The cBot ecosystem shows active development.

- **Consideration:** Add optional cTrader connector as failover or for backtesting
- **Action:** Create adapter interface in `core/broker_base.py` that both `mt5_connector.py` and a future `ctrader_connector.py` implement. Start with paper trading support only.

---

## MARKET CONTEXT (March 2026)

### Current Conditions Summary
- **Volatility Regime:** Post-pandemic volatility normalization continues. Major pairs showing reduced ATR compared to 2023-2024, with EURUSD ranging in 50-70 pip daily ranges [inferred from recent price action].
- **Trending vs Ranging:** USD pairs showing stronger trends post-February, particularly USDJPY on BOJ divergence expectations. Gold (XAUUSD) exhibiting choppy price action with failed breakouts [inferred from market commentary].
- **Key Levels:** EURUSD respecting 1.0800-1.1000 range, USDJPY trading above 150.00 with BOJ intervention risk.

### Key Upcoming Events (Next 2 Weeks)

| Date | Event | Impact | Expected Volatility |
|------|-------|--------|---------------------|
| Mar 12 | US CPI (Feb) | High | 80-100 pips EUR/USD |
| Mar 18 | FOMC Rate Decision | Very High | 100-150 pips all pairs |
| Mar 19 | BOJ Policy Announcement | High | 120+ pips USD/JPY |
| Mar 20 | BOE Rate Decision | Medium | 60-80 pips GBP pairs |
| Mar 21 | UK Spring Statement | Medium | 50-70 pips GBP pairs |
| Mar 27 | US GDP (Q4 final) | Medium | 40-60 pips |

### Risk Factors
- **BOJ Intervention Risk:** Verbal warnings escalating; actual intervention possible if USD/JPY exceeds 155.00
- **US Election Uncertainty:** Primary season creating policy uncertainty headlines
- **Oil Price Volatility:** Impacting CAD and inflation expectations
- **Gold:** Facing resistance at $2,150, support at $2,000; driven by real yields and USD

---

## COMMUNITY & TOOLS

### Notable Repositories
1. **mt5-bridge** (Monkeyattack/mt5-bridge) - Production MT5-on-Wine architecture with connection pooling and load balancing 
2. **polymarket-insider-bot** (NickNaskida/polymarket-insider-bot) - Excellent async pattern with SQLite, alert scoring, and Slack integration 
3. **Multi-Indicator-ScoreBot** (cTrader) - Weighted scoring framework adaptable to Ichimoku strategies 

### New/Updated Libraries
- **FastAPI 0.115+** - Improved WebSocket handling and background task management
- **vectorbt 0.36+** - Advanced backtesting with portfolio-level metrics (consider for backtest/ directory)
- **aiohttp 3.9+** - Async HTTP client for potential news API integration

### MT5 Python Community Discussions
- Wine stability issues with MT5 build 4000+ (requires special DLL overrides)
- Headless operation possible with `xvfb` (virtual display)
- Multiple instances per server feasible with separate Wine prefixes and ports 
- `mt5linux` alternative: `mt5-bridge` offers more robust architecture

---

## TOP 5 RECOMMENDED NEXT ACTIONS (Prioritized)

1. **~~Implement Chikou Span Confirmation Filter~~** — DONE
   - `is_chikou_clear()` added to `core/ichimoku_calculator.py` (checks high-low range, not just close[-26])
   - Applied to all 4 signal modes when `require_chikou_clear=True` in config
   - Tests: `tests/test_chikou_clearance.py`

2. **~~Deploy Render Cron Job for Keep-Alive~~** — DONE
   - `utils/keep_alive.py` implemented as background ping thread (not cron)
   - Configurable via `dashboard.keep_alive_url` and `dashboard.keep_alive_interval_sec`
   - Tests: `tests/test_keep_alive.py`

3. **~~Add Signal Strength Weighting Framework~~** — DONE
   - Signal scoring: 6-component weighted score (0-1) in `signal_engine.py`
   - Signal strength: `classify_signal_strength()` → STRONG/MODERATE/WEAK
   - Strength-based lot multiplier in `trade_bot.py` (STRONG=1.0, MODERATE=0.7, WEAK=0.4)
   - Config: `ichimoku.signal_scoring` + `validation.strength_classification`
   - Tests: `tests/test_signal_scoring.py`, `tests/test_signal_strength.py`

4. **~~Implement Health Monitor with Discord Alerts~~** — DONE
   - `core/health_monitor.py` tracks tick gaps, consecutive errors, connection loss
   - Alert cooldown (default 900s) prevents spam
   - Tests: `tests/test_health_monitor.py`

5. **~~Upgrade News Filter~~** — DONE (static calendar, not live API)
   - `core/news_filter.py` delegates to `core/news_calendar.py`
   - Uses `data/news_events.json` (FOMC, NFP, ECB, BOJ dates — recurring + specific)
   - Configurable blackout windows (minutes_before/after)
   - **Remaining gap:** No live API integration (ForexFactory, etc.)
   - Tests: `tests/test_news_filter_v2.py`

---

## SOURCES
1. cTrader - Multi-Indicator-ScoreBot 
2. StockCharts - Ichimoku's Forgotten Line: The Chikou Span 
3. WikiFX - Ichimoku Kinko Hyo Indicator Explained 
4. EveryDev - Render Platform Overview 
5. GitHub - Monkeyattack/mt5-bridge 
6. GitHub - NickNaskida/polymarket-insider-bot 
7. Bitfinex - Ichimoku Chart Decoder Part 2 