# Changelog

## [2.0.0] - 2026-01-24

### Major Update - Advanced Risk Management and Signal Filtering

#### Risk Management Overhaul
- Complete rewrite of position sizing algorithm using MT5 tick_value/tick_size
- Dynamic risk scaling based on account equity (protects small accounts)
- Added hard safety cap: 5% maximum risk per trade when minimum lot binding occurs
- Adaptive risk percentage scaling (0.25x-1.0x multiplier based on account size)
- Enhanced lot calculation with broker constraint validation (min/max/step)
- Broker diagnostics on startup showing tick economics and volume limits
- Low account equity warning (below 50 GBP)

#### Signal Quality Enhancement
- Multi-factor scoring system with 4.5/12 minimum threshold
- Anti-late-entry filters: blocks trades after >0.15% price movement in 5 bars
- Bollinger Band position filtering: rejects extremes (>80% for buys, <20% for sells)
- Momentum building requirement: rejects signals with weakening momentum
- Choppy market detection: blocks trades when ADX <18 with flat momentum
- Enhanced rejection logging with detailed diagnostic reasons
- Spread filtering: skips trades when spread exceeds 25 points

#### Technical Analysis Improvements
- Higher timeframe ATR blending (M5 + M15) prevents ultra-tight stops
- Improved ATR calculation using resampled 15-minute data
- Take profit compression (35-55%) for realistic targets
- Signal strength now scales TP compression dynamically

#### Position Management
- Point-accurate trailing stops for XAUUSD (1 point = 0.01 price)
- Four-tier trailing system:
  - 800+ points profit, retrace 150 points: close
  - 500+ points profit, retrace 120 points: close
  - 300+ points profit, retrace 100 points: close
  - 200+ points profit, retrace 80 points: close
- Time-decay exit: closes after 10 minutes if stalled with 150+ points profit
- Peak progress tracking for better exit timing
- Position cache stores entry time and max progress/points

#### Execution and Spread Control
- Added max_spread_points parameter (default: 25)
- Added max_price_deviation_points for slippage protection (default: 20)
- Automatic retry on requotes with refreshed tick price
- Point-to-price conversion helpers for accurate calculations
- IOC order filling maintained for fast execution

#### State Management Changes
- Removed JSON state persistence (in-memory only)
- Daily statistics calculated directly from MT5 history
- Automatic reset at 08:00 UK time each trading day
- Position tracking using runtime cache only
- Deal synchronization recalculates from scratch each cycle

#### Diagnostic Improvements
- Comprehensive signal diagnostics showing check results
- Detailed rejection reasons for every skipped signal
- Enhanced status display with progress indicators
- Real-time spread monitoring in status output
- Signal score display (bullish/bearish) when no trade taken

#### Configuration Updates
- Added: max_single_trade_risk_pct_cap = 5.0
- Added: max_spread_points = 25
- Added: max_price_deviation_points = 20
- Added: tp_compression_min = 0.35
- Added: tp_compression_max = 0.55
- Added: time_decay_minutes = 10
- Added: min_progress_after_decay = 0.15
- Updated: min_score threshold = 4.5 (from implicit value)

#### Bug Fixes
- Fixed position cache not initializing entry_time properly
- Fixed timezone handling in deal synchronization
- Fixed cooldown calculation with timezone-aware datetimes
- Fixed state reset logic for new trading days
- Fixed spread calculation to use symbol point size correctly

#### Breaking Changes
- State no longer persists between bot restarts
- Position sizing algorithm completely rewritten
- Trailing stop thresholds changed from percentage to point-based
- Signal scoring requirements increased for better quality

---

## [1.0.0] - 2026-01-21

### Initial Release

#### Features
- Advanced technical analysis with multiple indicators
- Dynamic risk management system
- Smart position monitoring and trailing stops
- Anti-late-entry filters
- Real-time status dashboard
- Session-aware trading (London/NY)
- Daily profit/drawdown limits

#### Technical Indicators
- EMA (9, 21, 50, 100)
- MACD with histogram
- RSI with overbought/oversold detection
- Bollinger Bands
- ADX trend strength
- Volume analysis
- Candle pattern recognition

#### Risk Management
- Dynamic lot sizing based on account equity
- Adaptive stop-loss (0.8-1.2x ATR)
- Take-profit ratios (1.8-2.5x)
- Maximum 25 daily trades
- 20% daily profit target
- 12% maximum drawdown protection