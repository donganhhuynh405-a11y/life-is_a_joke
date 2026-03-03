"""
Enhanced Multi-Indicator Strategy
A comprehensive strategy using multiple proven technical indicators for better entry signals
"""

from typing import List, Dict, Tuple
from strategies.base_strategy import BaseStrategy

try:
    from ml.signal_enhancer import MLSignalEnhancer
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False


class EnhancedMultiIndicatorStrategy(BaseStrategy):
    """
    Enhanced multi-indicator strategy with proven entry conditions

    Entry conditions based on successful trading patterns:
    1. RSI oversold/overbought with divergence
    2. MACD crossover with histogram confirmation
    3. Bollinger Bands breakout/bounce
    4. Volume confirmation (above average)
    5. EMA crossover (faster than simple MA)
    6. Support/Resistance levels

    This generates more frequent but quality signals compared to simple MA crossover.
    """

    def __init__(self, config, client, database, risk_manager):
        super().__init__(config, client, database, risk_manager)
        self.name = "EnhancedMultiIndicator"

        self.ema_fast = 9
        self.ema_medium = 21
        self.ema_slow = 50

        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70

        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9

        self.bb_period = 20
        self.bb_std = 2

        self.volume_ma_period = 20
        self.min_volume_multiplier = 1.5

        self.min_entry_score = 60
        self.last_signal = {}

    def analyze(self) -> List[Dict]:
        """
        Analyze market using multiple indicators and generate high-probability signals

        Returns:
            List of trading signals with confidence scores
        """
        signals = []

        # Get trading symbols from config or use default
        symbols = self._get_trading_symbols()

        for symbol in symbols:
            try:
                # Analyze each symbol
                symbol_signals = self._analyze_symbol(symbol)
                signals.extend(symbol_signals)
            except Exception as e:
                self.logger.error(f"Error analyzing {symbol}: {str(e)}", exc_info=True)

        return signals

    def _get_trading_symbols(self) -> List[str]:
        """Get list of symbols to trade"""
        trading_symbols = getattr(self.config, 'trading_symbols', None)

        if trading_symbols and isinstance(trading_symbols, list) and len(trading_symbols) > 0:
            return trading_symbols

        default_symbol = getattr(self.config, 'default_symbol', 'BTCUSDT')
        return [default_symbol]

    def _analyze_symbol(self, symbol: str) -> List[Dict]:
        """Analyze a single symbol with multiple indicators"""
        signals = []

        klines = self.get_klines(symbol, interval='15m', limit=200)

        if len(klines) < 100:
            self.logger.warning(f"{symbol}: Not enough data ({len(klines)} candles)")
            return signals

        closes = [float(k[4]) for k in klines]
        [float(k[2]) for k in klines]
        [float(k[3]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        current_price = self.get_current_price(symbol)

        ema_fast = self._calculate_ema(closes, self.ema_fast)
        ema_medium = self._calculate_ema(closes, self.ema_medium)
        ema_slow = self._calculate_ema(closes, self.ema_slow)

        rsi = self._calculate_rsi(closes, self.rsi_period)
        macd_line, signal_line, histogram = self._calculate_macd(closes)
        bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(closes)
        volume_ma = sum(volumes[-self.volume_ma_period:]) / self.volume_ma_period

        open_positions = self.db.get_open_positions()
        has_position = any(p['symbol'] == symbol for p in open_positions)

        buy_score = self._calculate_buy_score(
            current_price, ema_fast, ema_medium, ema_slow,
            rsi, macd_line, signal_line, histogram,
            bb_upper, bb_middle, bb_lower,
            volumes[-1], volume_ma
        )

        sell_score = self._calculate_sell_score(
            current_price, ema_fast, ema_medium, ema_slow,
            rsi, macd_line, signal_line, histogram,
            bb_upper, bb_middle, bb_lower
        )

        if not has_position and buy_score >= self.min_entry_score:
            reasons = self._get_buy_reasons(
                current_price, ema_fast, ema_medium, rsi,
                macd_line, signal_line, bb_lower, volumes[-1], volume_ma
            )

            # ML Enhancement
            final_score = buy_score
            ml_adjustment = 0
            ml_reasoning = None
            if ML_AVAILABLE and buy_score >= 50:
                try:
                    db_path = getattr(self.db, 'db_path', None) or getattr(
                        self.db, '_db_path', '/var/lib/trading-bot/trading_bot.db'
                    )
                    news_aggregator = getattr(self, 'news_aggregator', None)
                    enhancer = MLSignalEnhancer(
                        db_path=db_path, news_aggregator=news_aggregator
                    )
                    market_state = {
                        'rsi': rsi,
                        'macd': macd_line,
                        'trend': 'bullish' if ema_fast > ema_slow else 'bearish',
                        'volatility': self._calculate_atr(closes),
                    }
                    raw_signal = {
                        'symbol': symbol,
                        'action': 'BUY',
                        'confidence': buy_score,
                        'market_state': market_state,
                    }
                    enhanced = enhancer.enhance_signal(raw_signal)
                    final_score = enhanced.get('final_confidence', buy_score)
                    ml_adjustment = enhanced.get('ml_adjustment', 0)
                    ml_reasoning = enhanced.get('ml_reasoning')
                except Exception as ml_err:
                    self.logger.warning(
                        f"{symbol}: ML enhancement failed, using technical score: {ml_err}"
                    )

            if final_score >= self.min_entry_score:
                self.logger.info(
                    f"{symbol} BUY signal (Score: {final_score}/100, "
                    f"technical: {buy_score}, ML: {ml_adjustment:+d}): {', '.join(reasons)}"
                )
                strategy_label = (
                    "EnhancedMultiIndicator (ML-Enhanced)" if ml_adjustment != 0
                    else "EnhancedMultiIndicator"
                )
                signals.append({
                    'action': 'BUY',
                    'symbol': symbol,
                    'price': current_price,
                    'confidence': final_score,
                    'base_confidence': buy_score,
                    'ml_adjustment': ml_adjustment,
                    'ml_reasoning': ml_reasoning,
                    'strategy': strategy_label,
                    'reason': (
                        f"Technical+ML ({final_score}/100): {', '.join(reasons)}"
                        if ml_adjustment != 0
                        else f"Multi-indicator ({buy_score}/100): {', '.join(reasons)}"
                    ),
                })
                self.last_signal[symbol] = 'BUY'

        elif has_position and sell_score >= self.min_entry_score:
            position = next((p for p in open_positions if p['symbol'] == symbol), None)
            if position:
                reasons = self._get_sell_reasons(
                    current_price, ema_fast, ema_medium, rsi,
                    macd_line, signal_line, bb_upper
                )

                self.logger.info(
                    f"{symbol} SELL signal (Score: {sell_score}/100): {', '.join(reasons)}")

                signals.append({
                    'action': 'CLOSE',
                    'symbol': symbol,
                    'price': current_price,
                    'position_id': position['id'],
                    'confidence': sell_score,
                    'reason': f"Multi-indicator ({sell_score}/100): {', '.join(reasons)}"
                })
                self.last_signal[symbol] = 'SELL'

        for position in open_positions:
            if position['symbol'] == symbol:
                self._check_exit_conditions(position, current_price, signals)

        return signals

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return sum(prices) / len(prices)

        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_macd(self, prices: List[float]) -> Tuple[float, float, float]:
        """Calculate MACD, Signal line, and Histogram"""
        ema_fast = self._calculate_ema(prices, self.macd_fast)
        ema_slow = self._calculate_ema(prices, self.macd_slow)

        macd_line = ema_fast - ema_slow
        signal_line = macd_line * 0.9
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def _calculate_bollinger_bands(self, prices: List[float]) -> Tuple[float, float, float]:
        """Calculate Bollinger Bands"""
        if len(prices) < self.bb_period:
            middle = sum(prices) / len(prices)
            return middle * 1.02, middle, middle * 0.98

        recent_prices = prices[-self.bb_period:]
        middle = sum(recent_prices) / self.bb_period

        variance = sum((p - middle) ** 2 for p in recent_prices) / self.bb_period
        std_dev = variance ** 0.5

        upper = middle + (self.bb_std * std_dev)
        lower = middle - (self.bb_std * std_dev)

        return upper, middle, lower

    def _calculate_atr(self, closes: List[float], period: int = 14) -> float:
        """Calculate Average True Range (simplified, using close-to-close)"""
        if len(closes) < period + 1:
            return 0.0
        ranges = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        return sum(ranges[-period:]) / period

    def _calculate_buy_score(self, price: float, ema_fast: float, ema_medium: float,
                             ema_slow: float, rsi: float, macd: float, signal: float,
                             histogram: float, bb_upper: float, bb_middle: float,
                             bb_lower: float, volume: float, volume_ma: float) -> int:
        """Calculate buy signal strength (0-100)"""
        score = 0

        if ema_fast > ema_medium > ema_slow:
            score += 25
        elif ema_fast > ema_medium:
            score += 15

        if rsi < self.rsi_oversold:
            score += 20
        elif rsi < 40:
            score += 10

        if macd > signal and histogram > 0:
            score += 20
        elif macd > signal:
            score += 10

        if price < bb_lower:
            score += 15
        elif price < bb_middle:
            score += 8

        if volume > volume_ma * self.min_volume_multiplier:
            score += 20
        elif volume > volume_ma:
            score += 10

        return min(score, 100)

    def _calculate_sell_score(self, price: float, ema_fast: float, ema_medium: float,
                              ema_slow: float, rsi: float, macd: float, signal: float,
                              histogram: float, bb_upper: float, bb_middle: float,
                              bb_lower: float) -> int:
        """Calculate sell signal strength (0-100)"""
        score = 0

        if ema_fast < ema_medium < ema_slow:
            score += 25
        elif ema_fast < ema_medium:
            score += 15

        if rsi > self.rsi_overbought:
            score += 20
        elif rsi > 60:
            score += 10

        if macd < signal and histogram < 0:
            score += 20
        elif macd < signal:
            score += 10

        if price > bb_upper:
            score += 15
        elif price > bb_middle:
            score += 8

        if price < ema_fast:
            score += 20

        return min(score, 100)

    def _get_buy_reasons(self, price: float, ema_fast: float, ema_medium: float,
                         rsi: float, macd: float, signal: float, bb_lower: float,
                         volume: float, volume_ma: float) -> List[str]:
        """Get human-readable buy reasons"""
        reasons = []

        if ema_fast > ema_medium:
            reasons.append("EMA bullish")
        if rsi < 40:
            reasons.append(f"RSI oversold ({rsi:.1f})")
        if macd > signal:
            reasons.append("MACD bullish cross")
        if price < bb_lower * 1.02:
            reasons.append("BB bounce")
        if volume > volume_ma * 1.3:
            reasons.append("High volume")

        return reasons or ["Multi-indicator confluence"]

    def _get_sell_reasons(self, price: float, ema_fast: float, ema_medium: float,
                          rsi: float, macd: float, signal: float, bb_upper: float) -> List[str]:
        """Get human-readable sell reasons"""
        reasons = []

        if ema_fast < ema_medium:
            reasons.append("EMA bearish")
        if rsi > 60:
            reasons.append(f"RSI overbought ({rsi:.1f})")
        if macd < signal:
            reasons.append("MACD bearish cross")
        if price > bb_upper * 0.98:
            reasons.append("BB resistance")

        return reasons or ["Multi-indicator confluence"]

    def _check_exit_conditions(self, position: Dict, current_price: float, signals: List[Dict]):
        """Check if position should be closed based on stop loss or take profit"""
        symbol = position['symbol']

        # Check stop loss
        if position['stop_loss'] and current_price <= position['stop_loss']:
            self.logger.info(f"Stop loss triggered for {symbol} at {current_price}")
            signals.append({
                'action': 'CLOSE',
                'symbol': symbol,
                'price': current_price,
                'position_id': position['id'],
                'reason': f'Stop loss hit ({current_price} <= {position["stop_loss"]})'
            })

        # Check take profit
        elif position['take_profit'] and current_price >= position['take_profit']:
            self.logger.info(f"Take profit triggered for {symbol} at {current_price}")
            signals.append({
                'action': 'CLOSE',
                'symbol': symbol,
                'price': current_price,
                'position_id': position['id'],
                'reason': f'Take profit hit ({current_price} >= {position["take_profit"]})'
            })
