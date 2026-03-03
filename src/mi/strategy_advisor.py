"""
Strategy Advisor - Converts AI analysis insights into actionable strategy adjustments.
This module bridges the gap between market analysis and trading strategy adaptation.
"""

import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class StrategyAdvisor:
    """
    Analyzes market conditions and performance metrics to provide strategic recommendations.
    Uses AI-generated insights to dynamically adjust trading parameters.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Strategy Advisor.

        Args:
            config: Configuration dictionary with trading parameters
        """
        self.config = config
        self.last_adjustment = None
        self.adjustment_history = []

        # Load adaptive strategy settings
        self.enable_adaptive = config.get('ADAPTIVE_STRATEGY_ENABLED', True)
        self.min_adjustment_interval = config.get('ADAPTIVE_ADJUSTMENT_INTERVAL', 3600)  # 1 hour
        self.aggressive_mode = config.get('ADAPTIVE_AGGRESSIVE_MODE', False)

        logger.info(
            f"StrategyAdvisor initialized. Adaptive: {self.enable_adaptive}, Aggressive: {self.aggressive_mode}")

    def analyze_and_advise(
            self, market_data: Dict[str, Any], performance_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze current market and performance data to generate strategy recommendations.

        Args:
            market_data: Current market conditions (trends, volatility, etc.)
            performance_data: Trading performance metrics (win rate, P&L, drawdown, etc.)

        Returns:
            Dictionary with strategy adjustments and explanations
        """
        if not self.enable_adaptive:
            return {
                'adjustments': {},
                'risk_level': 'normal',
                'recommendations': ['Adaptive strategy disabled']
            }

        # Check if enough time has passed since last adjustment
        if self.last_adjustment:
            time_since_last = (datetime.now() - self.last_adjustment).total_seconds()
            if time_since_last < self.min_adjustment_interval:
                return {'adjustments': {}, 'risk_level': 'normal', 'recommendations': [
                    f'Waiting for adjustment interval ({int(time_since_last)}s / {self.min_adjustment_interval}s)']}

        # Calculate risk level based on current conditions
        risk_level = self._calculate_risk_level(market_data, performance_data)

        # Generate strategy adjustments
        adjustments = self._generate_adjustments(risk_level, market_data, performance_data)

        # Generate recommendations
        recommendations = self._generate_recommendations(risk_level, market_data, performance_data)

        # Record this adjustment
        self.last_adjustment = datetime.now()
        self.adjustment_history.append({
            'timestamp': self.last_adjustment,
            'risk_level': risk_level,
            'adjustments': adjustments,
            'recommendations': recommendations
        })

        # Keep only last 100 adjustments
        if len(self.adjustment_history) > 100:
            self.adjustment_history = self.adjustment_history[-100:]

        return {
            'adjustments': adjustments,
            'risk_level': risk_level,
            'recommendations': recommendations,
            'timestamp': self.last_adjustment.isoformat()
        }

    def _calculate_risk_level(
            self, market_data: Dict[str, Any], performance_data: Dict[str, Any]) -> str:
        """
        Calculate overall risk level based on market and performance conditions.

        Returns:
            'very_low', 'low', 'normal', 'high', or 'critical'
        """
        risk_score = 0

        # Analyze drawdown
        max_drawdown = performance_data.get('max_drawdown_pct', 0)
        if max_drawdown > 50:
            risk_score += 3
        elif max_drawdown > 30:
            risk_score += 2
        elif max_drawdown > 15:
            risk_score += 1

        # Analyze win rate
        win_rate = performance_data.get('win_rate', 50)
        if win_rate < 30:
            risk_score += 2
        elif win_rate < 40:
            risk_score += 1
        elif win_rate > 60:
            risk_score -= 1

        # Analyze recent performance
        daily_pnl = performance_data.get('daily_pnl', 0)
        weekly_pnl = performance_data.get('weekly_pnl', 0)

        if daily_pnl < 0 and weekly_pnl < 0:
            risk_score += 2
        elif daily_pnl < 0 or weekly_pnl < 0:
            risk_score += 1

        # Analyze market volatility
        avg_volatility = market_data.get('avg_volatility', 0)
        if avg_volatility > 5:  # High volatility
            risk_score += 1

        # Analyze Sharpe ratio
        sharpe = performance_data.get('sharpe_ratio', 0)
        if sharpe < 0:
            risk_score += 2
        elif sharpe < 0.5:
            risk_score += 1
        elif sharpe > 2:
            risk_score -= 1

        # Convert score to risk level
        if risk_score <= -1:
            return 'very_low'
        elif risk_score == 0:
            return 'low'
        elif risk_score <= 2:
            return 'normal'
        elif risk_score <= 5:
            return 'high'
        else:
            return 'critical'

    def _generate_adjustments(self, risk_level: str, market_data: Dict[str, Any],
                              performance_data: Dict[str, Any]) -> Dict[str, float]:
        """
        Generate specific parameter adjustments based on risk level and conditions.

        Returns:
            Dictionary with parameter adjustments (position_size_multiplier, confidence_threshold_adjustment, etc.)
        """
        adjustments = {}

        # Position size adjustments based on risk level
        if risk_level == 'critical':
            adjustments['position_size_multiplier'] = 0.25  # Reduce to 25%
            adjustments['confidence_threshold_adjustment'] = +20  # Require much higher confidence
            adjustments['max_positions_multiplier'] = 0.3  # Reduce max positions
        elif risk_level == 'high':
            adjustments['position_size_multiplier'] = 0.5  # Reduce to 50%
            adjustments['confidence_threshold_adjustment'] = +10  # Require higher confidence
            adjustments['max_positions_multiplier'] = 0.5
        elif risk_level == 'normal':
            adjustments['position_size_multiplier'] = 1.0  # Normal size
            adjustments['confidence_threshold_adjustment'] = 0
            adjustments['max_positions_multiplier'] = 1.0
        elif risk_level == 'low':
            adjustments['position_size_multiplier'] = 1.2 if self.aggressive_mode else 1.0
            adjustments['confidence_threshold_adjustment'] = -5 if self.aggressive_mode else 0
            adjustments['max_positions_multiplier'] = 1.2 if self.aggressive_mode else 1.0
        else:  # very_low
            adjustments['position_size_multiplier'] = 1.5 if self.aggressive_mode else 1.0
            adjustments['confidence_threshold_adjustment'] = -10 if self.aggressive_mode else 0
            adjustments['max_positions_multiplier'] = 1.5 if self.aggressive_mode else 1.0

        # Adjust for drawdown
        max_drawdown = performance_data.get('max_drawdown_pct', 0)
        if max_drawdown > 20:
            # Further reduce position size if in significant drawdown
            adjustments['position_size_multiplier'] *= 0.7

        # Adjust for win rate
        win_rate = performance_data.get('win_rate', 50)
        if win_rate < 35:
            # Lower win rate = more cautious
            adjustments['confidence_threshold_adjustment'] += 10
            adjustments['position_size_multiplier'] *= 0.8
        elif win_rate > 65:
            # Higher win rate = can be slightly more aggressive
            if self.aggressive_mode:
                adjustments['position_size_multiplier'] *= 1.1

        # Adjust for market trends
        trend_strength = market_data.get('trend_strength', 'weak')
        if trend_strength == 'strong':
            # Strong trends = can trade more confidently
            adjustments['confidence_threshold_adjustment'] -= 5
        elif trend_strength == 'weak':
            # Weak trends = more cautious
            adjustments['confidence_threshold_adjustment'] += 5

        return adjustments

    def _generate_recommendations(self, risk_level: str, market_data: Dict[str, Any],
                                  performance_data: Dict[str, Any]) -> list:
        """
        Generate human-readable recommendations based on analysis.

        Returns:
            List of recommendation strings
        """
        recommendations = []

        # Risk level recommendations
        if risk_level == 'critical':
            recommendations.append(
                "⚠️ CRITICAL RISK: Significantly reduce position sizes and trading activity")
            recommendations.append("🔒 Consider pausing trading until conditions improve")
        elif risk_level == 'high':
            recommendations.append("⚠️ HIGH RISK: Trade with extreme caution")
            recommendations.append("📉 Reduce position sizes and increase confidence requirements")
        elif risk_level == 'low' or risk_level == 'very_low':
            recommendations.append("✅ LOW RISK: Favorable conditions for trading")
            if self.aggressive_mode:
                recommendations.append("📈 Consider increasing position sizes within limits")

        # Drawdown recommendations
        max_drawdown = performance_data.get('max_drawdown_pct', 0)
        if max_drawdown > 30:
            recommendations.append(
                f"🚨 High drawdown ({max_drawdown:.1f}%): Focus on capital preservation")
        elif max_drawdown > 15:
            recommendations.append(f"⚠️ Moderate drawdown ({max_drawdown:.1f}%): Trade cautiously")

        # Win rate recommendations
        win_rate = performance_data.get('win_rate', 50)
        if win_rate < 35:
            recommendations.append(
                f"📊 Low win rate ({win_rate:.1f}%): Review strategy and reduce activity")
        elif win_rate > 65:
            recommendations.append(f"✅ High win rate ({win_rate:.1f}%): Strategy performing well")

        # Trend recommendations
        trend_info = market_data.get('trend_summary', '')
        if 'strong' in trend_info.lower():
            recommendations.append("📈 Strong market trends detected: Focus on trend-following")
        elif 'weak' in trend_info.lower() or 'range' in trend_info.lower():
            recommendations.append(
                "↔️ Weak trends/ranging market: Use tight stops and be selective")

        # Sharpe ratio recommendations
        sharpe = performance_data.get('sharpe_ratio', 0)
        if sharpe < 0:
            recommendations.append(
                "📉 Negative Sharpe ratio: Strategy underperforming risk-free rate")
        elif sharpe > 2:
            recommendations.append(
                f"✅ Excellent Sharpe ratio ({sharpe:.2f}): Strong risk-adjusted returns")

        return recommendations

    def get_adjustment_summary(self) -> str:
        """
        Get a summary of the current strategy adjustments.

        Returns:
            Formatted string with adjustment summary
        """
        if not self.adjustment_history:
            return "No adjustments made yet"

        latest = self.adjustment_history[-1]

        summary = f"Last Adjustment: {latest['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        summary += f"Risk Level: {latest['risk_level'].upper()}\n\n"

        if latest['adjustments']:
            summary += "Adjustments:\n"
            for key, value in latest['adjustments'].items():
                if 'multiplier' in key:
                    summary += f"  {key}: {value:.2f}x\n"
                else:
                    summary += f"  {key}: {value:+.1f}\n"

        if latest['recommendations']:
            summary += "\nRecommendations:\n"
            for rec in latest['recommendations']:
                summary += f"  • {rec}\n"

        return summary
