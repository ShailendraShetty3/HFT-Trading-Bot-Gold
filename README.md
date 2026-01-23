# Gold Trading Bot (XAUUSD)

An automated forex trading bot for gold (XAUUSD) using MetaTrader 5 with technical analysis, risk management, and position monitoring.

![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-success)

## Disclaimer

**Trading forex and CFDs involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results. This bot is provided for educational purposes only. Use at your own risk.**

## Features

### Technical Analysis
- Multiple EMA crossovers (9, 21, 50, 100)
- MACD histogram momentum tracking
- RSI with overbought/oversold detection
- Bollinger Bands positioning
- ADX trend strength measurement
- Volume analysis and confirmation
- Candle pattern recognition (Hammer, Shooting Star)

### Risk Management
- Dynamic position sizing based on account equity
- ATR-based stop loss with higher timeframe blending
- Small account protection (caps risk when minimum lot would over-leverage)
- Adaptive take-profit levels with signal strength scaling
- TP compression (35-55%) for realistic profit targets
- Maximum daily trade limits
- Profit target and drawdown protection
- Spread filtering to avoid expensive trades

### Entry and Exit Logic
- Multi-factor scoring system (minimum 4.5/12 required)
- Anti-late-entry filters prevent chasing moves
- BB position filtering (no extremes)
- Momentum building requirement
- Trailing stop system based on progress and peak tracking
- Emergency exit conditions for rapid losses
- Time-decay exits for stale positions
- Win/loss cooldown periods

### Monitoring
- Live position tracking with P&L percentage
- Market session awareness (London/NY)
- Comprehensive status dashboard
- Signal strength diagnostics
- Rejection reason logging

## Requirements

- Python 3.8 or higher
- MetaTrader 5 platform
- Active MT5 trading account (demo or live)
- Algo Trading enabled in MT5 with DLL imports allowed

## Installation

### Windows - Quick Start

1. Download the latest release from the [Releases page](../../releases)
2. Extract the ZIP file to your desired location
3. Install MetaTrader 5 from [MetaQuotes website](https://www.metatrader5.com/)
4. Log in to your trading account and ensure XAUUSD is visible
5. Double-click `gold_bot_start.bat`

The batch file will automatically install dependencies and launch the bot.

### Linux/Mac

```bash
# Download and extract the latest release
wget https://github.com/Morticuss/Gold-trading-bot/archive/refs/tags/v1.1.0.zip
unzip v1.1.0.zip
cd gold-trading-bot-1.1.0

# Install dependencies
pip3 install -r requirements.txt

# Run the bot
python3 gold_bot.py
```

### Manual Installation

```bash
git clone https://github.com/Morticuss/Gold-trading-bot.git
cd gold-trading-bot
pip install -r requirements.txt
python gold_bot.py
```

## Configuration

Key parameters in `gold_bot.py`:

```python
# Risk Management
self.base_risk_pct = 0.25                    # Base risk per trade
self.max_risk_pct = 0.6                      # Maximum risk for strong signals
self.min_lot = 0.01                          # Minimum lot size
self.max_lot = 0.5                           # Maximum lot size
self.max_single_trade_risk_pct_cap = 5.0     # Hard cap per trade (protects small accounts)

# Spread and Execution
self.max_spread_points = 25                  # Skip if spread exceeds this (in points)
self.max_price_deviation_points = 20         # Slippage tolerance for orders

# Daily Limits
self.daily_profit_target = 20.0              # Daily profit target (%)
self.max_drawdown = 12.0                     # Maximum daily loss (%)
self.max_daily_trades = 25                   # Maximum trades per day

# Cooldowns
self.win_cooldown = 20                       # Seconds after winning trade
self.loss_cooldown = 45                      # Seconds after losing trade

# Position Management
self.tp_compression_min = 0.35               # Minimum TP compression
self.tp_compression_max = 0.55               # Maximum TP compression
self.time_decay_minutes = 10                 # Minutes before time-decay check
self.min_progress_after_decay = 0.15         # Minimum progress required to hold
```

## Trading Strategy

### Signal Scoring System

The bot uses a multi-factor scoring system where trades require a minimum score of 4.5 out of 12 possible points.

**Bullish Signals:**
- Strong uptrend (EMA 9 > 21 > 50 > 100): +2.5 points
- Price above EMA9 with strong trend: +1.5 points
- MACD histogram rising strongly: +2.0 points
- RSI oversold with positive momentum: +2.0 points
- Volume spike with bullish candle: +1.5 points
- Price near lower Bollinger Band: +1.5 points
- Strong bullish candle: +1.5 points
- Hammer pattern near BB lower: +2.0 points

**Bearish Signals:**
- Strong downtrend (EMA 9 < 21 < 50 < 100): +2.5 points
- Price below EMA9 with strong trend: +1.5 points
- MACD histogram falling strongly: +2.0 points
- RSI overbought with negative momentum: +2.0 points
- Volume spike with bearish candle: +1.5 points
- Price near upper Bollinger Band: +1.5 points
- Strong bearish candle: +1.5 points
- Shooting star near BB upper: +2.0 points

### Entry Filters

Trades are rejected if:
- Score below 4.5 minimum threshold
- Opposing signal too strong (need 1.2x advantage)
- Extreme RSI levels (>75 or <25)
- Price moved >0.15% in last 5 bars (anti-late-entry)
- BB position too extreme (>80% for buys, <20% for sells)
- Momentum weakening
- Spread exceeds maximum allowed
- ADX <18 with choppy conditions
- Minimum lot would exceed risk cap

### Position Management

**Stop Loss:**
- Dynamic ATR-based calculation
- Blends M5 ATR with higher timeframe ATR (M15)
- Scales with signal strength: 0.8-1.2x ATR

**Take Profit:**
- Ratio of 1.8-2.5x stop loss distance
- Compressed by 35-55% for realism
- Scales with signal strength and trend

**Trailing System (Point-Based for XAUUSD):**
- 800+ points profit, retrace 150 points: close
- 500+ points profit, retrace 120 points: close
- 300+ points profit, retrace 100 points: close
- 200+ points profit, retrace 80 points: close

Note: For XAUUSD, 1 point = 0.01 price movement (e.g., 150 points = $1.50)

**Emergency Exits:**
- P&L drops below -0.6% with rapid price movement
- Profit reverses 25% after reaching 0.4% gain
- Time-decay after 10 minutes if progress stalls and profit ≥150 points

## Trading Hours

- Active Sessions: London Open, Mid, NY Open, Mid
- Trading Hours: 24/5 (Monday 00:00 - Friday 22:00 UK time)
- Weekend Handling: Automatically pauses

## State Management

The bot maintains state in memory only while running. Daily statistics are calculated from MT5 history and reset at 08:00 UK time each trading day.

## Troubleshooting

### Python Not Found
- Install Python from python.org
- During installation, check "Add Python to PATH"
- Restart your computer

### MT5 Initialization Failed
- Ensure MT5 is running and logged in
- Restart MT5 and try again
- Check account credentials

### Symbol XAUUSD Not Found
- Open MT5 Market Watch
- Right-click → "Show All"
- Search for XAUUSD and add it
- Verify symbol name matches your broker

### No Trading Permissions
- MT5: Tools → Options → Expert Advisors
- Enable "Allow automated trading"
- Enable "Allow DLL imports"
- Verify algo trading is allowed on your account

### Dependencies Won't Install
- Run Command Prompt as Administrator
- Navigate to bot folder
- Run: `pip install -r requirements.txt`

### Bot Closes Immediately
- Check MT5 is running and logged in
- Verify Python version is 3.8+
- Check console for error messages

## Performance Monitoring

The bot displays:
- Real-time account equity and balance
- Market status and trading session
- Active position details with P&L percentage
- Progress toward take-profit with peak tracking
- Cooldown timers and daily trade count
- Signal diagnostics and rejection reasons
- Daily profit/loss statistics

## First-Time Setup Checklist

- Python 3.8+ installed
- MetaTrader 5 installed and running
- MT5 account logged in (demo recommended)
- XAUUSD visible in Market Watch
- AutoTrading enabled in MT5
- DLL imports enabled in MT5
- Bot extracted and dependencies installed
- Bot shows "SCANNING FOR SIGNALS" status

## Contributing

Contributions are welcome. Please:
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Risk Warning

**Trading carries a high level of risk and may not be suitable for all investors. Before deciding to trade, you should carefully consider your investment objectives, level of experience, and risk appetite. You should be aware of all the risks associated with trading and seek advice from an independent financial advisor if you have any doubts.**

**The possibility exists that you could sustain a loss in excess of your deposited funds. Therefore, you should not speculate with capital that you cannot afford to lose.**

## Support

For issues and questions:
- Open an issue on GitHub Issues
- Check existing issues for solutions
- Review the troubleshooting section

## Acknowledgments

- MetaTrader 5 API by MetaQuotes
- Technical analysis libraries: pandas, numpy
- Trading community feedback

---

Remember: Past performance is not indicative of future results. Trade responsibly.