import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import time as time_module
import pytz
import sys
import os
import csv
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

class GoldBot:
    def __init__(self):
        self.symbol = "XAUUSD"
        self.magic = 100001
        self.uk_tz = pytz.timezone("Europe/London")
        self.debug_signal_lines = []
        self.last_bullish_score = 0.0
        self.last_bearish_score = 0.0
        self.last_rejection_reasons = []
        self._last_sizing_rejection = None
        self.journal_file = "trade_journal.csv"
        self._logged_positions = set()


        
        # Risk management
        # NOTE: Position sizing is computed from MT5 tick_value/tick_size so risk stays consistent,
        # especially on small accounts (e.g., £100).
        self.base_risk_pct = 0.25
        self.max_risk_pct = 0.6
        self.min_lot = 0.01
        self.max_lot = 0.5
        # Hard safety cap: if the smallest allowed lot would risk more than this % of equity, skip.
        # Tuned for brokers like Vantage where XAUUSD min lot is 0.01 and tick economics are sizable.
        self.max_single_trade_risk_pct_cap = 1.5
        self.tp_compression_min = 0.35
        self.tp_compression_max = 0.55

        # Execution / spread controls
        # Max allowed spread in points (XAUUSD on Vantage: 1 point == 0.01).
        # Example: 25 points == $0.25 spread. Tune based on your usual live/demo spread.
        self.max_spread_points = 25
        # Price slippage tolerance (points) for market orders.
        self.max_price_deviation_points = 20

        self.time_decay_minutes = 10
        self.min_progress_after_decay = 0.15


        # Daily limits
        self.daily_profit_target = 20.0
        self.max_drawdown = 12.0
        self.max_daily_trades = 25
        
        # Cooldowns - Shorter for more action
        self.win_cooldown = 20
        self.loss_cooldown = 45
        
        # State management (runtime only; no JSON persistence)
        self.state = self._init_state()
        
        # Position tracking
        self._position_cache = {}


    def _price_to_points(self, price_delta: float) -> float:
        """Convert a price delta to 'points' using the symbol's point size (correct for XAUUSD digits)."""
        info = mt5.symbol_info(self.symbol)
        point = float(getattr(info, "point", 0.0) or 0.0) if info else 0.0
        if point <= 0:
            # Safe fallback: treat price delta as points (won't be accurate but avoids crashing)
            return float(price_delta)
        return float(price_delta) / point

    def _current_spread_points(self) -> Optional[float]:
        """Return current spread in symbol points, or None if tick/symbol info missing."""
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
        # Kept minimal on purpose: we only store what the bot uses for flow control and daily limits.
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
        # Reset at 8am each day
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
            # Don't clear these anymore - we recalculate from MT5 history
            # self._processed_deals.clear()
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
        
        # Weekend check
        if uk_now.weekday() >= 5:
            return False
        
        # Friday close
        if uk_now.weekday() == 4 and uk_now.time() >= time(22, 0):
            return False
        
        current_time = uk_now.time()
        return time(0, 0) <= current_time <= time(23, 0)
    
    def _get_market_status(self) -> str:
        uk_now = self._get_uk_time()
        current_time = uk_now.time()
        
        if uk_now.weekday() == 5:
            return "WEEKEND (Saturday)"
        elif uk_now.weekday() == 6:
            if current_time < time(23, 0):
                return "WEEKEND (Sunday - Opens 23:00)"
            else:
                return "OPENING"
        elif uk_now.weekday() == 4 and current_time >= time(22, 0):
            return "CLOSED (Friday)"
        elif current_time >= time(23, 0) or current_time < time(0, 0):
            return "PAUSED (23:00-00:00)"
        else:
            return "ACTIVE"
    
    def _can_trade(self) -> bool:
        if not self.state["last_trade_time"]:
            return True
        
        try:
            last_trade = datetime.fromisoformat(self.state["last_trade_time"])
            # Convert to UK timezone if not already timezone-aware
            if last_trade.tzinfo is None:
                last_trade = self.uk_tz.localize(last_trade)
            elapsed = (self._get_uk_time() - last_trade).total_seconds()
            
            cooldown = self.loss_cooldown if self.state["last_result"] == "loss" else self.win_cooldown
            return elapsed >= cooldown
        except Exception as e:
            # If there's any error parsing time, allow trading (fail open)
            print(f"Warning: Error checking cooldown: {e}")
            return True
    
    def _get_market_data(self) -> Optional[pd.DataFrame]:
        try:
            rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M5, 0, 200)
            if rates is None or len(rates) < 100:
                return None
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            
            # EMAs
            df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
            df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
            df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
            df['ema_100'] = df['close'].ewm(span=100, adjust=False).mean()
            
            # ATR
            high_low = df['high'] - df['low']
            high_close = abs(df['high'] - df['close'].shift())
            low_close = abs(df['low'] - df['close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df['atr'] = tr.rolling(14).mean()
            
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            
            # Bollinger Bands
            df['bb_mid'] = df['close'].rolling(20).mean()
            df['bb_std'] = df['close'].rolling(20).std()
            df['bb_upper'] = df['bb_mid'] + (2 * df['bb_std'])
            df['bb_lower'] = df['bb_mid'] - (2 * df['bb_std'])
            
            # Volume
            df['vol_ma'] = df['tick_volume'].rolling(20).mean()
            
            # Candle patterns
            df['body'] = abs(df['close'] - df['open'])
            df['range'] = df['high'] - df['low']
            df['upper_wick'] = df.apply(lambda x: x['high'] - max(x['open'], x['close']), axis=1)
            df['lower_wick'] = df.apply(lambda x: min(x['open'], x['close']) - x['low'], axis=1)
            
            # Momentum
            df['momentum'] = df['close'] - df['close'].shift(10)
            
            # Trend strength
            df['adx'] = self._calculate_adx(df)
            
            return df.dropna()
        except Exception as e:
            print(f"Error getting market data: {e}")
            return None
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ADX for trend strength"""
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            plus_dm = high.diff()
            minus_dm = low.diff().mul(-1)
            
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            
            tr = pd.concat([
                high - low,
                abs(high - close.shift()),
                abs(low - close.shift())
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(period).mean()
            
            plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
            
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
            adx = dx.rolling(period).mean()
            
            return adx
        except:
            return pd.Series([0] * len(df))
    
    def _analyze_signal(self, df: pd.DataFrame) -> Optional[TradeSignal]:
        if len(df) < 100:
            return None
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]
        prev3 = df.iloc[-4]
        
        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return None
        
        # === TREND ANALYSIS ===
        ema_bull_align = last['ema_9'] > last['ema_21'] > last['ema_50']
        ema_bear_align = last['ema_9'] < last['ema_21'] < last['ema_50']
        
        strong_uptrend = ema_bull_align and last['ema_50'] > last['ema_100']
        strong_downtrend = ema_bear_align and last['ema_50'] < last['ema_100']
        
        price_above_ema9 = last['close'] > last['ema_9']
        price_below_ema9 = last['close'] < last['ema_9']
        
        # === MOMENTUM ===
        macd_bullish = last['macd_hist'] > 0 and last['macd_hist'] > prev['macd_hist']
        macd_bearish = last['macd_hist'] < 0 and last['macd_hist'] < prev['macd_hist']
        
        macd_strong_up = (last['macd_hist'] > prev['macd_hist'] > prev2['macd_hist'] > prev3['macd_hist'])
        macd_strong_down = (last['macd_hist'] < prev['macd_hist'] < prev2['macd_hist'] < prev3['macd_hist'])
        
        # === RSI CONDITIONS ===
        rsi_neutral = 45 < last['rsi'] < 55
        rsi_bullish = 40 < last['rsi'] < 65
        rsi_bearish = 35 < last['rsi'] < 60
        rsi_oversold = last['rsi'] < 35
        rsi_overbought = last['rsi'] > 65
        
        # Avoid extreme RSI
        rsi_extreme_high = last['rsi'] > 75
        rsi_extreme_low = last['rsi'] < 25
        
        # === VOLUME ===
        volume_spike = last['tick_volume'] > last['vol_ma'] * 1.2
        volume_normal = last['tick_volume'] > last['vol_ma'] * 0.8
        
        # === BOLLINGER BANDS ===
        near_bb_lower = last['close'] < last['bb_lower'] + (last['bb_std'] * 0.3)
        near_bb_upper = last['close'] > last['bb_upper'] - (last['bb_std'] * 0.3)
        
        in_bb_middle = last['bb_lower'] + last['bb_std'] < last['close'] < last['bb_upper'] - last['bb_std']
        
        # === CANDLE PATTERNS ===
        bullish_candle = last['close'] > last['open'] and last['body'] > last['range'] * 0.6
        bearish_candle = last['close'] < last['open'] and last['body'] > last['range'] * 0.6
        
        strong_bullish = bullish_candle and last['body'] > prev['body'] * 1.2
        strong_bearish = bearish_candle and last['body'] > prev['body'] * 1.2
        
        hammer = last['lower_wick'] > last['body'] * 2 and last['upper_wick'] < last['body'] * 0.5
        shooting_star = last['upper_wick'] > last['body'] * 2 and last['lower_wick'] < last['body'] * 0.5
        
        # === TREND STRENGTH ===
        strong_trend = last['adx'] > 25
        very_strong_trend = last['adx'] > 35
        
        # === MOMENTUM ===
        positive_momentum = last['momentum'] > 0
        negative_momentum = last['momentum'] < 0
        
        # === SCORING SYSTEM (More Conservative) ===
        bullish_score = 0
        bearish_score = 0
        
        # BULLISH SCORING
        if strong_uptrend:
            bullish_score += 2.5
        elif ema_bull_align:
            bullish_score += 1.5
        
        if price_above_ema9 and strong_trend:
            bullish_score += 1.5
        elif price_above_ema9:
            bullish_score += 0.8
        
        if macd_strong_up:
            bullish_score += 2.0
        elif macd_bullish:
            bullish_score += 1.0
        
        if rsi_oversold and positive_momentum:
            bullish_score += 2.0
        elif rsi_bullish:
            bullish_score += 1.0
        elif rsi_neutral:
            bullish_score += 0.5
        
        if volume_spike and bullish_candle:
            bullish_score += 1.5
        elif volume_normal:
            bullish_score += 0.5
        
        if near_bb_lower and positive_momentum:
            bullish_score += 1.5
        
        if strong_bullish:
            bullish_score += 1.5
        elif bullish_candle:
            bullish_score += 0.8
        
        if hammer and near_bb_lower:
            bullish_score += 2.0
        elif hammer:
            bullish_score += 1.0
        
        if very_strong_trend and ema_bull_align:
            bullish_score += 1.0
        
        # BEARISH SCORING
        if strong_downtrend:
            bearish_score += 2.5
        elif ema_bear_align:
            bearish_score += 1.5
        
        if price_below_ema9 and strong_trend:
            bearish_score += 1.5
        elif price_below_ema9:
            bearish_score += 0.8
        
        if macd_strong_down:
            bearish_score += 2.0
        elif macd_bearish:
            bearish_score += 1.0
        
        if rsi_overbought and negative_momentum:
            bearish_score += 2.0
        elif rsi_bearish:
            bearish_score += 1.0
        elif rsi_neutral:
            bearish_score += 0.5
        
        if volume_spike and bearish_candle:
            bearish_score += 1.5
        elif volume_normal:
            bearish_score += 0.5
        
        if near_bb_upper and negative_momentum:
            bearish_score += 1.5
        
        if strong_bearish:
            bearish_score += 1.5
        elif bearish_candle:
            bearish_score += 0.8
        
        if shooting_star and near_bb_upper:
            bearish_score += 2.0
        elif shooting_star:
            bearish_score += 1.0
        
        if very_strong_trend and ema_bear_align:
            bearish_score += 1.0
        
        # === FILTERS (Reject bad setups) ===
        if rsi_extreme_high:
            bullish_score = 0.4
        if rsi_extreme_low:
            bearish_score = 0.4
        
        # Require minimum trend strength
        if not strong_trend:
            bullish_score *= 0.85
            bearish_score *= 0.85
        
        # Penalize choppy conditions
        if in_bb_middle and not strong_trend:
            bullish_score *= 0.8
            bearish_score *= 0.8

        # Hard block for super-choppy/noise conditions:
        #  - ADX very low
        #  - price in middle of Bollinger band
        #  - momentum flat
        if last['adx'] < 18 and in_bb_middle and abs(last['momentum']) < abs(prev['momentum']) * 0.5:
            self.last_bullish_score = bullish_score
            self.last_bearish_score = bearish_score
            self.last_rejection_reasons = [f"Choppy market: ADX={last['adx']:.1f} < 18, low momentum"]
            self._debug_signal_state(df)
            return None
        
        # === DECISION (Lower threshold = more trades) ===
        min_score = 4.5  # Back to more active trading
        
        # Store scores for diagnostics
        self.last_bullish_score = bullish_score
        self.last_bearish_score = bearish_score
        self.last_rejection_reasons = []
        
        if bullish_score >= min_score and bullish_score > bearish_score * 1.2:
            direction = "BUY"
            strength = min(bullish_score / 12, 1.0)
        elif bearish_score >= min_score and bearish_score > bullish_score * 1.2:
            direction = "SELL"
            strength = min(bearish_score / 12, 1.0)
        else:
            if bullish_score < min_score and bearish_score < min_score:
                self.last_rejection_reasons.append(f"Scores too low: BUY={bullish_score:.2f}, SELL={bearish_score:.2f} (min {min_score})")
            elif bullish_score >= min_score and bearish_score >= min_score:
                if bullish_score <= bearish_score * 1.2 and bearish_score <= bullish_score * 1.2:
                    self.last_rejection_reasons.append(f"No clear winner: BUY={bullish_score:.2f} vs SELL={bearish_score:.2f} (need 1.2x advantage)")
            elif bullish_score >= min_score:
                self.last_rejection_reasons.append(f"BUY score OK ({bullish_score:.2f}) but SELL too close ({bearish_score:.2f})")
            else:
                self.last_rejection_reasons.append(f"SELL score OK ({bearish_score:.2f}) but BUY too close ({bullish_score:.2f})")
            return None
        
        # === ANTI-LATE ENTRY FILTERS ===
        # Don't buy after big move up or sell after big move down
        recent_5_bars = df.tail(5)
        price_change_5bars = ((recent_5_bars['close'].iloc[-1] - recent_5_bars['close'].iloc[0]) / recent_5_bars['close'].iloc[0]) * 100
        
        # If price moved up >0.15% in last 5 bars, don't buy (too late)
        if direction == "BUY" and price_change_5bars > 0.15:
            self.last_rejection_reasons.append(f"Anti-late entry: Price moved up {price_change_5bars:.2f}% in last 5 bars")
            return None
        
        # If price moved down >0.15% in last 5 bars, don't sell (too late)
        if direction == "SELL" and price_change_5bars < -0.15:
            self.last_rejection_reasons.append(f"Anti-late entry: Price moved down {abs(price_change_5bars):.2f}% in last 5 bars")
            return None
        
        # Don't trade at extreme BB positions (already moved too much)
        bb_position = (last['close'] - last['bb_lower']) / (last['bb_upper'] - last['bb_lower'])
        if direction == "BUY" and bb_position > 0.8:  # Price too high in BB
            self.last_rejection_reasons.append(f"BB position too high: {bb_position:.2%} (max 80%)")
            return None
        if direction == "SELL" and bb_position < 0.2:  # Price too low in BB
            self.last_rejection_reasons.append(f"BB position too low: {bb_position:.2%} (min 20%)")
            return None
        
        # Check if momentum is still building (not exhausted)
        momentum_increasing = abs(last['momentum']) > abs(prev['momentum'])
        if not momentum_increasing:
            # Reduce score if momentum weakening
            if direction == "BUY":
                bullish_score *= 0.7
                if bullish_score < min_score:
                    self.last_rejection_reasons.append(f"Momentum weakening: BUY score reduced to {bullish_score:.2f} < {min_score}")
                    return None
            else:
                bearish_score *= 0.7
                if bearish_score < min_score:
                    self.last_rejection_reasons.append(f"Momentum weakening: SELL score reduced to {bearish_score:.2f} < {min_score}")
                    return None
        
        # === SPREAD FILTER ===
        spread_pts = self._current_spread_points()
        if spread_pts is not None and spread_pts > self.max_spread_points:
            # Too expensive spread right now – skip this bar.
            self.debug_signal_lines = [
                "SIGNAL CHECK (NO TRADE)",
                f"✖ Spread too high: {spread_pts:.1f} pts (max {self.max_spread_points})",
            ]
            return None

        # === POSITION SIZING / SL-TP (with higher-timeframe ATR blend) ===
        atr_m5 = last['atr']
        # Approximate a higher-timeframe ATR (M15) from existing M5 data
        try:
            df_htf = (
                df.set_index("time")[["high", "low", "close"]]
                .resample("15min")
                .agg({"high": "max", "low": "min", "close": "last"})
                .dropna()
            )
            high_low_htf = df_htf['high'] - df_htf['low']
            high_close_htf = abs(df_htf['high'] - df_htf['close'].shift())
            low_close_htf = abs(df_htf['low'] - df_htf['close'].shift())
            tr_htf = pd.concat([high_low_htf, high_close_htf, low_close_htf], axis=1).max(axis=1)
            atr_htf = tr_htf.rolling(14).mean().iloc[-1]
        except Exception:
            atr_htf = atr_m5

        # Blend intraday ATR with higher-timeframe ATR to avoid ultra-tight stops in noisy periods.
        atr = max(atr_m5, float(atr_htf) * 0.4)
        entry = tick.ask if direction == "BUY" else tick.bid
        
        # Dynamic SL/TP based on strength and trend
        if strength > 0.75 and very_strong_trend:
            sl_distance = atr * 0.8
            tp_distance = sl_distance * 2.5
        elif strength > 0.65:
            sl_distance = atr * 1.0
            tp_distance = sl_distance * 2.2
        else:
            sl_distance = atr * 1.2
            tp_distance = sl_distance * 1.8
        
        sl = entry - sl_distance if direction == "BUY" else entry + sl_distance
        tp = entry + tp_distance if direction == "BUY" else entry - tp_distance

        # === REALISTIC TP COMPRESSION ===
        compression = self.tp_compression_min + (
            strength * (self.tp_compression_max - self.tp_compression_min)
        )

        tp_distance *= compression
        
        # === LOT SIZING ===
        acc = mt5.account_info()
        if not acc:
            return None
        
        risk_pct = self._risk_pct_for_equity(acc.equity, strength)
        risk_money = acc.equity * (risk_pct / 100.0)

        lot = self._calc_lot_from_risk(
            entry_price=entry,
            stop_loss=sl,
            risk_money=risk_money,
            account_equity=acc.equity,
        )
        if lot is None:
            # Provide detailed rejection reason
            if self._last_sizing_rejection:
                rej = self._last_sizing_rejection
                self.last_rejection_reasons.append(
                    f"Position sizing failed: Min lot (0.01) would risk {rej['min_lot_risk']:.2f}% "
                    f"(cap: {self.max_single_trade_risk_pct_cap}%) | "
                    f"Account: £{rej['account_equity']:.2f} | SL distance: ${rej['stop_loss_distance']:.2f}"
                )
            else:
                self.last_rejection_reasons.append("Position sizing failed (lot calculation returned None - check risk limits)")
            return None
        
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
        """
        Risk scales with signal strength and also scales down on small accounts,
        so a £100 account doesn't get over-levered by minimum lot constraints.
        """
        strength = max(0.0, min(float(strength), 1.0))
        base = self.base_risk_pct + (strength * (self.max_risk_pct - self.base_risk_pct))

        # Scale down risk for small accounts, approach 1.0 at ~£500+
        # (sqrt curve: gentle on mid accounts, protective on tiny accounts)
        if equity <= 0:
            return base
        scale = min(1.0, max(0.25, (equity / 500.0) ** 0.5))
        return base * scale

    def _calc_lot_from_risk(
        self,
        entry_price: float,
        stop_loss: float,
        risk_money: float,
        account_equity: float,
    ) -> Optional[float]:
        """
        Convert intended £ risk into lots using MT5 symbol tick_value/tick_size.
        Returns None when sizing is impossible or would exceed risk due to min lot.
        """
        info = mt5.symbol_info(self.symbol)
        if not info:
            return None

        sl_dist = abs(float(entry_price) - float(stop_loss))
        if sl_dist <= 0 or risk_money <= 0:
            return None

        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
        tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
        if tick_size <= 0 or tick_value <= 0:
            # Fallback: do not trade if broker doesn't provide economics (safer than guessing wrong).
            return None

        # £ per 1.0 price-unit move, per 1 lot
        value_per_price_unit_per_lot = tick_value / tick_size
        risk_per_lot = sl_dist * value_per_price_unit_per_lot
        if risk_per_lot <= 0:
            return None

        raw_lot = risk_money / risk_per_lot

        # Clamp to broker constraints
        vol_min = float(getattr(info, "volume_min", self.min_lot) or self.min_lot)
        vol_max = float(getattr(info, "volume_max", self.max_lot) or self.max_lot)
        vol_step = float(getattr(info, "volume_step", 0.01) or 0.01)

        # Also respect bot caps
        vol_min = max(vol_min, self.min_lot)
        vol_max = min(vol_max, self.max_lot)
        if vol_max < vol_min:
            return None

        # Round down to step to avoid accidentally exceeding risk
        stepped = np.floor(raw_lot / vol_step) * vol_step
        lot = float(max(vol_min, min(stepped, vol_max)))

        # Compute actual risk for the final lot size
        actual_risk = lot * risk_per_lot

        # Absolute safety: never allow a single trade to risk more than the cap (esp. when min lot binds)
        if account_equity > 0:
            risk_pct_actual = (actual_risk / account_equity) * 100.0
            if risk_pct_actual > self.max_single_trade_risk_pct_cap:
                # Store rejection reason for diagnostics
                self._last_sizing_rejection = {
                    "requested_risk_pct": (risk_money / account_equity) * 100.0,
                    "actual_risk_pct": risk_pct_actual,
                    "min_lot_risk": (vol_min * risk_per_lot / account_equity) * 100.0,
                    "stop_loss_distance": sl_dist,
                    "account_equity": account_equity
                }
                return None

        return round(lot, 2)
    
    def _debug_signal_state(self, df: pd.DataFrame):
        last = df.iloc[-1]
        prev = df.iloc[-2]

        checks = {
            "EMA Trend (9>21>50)": last['ema_9'] > last['ema_21'] > last['ema_50'],
            "Strong Trend (ADX>25)": last['adx'] > 25,
            "MACD Momentum": last['macd_hist'] > 0,
            "RSI OK (40–65)": 40 < last['rsi'] < 65,
            "Volume OK": last['tick_volume'] > last['vol_ma'] * 0.8,
            "Not BB Chop": not (
                last['bb_lower'] + last['bb_std']
                < last['close']
                < last['bb_upper'] - last['bb_std']
            ),
            "Momentum Building": abs(last['momentum']) > abs(prev['momentum'])
        }

        passed = sum(1 for v in checks.values() if v)
        total = len(checks)

        lines = []
        lines.append("SIGNAL CHECK (NO TRADE)")
        lines.append(f"Matched: {passed}/{total}")

        for k, v in checks.items():
            lines.append(f"{'✔' if v else '✖'} {k}")

        self.debug_signal_lines = lines
    
    def _log_signal_rejection_reason(self, df: pd.DataFrame):
        """Enhanced logging to show why signal was rejected"""
        if len(df) < 100:
            return
        
        # Check spread
        spread_pts = self._current_spread_points()
        
        # Add stored rejection reasons
        if self.last_rejection_reasons:
            self.debug_signal_lines.extend([
                "",
                "REJECTION REASONS:"
            ])
            for reason in self.last_rejection_reasons:
                self.debug_signal_lines.append(f"  ✖ {reason}")
        
        # Check spread separately (it's checked early in the flow)
        if spread_pts is not None and spread_pts > self.max_spread_points:
            if "REJECTION REASONS:" not in '\n'.join(self.debug_signal_lines):
                self.debug_signal_lines.extend([
                    "",
                    "REJECTION REASONS:"
                ])
            self.debug_signal_lines.append(f"  ✖ Spread too high: {spread_pts:.1f} pts (max {self.max_spread_points})")
        
        # Always show current scores and spread
        min_score = 4.5
        if spread_pts is not None:
            self.debug_signal_lines.append(f"\nSpread: {spread_pts:.1f} pts (max {self.max_spread_points})")
        self.debug_signal_lines.append(f"BUY Score: {self.last_bullish_score:.2f} | SELL Score: {self.last_bearish_score:.2f} (need ≥{min_score})")

    def _place_trade(self, signal: TradeSignal):
        info = mt5.symbol_info(self.symbol)
        if not info:
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return

        # Use the latest prices from tick to reduce slippage vs the analysed bar
        entry_price = tick.ask if signal.direction == "BUY" else tick.bid

        # Convert max_price_deviation_points to price units for MT5 deviation
        point = float(getattr(info, "point", 0.0) or 0.0)
        deviation_points = int(self.max_price_deviation_points)
        deviation_price = deviation_points * point if point > 0 else 0.0
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": signal.lot_size,
            "type": mt5.ORDER_TYPE_BUY if signal.direction == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": entry_price,
            "sl": round(signal.stop_loss, info.digits),
            "tp": round(signal.take_profit, info.digits),
            "magic": self.magic,
            "comment": f"Elite_{signal.direction}_{int(signal.strength*100)}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "deviation": deviation_points,
        }

        # Basic retry on requotes / slight price changes
        result = mt5.order_send(request)
        if result and result.retcode in (
            mt5.TRADE_RETCODE_REQUOTE,
            mt5.TRADE_RETCODE_PRICE_CHANGED,
        ):
            # Refresh tick and try once more with updated price
            tick_retry = mt5.symbol_info_tick(self.symbol)
            if tick_retry:
                request["price"] = tick_retry.ask if signal.direction == "BUY" else tick_retry.bid
                result = mt5.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.state["last_trade_time"] = self._get_uk_time().isoformat()
            self.debug_signal_lines = []
    
    def _should_emergency_exit(self, pos, current_pnl_pct: float, peak_pnl_pct: float) -> tuple[bool, str]:
        if pos.type == mt5.POSITION_TYPE_BUY:
            price_movement = ((pos.price_current - pos.price_open) / pos.price_open) * 100
        else:
            price_movement = ((pos.price_open - pos.price_current) / pos.price_open) * 100
        
        if current_pnl_pct < -0.6:
            if price_movement < -0.2:
                return True, "Emergency_RapidLoss"
        
        if peak_pnl_pct > 0.4:
            if current_pnl_pct < peak_pnl_pct * -0.25:
                return True, "ProfitReversed"
        
        return False, ""
    
    def _should_trail_exit(self, pos) -> tuple[bool, str]:
        entry = pos.price_open
        current = pos.price_current
        tp = pos.tp

        if tp == 0:
            return False, ""

        if pos.type == mt5.POSITION_TYPE_BUY:
            progress = (current - entry) / (tp - entry)
            points_profit = self._price_to_points(current - entry)
        else:
            progress = (entry - current) / (entry - tp)
            points_profit = self._price_to_points(entry - current)

        progress = max(0.0, min(progress, 1.2))

        cache = self._position_cache.setdefault(pos.ticket, {})
        max_points = cache.get("max_points", points_profit)
        max_progress = cache.get("max_progress", progress)

        if points_profit > max_points:
            cache["max_points"] = points_profit
            max_points = points_profit

        if progress > max_progress:
            cache["max_progress"] = progress
            max_progress = progress

        points_retrace = max_points - points_profit

        entry_time = self._position_cache[pos.ticket].get("entry_time")
        if entry_time:
            age_min = (self._get_uk_time() - entry_time).total_seconds() / 60

            if age_min >= self.time_decay_minutes:
                # For XAUUSD on Vantage: 1 point == 0.01, so 150 points == $1.50 move.
                if points_profit >= 150:
                    return True, "TimeDecay"

        # Trailing thresholds expressed in POINTS (not FX pips).
        if max_points >= 800 and points_retrace >= 150:
            return True, "Trail_800pts"
        if max_points >= 500 and points_retrace >= 120:
            return True, "Trail_500pts"
        if max_points >= 300 and points_retrace >= 100:
            return True, "Trail_300pts"
        if max_points >= 200 and points_retrace >= 80:
            return True, "Trail_200pts"

        return False, ""
    
    def _log_closed_trade(self, deal):
        if deal.position in self._logged_positions:
            return

        self._logged_positions.add(deal.position)
        file_exists = os.path.isfile(self.journal_file)

        with open(self.journal_file, "a", newline="") as f:
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow([
                    "date",
                    "time",
                    "symbol",
                    "direction",
                    "entry_price",
                    "stop_loss",
                    "take_profit",
                    "exit_price",
                    "profit",
                    "result",
                    "position_id"
                ])

            writer.writerow([
                datetime.fromtimestamp(deal.time, tz=self.uk_tz).date().isoformat(),
                datetime.fromtimestamp(deal.time, tz=self.uk_tz).time().strftime("%H:%M:%S"),
                deal.symbol,
                "BUY" if deal.type == mt5.DEAL_TYPE_SELL else "SELL",
                deal.price_position,
                deal.sl,
                deal.tp,
                deal.price,
                round(deal.profit, 2),
                "WIN" if deal.profit > 0 else "LOSS",
                deal.position
            ])

    def _sync_deals_to_state(self):
        """Process new closed deals and update state"""
        try:
            uk_now = self._get_uk_time()
            
            # Get start of current trading day (8am logic)
            if uk_now.hour >= 8:
                today_start = uk_now.replace(hour=8, minute=0, second=0, microsecond=0)
            else:
                today_start = (uk_now - timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            
            # Get all deals since 8am today
            history = mt5.history_deals_get(
                from_date=today_start,
                to_date=uk_now
            )
            
            if not history:
                return
            
            # Reset tracking - recalculate from scratch each time
            daily_profit = 0.0
            daily_trades = 0
            processed_positions = set()
            last_deal_time = None
            last_deal_result = None
            
            # Process all deals for today
            for deal in history:
                # Only count our bot's deals
                if deal.magic != self.magic:
                    continue
                
                # Only count exit deals (not entries)
                if deal.entry == mt5.DEAL_ENTRY_OUT:
                     # Avoid double-counting the same position
                    if deal.position in processed_positions:
                        continue

                    processed_positions.add(deal.position)

                    # NEW: journal the trade (permanent, once ever)
                    self._log_closed_trade(deal)

                    # Accumulate profit
                    daily_profit += deal.profit

                    # Track last result for cooldown logic
                    if deal.profit > 0:
                        last_deal_result = "win"
                    elif deal.profit < 0:
                        last_deal_result = "loss"

                    daily_trades += 1

                    # Track the most recent deal time
                    deal_time = datetime.fromtimestamp(deal.time, tz=self.uk_tz)
                    if last_deal_time is None or deal_time > last_deal_time:
                        last_deal_time = deal_time

            
            # Update state with recalculated values
            self.state['profit'] = daily_profit
            self.state['daily_trades'] = daily_trades
            
            # Update last trade time and result ONLY if we found deals
            if last_deal_time:
                self.state['last_trade_time'] = last_deal_time.isoformat()
                self.state['last_result'] = last_deal_result
            
            # Store for easy access
            self.state['day_pnl'] = daily_profit
            if self.state['starting_balance'] > 0:
                self.state['day_pnl_pct'] = (daily_profit / self.state['starting_balance']) * 100
            else:
                self.state['day_pnl_pct'] = 0
            # No JSON persistence by design
            
        except Exception as e:
            print(f"Error syncing deals: {e}")
            import traceback
            traceback.print_exc()
    
    def _monitor_positions(self):
        """Monitor and manage open positions"""
        try:
            positions = mt5.positions_get(symbol=self.symbol, magic=self.magic)
            
            if positions:
                for pos in positions:
                    # Calculate P&L percentage
                    if self.state['starting_balance'] > 0:
                        pnl_pct = (pos.profit / self.state['starting_balance']) * 100
                    else:
                        pnl_pct = 0
                    
                    # Initialize position cache
                    if pos.ticket not in self._position_cache:
                        self._position_cache[pos.ticket] = {
                            "peak_pnl_pct": pnl_pct,
                            "max_progress": 0.0,
                            "entry_time": self._get_uk_time()
                        }

                    
                    # Update peak
                    peak_pnl_pct = self._position_cache[pos.ticket]["peak_pnl_pct"]
                    if pnl_pct > peak_pnl_pct:
                        self._position_cache[pos.ticket]["peak_pnl_pct"] = pnl_pct
                        peak_pnl_pct = pnl_pct
                    
                    # Check exit conditions
                    should_emergency, emergency_reason = self._should_emergency_exit(pos, pnl_pct, peak_pnl_pct)
                    if should_emergency:
                        self._close_position(pos, emergency_reason)
                        continue
                    
                    should_trail, trail_reason = self._should_trail_exit(pos)
                    if should_trail:
                        self._close_position(pos, trail_reason)
                        continue
            
            # Sync deals to update W/L stats
            self._sync_deals_to_state()
        
        except Exception as e:
            print(f"Error monitoring positions: {e}")
    
    def _close_position(self, pos, reason: str):
        """Close a position"""
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
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                # Clean up cache immediately
                if pos.ticket in self._position_cache:
                    del self._position_cache[pos.ticket]
        
        except Exception as e:
            print(f"Error closing position: {e}")
    
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
            output.append(f"GOLD TRADING BOT INITIALIZED - {uk_now.strftime('%H:%M:%S %A')}".center(70))
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

                    pnl_pct = 0
                    if self.state['starting_balance'] > 0:
                        pnl_pct = (pos.profit / self.state['starting_balance']) * 100

                    peak_pnl = 0
                    if pos.ticket in self._position_cache:
                        peak_pnl = self._position_cache[pos.ticket].get("peak_pnl_pct", 0)

                    status_icon = "🟢" if pnl_pct > 0 else "🟡" if pnl_pct > -0.3 else "🔴"

                    output.append(f"#{pos.ticket} │ {pos_type} {pos.volume} lots │ {status_icon}")
                    output.append(f"Entry: ${pos.price_open:.2f} → Current: ${pos.price_current:.2f}")
                    progress = 0.0
                    peak_progress = 0.0

                    if pos.tp != 0:
                        if pos.type == mt5.POSITION_TYPE_BUY:
                            progress = (pos.price_current - pos.price_open) / (pos.tp - pos.price_open)
                        else:
                            progress = (pos.price_open - pos.price_current) / (pos.price_open - pos.tp)

                        progress = max(0.0, min(progress, 1.2))

                        if pos.ticket in self._position_cache:
                            peak_progress = self._position_cache[pos.ticket].get("max_progress", 0.0)

                    output.append(
                        f"P/L: £{pos.profit:+.2f} "
                        f"({progress:+.2%} TP) │ Peak: {peak_progress:+.2%}"
                    )

            else:
                if not self._can_trade():
                    try:
                        last_trade = datetime.fromisoformat(self.state["last_trade_time"])
                        # Convert to UK timezone if not already
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
                    if market_status == "ACTIVE":
                        output.append(f"\nStatus   │ SCANNING FOR SIGNALS...")
                        
                        # Show daily stats
                        if self.state['daily_trades'] > 0:
                            output.append(f"Daily    │ Trades: {self.state['daily_trades']}/{self.max_daily_trades} │ P/L: £{self.state['day_pnl']:+.2f} ({self.state['day_pnl_pct']:+.2f}%)")
                        
                        # Show cooldown if active
                        if not self._can_trade():
                            try:
                                last_trade = datetime.fromisoformat(self.state["last_trade_time"])
                                if last_trade.tzinfo is None:
                                    last_trade = self.uk_tz.localize(last_trade)
                                elapsed = (self._get_uk_time() - last_trade).total_seconds()
                                cooldown = self.loss_cooldown if self.state.get("last_result") == "loss" else self.win_cooldown
                                remaining = max(0, int(cooldown - elapsed))
                                if remaining > 0:
                                    output.append(f"Cooldown │ {remaining}s remaining ({self.state.get('last_result', 'unknown').upper()})")
                            except:
                                pass

                        if self.debug_signal_lines:
                            output.append(f"\n{'─'*70}")
                            for line in self.debug_signal_lines:
                                output.append(line)

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
            symbol_info = mt5.symbol_info(self.symbol)
        
        acc = mt5.account_info()
        if not acc:
            print("Failed to get account info")
            mt5.shutdown()
            return

        # One-time broker/symbol diagnostics (helps tune risk sizing for your broker)
        try:
            info = mt5.symbol_info(self.symbol)
            print("\n" + "-" * 70)
            print(f"Broker diagnostics for {self.symbol}")
            print(f"Server/Currency │ {getattr(acc, 'server', '?')} │ {getattr(acc, 'currency', '?')}")
            if info:
                print(
                    "Tick/Trade │ "
                    f"tick_size={getattr(info, 'trade_tick_size', None)} │ "
                    f"tick_value={getattr(info, 'trade_tick_value', None)} │ "
                    f"contract_size={getattr(info, 'trade_contract_size', None)}"
                )
                print(
                    "Volume     │ "
                    f"min={getattr(info, 'volume_min', None)} │ "
                    f"step={getattr(info, 'volume_step', None)} │ "
                    f"max={getattr(info, 'volume_max', None)}"
                )
            print("-" * 70 + "\n")
        except Exception as _e:
            pass
        
        if acc.equity < 50:
            print("\n" + "="*70)
            print("WARNING: Account equity below £50 minimum recommended")
            print("Bot will continue but will aggressively downscale risk and may skip trades due to min lot risk.")
            print("="*70)
        
        if self.state["starting_balance"] == 0:
            self.state["starting_balance"] = acc.equity
        
        print("\n" + "="*70)
        print("GOLD TRADING BOT INITIALIZED".center(70))
        print("="*70)
        print(f"\nStarting Balance: £{self.state['starting_balance']:,.2f}")
        print(f"Daily Target: {self.daily_profit_target}% | Max Drawdown: {self.max_drawdown}%")
        print(f"Risk: {self.base_risk_pct}-{self.max_risk_pct}% per trade | Max Lot: {self.max_lot}")
        print(f"Minimum Score Required: 4.5 (Active Trading Mode)")
        print(f"Anti-Late Entry: Enabled (No chasing!)")
        print("\nStarting in 3 seconds...\n")
        time_module.sleep(3)
        
        last_print = datetime.now()
        
        while True:
            try:
                # Reset daily stats if new day
                self._reset_daily_stats()

                self._sync_deals_to_state()
                
                # Check if market is open
                if not self._is_market_open():
                    if (datetime.now() - last_print).total_seconds() >= 10:
                        self._print_status()
                        last_print = datetime.now()
                    time_module.sleep(5)
                    continue
                
                # Monitor existing positions
                self._monitor_positions()
                
                # Check daily limits
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
                
                # Check if position already open
                positions = mt5.positions_get(symbol=self.symbol, magic=self.magic)
                has_positions = positions and len(positions) > 0
                
                if has_positions:
                    if (datetime.now() - last_print).total_seconds() >= 1.5:
                        self._print_status()
                        last_print = datetime.now()
                    time_module.sleep(0.5)
                    continue
                
                # Print status periodically
                if (datetime.now() - last_print).total_seconds() >= 10:
                    self._print_status()
                    last_print = datetime.now()
                
                # Check cooldown
                if not self._can_trade():
                    time_module.sleep(2)
                    continue
                
                # Get market data
                df = self._get_market_data()
                if df is None:
                    time_module.sleep(5)
                    continue
                
                # Analyze for signal
                signal = self._analyze_signal(df)
                if signal:
                    self._place_trade(signal)
                    time_module.sleep(2)
                else:
                    # Enhanced diagnostics when no signal
                    self._debug_signal_state(df)
                    # Also log why signal was rejected
                    self._log_signal_rejection_reason(df)
                    time_module.sleep(3)

                
            except KeyboardInterrupt:
                print("\n\nShutting down bot...\n")
                break
            except Exception as e:
                print(f"\nError in main loop: {str(e)}")
                import traceback
                traceback.print_exc()
                time_module.sleep(10)
        
        mt5.shutdown()

if __name__ == "__main__":
    GoldBot().run()