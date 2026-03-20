import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import time as time_module
import pytz
import sys
from dataclasses import dataclass
from typing import Optional, Literal

@dataclass
class TradeSignal:
    direction: Literal["BUY", "SELL"]
    strength: float
    atr: float
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float

class GoldBotHFT:
    def __init__(self):
        self.symbol = "XAUUSD.vx"
        self.magic = 100002  # Changed magic number for HFT version
        self.uk_tz = pytz.timezone("Europe/London")
        self.debug_signal_lines = []
        self.last_bullish_score = 0.0
        self.last_bearish_score = 0.0
        self.last_rejection_reasons = []
        self._last_sizing_rejection = None

        # ===== HFT OPTIMIZED RISK MANAGEMENT =====
        # Increased risk for micro trades (smaller moves need higher risk %)
        self.base_risk_pct = 0.5      # Increased from 0.25
        self.max_risk_pct = 1.0       # Increased from 0.6
        self.min_lot = 0.01
        self.max_lot = 0.5
        self.max_single_trade_risk_pct_cap = 5
        self.tp_compression_min = 0.5  # Increased for quicker profits
        self.tp_compression_max = 0.8  # Increased for quicker profits

        # ===== HFT EXECUTION SETTINGS =====
        self.max_spread_points = 35    # Tighter spread requirement for micro trades
        self.max_price_deviation_points = 10  # Less slippage tolerance

        # ===== HFT POSITION MANAGEMENT =====
        self.time_decay_minutes = 5     # Shorter max hold time
        self.min_progress_after_decay = 0.25

        # ===== HFT DAILY LIMITS =====
        self.daily_profit_target = 30.0  # Higher target
        self.max_drawdown = 8.0          # Tighter drawdown control
        self.max_daily_trades = 50       # More trades per day for HFT
        
        # ===== HFT COOLDOWNS =====
        self.win_cooldown = 5    # Much shorter cooldowns
        self.loss_cooldown = 15  # Still some protection after losses
        
        # State management
        self.state = self._init_state()
        self._position_cache = {}

    def _price_to_points(self, price_delta: float) -> float:
        info = mt5.symbol_info(self.symbol)
        point = float(getattr(info, "point", 0.0) or 0.0) if info else 0.0
        if point <= 0:
            return float(price_delta)
        return float(price_delta) / point

    def _current_spread_points(self) -> Optional[float]:
        info = mt5.symbol_info(self.symbol)
        tick = mt5.symbol_info_tick(self.symbol)
        if not info or not tick:
            return None
        point = float(getattr(info, "point", 0.0) or 0.0)
        if point <= 0:
            return None
        spread_price = float(tick.ask) - float(tick.bid)
        return spread_price / point
        
    def _init_state(self) -> dict:
        return {
            "starting_balance": 0.0,
            "daily_trades": 0,
            "profit": 0.0,
            "last_trade_time": None,
            "last_result": None,
            "trading_day": None,
            "day_pnl": 0.0,
            "day_pnl_pct": 0.0,
        }
    
    def _reset_daily_stats(self):
        uk_now = self._get_uk_time()
        if uk_now.hour >= 8:
            current_day = uk_now.date().isoformat()
        else:
            current_day = (uk_now.date() - timedelta(days=1)).isoformat()
        
        if self.state["trading_day"] != current_day:
            acc = mt5.account_info()
            self.state.update({
                "starting_balance": acc.equity if acc else self.state.get("starting_balance", 0),
                "daily_trades": 0,
                "profit": 0.0,
                "day_pnl": 0.0,
                "day_pnl_pct": 0.0,
                "last_trade_time": None,
                "last_result": None,
                "trading_day": current_day
            })
            self._position_cache.clear()
    
    def _get_uk_time(self) -> datetime:
        return datetime.now(self.uk_tz)
    
    def _current_session(self):
        hour = self._get_uk_time().hour
        if 7 <= hour < 10:
            return "LONDON_OPEN"
        if 10 <= hour < 13:
            return "LONDON_MID"
        if 13 <= hour < 16:
            return "NY_OPEN"
        if 16 <= hour < 19:
            return "NY_MID"
        return "OFF_SESSION"
    
    def _is_market_open(self) -> bool:
        uk_now = self._get_uk_time()
        current_time = uk_now.time()
        
        if uk_now.weekday() >= 5:
            return False
        if uk_now.weekday() == 4 and current_time >= time(19, 0):
            return False
        # HFT: Trade ALL active hours, not just London/NY
        if time(6, 0) <= current_time < time(20, 0):
            return True
        return False
    
    def _get_market_status(self) -> str:
        uk_now = self._get_uk_time()
        current_time = uk_now.time()
        
        if uk_now.weekday() == 5:
            return "WEEKEND (Saturday)"
        elif uk_now.weekday() == 6:
            if current_time < time(23, 0):
                return "WEEKEND (Sunday - Opens 07:00 Monday)"
            else:
                return "OPENING SOON"
        elif uk_now.weekday() == 4 and current_time >= time(19, 0):
            return "CLOSED (Friday - Opens 07:00 Monday)"
        elif time(6, 0) <= current_time < time(20, 0):
            hour = current_time.hour
            if 6 <= hour < 8:
                return "ACTIVE (Early London)"
            elif 8 <= hour < 13:
                return "ACTIVE (London Mid)"
            elif 13 <= hour < 17:
                return "ACTIVE (NY)"
            elif 17 <= hour < 20:
                return "ACTIVE (NY Late)"
            else:
                return "ACTIVE"
        else:
            return "CLOSED (Off Hours)"
    
    def _can_trade(self) -> bool:
        if not self.state["last_trade_time"]:
            return True
        try:
            last_trade = datetime.fromisoformat(self.state["last_trade_time"])
            if last_trade.tzinfo is None:
                last_trade = self.uk_tz.localize(last_trade)
            elapsed = (self._get_uk_time() - last_trade).total_seconds()
            cooldown = self.loss_cooldown if self.state["last_result"] == "loss" else self.win_cooldown
            return elapsed >= cooldown
        except Exception as e:
            print(f"Warning: Error checking cooldown: {e}")
            return True
    
    def _get_market_data(self) -> Optional[pd.DataFrame]:
        try:
            # HFT: Use M1 timeframe for faster signals
            rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 0, 100)
            if rates is None or len(rates) < 50:
                return None
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            
            # HFT: Faster EMAs for quicker signals
            df['ema_5'] = df['close'].ewm(span=5, adjust=False).mean()
            df['ema_10'] = df['close'].ewm(span=10, adjust=False).mean()
            df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
            
            # ATR
            high_low = df['high'] - df['low']
            high_close = abs(df['high'] - df['close'].shift())
            low_close = abs(df['low'] - df['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df['atr'] = tr.rolling(7).mean()  # Shorter ATR period
            
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(7).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(7).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD (faster settings for HFT)
            exp1 = df['close'].ewm(span=6, adjust=False).mean()
            exp2 = df['close'].ewm(span=13, adjust=False).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=4, adjust=False).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            
            # Volume
            df['vol_ma'] = df['tick_volume'].rolling(10).mean()
            
            # Momentum
            df['momentum'] = df['close'] - df['close'].shift(3)  # Shorter momentum
            
            return df.dropna()
        except Exception as e:
            print(f"Error getting market data: {e}")
            return None
    
    def _analyze_signal(self, df: pd.DataFrame) -> Optional[TradeSignal]:
        if len(df) < 50:
            return None
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return None
        
        # === SCORING SYSTEM ===
        bullish_score = 0
        bearish_score = 0
        
        # EMA alignment
        if last['ema_5'] > last['ema_10']:
            bullish_score += 2
        if last['ema_5'] < last['ema_10']:
            bearish_score += 2
        
        # MACD momentum
        if last['macd_hist'] > 0 and last['macd_hist'] > prev['macd_hist']:
            bullish_score += 2
        if last['macd_hist'] < 0 and last['macd_hist'] < prev['macd_hist']:
            bearish_score += 2
        
        # RSI conditions
        if last['rsi'] < 35:
            bullish_score += 2
        elif last['rsi'] > 65:
            bearish_score += 2
        elif 40 < last['rsi'] < 60:
            bullish_score += 1
            bearish_score += 1
        
        # Volume spike
        if last['tick_volume'] > last['vol_ma'] * 1.2:
            if bullish_score > bearish_score:
                bullish_score += 2
            else:
                bearish_score += 2
        
        # Momentum
        if last['momentum'] > 0:
            bullish_score += 1
        if last['momentum'] < 0:
            bearish_score += 1
        
        min_score = 3.0
        
        print(f"\n🔍 SIGNAL CHECK - BUY: {bullish_score}, SELL: {bearish_score}, min: {min_score}")
        
        if bullish_score >= min_score and bullish_score > bearish_score:
            direction = "BUY"
            strength = min(bullish_score / 8, 1.0)
            print(f"✅ BUY signal PASSED - {bullish_score} > {bearish_score}")
        elif bearish_score >= min_score and bearish_score > bullish_score:
            direction = "SELL"
            strength = min(bearish_score / 8, 1.0)
            print(f"✅ SELL signal PASSED - {bearish_score} > {bullish_score}")
        else:
            print(f"❌ No signal: BUY={bullish_score}, SELL={bearish_score}")
            return None
        
        print(f"➡️ Direction: {direction}, Strength: {strength:.2f}")
        
        # === ANTI-LATE ENTRY ===
        price_change_3bars = ((df['close'].iloc[-1] - df['close'].iloc[-3]) / df['close'].iloc[-3]) * 100
        if direction == "BUY" and price_change_3bars > 0.1:
            print(f"❌ Anti-late: Price moved up {price_change_3bars:.2f}%")
            return None
        if direction == "SELL" and price_change_3bars < -0.1:
            print(f"❌ Anti-late: Price moved down {abs(price_change_3bars):.2f}%")
            return None
        
        # === M5 TREND FILTER ===
        m5_rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M5, 0, 20)
        if m5_rates is not None and len(m5_rates) > 10:
            m5_close = pd.Series([r[4] for r in m5_rates])
            m5_ema9 = m5_close.ewm(span=9).mean().iloc[-1]
            m5_ema21 = m5_close.ewm(span=21).mean().iloc[-1]
            
            if direction == "BUY" and m5_ema9 < m5_ema21:
                print("❌ M5 trend bearish - skipping BUY")
                return None
            if direction == "SELL" and m5_ema9 > m5_ema21:
                print("❌ M5 trend bullish - skipping SELL")
                return None
            print(f"✅ M5 trend confirmed")
        
        # === SPREAD FILTER ===
        spread_pts = self._current_spread_points()
        if spread_pts is not None and spread_pts > 35:
            print(f"❌ Spread too high: {spread_pts:.1f} pts")
            return None
        
        # === OPTIMIZED SL/TP CALCULATION ===
        atr = last['atr']
        entry = tick.ask if direction == "BUY" else tick.bid
        
        # DYNAMIC SL/TP BASED ON STRENGTH AND VOLATILITY
        if strength > 0.7:
            sl_distance = atr * 0.5   # Tighter stop for strong signals
            tp_distance = atr * 1.8   # 3.6x reward (1:3.6 R:R)
        elif strength > 0.5:
            sl_distance = atr * 0.6
            tp_distance = atr * 1.5   # 2.5x reward (1:2.5 R:R)
        else:
            sl_distance = atr * 0.8
            tp_distance = atr * 1.2   # 1.5x reward (1:1.5 R:R)
        
        sl = entry - sl_distance if direction == "BUY" else entry + sl_distance
        tp = entry + tp_distance if direction == "BUY" else entry - tp_distance
        
        print(f"📊 R:R Ratio: {tp_distance/sl_distance:.2f}")
        
        # === DYNAMIC RISK SIZING ===
        acc = mt5.account_info()
        if not acc:
            return None
        
        # Risk based on signal strength
        if strength > 0.7:
            risk_pct = 1.0
            print(f"💪 Strong signal - Risk: {risk_pct}%")
        elif strength > 0.5:
            risk_pct = 0.7
            print(f"📈 Medium signal - Risk: {risk_pct}%")
        else:
            risk_pct = 0.5
            print(f"📉 Weak signal - Risk: {risk_pct}%")
        
        # Reduce risk for high spread
        if spread_pts is not None and spread_pts > 25:
            risk_pct = risk_pct * 0.7
            print(f"⚠️ High spread adjustment: Risk reduced to {risk_pct:.2f}%")
        
        risk_money = acc.equity * (risk_pct / 100.0)
        
        # Calculate lot size
        lot = self._calc_lot_from_risk(
            entry_price=entry,
            stop_loss=sl,
            risk_money=risk_money,
            account_equity=acc.equity,
        )
        if lot is None:
            print("❌ Lot calculation failed")
            return None
        
        print(f"🎯 TradeSignal CREATED: {direction} at {entry:.2f}, SL: {sl:.2f}, TP: {tp:.2f}, lot: {lot}")
        
        return TradeSignal(
            direction=direction,
            strength=strength,
            atr=atr,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            lot_size=lot
        )
    
    def _risk_pct_for_equity(self, equity: float, strength: float) -> float:
        strength = max(0.0, min(float(strength), 1.0))
        base = self.base_risk_pct + (strength * (self.max_risk_pct - self.base_risk_pct))
        
        if equity <= 0:
            return base
        scale = min(1.0, max(0.25, (equity / 500.0) ** 0.5))
        return base * scale
    
    def _calc_lot_from_risk(self, entry_price: float, stop_loss: float, risk_money: float, account_equity: float) -> Optional[float]:
        info = mt5.symbol_info(self.symbol)
        if not info:
            return None
        
        sl_dist = abs(float(entry_price) - float(stop_loss))
        if sl_dist <= 0 or risk_money <= 0:
            return None
        
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
        tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
        if tick_size <= 0 or tick_value <= 0:
            return None
        
        value_per_price_unit_per_lot = tick_value / tick_size
        risk_per_lot = sl_dist * value_per_price_unit_per_lot
        if risk_per_lot <= 0:
            return None
        
        raw_lot = risk_money / risk_per_lot
        
        vol_min = float(getattr(info, "volume_min", self.min_lot) or self.min_lot)
        vol_max = float(getattr(info, "volume_max", self.max_lot) or self.max_lot)
        vol_step = float(getattr(info, "volume_step", 0.01) or 0.01)
        
        vol_min = max(vol_min, self.min_lot)
        vol_max = min(vol_max, self.max_lot)
        if vol_max < vol_min:
            return None
        
        stepped = np.floor(raw_lot / vol_step) * vol_step
        lot = float(max(vol_min, min(stepped, vol_max)))
        
        return round(lot, 2)
    
    # def _place_trade(self, signal: TradeSignal):
    #     info = mt5.symbol_info(self.symbol)
    #     if not info:
    #         return

    def _place_trade(self, signal: TradeSignal):
        print(f"💹 ENTERING _place_trade() with {signal.direction} signal")
        info = mt5.symbol_info(self.symbol)
        if not info:
            print("❌ No symbol info - aborting trade")
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            print("❌ No tick data - aborting trade")
            return

        entry_price = tick.ask if signal.direction == "BUY" else tick.bid
        deviation_points = int(self.max_price_deviation_points)
        
        print(f"📊 Preparing order: {signal.direction} {signal.lot_size} lots at {entry_price:.2f}")
        print(f"   SL: {signal.stop_loss:.2f}, TP: {signal.take_profit:.2f}")
        
        # Try different filling modes
        filling_modes = [
            (0, "Auto"),
            (mt5.ORDER_FILLING_RETURN, "RETURN"),
            (mt5.ORDER_FILLING_FOK, "FOK"),
        ]
        
        for mode, mode_name in filling_modes:
            print(f"🔄 Trying {mode_name} filling mode...")
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": signal.lot_size,
                "type": mt5.ORDER_TYPE_BUY if signal.direction == "BUY" else mt5.ORDER_TYPE_SELL,
                "price": entry_price,
                "sl": round(signal.stop_loss, info.digits),
                "tp": round(signal.take_profit, info.digits),
                "magic": self.magic,
                "comment": f"HFT_{signal.direction}_{int(signal.strength*100)}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mode,
                "deviation": deviation_points,
            }
            
            print(f"📤 Sending order with {mode_name} mode...")
            result = mt5.order_send(request)
            
            if result is None:
                print(f"❌ order_send returned None - MT5 error")
                continue
            
            print(f"📨 Order send result - retcode: {result.retcode}")
            print(f"   Comment: {result.comment}")
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"✅✅✅ TRADE EXECUTED! Ticket: {result.order}")
                self.state["last_trade_time"] = self._get_uk_time().isoformat()
                self.debug_signal_lines = []
                return  # Success - exit function
            
            elif result.retcode == 10030:  # Unsupported filling mode
                print(f"❌ {mode_name} mode not supported, trying next...")
                continue
            else:
                print(f"❌❌❌ TRADE FAILED! Error code: {result.retcode}")
                if result.retcode == 10004:
                    print("   - Requote (price changed)")
                elif result.retcode == 10006:
                    print("   - Invalid request")
                elif result.retcode == 10007:
                    print("   - Volume invalid")
                elif result.retcode == 10008:
                    print("   - Market closed")
                elif result.retcode == 10013:
                    print("   - Not enough money")
                elif result.retcode == 10014:
                    print("   - SL/TP invalid")
                elif result.retcode == 10019:
                    print("   - Position locked")
                return  # Stop trying on other errors
        
        print("❌ All filling modes failed")

    def _monitor_positions(self):
        try:
            positions = mt5.positions_get(symbol=self.symbol, magic=self.magic)
            if positions:
                for pos in positions:
                    if pos.ticket not in self._position_cache:
                        self._position_cache[pos.ticket] = {
                            "entry_time": self._get_uk_time(),
                            "peak_profit": 0.0
                        }
                    
                    # Track peak profit for trailing stops
                    if pos.profit > self._position_cache[pos.ticket]["peak_profit"]:
                        self._position_cache[pos.ticket]["peak_profit"] = pos.profit
                    
                    peak = self._position_cache[pos.ticket]["peak_profit"]
                    
                    # === TRAILING STOP LOSS ===
                    # If profit > $2, trail stop to lock in gains
                    if peak > 2.0:
                        # Calculate new stop loss at 50% of peak profit
                        trail_price = pos.price_open
                        if pos.type == mt5.POSITION_TYPE_BUY:
                            trail_price = pos.price_current - (peak * 0.5 / (pos.volume * 100))
                        else:
                            trail_price = pos.price_current + (peak * 0.5 / (pos.volume * 100))
                        
                        # Only move stop in profitable direction
                        if (pos.type == mt5.POSITION_TYPE_BUY and trail_price > pos.sl) or \
                        (pos.type == mt5.POSITION_TYPE_SELL and trail_price < pos.sl):
                            # Modify stop loss
                            request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": pos.ticket,
                                "sl": trail_price,
                                "tp": pos.tp,
                                "symbol": self.symbol,
                                "magic": self.magic,
                            }
                            mt5.order_send(request)
                            print(f"🔹 Trailing stop moved to {trail_price:.2f}")
                    
                    # === PARTIAL PROFIT TAKING ===
                    # Take 50% profit at $1.50
                    if pos.profit > 1.5 and not hasattr(self._position_cache[pos.ticket], 'partial_taken'):
                        # Close half position
                        half_volume = round(pos.volume / 2, 2)
                        if half_volume >= 0.01:
                            tick = mt5.symbol_info_tick(self.symbol)
                            close_price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
                            close_request = {
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": self.symbol,
                                "volume": half_volume,
                                "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                                "position": pos.ticket,
                                "price": close_price,
                                "magic": self.magic,
                                "comment": "PartialProfit",
                                "type_time": mt5.ORDER_TIME_GTC,
                                "type_filling": mt5.ORDER_FILLING_RETURN
                            }
                            result = mt5.order_send(close_request)
                            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                self._position_cache[pos.ticket].partial_taken = True
                                print(f"✅ Partial profit taken: ${pos.profit:.2f}")
                    
                    # === TIME-BASED EXIT ===
                    # Close after 10 minutes regardless of profit
                    age_minutes = (self._get_uk_time() - self._position_cache[pos.ticket]["entry_time"]).total_seconds() / 60
                    if age_minutes > 10:
                        self._close_position(pos, "TimeExit")
                        print(f"⏰ Time exit after {age_minutes:.0f} minutes")
            
            self._sync_deals_to_state()
        except Exception as e:
            print(f"Error monitoring positions: {e}")
    
    def _close_position(self, pos, reason: str):
        try:
            tick = mt5.symbol_info_tick(self.symbol)
            if not tick:
                return
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "price": tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask,
                "magic": self.magic,
                "comment": reason,
                "type_time": mt5.ORDER_TIME_GTC,
                # "type_filling": mt5.ORDER_FILLING_IOC
                "type_filling": mt5.ORDER_FILLING_RETURN
            }
            
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                if pos.ticket in self._position_cache:
                    del self._position_cache[pos.ticket]
                print(f"✅ Position closed: {reason}")
        except Exception as e:
            print(f"Error closing position: {e}")
    
    def _sync_deals_to_state(self):
        """Process new closed deals and update state"""
        try:
            uk_now = self._get_uk_time()
            
            if uk_now.hour >= 8:
                today_start = uk_now.replace(hour=8, minute=0, second=0, microsecond=0)
            else:
                today_start = (uk_now - timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            
            history = mt5.history_deals_get(from_date=today_start, to_date=uk_now)
            if not history:
                return
            
            daily_profit = 0.0
            daily_trades = 0
            processed_positions = set()
            last_deal_time = None
            last_deal_result = None
            
            for deal in history:
                if deal.magic != self.magic:
                    continue
                
                if deal.entry == mt5.DEAL_ENTRY_OUT:
                    if deal.position in processed_positions:
                        continue
                    
                    processed_positions.add(deal.position)
                    daily_profit += deal.profit
                    
                    if deal.profit > 0:
                        last_deal_result = "win"
                    elif deal.profit < 0:
                        last_deal_result = "loss"
                    
                    daily_trades += 1
                    
                    deal_time = datetime.fromtimestamp(deal.time, tz=self.uk_tz)
                    if last_deal_time is None or deal_time > last_deal_time:
                        last_deal_time = deal_time
            
            self.state['profit'] = daily_profit
            self.state['daily_trades'] = daily_trades
            
            if last_deal_time:
                self.state['last_trade_time'] = last_deal_time.isoformat()
                self.state['last_result'] = last_deal_result
            
            self.state['day_pnl'] = daily_profit
            if self.state['starting_balance'] > 0:
                self.state['day_pnl_pct'] = (daily_profit / self.state['starting_balance']) * 100
            else:
                self.state['day_pnl_pct'] = 0
            
        except Exception as e:
            print(f"Error syncing deals: {e}")
            import traceback
            traceback.print_exc()
    
    def _print_status(self):
        """Print bot status"""
        try:
            acc = mt5.account_info()
            if not acc:
                return

            uk_now = self._get_uk_time()
            positions = mt5.positions_get(symbol=self.symbol, magic=self.magic)
            has_positions = positions and len(positions) > 0

            market_status = self._get_market_status()

            output = []
            output.append(f"\n{'='*70}")
            output.append(f"HFT GOLD TRADING BOT - {uk_now.strftime('%H:%M:%S %A')}".center(70))
            output.append(f"{'='*70}\n")

            output.append(f"Account  │ Equity: £{acc.equity:,.2f} │ Balance: £{acc.balance:,.2f}")
            output.append(f"Market   │ {market_status}")

            if has_positions:
                output.append(f"\n{'─'*70}")
                output.append(f"ACTIVE TRADE")
                output.append(f"{'─'*70}")

                for pos in positions:
                    if pos.magic != self.magic:
                        continue

                    pos_type = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                    output.append(f"#{pos.ticket} │ {pos_type} {pos.volume} lots")
                    output.append(f"Entry: ${pos.price_open:.2f} → Current: ${pos.price_current:.2f}")
                    output.append(f"P/L: £{pos.profit:+.2f}")

            else:
                if not self._can_trade():
                    try:
                        last_trade = datetime.fromisoformat(self.state["last_trade_time"])
                        if last_trade.tzinfo is None:
                            last_trade = self.uk_tz.localize(last_trade)
                        elapsed = (self._get_uk_time() - last_trade).total_seconds()
                        cooldown = self.loss_cooldown if self.state.get("last_result") == "loss" else self.win_cooldown
                        remaining = max(0, int(cooldown - elapsed))
                        result_type = self.state.get('last_result', 'TRADE').upper()
                        output.append(f"\nStatus   │ COOLDOWN: {remaining}s remaining ({result_type})")
                    except Exception as e:
                        output.append(f"\nStatus   │ COOLDOWN (error: {e})")
                else:
                    if "ACTIVE" in market_status:
                        output.append(f"\nStatus   │ HFT SCANNING FOR MICRO TRADES...")
                        
                        if self.state['daily_trades'] > 0:
                            output.append(f"Daily    │ Trades: {self.state['daily_trades']}/{self.max_daily_trades} │ P/L: £{self.state['day_pnl']:+.2f} ({self.state['day_pnl_pct']:+.2f}%)")
                        
                        if self.debug_signal_lines:
                            output.append(f"\n{'─'*70}")
                            for line in self.debug_signal_lines:
                                output.append(line)
                        else:
                            output.append(f"\nBUY Score: {self.last_bullish_score:.1f} | SELL Score: {self.last_bearish_score:.1f} (min 3.0)")

                    else:
                        output.append(f"\nStatus   │ WAITING FOR MARKET ({market_status})")

            output.append(f"\n{'='*70}\n")

            sys.stdout.write('\033[2J\033[H')
            sys.stdout.write('\n'.join(output))
            sys.stdout.flush()

        except Exception as e:
            print(f"Error printing status: {e}")
    
    def run(self):
        """Main bot loop"""
        if not mt5.initialize():
            print("MT5 initialization failed")
            return
        
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            print(f"Symbol {self.symbol} not found")
            mt5.shutdown()
            return
        
        if not symbol_info.visible:
            mt5.symbol_select(self.symbol, True)
        
        acc = mt5.account_info()
        if not acc:
            print("Failed to get account info")
            mt5.shutdown()
            return
        
        if self.state["starting_balance"] == 0:
            self.state["starting_balance"] = acc.equity
        
        print("\n" + "="*70)
        print("HFT GOLD TRADING BOT INITIALIZED".center(70))
        print("="*70)
        print(f"\nStarting Balance: £{self.state['starting_balance']:,.2f}")
        print(f"Mode: HFT Micro Trading (M1 Timeframe)")
        print(f"Min Score: 3.0 (Aggressive)")
        print(f"Risk: {self.base_risk_pct}-{self.max_risk_pct}% per trade")
        print(f"Max Daily Trades: {self.max_daily_trades}")
        print("\nStarting in 3 seconds...\n")
        time_module.sleep(3)
        
        last_print = datetime.now()
        
        while True:
            try:
                self._reset_daily_stats()
                self._sync_deals_to_state()
                
                if not self._is_market_open():
                    if (datetime.now() - last_print).total_seconds() >= 10:
                        self._print_status()
                        last_print = datetime.now()
                    time_module.sleep(5)
                    continue
                
                self._monitor_positions()
                
                acc = mt5.account_info()
                if acc and self.state['starting_balance'] > 0:
                    profit_pct = ((acc.equity - self.state['starting_balance']) / self.state['starting_balance']) * 100
                    if profit_pct >= self.daily_profit_target:
                        self._print_status()
                        print(f"\n🎯 DAILY TARGET REACHED: {profit_pct:+.2f}%\n")
                        time_module.sleep(3600)
                        continue
                    if profit_pct < -self.max_drawdown:
                        self._print_status()
                        print(f"\n⚠️  MAX DRAWDOWN HIT: {profit_pct:+.2f}%\n")
                        time_module.sleep(3600)
                        continue
                
                if self.state['daily_trades'] >= self.max_daily_trades:
                    if (datetime.now() - last_print).total_seconds() >= 10:
                        self._print_status()
                        last_print = datetime.now()
                    time_module.sleep(5)
                    continue
                
                positions = mt5.positions_get(symbol=self.symbol, magic=self.magic)
                has_positions = positions and len(positions) > 0
                
                if has_positions:
                    if (datetime.now() - last_print).total_seconds() >= 1.5:
                        self._print_status()
                        last_print = datetime.now()
                    time_module.sleep(0.5)
                    continue
                
                if (datetime.now() - last_print).total_seconds() >= 5:
                    self._print_status()
                    last_print = datetime.now()
                
                if not self._can_trade():
                    time_module.sleep(1)
                    continue
                
                df = self._get_market_data()
                if df is None:
                    time_module.sleep(2)
                    continue
                
                # signal = self._analyze_signal(df)
                # if signal:
                #     self._place_trade(signal)
                #     time_module.sleep(1)
                # else:
                #     time_module.sleep(1)

                signal = self._analyze_signal(df)
                if signal:
                    print(f"🚀 SIGNAL RECEIVED in run() - Calling _place_trade()")
                    self._place_trade(signal)
                    time_module.sleep(1)
                else:
                    print(f"⏸️ No signal this cycle")
                    time_module.sleep(1)
                
            except KeyboardInterrupt:
                print("\n\nShutting down bot...\n")
                break
            except Exception as e:
                print(f"\nError in main loop: {str(e)}")
                import traceback
                traceback.print_exc()
                time_module.sleep(5)
        
        mt5.shutdown()

if __name__ == "__main__":
    GoldBotHFT().run()