"""
Signal predictor using classical trading strategies
"""
import logging
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from classic_strategy import ClassicTradingStrategy

logger = logging.getLogger(__name__)


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"


@dataclass
class TradingSignal:
    """Structured trading signal"""
    symbol: str
    signal_type: SignalType
    confidence: float
    price: float
    indicators: Dict[str, float]
    conditions: Dict[str, bool]
    timestamp: pd.Timestamp
    position_size: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'signal': self.signal_type.value,
            'confidence': self.confidence,
            'price': self.price,
            'indicators': self.indicators,
            'conditions': self.conditions,
            'timestamp': self.timestamp.isoformat(),
            'position_size': self.position_size,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit
        }


class HybridPredictor:
    """
    Main predictor combining multiple strategies and timeframes
    """

    def __init__(self, config):
        self.config = config
        self.strategies = {}
        self.initialize_strategies()

    def initialize_strategies(self):
        """Initialize all trading strategies"""
        # Classical strategy
        if self.config.trading.strategy == 'classic_macd_rsi':
            self.strategies['classic'] = ClassicTradingStrategy(self.config)
            logger.info("Initialized Classic MACD+RSI strategy")

        # Add more strategies here as needed
        # if 'momentum' in self.config.trading.strategies:
        #     self.strategies['momentum'] = MomentumStrategy(self.config)

    async def analyze_symbol(
            self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[TradingSignal]:
        """
        Analyze a single symbol across multiple timeframes

        Args:
            symbol: Trading symbol
            data: Dictionary with timeframe -> DataFrame mappings

        Returns:
            TradingSignal or None
        """
        try:
            primary_tf = self.config.trading.timeframes.primary
            secondary_tf = self.config.trading.timeframes.secondary

            if primary_tf not in data or data[primary_tf] is None:
                logger.warning(f"No {primary_tf} data for {symbol}")
                return None

            # Get current price
            current_price = data[primary_tf]['close'].iloc[-1]

            # Analyze with primary strategy
            primary_analysis = self.strategies['classic'].analyze_market(data[primary_tf])

            # Check secondary timeframe for confirmation
            confirmation = None
            if secondary_tf in data and data[secondary_tf] is not None:
                secondary_analysis = self.strategies['classic'].analyze_market(data[secondary_tf])
                confirmation = secondary_analysis

            # Combine analyses
            signal = self._combine_analyses(
                symbol=symbol,
                primary=primary_analysis,
                secondary=confirmation,
                price=current_price
            )

            # Apply filters
            if signal and signal.signal_type != SignalType.HOLD:
                if not self._passes_filters(signal, data[primary_tf]):
                    logger.info(f"{symbol} failed filters, changing to HOLD")
                    signal.signal_type = SignalType.HOLD
                    signal.confidence = 0.0

            return signal

        except Exception as e:
            logger.error(f"Analysis failed for {symbol}: {e}")
            return None

    def _combine_analyses(self, symbol: str, primary: Dict,
                          secondary: Optional[Dict], price: float) -> Optional[TradingSignal]:
        """
        Combine analyses from different timeframes
        """
        if primary['signal'] == 'HOLD':
            return TradingSignal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0,
                price=price,
                indicators=primary['indicators'],
                conditions=primary['conditions'],
                timestamp=pd.Timestamp.now()
            )

        # Determine final signal
        signal_type = SignalType[primary['signal']]
        confidence = primary['confidence']

        # Adjust confidence based on secondary timeframe
        if secondary and secondary['signal'] == primary['signal']:
            confidence = min(0.95, confidence * 1.2)  # Boost confidence
        elif secondary and secondary['signal'] != 'HOLD':
            # Conflicting signals - reduce confidence
            confidence = max(0.3, confidence * 0.7)

        return TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            confidence=round(confidence, 3),
            price=price,
            indicators=primary['indicators'],
            conditions=primary['conditions'],
            timestamp=pd.Timestamp.now()
        )

    def _passes_filters(self, signal: TradingSignal, data: pd.DataFrame) -> bool:
        """
        Apply additional filters to signals
        """
        try:
            filters = self.config.trading.filters

            # Price filter
            if signal.price < filters.min_price:
                logger.debug(f"Price {signal.price} below minimum {filters.min_price}")
                return False

            # Volume filter (check recent volume)
            recent_volume = data['volume'].tail(20).mean()
            min_volume = filters.min_24h_volume / 24  # Approx hourly minimum

            if recent_volume < min_volume:
                logger.debug(f"Volume {recent_volume:.2f} below minimum {min_volume:.2f}")
                return False

            # Volatility filter (using ATR)
            if 'atr_percent' in signal.indicators:
                min_volatility = self.config.trading.strategies.classic_macd_rsi.min_atr_pct
                if signal.indicators['atr_percent'] < min_volatility:
                    logger.debug(
                        f"Volatility {signal.indicators['atr_percent']}% below minimum {min_volatility}%")
                    return False

            # Trend strength filter
            if 'ema20' in signal.indicators and 'ema50' in signal.indicators:
                trend_strength = abs(
                    signal.indicators['ema20'] - signal.indicators['ema50']) / signal.price
                if trend_strength < 0.005:  # Less than 0.5% difference
                    logger.debug(f"Trend too weak: {trend_strength:.4f}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Filter check failed: {e}")
            return False

    async def analyze(self, market_data: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        Analyze all symbols

        Args:
            market_data: Dictionary of symbol -> DataFrame

        Returns:
            List of trading signals
        """
        logger.info(f"Analyzing {len(market_data)} symbols...")

        signals = []
        for symbol, data in market_data.items():
            try:
                # Ensure we have data for required timeframes
                if not isinstance(data, dict):
                    # Single timeframe, convert to dict
                    data_dict = {self.config.trading.timeframes.primary: data}
                else:
                    data_dict = data

                signal = await self.analyze_symbol(symbol, data_dict)

                if signal:
                    signals.append(signal.to_dict())

                    # Log strong signals
                    if signal.confidence > 0.7:
                        logger.info(
                            f"STRONG {signal.signal_type.value} for {symbol} "
                            f"(confidence: {signal.confidence:.2f}, "
                            f"price: {signal.price:.2f})"
                        )

            except Exception as e:
                logger.error(f"Failed to analyze {symbol}: {e}")

        # Sort by confidence (descending)
        signals.sort(key=lambda x: x['confidence'], reverse=True)

        logger.info(
            f"Generated {len([s for s in signals if s['signal'] != 'HOLD'])} trading signals")
        return signals

    def calculate_risk_adjusted_position(self, signal: Dict, balance: float) -> Dict:
        """
        Calculate position size with risk adjustment
        """
        self.config.trading.strategies.classic_macd_rsi

        # Base position size from strategy
        if 'position_size' in signal:
            base_size = signal['position_size']
        else:
            base_size = balance * 0.02  # Default 2%

        # Adjust for confidence
        confidence_multiplier = signal['confidence'] ** 2
        adjusted_size = base_size * confidence_multiplier

        # Apply maximum position limit
        max_position = balance * (self.config.trading.risk.max_position_pct / 100)
        final_size = min(adjusted_size, max_position)

        # Calculate stop loss and take profit
        stop_loss_pct = self.config.trading.risk.stop_loss_pct / 100
        take_profit_pct = self.config.trading.risk.take_profit_pct / 100

        if signal['signal'] == 'BUY':
            stop_loss = signal['price'] * (1 - stop_loss_pct)
            take_profit = signal['price'] * (1 + take_profit_pct)
        else:  # SELL
            stop_loss = signal['price'] * (1 + stop_loss_pct)
            take_profit = signal['price'] * (1 - take_profit_pct)

        return {
            'size': round(final_size, 8),
            'value': round(final_size * signal['price'], 2),
            'stop_loss': round(stop_loss, 8),
            'take_profit': round(take_profit, 8),
            'risk_amount': round(final_size * abs(signal['price'] - stop_loss), 2),
            'potential_reward': round(final_size * abs(take_profit - signal['price']), 2),
            'risk_reward_ratio': take_profit_pct / stop_loss_pct
        }
