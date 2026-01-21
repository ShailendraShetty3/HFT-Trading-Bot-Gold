# 🏆 Gold Trading Bot (XAUUSD)

An advanced automated forex trading bot for gold (XAUUSD) using MetaTrader 5 with sophisticated technical analysis, risk management, and position monitoring.

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-success)

## ⚠️ Disclaimer

**Trading forex and CFDs involves substantial risk of loss and is not suitable for all investors. Past performance is not indicative of future results. This bot is provided for educational purposes only. Use at your own risk.**

## ✨ Features

- **Advanced Technical Analysis**
  - Multiple EMA crossovers (9, 21, 50, 100)
  - MACD histogram momentum
  - RSI with overbought/oversold detection
  - Bollinger Bands positioning
  - ADX trend strength measurement
  - Volume analysis
  - Candle pattern recognition (Hammer, Shooting Star)

- **Intelligent Risk Management**
  - Dynamic position sizing based on account equity
  - Adaptive stop-loss and take-profit levels
  - Maximum daily trade limits
  - Profit target and drawdown protection
  - Win-rate based risk adjustment

- **Smart Entry/Exit Logic**
  - Anti-late-entry filters (no chasing moves)
  - Trailing stop system based on TP progress
  - Emergency exit conditions
  - Time-decay exits for stale positions
  - Cooldown periods after wins/losses

- **Real-time Monitoring**
  - Live position tracking with P&L display
  - Market session awareness (London/NY)
  - Comprehensive status dashboard
  - Signal strength indicators

## 📋 Requirements

- Python 3.8 or higher
- MetaTrader 5 platform
- Active MT5 trading account

## 🔧 Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/gold-trading-bot.git
cd gold-trading-bot
```

2. **Install required packages**
```bash
pip install -r requirements.txt
```

3. **Install MetaTrader 5**
   - Download from [MetaQuotes website](https://www.metatrader5.com/)
   - Set up your trading account

## 🚀 Quick Start

### Windows

Double-click `gold_bot_start.bat` or run:
```bash
python gold_bot.py
```

### Linux/Mac

```bash
python3 gold_bot.py
```

## ⚙️ Configuration

Edit the parameters in `gold_bot.py` to customize:

```python
# Risk Management
self.base_risk_pct = 0.25        # Base risk per trade
self.max_risk_pct = 0.6          # Maximum risk for high-confidence trades
self.min_lot = 0.01              # Minimum lot size
self.max_lot = 0.5               # Maximum lot size

# Daily Limits
self.daily_profit_target = 20.0  # Target profit %
self.max_drawdown = 12.0         # Maximum loss %
self.max_daily_trades = 25       # Maximum trades per day

# Cooldowns
self.win_cooldown = 20           # Seconds after winning trade
self.loss_cooldown = 45          # Seconds after losing trade
```

## 📊 Strategy Overview

The bot uses a multi-factor scoring system to identify high-probability trades:

### Bullish Signals
- Strong uptrend (EMA alignment)
- MACD histogram rising
- RSI in bullish range (40-65) or oversold with momentum
- Volume confirmation
- Bullish candle patterns
- Price near lower Bollinger Band with positive momentum

### Bearish Signals
- Strong downtrend (EMA alignment)
- MACD histogram falling
- RSI in bearish range or overbought with momentum
- Volume confirmation
- Bearish candle patterns
- Price near upper Bollinger Band with negative momentum

### Entry Requirements
- Minimum signal score: 4.5/12
- No extreme RSI levels (avoiding exhaustion)
- Momentum must be building (not exhausted)
- Position within Bollinger Bands
- No recent large price moves (anti-late-entry)

## 📈 Position Management

### Stop Loss & Take Profit
- Dynamic SL based on ATR (0.8-1.2x)
- TP ratio: 1.8-2.5x risk (based on signal strength)
- TP compression for realism (35-55%)

### Trailing System
- 80% TP progress → 10% retrace closes
- 60% TP progress → 15% retrace closes
- 40% TP progress → 20% retrace closes
- 30% TP progress → 25% retrace closes

### Emergency Exits
- Rapid loss > 0.6% of account
- Profit reversal after 0.4% gain
- Time decay after 10 minutes with minimal progress

## 🕐 Trading Hours

- **Active Sessions**: London Open, Mid, NY Open, Mid
- **Trading Hours**: 00:00 - 23:00 UK time (Mon-Fri)
- **Weekend Handling**: Automatically pauses

## 📁 File Structure

```
gold-trading-bot/
├── gold_bot.py              # Main bot script
├── gold_bot_start.bat       # Windows launcher
├── requirements.txt         # Python dependencies
├── README.md               # This file
├── LICENSE                 # MIT License
├── .gitignore             # Git ignore rules
└── bot_state_v3.json      # State file (auto-generated)
```

## 🐛 Troubleshooting

### Common Issues

**"MT5 initialization failed"**
- Ensure MetaTrader 5 is installed and running
- Check that your account is logged in

**"Symbol XAUUSD not found"**
- Add XAUUSD to Market Watch in MT5
- Verify symbol name matches your broker's naming

**"No trading permissions"**
- Enable AutoTrading in MT5 (Tools → Options → Expert Advisors)
- Check that algo trading is allowed on your account

**State file corruption**
- Delete `bot_state_v3.json` to reset daily stats

## 📝 State Management

The bot maintains state in `bot_state_v3.json`:
- Starting balance
- Daily trade count
- Win/loss statistics
- Current P&L
- Last trade timing

State automatically resets at 8:00 AM UK time each trading day.

## 🔐 Security Notes

- Never commit API keys or account credentials
- Use environment variables for sensitive data
- Test on demo accounts first
- Start with minimal lot sizes

## 📊 Performance Monitoring

The bot displays:
- Real-time account equity and balance
- Active position details with P&L
- Progress toward take-profit levels
- Peak progress tracking
- Cooldown timers
- Daily statistics

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Risk Warning

**Trading carries a high level of risk and may not be suitable for all investors. Before deciding to trade, you should carefully consider your investment objectives, level of experience, and risk appetite. You should be aware of all the risks associated with trading and seek advice from an independent financial advisor if you have any doubts.**

**The possibility exists that you could sustain a loss in excess of your deposited funds. Therefore, you should not speculate with capital that you cannot afford to lose.**

## 📧 Support

For issues and questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review the troubleshooting section

## 🙏 Acknowledgments

- MetaTrader 5 API by MetaQuotes
- Technical analysis libraries: pandas, numpy
- Trading community feedback

---

**Made with ❤️ for algorithmic traders**

*Remember: Past performance is not indicative of future results. Trade responsibly.*
