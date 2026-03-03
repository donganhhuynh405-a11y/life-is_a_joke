"""
Advanced Risk Manager with Kelly Criterion and Volatility-Based Position Sizing
Based on analysis of top 20 profitable trading bots (2026)

Implements:
- Kelly Criterion position sizing (fractional for safety)
- ATR-based volatility adaptive sizing
- Portfolio heat management
- Correlation-aware risk adjustment
- Performance-based risk throttling
"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class AdvancedRiskManager:
    """
    Elite risk management system implementing strategies from top performing bots
    """

    def __init__(self, config: Dict):
        """
        Initialize advanced risk manager

        Args:
            config: Configuration dictionary with risk parameters
        """
        self.config = config

        # Kelly Criterion parameters
        self.use_kelly = config.get('USE_KELLY_CRITERION', True)
        self.kelly_fraction = config.get('KELLY_FRACTION', 0.25)  # 25% of Kelly for safety

        # Volatility parameters
        self.use_volatility_sizing = config.get('USE_VOLATILITY_SIZING', True)
        self.volatility_lookback = config.get('VOLATILITY_LOOKBACK', 14)
        self.risk_per_trade_pct = config.get('RISK_PER_TRADE_PCT', 1.0)  # 1% per trade

        # Portfolio heat parameters
        self.max_portfolio_heat_pct = config.get('MAX_PORTFOLIO_HEAT_PCT', 6.0)  # 6% total risk
        self.max_correlated_risk_pct = config.get(
            'MAX_CORRELATED_RISK_PCT', 3.0)  # 3% for correlated

        # Performance throttling
        self.throttle_on_drawdown = config.get('THROTTLE_ON_DRAWDOWN', True)
        self.max_drawdown_threshold_pct = config.get('MAX_DRAWDOWN_THRESHOLD_PCT', 10.0)
        self.throttle_multiplier = config.get('THROTTLE_MULTIPLIER', 0.5)  # 50% reduction

        # Tracking
        self.current_portfolio_heat = 0.0
        self.open_positions_risk = {}
        self.performance_history = []

        logger.info("🎯 Advanced Risk Manager initialized")
        logger.info(f"  Kelly Criterion: {self.use_kelly} (fraction: {self.kelly_fraction})")
        logger.info(f"  Volatility Sizing: {self.use_volatility_sizing}")
        logger.info(f"  Max Portfolio Heat: {self.max_portfolio_heat_pct}%")
        logger.info(f"  Risk per Trade: {self.risk_per_trade_pct}%")

    def calculate_kelly_position_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        account_balance: float
    ) -> float:
        """
        Calculate optimal position size using Kelly Criterion

        Formula: f = (bp - q) / b
        where:
            f = fraction of capital to risk
            b = win/loss ratio (avg_win/avg_loss)
            p = probability of winning
            q = probability of losing (1-p)

        Args:
            win_rate: Historical win rate (0-1)
            avg_win: Average win amount
            avg_loss: Average loss amount
            account_balance: Current account balance

        Returns:
            Position size in dollars
        """
        if not self.use_kelly or avg_loss <= 0 or win_rate <= 0:
            return 0.0

        # Kelly calculation
        b = abs(avg_win / avg_loss)  # Win/loss ratio
        p = win_rate
        q = 1 - p

        kelly_pct = (b * p - q) / b

        # Apply fractional Kelly for safety (typically 25% or 50%)
        fractional_kelly = kelly_pct * self.kelly_fraction

        # Ensure positive and capped
        fractional_kelly = max(0, min(fractional_kelly, 0.25))  # Cap at 25% of account

        position_size = account_balance * fractional_kelly

        logger.debug(f"Kelly sizing: WR={win_rate:.2%}, Ratio={b:.2f}, "
                     f"Full Kelly={kelly_pct:.2%}, Fractional={fractional_kelly:.2%}")

        return position_size

    def calculate_volatility_adjusted_size(
        self,
        symbol: str,
        atr: float,
        price: float,
        account_balance: float,
        direction: str = 'LONG'
    ) -> Tuple[float, float]:
        """
        Calculate position size based on volatility (ATR)

        This ensures consistent risk regardless of volatility:
        - Sets stop-loss at 2x ATR
        - Sizes position so stop-out = risk_per_trade_pct of account

        Args:
            symbol: Trading symbol
            atr: Average True Range
            price: Current price
            account_balance: Account balance
            direction: 'LONG' or 'SHORT'

        Returns:
            (position_size_dollars, stop_loss_price)
        """
        if not self.use_volatility_sizing or atr <= 0:
            return 0.0, 0.0

        # Stop loss at 2x ATR
        stop_distance = 2 * atr

        # Calculate stop loss price
        if direction == 'LONG':
            stop_loss_price = price - stop_distance
        else:
            stop_loss_price = price + stop_distance

        # Risk amount in dollars
        risk_amount = account_balance * (self.risk_per_trade_pct / 100.0)

        # Position size = risk_amount / stop_distance_pct
        stop_distance_pct = abs(stop_distance / price)

        if stop_distance_pct > 0:
            position_size = risk_amount / stop_distance_pct
        else:
            position_size = 0.0

        logger.debug(f"Volatility sizing for {symbol}: ATR={atr:.4f}, "
                     f"Stop@{stop_loss_price:.4f}, Size=${position_size:.2f}")

        return position_size, stop_loss_price

    def check_portfolio_heat(
        self,
        new_position_risk_pct: float,
        symbol: str,
        correlated_symbols: List[str] = None
    ) -> Tuple[bool, str]:
        """
        Check if adding new position would exceed portfolio heat limits

        Args:
            new_position_risk_pct: Risk % for new position
            symbol: Symbol to trade
            correlated_symbols: List of symbols correlated with this one

        Returns:
            (allowed, reason)
        """
        # Calculate current total heat
        total_heat = self.current_portfolio_heat + new_position_risk_pct

        # Check total portfolio heat
        if total_heat > self.max_portfolio_heat_pct:
            return False, f"Portfolio heat would be {total_heat:.1f}% (max {self.max_portfolio_heat_pct}%)"

        # Check correlated risk if provided
        if correlated_symbols:
            correlated_heat = new_position_risk_pct
            for corr_symbol in correlated_symbols:
                if corr_symbol in self.open_positions_risk:
                    correlated_heat += self.open_positions_risk[corr_symbol]

            if correlated_heat > self.max_correlated_risk_pct:
                return False, f"Correlated risk would be {correlated_heat:.1f}% (max {self.max_correlated_risk_pct}%)"

        return True, "OK"

    def apply_performance_throttle(
        self,
        position_size: float,
        current_drawdown_pct: float
    ) -> float:
        """
        Reduce position size during drawdown periods

        Args:
            position_size: Calculated position size
            current_drawdown_pct: Current drawdown percentage

        Returns:
            Throttled position size
        """
        if not self.throttle_on_drawdown:
            return position_size

        if current_drawdown_pct > self.max_drawdown_threshold_pct:
            throttled_size = position_size * self.throttle_multiplier
            logger.info(f"⚠️ Performance throttle applied: DD={current_drawdown_pct:.1f}%, "
                        f"Size reduced {100 * (1 - self.throttle_multiplier):.0f}%")
            return throttled_size

        return position_size

    def calculate_optimal_position_size(
        self,
        symbol: str,
        account_balance: float,
        price: float,
        atr: float,
        direction: str,
        win_rate: float = None,
        avg_win: float = None,
        avg_loss: float = None,
        current_drawdown_pct: float = 0.0,
        correlated_symbols: List[str] = None
    ) -> Dict:
        """
        Calculate optimal position size using multiple methods

        Combines Kelly Criterion and Volatility sizing for robust results

        Args:
            symbol: Trading symbol
            account_balance: Current account balance
            price: Current price
            atr: Average True Range
            direction: 'LONG' or 'SHORT'
            win_rate: Historical win rate (optional, for Kelly)
            avg_win: Average win (optional, for Kelly)
            avg_loss: Average loss (optional, for Kelly)
            current_drawdown_pct: Current drawdown %
            correlated_symbols: Correlated symbols

        Returns:
            Dict with position sizing recommendations
        """
        result = {
            'symbol': symbol,
            'recommended_size': 0.0,
            'stop_loss': 0.0,
            'risk_pct': 0.0,
            'method': 'none',
            'kelly_size': 0.0,
            'volatility_size': 0.0,
            'can_trade': False,
            'reason': ''
        }

        try:
            # Method 1: Kelly Criterion (if stats available)
            kelly_size = 0.0
            if win_rate and avg_win and avg_loss:
                kelly_size = self.calculate_kelly_position_size(
                    win_rate, avg_win, avg_loss, account_balance
                )
                result['kelly_size'] = kelly_size

            # Method 2: Volatility-based sizing
            volatility_size, stop_loss = self.calculate_volatility_adjusted_size(
                symbol, atr, price, account_balance, direction
            )
            result['volatility_size'] = volatility_size
            result['stop_loss'] = stop_loss

            # Choose sizing method
            if kelly_size > 0 and volatility_size > 0:
                # Use conservative estimate (minimum of both)
                recommended_size = min(kelly_size, volatility_size)
                result['method'] = 'kelly_volatility_min'
            elif volatility_size > 0:
                recommended_size = volatility_size
                result['method'] = 'volatility'
            elif kelly_size > 0:
                recommended_size = kelly_size
                result['method'] = 'kelly'
            else:
                # Fallback to simple percentage
                recommended_size = account_balance * (self.risk_per_trade_pct / 100.0)
                result['method'] = 'fixed_pct'

            # Apply performance throttle
            recommended_size = self.apply_performance_throttle(
                recommended_size, current_drawdown_pct
            )

            # Calculate risk percentage
            if stop_loss > 0 and price > 0:
                risk_per_unit = abs(price - stop_loss)
                quantity = recommended_size / price
                total_risk = risk_per_unit * quantity
                risk_pct = (total_risk / account_balance) * 100
            else:
                risk_pct = self.risk_per_trade_pct

            result['risk_pct'] = risk_pct

            # Check portfolio heat
            can_trade, reason = self.check_portfolio_heat(
                risk_pct, symbol, correlated_symbols
            )

            if can_trade:
                result['recommended_size'] = recommended_size
                result['can_trade'] = True
                result['reason'] = 'Position sizing approved'
            else:
                result['can_trade'] = False
                result['reason'] = reason

            logger.info(f"📊 Position sizing for {symbol}: "
                        f"${recommended_size:.2f} ({result['method']}, "
                        f"risk: {risk_pct:.2f}%) - {result['reason']}")

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            result['reason'] = f"Error: {str(e)}"

        return result

    def update_position_risk(self, symbol: str, risk_pct: float):
        """Update tracking for open position"""
        self.open_positions_risk[symbol] = risk_pct
        self.current_portfolio_heat = sum(self.open_positions_risk.values())
        logger.debug(f"Portfolio heat updated: {self.current_portfolio_heat:.2f}%")

    def remove_position_risk(self, symbol: str):
        """Remove closed position from tracking"""
        if symbol in self.open_positions_risk:
            del self.open_positions_risk[symbol]
            self.current_portfolio_heat = sum(self.open_positions_risk.values())
            logger.debug(f"Position {symbol} removed, heat: {self.current_portfolio_heat:.2f}%")

    def get_risk_summary(self) -> Dict:
        """Get current risk management summary"""
        return {
            'portfolio_heat_pct': self.current_portfolio_heat,
            'max_heat_pct': self.max_portfolio_heat_pct,
            'heat_utilization': (self.current_portfolio_heat / self.max_portfolio_heat_pct) * 100,
            'open_positions': len(self.open_positions_risk),
            'positions_risk': self.open_positions_risk,
            'kelly_enabled': self.use_kelly,
            'volatility_sizing_enabled': self.use_volatility_sizing
        }
