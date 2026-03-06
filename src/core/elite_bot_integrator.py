"""
Elite AI Bot Integrator
Integrates elite AI modules into the trading bot
"""
import logging
import os
import numpy as np
from typing import Dict, Optional
from mi.advanced_risk_manager import AdvancedRiskManager
from mi.market_regime_detector import MarketRegimeDetector
from mi.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from mi.elite_position_manager import ElitePositionManager

logger = logging.getLogger(__name__)


class EliteBotIntegrator:
    """Integrates elite AI features into the trading bot"""

    def __init__(self, exchange, config):
        """Initialize elite modules if enabled in config"""
        self.config = config
        self.exchange = exchange

        # Initialize elite modules based on config
        self.elite_risk_mgr = None
        self.regime_detector = None
        self.mtf_analyzer = None
        self.elite_position_mgr = None

        # Check which features are enabled
        self.enable_elite_risk = os.getenv(
            'ENABLE_ELITE_RISK_MANAGEMENT',
            'false').lower() == 'true'
        self.enable_regime = os.getenv('ENABLE_REGIME_DETECTION', 'false').lower() == 'true'
        self.enable_mtf = os.getenv('ENABLE_MTF_ANALYSIS', 'false').lower() == 'true'
        self.enable_elite_pos = os.getenv('ENABLE_ELITE_POSITION_MGMT', 'false').lower() == 'true'

        self._initialize_modules()

    def _initialize_modules(self):
        """Initialize enabled elite modules"""
        if self.enable_elite_risk:
            logger.info("🚀 Elite Risk Management ENABLED - Kelly Criterion + Volatility Sizing")
            risk_config = {
                'USE_KELLY_CRITERION': os.getenv(
                    'USE_KELLY_CRITERION', 'true').lower() == 'true', 'KELLY_FRACTION': float(
                    os.getenv(
                        'KELLY_FRACTION', '0.25')), 'USE_VOLATILITY_SIZING': os.getenv(
                    'USE_VOLATILITY_SIZING', 'true').lower() == 'true', 'RISK_PER_TRADE_PCT': float(
                        os.getenv(
                            'RISK_PER_TRADE_PCT', '1.0')), 'MAX_PORTFOLIO_HEAT_PCT': float(
                                os.getenv(
                                    'MAX_PORTFOLIO_HEAT_PCT', '6.0'))}
            self.elite_risk_mgr = AdvancedRiskManager(risk_config)

        if self.enable_regime:
            logger.info("🎯 Regime Detection ENABLED - 7 Market Regimes + Adaptive Strategies")
            regime_config = {
                'ADX_STRONG_TREND': float(os.getenv('ADX_STRONG_TREND', '40')),
                'ADX_WEAK_TREND': float(os.getenv('ADX_WEAK_TREND', '25')),
                'VOLATILITY_HIGH_THRESHOLD': float(os.getenv('VOLATILITY_HIGH_THRESHOLD', '3.0'))
            }
            self.regime_detector = MarketRegimeDetector(regime_config)

        if self.enable_mtf:
            logger.info("📊 MTF Analysis ENABLED - Multi-Timeframe Trend Confirmation")
            mtf_config = {
                'ANALYSIS_TIMEFRAMES': os.getenv('ANALYSIS_TIMEFRAMES', '1h,4h,1d').split(',')
            }
            self.mtf_analyzer = MultiTimeframeAnalyzer(mtf_config)

        if self.enable_elite_pos:
            logger.info("⚡ Elite Position Management ENABLED - Trailing Stops + Partial TPs")
            pos_config = {
                'USE_TRAILING_STOP': os.getenv(
                    'USE_TRAILING_STOP', 'true').lower() == 'true', 'TRAILING_STOP_ACTIVATION_PCT': float(
                    os.getenv(
                        'TRAILING_STOP_ACTIVATION_PCT', '2.0')), 'USE_PARTIAL_TP': os.getenv(
                    'USE_PARTIAL_TP', 'true').lower() == 'true', 'PARTIAL_TP_LEVELS': os.getenv(
                        'PARTIAL_TP_LEVELS', '1.5:0.33,3.0:0.33')}
            self.elite_position_mgr = ElitePositionManager(pos_config)

    def calculate_position_size(self, symbol: str, base_size: float, confidence: float,
                                win_rate: float, balance: float, price: float) -> float:
        """
        Calculate position size using elite risk management

        Args:
            symbol: Trading symbol
            base_size: Base position size from standard calculation
            confidence: Signal confidence (0-100)
            win_rate: Historical win rate (0-1)
            balance: Account balance
            price: Current price

        Returns:
            Adjusted position size
        """
        if not self.enable_elite_risk or not self.elite_risk_mgr:
            return base_size

        try:
            # Get market data for volatility calculation
            candles = self.exchange.get_klines(symbol, '1h', limit=100)

            # Calculate elite position size
            elite_size = self.elite_risk_mgr.calculate_position_size(
                symbol=symbol,
                balance=balance,
                price=price,
                win_rate=win_rate,
                avg_win=1.5,  # Placeholder - should come from performance tracker
                avg_loss=1.0,  # Placeholder
                candles=candles,
                confidence=confidence / 100.0
            )

            logger.info(f"✅ Elite Risk Management: Base={base_size:.6f} → Elite={elite_size:.6f} "
                        f"(Kelly + Volatility + Performance)")

            return elite_size

        except Exception as e:
            logger.error(f"❌ Elite risk calculation failed: {e}")
            return base_size

    def detect_market_regime(self, symbol: str) -> Optional[Dict]:
        """
        Detect current market regime

        Returns:
            Dict with regime info: {regime, strength, recommended_strategy}
        """
        if not self.enable_regime or not self.regime_detector:
            return None

        try:
            # Fetch multiple timeframes for regime detection
            candles_1h = self.exchange.get_klines(symbol, '1h', limit=100)

            # Extract close prices from candles and convert to float64
            prices = np.array([float(c[4]) for c in candles_1h], dtype=np.float64)  # Close prices

            # Detect regime using prices
            regime_info = self.regime_detector.detect_regime(prices)

            logger.info(f"📈 Regime Detection for {symbol}: {regime_info.get('regime', 'UNKNOWN')} "
                        f"(Confidence: {regime_info.get('confidence', 0):.2f})")

            return regime_info

        except Exception as e:
            logger.error(f"❌ Regime detection failed: {e}")
            return None

    def validate_with_mtf(self, symbol: str, signal_direction: str):
        """
        Validate signal using multi-timeframe analysis

        Args:
            symbol: Trading symbol
            signal_direction: 'long' or 'short'

        Returns:
            Tuple of (bool, dict): (confirmed, mtf_analysis)
        """
        if not self.enable_mtf or not self.mtf_analyzer:
            return True, None  # If MTF disabled, allow all signals

        try:
            # Fetch data for multiple timeframes
            data_by_tf = {}
            for tf in self.mtf_analyzer.timeframes:
                try:
                    candles = self.exchange.get_klines(symbol, tf, limit=100)
                    if candles and len(candles) > 0:
                        prices = np.array([float(c[4]) for c in candles],
                                          dtype=np.float64)  # Close prices
                        data_by_tf[tf] = {'prices': prices}
                except Exception as e:
                    logger.warning(f"⚠️ Could not fetch {tf} data for {symbol}: {e}")

            if not data_by_tf:
                logger.warning(f"⚠️ MTF Analysis unavailable for {symbol}, allowing signal")
                return True, None

            # Analyze timeframes
            mtf_analysis = self.mtf_analyzer.analyze_timeframes(symbol, data_by_tf)

            # Check trend alignment
            trend_alignment = mtf_analysis.get('trend_alignment', 0)
            recommendation = mtf_analysis.get('recommendation', 'NEUTRAL')

            # For long signals, need bullish recommendation; for short, bearish
            if signal_direction.lower() == 'long':
                confirmed = recommendation == 'BULLISH' or trend_alignment > 0.5
            else:
                confirmed = recommendation == 'BEARISH' or trend_alignment < -0.5

            if confirmed:
                logger.info(
                    f"✅ MTF Analysis CONFIRMS {signal_direction.upper()} signal for {symbol} "
                    f"(Alignment: {trend_alignment:.2f}, Recommendation: {recommendation})")
            else:
                logger.warning(
                    f"❌ MTF Analysis REJECTS {signal_direction.upper()} signal for {symbol} "
                    f"(Alignment: {trend_alignment:.2f}, Recommendation: {recommendation})")

            return confirmed, mtf_analysis

        except Exception as e:
            logger.error(f"❌ MTF analysis failed: {e}")
            return True, None  # On error, allow signal (fail-safe)

    def update_position_management(self, symbol: str, position: Dict,
                                   current_price: float) -> Optional[Dict]:
        """
        Update position with elite management (trailing stops, partial TPs)

        Args:
            symbol: Trading symbol
            position: Position dict with entry_price, size, side/direction
            current_price: Current market price

        Returns:
            Dict with updated stop_loss and take_profit levels, or None if no update
        """
        if not self.enable_elite_pos or not self.elite_position_mgr:
            return None

        try:
            # Normalize position dict
            pos_data = {
                'entry_price': position.get('entry_price'),
                'direction': position.get('side', position.get('direction', 'LONG')).upper(),
                'stop_loss': position.get('stop_loss', 0),
                'size': position.get('size', 0),
                'partial_tp_taken': position.get('partial_tp_taken', [])
            }

            updates = {}
            actions = []

            # Check for trailing stop update
            new_stop = self.elite_position_mgr.update_trailing_stop(pos_data, current_price)
            if new_stop:
                updates['stop_loss'] = new_stop
                actions.append('TRAILING_STOP')

            # Check for breakeven move
            if self.elite_position_mgr.should_move_to_breakeven(pos_data, current_price):
                updates['stop_loss'] = pos_data['entry_price']
                actions.append('MOVE_TO_BREAKEVEN')

            # Check for partial take profit
            partial_tp = self.elite_position_mgr.check_partial_take_profit(pos_data, current_price)
            if partial_tp:
                updates['partial_close'] = partial_tp
                actions.append('PARTIAL_TP')

            if updates:
                updates['action'] = ','.join(actions) if actions else 'HOLD'
                logger.info(
                    f"🎯 Advanced Position Management for {symbol}: "
                    f"Actions={updates.get('action')} "
                    f"SL={updates.get('stop_loss', 'N/A')} "
                    f"Partial={partial_tp.get('close_percentage', 0) * 100 if partial_tp else 0}%")
                return updates

            return None

        except Exception as e:
            logger.error(f"❌ Elite position management failed: {e}", exc_info=True)
            return None

    def get_regime_adjusted_params(self, regime_info: Optional[Dict]) -> Dict:
        """
        Get trading parameters adjusted for current market regime

        Returns:
            Dict with adjusted parameters
        """
        if not regime_info:
            return {}

        regime = regime_info['regime']
        adjustments = {}

        # Adjust based on regime
        if regime == 'strong_trending':
            adjustments['position_size_multiplier'] = 1.2
            adjustments['stop_loss_atr_multiplier'] = 2.0
            adjustments['min_confidence'] = 60
        elif regime == 'weak_trending':
            adjustments['position_size_multiplier'] = 1.0
            adjustments['stop_loss_atr_multiplier'] = 1.5
            adjustments['min_confidence'] = 65
        elif regime == 'ranging':
            adjustments['position_size_multiplier'] = 0.8
            adjustments['stop_loss_atr_multiplier'] = 1.0
            adjustments['min_confidence'] = 70
        elif regime == 'volatile':
            adjustments['position_size_multiplier'] = 0.6
            adjustments['stop_loss_atr_multiplier'] = 2.5
            adjustments['min_confidence'] = 75
        elif regime == 'choppy':
            adjustments['position_size_multiplier'] = 0.5
            adjustments['stop_loss_atr_multiplier'] = 1.5
            adjustments['min_confidence'] = 80
        else:  # low_volatility or unknown
            adjustments['position_size_multiplier'] = 0.7
            adjustments['stop_loss_atr_multiplier'] = 1.2
            adjustments['min_confidence'] = 70

        logger.info(f"🔧 Regime-Based Adjustments: {adjustments}")
        return adjustments

    def is_active(self) -> bool:
        """Check if any elite features are active"""
        return any([
            self.enable_elite_risk,
            self.enable_regime,
            self.enable_mtf,
            self.enable_elite_pos
        ])

    def get_status_summary(self) -> str:
        """Get summary of active elite features"""
        features = []
        if self.enable_elite_risk:
            features.append("Elite Risk Mgmt")
        if self.enable_regime:
            features.append("Regime Detection")
        if self.enable_mtf:
            features.append("MTF Analysis")
        if self.enable_elite_pos:
            features.append("Elite Position Mgmt")

        if not features:
            return "No elite features active"

        return f"Active: {', '.join(features)}"
