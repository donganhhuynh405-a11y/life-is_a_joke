"""
ML Signal Enhancer

Enhances technical trading signals with ML-based confidence adjustments.
The technical analysis always remains the primary decision maker; ML only
adjusts the existing confidence score within a bounded range.

Adjustment sources:
1. News sentiment   : -10 to +10
2. Pattern matching : -10 to +10
3. Symbol stats     : -10 to +10
Total ML adjustment : -20 to +20 (capped)
"""

import logging
from typing import Dict, Optional

from ml.news_sentiment import NewsSentimentAnalyzer
from ml.pattern_matcher import PatternMatcher

logger = logging.getLogger(__name__)

# Only enhance signals above this technical score
MIN_TECHNICAL_SCORE = 50
# Overall ML adjustment bounds
ML_ADJUSTMENT_MAX = 20
ML_ADJUSTMENT_MIN = -20


class MLSignalEnhancer:
    """
    Enhances technical trading signals with ML-derived confidence adjustments.

    Safety guarantees:
    - ML adjustment is bounded to [-20, +20].
    - Final confidence is capped at 100 and floored at 0.
    - If any ML component fails, the original signal is returned unchanged.
    - ML will NEVER generate independent signals.
    """

    def __init__(self,
                 db_path: str = '/var/lib/trading-bot/trading_bot.db',
                 news_aggregator=None):
        """
        Args:
            db_path: Path to the SQLite trading database.
            news_aggregator: Optional NewsAggregator for live news lookup.
        """
        self.db_path = db_path
        self.news_sentiment = NewsSentimentAnalyzer(
            db_path=db_path, news_aggregator=news_aggregator
        )
        self.pattern_matcher = PatternMatcher(db_path=db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enhance_signal(self, signal: Dict,
                       current_market_data: Optional[Dict] = None) -> Dict:
        """
        Enhance a technical signal with ML-derived confidence adjustments.

        Args:
            signal: Technical signal dict with at minimum:
                    'symbol' (str), 'action' (str), 'confidence' (int 0-100).
                    Optionally 'market_state' dict with rsi, macd, trend,
                    volatility keys.
            current_market_data: Additional market data (merged into
                                 market_state if provided).

        Returns:
            Enhanced signal dict with additional keys:
                base_confidence, ml_adjustment, final_confidence, ml_reasoning.
        """
        symbol = signal.get('symbol', '')
        action = signal.get('action', 'BUY')
        base_confidence = int(signal.get('confidence', 0))

        # Build market state from signal and/or extra data
        market_state = dict(signal.get('market_state') or {})
        if current_market_data:
            market_state.update(current_market_data)

        if base_confidence < MIN_TECHNICAL_SCORE:
            logger.debug(
                f"{symbol}: base confidence {base_confidence} below minimum "
                f"{MIN_TECHNICAL_SCORE} – skipping ML enhancement"
            )
            return self._passthrough(signal, base_confidence)

        try:
            # --- News sentiment ---
            news_result = self.news_sentiment.get_sentiment_boost(symbol, hours=6)
            news_boost = news_result.get('confidence_boost', 0)

            # --- Pattern matching ---
            pattern_result = self.pattern_matcher.find_similar_patterns(
                market_state, lookback_days=90
            )
            pattern_boost = pattern_result.get('confidence_boost', 0)

            # --- Symbol-specific stats ---
            symbol_boost = self.pattern_matcher.get_symbol_stats_boost(symbol, action)

            # --- Combine and cap ---
            raw_adjustment = news_boost + pattern_boost + symbol_boost
            ml_adjustment = max(ML_ADJUSTMENT_MIN, min(ML_ADJUSTMENT_MAX, raw_adjustment))
            final_confidence = max(0, min(100, base_confidence + ml_adjustment))

            ml_reasoning = {
                'news_sentiment': news_boost,
                'pattern_match': pattern_boost,
                'symbol_stats': symbol_boost,
                # Extra info for UI rendering
                'matches': pattern_result.get('matches', 0),
                'wins': pattern_result.get('wins', 0),
                'avg_pnl': pattern_result.get('avg_pnl', 0.0),
                'news_count': news_result.get('news_count', 0),
                'bullish_count': news_result.get('bullish_count', 0),
                'bearish_count': news_result.get('bearish_count', 0),
            }

            logger.info(
                f"{symbol} ML enhancement: base={base_confidence}, "
                f"news={news_boost:+d}, pattern={pattern_boost:+d}, "
                f"symbol={symbol_boost:+d}, "
                f"total_adjustment={ml_adjustment:+d}, final={final_confidence}"
            )

            enhanced = dict(signal)
            enhanced.update({
                'base_confidence': base_confidence,
                'ml_adjustment': ml_adjustment,
                'final_confidence': final_confidence,
                'ml_reasoning': ml_reasoning,
            })
            return enhanced

        except Exception as e:
            logger.warning(
                f"{symbol}: ML enhancement failed ({e}), "
                f"falling back to technical signal",
                exc_info=True
            )
            return self._passthrough(signal, base_confidence)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _passthrough(signal: Dict, base_confidence: int) -> Dict:
        """Return a copy of the signal with neutral ML metadata."""
        result = dict(signal)
        result.update({
            'base_confidence': base_confidence,
            'ml_adjustment': 0,
            'final_confidence': base_confidence,
            'ml_reasoning': None,
        })
        return result
