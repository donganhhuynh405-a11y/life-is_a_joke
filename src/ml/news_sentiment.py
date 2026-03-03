"""
News Sentiment Analyzer for ML Signal Enhancement

Analyzes crypto news sentiment to provide confidence adjustments for trading signals.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


class NewsSentimentAnalyzer:
    """
    Analyzes recent crypto news sentiment and suggests confidence adjustments.

    Uses keyword-based sentiment scoring on news retrieved from the database.
    Adjustment range: -10 to +10 to prevent over-reliance on news alone.
    """

    BULLISH_KEYWORDS = [
        'bullish', 'rally', 'surge', 'pump', 'moon', 'breakout',
        'breakthrough', 'all-time high', 'ath', 'gains', 'soar',
        'upgrade', 'adoption', 'partnership', 'integration', 'positive',
        'growth', 'rise', 'increase', 'profit', 'success', 'recovery',
        'rebound', 'accumulate', 'buy', 'long'
    ]

    BEARISH_KEYWORDS = [
        'bearish', 'crash', 'dump', 'plunge', 'fall', 'decline',
        'drop', 'correction', 'selloff', 'sell-off', 'fear', 'panic',
        'hack', 'scam', 'fraud', 'regulatory', 'ban', 'crackdown',
        'concerns', 'negative', 'loss', 'losses', 'fails', 'collapse',
        'warning', 'risk', 'liquidation', 'short'
    ]

    MAX_BOOST = 10
    MIN_BOOST = -10

    def __init__(self, db_path: str = '/var/lib/trading-bot/trading_bot.db',
                 news_aggregator=None):
        """
        Initialize the news sentiment analyzer.

        Args:
            db_path: Path to the SQLite database with news data.
            news_aggregator: Optional NewsAggregator instance for fetching news.
        """
        self.db_path = db_path
        self.news_aggregator = news_aggregator

    def _analyze_text_sentiment(self, text: str) -> str:
        """Return 'bullish', 'bearish', or 'neutral' for given text."""
        if not text:
            return 'neutral'
        text_lower = text.lower()
        bullish = sum(1 for kw in self.BULLISH_KEYWORDS if kw in text_lower)
        bearish = sum(1 for kw in self.BEARISH_KEYWORDS if kw in text_lower)
        if bullish > bearish:
            return 'bullish'
        if bearish > bullish:
            return 'bearish'
        return 'neutral'

    def _fetch_recent_news(self, symbol: str, hours: int) -> List[Dict]:
        """Fetch recent news from database or news_aggregator."""
        if self.news_aggregator is not None:
            try:
                # Use sync wrapper if available
                if hasattr(self.news_aggregator, 'get_recent_news_sync'):
                    return self.news_aggregator.get_recent_news_sync(hours=hours, symbol=symbol)
            except Exception as e:
                logger.warning(f"News aggregator fetch failed: {e}")

        # Fallback: query database directly
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
            base_symbol = symbol.replace('USDT', '').replace('BTC', '')
            cursor.execute(
                '''SELECT title, content FROM crypto_news
                   WHERE published_at >= ?
                   AND (symbols LIKE ? OR title LIKE ? OR content LIKE ?)
                   ORDER BY published_at DESC''',
                (cutoff, f'%{base_symbol}%', f'%{base_symbol}%', f'%{base_symbol}%')
            )
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.debug(f"DB news fetch failed: {e}")
            return []

    def get_sentiment_boost(self, symbol: str, hours: int = 6) -> Dict:
        """
        Analyze recent news sentiment and return a confidence adjustment.

        Args:
            symbol: Trading pair symbol (e.g. 'BTCUSDT').
            hours: How many hours back to look for news (default 6).

        Returns:
            Dict with keys: sentiment_score, confidence_boost, news_count,
                            bullish_count, bearish_count.
        """
        try:
            news_items = self._fetch_recent_news(symbol, hours)

            bullish_count = 0
            bearish_count = 0

            for item in news_items:
                text = (item.get('title') or '') + ' ' + (item.get('content') or '')
                sentiment = self._analyze_text_sentiment(text)
                if sentiment == 'bullish':
                    bullish_count += 1
                elif sentiment == 'bearish':
                    bearish_count += 1

            news_count = len(news_items)
            total_tagged = bullish_count + bearish_count

            if total_tagged == 0:
                sentiment_score = 0.0
                confidence_boost = 0
            else:
                sentiment_score = (bullish_count - bearish_count) / total_tagged
                # Scale to -10..+10 range
                raw_boost = round(sentiment_score * self.MAX_BOOST)
                confidence_boost = max(self.MIN_BOOST, min(self.MAX_BOOST, raw_boost))

                # Apply minimum threshold: require at least 2 articles to boost/penalise
                if news_count < 2:
                    confidence_boost = 0
                    sentiment_score = 0.0

            logger.debug(
                f"News sentiment for {symbol}: {bullish_count} bullish, "
                f"{bearish_count} bearish → boost {confidence_boost:+d}"
            )

            return {
                'sentiment_score': round(sentiment_score, 3),
                'confidence_boost': confidence_boost,
                'news_count': news_count,
                'bullish_count': bullish_count,
                'bearish_count': bearish_count,
            }

        except Exception as e:
            logger.error(f"Error analyzing news sentiment for {symbol}: {e}", exc_info=True)
            return {
                'sentiment_score': 0.0,
                'confidence_boost': 0,
                'news_count': 0,
                'bullish_count': 0,
                'bearish_count': 0,
            }
