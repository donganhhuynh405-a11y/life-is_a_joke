"""
Adaptive Trading Tactics System
Automatically adjusts bot trading behavior based on AI performance analysis
"""

import logging
from typing import Dict, List
from datetime import datetime, timedelta


class AdaptiveTacticsManager:
    """Manages automatic adjustment of trading tactics based on performance"""

    def __init__(self, config, database, logger=None):
        self.config = config
        self.database = database
        self.logger = logger or logging.getLogger(__name__)

        self.db_path = config.db_path

        self.last_adjustment_time = {}
        self.adjustment_cooldown = timedelta(hours=1)

        self.tactical_overrides = {
            'position_size_multiplier': 1.0,
            'min_confidence_threshold': 50.0,
            'paused_symbols': set(),
            'paused_since': {},
            'max_positions_override': None,
        }

    def analyze_and_adjust(self) -> Dict:
        """
        Analyze recent performance and automatically adjust trading tactics
        Returns dict of adjustments made
        """
        self.logger.info("🤖 Analyzing performance for tactical adjustments...")

        adjustments_made = []

        # Auto-unblock symbols that have been paused for too long
        adjustments_made.extend(self._auto_unblock_old_paused_symbols())

        try:
            # Get recent performance (7 days and 30 days)
            from ml import TradeAnalyzer, PerformanceAnalyzer

            analyzer = TradeAnalyzer(db_path=self.db_path)
            perf_analyzer = PerformanceAnalyzer(db_path=self.db_path)

            perf_7d = analyzer.analyze_performance(days=7)
            perf_30d = analyzer.analyze_performance(days=30)
            advanced = perf_analyzer.get_performance_summary()

            # 1. Adjust position sizing based on recent performance
            adjustments_made.extend(self._adjust_position_sizing(perf_7d, advanced))

            # 2. Adjust confidence thresholds based on win rate
            adjustments_made.extend(self._adjust_confidence_threshold(perf_7d, perf_30d))

            # 3. Pause trading on underperforming symbols
            adjustments_made.extend(self._adjust_symbol_trading(perf_30d))

            # 4. Adjust max positions based on risk metrics
            adjustments_made.extend(self._adjust_max_positions(advanced))

            if adjustments_made:
                self.logger.info(f"✅ Made {len(adjustments_made)} tactical adjustments:")
                for adj in adjustments_made:
                    self.logger.info(f"   - {adj}")
            else:
                self.logger.info("✅ No tactical adjustments needed - strategy performing well")

            return {
                'timestamp': datetime.now().isoformat(),
                'adjustments': adjustments_made,
                'overrides': self.tactical_overrides.copy()
            }

        except Exception as e:
            self.logger.error(f"Error in adaptive tactics analysis: {e}", exc_info=True)
            return {'error': str(e)}

    def _auto_unblock_old_paused_symbols(self) -> List[str]:
        """Automatically unblock symbols that have been paused for too long to prevent deadlock"""
        adjustments = []

        try:
            from datetime import datetime, timedelta

            AUTO_UNBLOCK_DAYS = 7
            cutoff_time = datetime.now() - timedelta(days=AUTO_UNBLOCK_DAYS)

            symbols_to_unblock = []
            for symbol in list(self.tactical_overrides['paused_symbols']):
                paused_since = self.tactical_overrides['paused_since'].get(symbol)

                if paused_since is None:
                    symbols_to_unblock.append(symbol)
                    adjustments.append(
                        f"🔄 Auto-unblocking {symbol} - No pause timestamp (legacy pause)")
                elif paused_since < cutoff_time:
                    symbols_to_unblock.append(symbol)
                    days_paused = (datetime.now() - paused_since).days
                    adjustments.append(
                        f"🔄 Auto-unblocking {symbol} - Paused for {days_paused} days (trial period)")

            for symbol in symbols_to_unblock:
                self.tactical_overrides['paused_symbols'].discard(symbol)
                self.tactical_overrides['paused_since'].pop(symbol, None)

        except Exception as e:
            self.logger.debug(f"Error in auto-unblock: {e}")

        return adjustments

    def _adjust_position_sizing(self, perf_7d: Dict, advanced: Dict) -> List[str]:
        """Adjust position size multiplier based on recent performance"""
        adjustments = []

        try:
            win_rate = perf_7d.get('win_rate', 0)
            profit_factor = perf_7d.get('profit_factor', 0)
            sharpe = advanced.get('sharpe_ratio', 0)
            max_dd = advanced.get('max_drawdown_pct', 0)

            new_multiplier = 1.0

            if win_rate > 70 and profit_factor > 2.0 and sharpe > 1.5:
                new_multiplier = 1.3
                adjustments.append(
                    "📈 Increasing position sizes by 30% - Excellent performance detected")
            elif win_rate > 60 and profit_factor > 1.5 and sharpe > 1.0:
                new_multiplier = 1.15
                adjustments.append("📈 Increasing position sizes by 15% - Strong performance")
            elif win_rate < 40 or profit_factor < 0.8 or max_dd > 20:
                new_multiplier = 0.5
                adjustments.append(
                    "📉 Reducing position sizes by 50% - Poor performance, protecting capital")
            elif win_rate < 50 or profit_factor < 1.0 or max_dd > 15:
                new_multiplier = 0.75
                adjustments.append("📉 Reducing position sizes by 25% - Underperformance detected")

            if new_multiplier != self.tactical_overrides['position_size_multiplier']:
                self.tactical_overrides['position_size_multiplier'] = new_multiplier

        except Exception as e:
            self.logger.debug(f"Error adjusting position sizing: {e}")

        return adjustments

    def _adjust_confidence_threshold(self, perf_7d: Dict, perf_30d: Dict) -> List[str]:
        """Adjust minimum confidence threshold for trading"""
        adjustments = []

        try:
            win_rate_7d = perf_7d.get('win_rate', 0)
            win_rate_30d = perf_30d.get('win_rate', 0)

            new_threshold = 50.0  # Default

            # Poor win rate - only take high confidence trades
            if win_rate_7d < 40:
                new_threshold = 85.0
                adjustments.append(
                    "🎯 Raising confidence threshold to 85% - Only taking highest conviction trades")

            # Weak win rate - higher selectivity
            elif win_rate_7d < 50:
                new_threshold = 70.0
                adjustments.append(
                    "🎯 Raising confidence threshold to 70% - Increasing trade selectivity")

            # Excellent win rate - can be less selective
            elif win_rate_7d > 75 and win_rate_30d > 70:
                new_threshold = 40.0
                adjustments.append(
                    "🎯 Lowering confidence threshold to 40% - High win rate allows more opportunities")

            # Good win rate - normal selectivity
            elif win_rate_7d > 60:
                new_threshold = 50.0
                adjustments.append("🎯 Maintaining confidence threshold at 50% - Good performance")

            # Apply if changed
            if new_threshold != self.tactical_overrides['min_confidence_threshold']:
                self.tactical_overrides['min_confidence_threshold'] = new_threshold

        except Exception as e:
            self.logger.debug(f"Error adjusting confidence threshold: {e}")

        return adjustments

    def _adjust_symbol_trading(self, perf_30d: Dict) -> List[str]:
        """Pause trading on consistently losing symbols"""
        adjustments = []

        try:
            from ml import TradeAnalyzer
            analyzer = TradeAnalyzer(self.database, self.logger)

            symbol_perf = analyzer.get_performance_by_symbol(days=30)

            newly_paused = set()
            newly_resumed = set()

            for symbol, stats in symbol_perf.items():
                trades = stats.get('total_trades', 0)
                win_rate = stats.get('win_rate', 0)
                total_pnl = stats.get('total_pnl', 0)

                should_pause = (
                    trades >= 5 and
                    (win_rate < 30 or total_pnl < -50)
                )

                should_resume = (
                    trades >= 3 and
                    win_rate >= 60 and
                    total_pnl > 0
                )

                if should_pause and symbol not in self.tactical_overrides['paused_symbols']:
                    from datetime import datetime
                    self.tactical_overrides['paused_symbols'].add(symbol)
                    self.tactical_overrides['paused_since'][symbol] = datetime.now()
                    newly_paused.add(symbol)
                    adjustments.append(
                        f"⛔ Pausing {symbol} - Consistently underperforming "
                        f"({win_rate:.0f}% win rate, ${total_pnl:.2f} P&L)")

                elif should_resume and symbol in self.tactical_overrides['paused_symbols']:
                    self.tactical_overrides['paused_symbols'].discard(symbol)
                    self.tactical_overrides['paused_since'].pop(symbol, None)
                    newly_resumed.add(symbol)
                    adjustments.append(
                        f"✅ Resuming {symbol} - Performance improved ({win_rate:.0f}% win rate, ${total_pnl:.2f} P&L)")

        except Exception as e:
            self.logger.debug(f"Error adjusting symbol trading: {e}")

        return adjustments

    def _adjust_max_positions(self, advanced: Dict) -> List[str]:
        """Adjust maximum open positions based on risk metrics"""
        adjustments = []

        try:
            sharpe = advanced.get('sharpe_ratio', 0)
            max_dd = advanced.get('max_drawdown_pct', 0)

            new_max = None
            current_max = self.config.max_open_positions

            if max_dd > 25 or sharpe < -1:
                new_max = max(1, current_max - 2)
                adjustments.append(
                    f"⚠️ Reducing max positions to {new_max} - High risk detected (DD: {max_dd:.1f}%)")
            elif max_dd > 15 or sharpe < 0:
                new_max = max(1, current_max - 1)
                adjustments.append(
                    f"⚠️ Reducing max positions to {new_max} - Elevated risk (DD: {max_dd:.1f}%)")
            elif max_dd < 5 and sharpe > 2.0:
                new_max = min(10, current_max + 1)
                adjustments.append(
                    f"✅ Increasing max positions to {new_max} - Excellent risk management "
                    f"(DD: {max_dd:.1f}%, Sharpe: {sharpe:.2f})")

            if new_max and new_max != self.tactical_overrides.get('max_positions_override'):
                self.tactical_overrides['max_positions_override'] = new_max

        except Exception as e:
            self.logger.debug(f"Error adjusting max positions: {e}")

        return adjustments

    def should_trade_symbol(self, symbol: str) -> bool:
        """Check if trading is allowed for this symbol"""
        return symbol not in self.tactical_overrides['paused_symbols']

    def get_adjusted_position_size(self, base_size: float) -> float:
        """Get position size adjusted by tactical multiplier"""
        multiplier = self.tactical_overrides['position_size_multiplier']
        return base_size * multiplier

    def get_min_confidence(self) -> float:
        """Get current minimum confidence threshold"""
        return self.tactical_overrides['min_confidence_threshold']

    def get_max_positions(self) -> int:
        """Get current maximum positions (override or config)"""
        override = self.tactical_overrides.get('max_positions_override')
        return override if override is not None else self.config.max_open_positions

    def get_tactical_status(self) -> Dict:
        """Get current tactical adjustments status"""
        return {
            'position_size_multiplier': self.tactical_overrides['position_size_multiplier'],
            'min_confidence_threshold': self.tactical_overrides['min_confidence_threshold'],
            'paused_symbols': list(self.tactical_overrides['paused_symbols']),
            'max_positions': self.get_max_positions(),
            'status': 'active' if any([
                self.tactical_overrides['position_size_multiplier'] != 1.0,
                self.tactical_overrides['min_confidence_threshold'] != 50.0,
                len(self.tactical_overrides['paused_symbols']) > 0,
                self.tactical_overrides['max_positions_override'] is not None
            ]) else 'default'
        }

    def get_current_tactics(self) -> Dict:
        """Get current tactical adjustments for diagnostic purposes"""
        return {
            'position_size_multiplier': self.tactical_overrides['position_size_multiplier'],
            'confidence_threshold': self.tactical_overrides['min_confidence_threshold'] / 100.0,
            'max_positions': self.get_max_positions(),
            'blocked_symbols': list(self.tactical_overrides['paused_symbols']),
        }
