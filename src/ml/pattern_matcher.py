"""
Pattern Matcher for ML Signal Enhancement

Finds similar historical market conditions in the trade database and returns
a confidence adjustment based on how those past situations resolved.
"""

import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 900  # 15 minutes


class PatternMatcher:
    """
    Finds historically similar market states from closed positions and
    uses their outcomes to suggest a confidence adjustment.

    Similarity criteria:
    - RSI within ±10
    - MACD sign matches (both positive or both negative)
    - Trend direction matches
    - Volatility (ATR) within ±20%

    A pattern is considered "similar" when at least 3 of 4 criteria match.
    """

    SIMILARITY_THRESHOLD = 0.70  # 3 of 4 criteria = 75%
    MAX_BOOST = 10
    MIN_BOOST = -10
    MIN_MATCHES = 3

    def __init__(self, db_path: str = '/var/lib/trading-bot/trading_bot.db'):
        """
        Args:
            db_path: Path to the SQLite trading database.
        """
        self.db_path = db_path
        self._cache: Dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_similar_patterns(self, current_market_state: Dict,
                              lookback_days: int = 90) -> Dict:
        """
        Find historical trades with similar market conditions.

        Args:
            current_market_state: Dict with keys:
                rsi (float), macd (float), trend (str 'bullish'|'bearish'),
                volatility (float, ATR value).
            lookback_days: How far back to search in the database.

        Returns:
            Dict with keys: matches, wins, avg_pnl, confidence_boost.
        """
        cache_key = self._cache_key(current_market_state, lookback_days)
        cached = self._cache.get(cache_key)
        if cached:
            result, ts = cached
            if time.time() - ts < _CACHE_TTL_SECONDS:
                logger.debug("Pattern matcher: returning cached result")
                return result

        try:
            result = self._compute_patterns(current_market_state, lookback_days)
        except Exception as e:
            logger.error(f"PatternMatcher error: {e}", exc_info=True)
            result = self._empty_result()

        self._cache[cache_key] = (result, time.time())
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_key(self, state: Dict, lookback_days: int) -> str:
        rsi = round(state.get('rsi', 50) / 5) * 5  # bucket to nearest 5
        macd_sign = 1 if (state.get('macd', 0) or 0) >= 0 else -1
        trend = state.get('trend', 'neutral')
        vol = round((state.get('volatility', 0) or 0), 2)
        return f"{rsi}_{macd_sign}_{trend}_{vol}_{lookback_days}"

    def _fetch_closed_positions(self, lookback_days: int) -> List[Dict]:
        """Load closed positions that have market_state metadata stored."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=lookback_days)).isoformat()

            # Try to load from a market_snapshots table first (future-proof)
            # Fall back to closed positions table
            try:
                cursor.execute(
                    '''SELECT rsi, macd, trend, volatility, pnl
                       FROM market_snapshots
                       WHERE created_at >= ?
                       AND pnl IS NOT NULL''',
                    (cutoff,)
                )
                rows = [dict(r) for r in cursor.fetchall()]
            except sqlite3.OperationalError:
                rows = []

            if not rows:
                # Fallback: use positions table with available fields
                cursor.execute(
                    '''SELECT pnl, signal_confidence, side
                       FROM positions
                       WHERE status = 'closed'
                       AND pnl IS NOT NULL
                       AND closed_at >= ?''',
                    (cutoff,)
                )
                rows = [dict(r) for r in cursor.fetchall()]

            conn.close()
            return rows
        except Exception as e:
            logger.debug(f"PatternMatcher DB fetch failed: {e}")
            return []

    def _is_similar(self, current: Dict, historical: Dict) -> bool:
        """
        Return True if historical record matches current market state
        with at least SIMILARITY_THRESHOLD overlap.
        """
        criteria_met = 0
        total_criteria = 4

        # 1. RSI within ±10
        cur_rsi = current.get('rsi')
        hist_rsi = historical.get('rsi')
        if cur_rsi is not None and hist_rsi is not None:
            if abs(cur_rsi - hist_rsi) <= 10:
                criteria_met += 1
        else:
            total_criteria -= 1  # missing data; don't penalise

        # 2. MACD sign matches
        cur_macd = current.get('macd')
        hist_macd = historical.get('macd')
        if cur_macd is not None and hist_macd is not None:
            if (cur_macd >= 0) == (hist_macd >= 0):
                criteria_met += 1
        else:
            total_criteria -= 1

        # 3. Trend direction matches
        cur_trend = current.get('trend')
        hist_trend = historical.get('trend')
        if cur_trend is not None and hist_trend is not None:
            if cur_trend == hist_trend:
                criteria_met += 1
        else:
            total_criteria -= 1

        # 4. Volatility within ±20%
        cur_vol = current.get('volatility')
        hist_vol = historical.get('volatility')
        if cur_vol is not None and hist_vol is not None and cur_vol > 0 and hist_vol > 0:
            ratio = abs(cur_vol - hist_vol) / cur_vol
            if ratio <= 0.20:
                criteria_met += 1
        else:
            total_criteria -= 1

        if total_criteria <= 0:
            return False
        return (criteria_met / total_criteria) >= self.SIMILARITY_THRESHOLD

    def _compute_patterns(self, current_market_state: Dict, lookback_days: int) -> Dict:
        """Core computation: find matches and compute stats."""
        historical = self._fetch_closed_positions(lookback_days)

        matches = 0
        wins = 0
        pnl_sum = 0.0

        for record in historical:
            if self._is_similar(current_market_state, record):
                pnl = record.get('pnl', 0) or 0
                matches += 1
                pnl_sum += pnl
                if pnl > 0:
                    wins += 1

        if matches < self.MIN_MATCHES:
            logger.debug(f"Pattern matcher: only {matches} matches (min {self.MIN_MATCHES})")
            return self._empty_result(matches=matches)

        avg_pnl = pnl_sum / matches
        win_rate = wins / matches

        # Scale boost: win_rate 1.0 → +10, win_rate 0.0 → -10
        raw_boost = round((win_rate - 0.5) * 2 * self.MAX_BOOST)
        confidence_boost = max(self.MIN_BOOST, min(self.MAX_BOOST, raw_boost))

        logger.debug(
            f"Pattern matcher: {matches} matches, {wins} wins, "
            f"avg_pnl={avg_pnl:.2f}, boost={confidence_boost:+d}"
        )

        return {
            'matches': matches,
            'wins': wins,
            'avg_pnl': round(avg_pnl, 2),
            'confidence_boost': confidence_boost,
        }

    @staticmethod
    def _empty_result(matches: int = 0) -> Dict:
        return {
            'matches': matches,
            'wins': 0,
            'avg_pnl': 0.0,
            'confidence_boost': 0,
        }

    def get_symbol_stats_boost(self, symbol: str, action: str) -> int:
        """
        Return a confidence adjustment based on historical win-rate for this
        symbol/action combination stored in the positions table.

        Returns an int in the range -10..+10.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT COUNT(*) as total,
                          SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
                   FROM positions
                   WHERE symbol = ?
                   AND side = ?
                   AND status = 'closed'
                   AND pnl IS NOT NULL''',
                (symbol, action)
            )
            row = cursor.fetchone()
            conn.close()

            if not row or row[0] < 3:
                return 0  # not enough history

            total, wins = row
            win_rate = wins / total
            raw = round((win_rate - 0.5) * 2 * 10)  # -10..+10
            return max(-10, min(10, raw))
        except Exception as e:
            logger.debug(f"Symbol stats boost error for {symbol}: {e}")
            return 0
