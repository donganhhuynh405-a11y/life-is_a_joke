"""
News Strategy Integrator for Crypto Trading Bot
Integrates news sentiment into trading strategies
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger('bot.news_strategy_integrator')


class NewsStrategyIntegrator:
    """
    Integrates news sentiment analysis into trading strategies

    Provides signals and recommendations based on news sentiment
    """

    def __init__(self):
        """Initialize the news strategy integrator"""
        logger.info("NewsStrategyIntegrator initialized")

    def get_news_signal(self, sentiment_data: Dict, symbol: str = None) -> Dict[str, any]:
        """
        Get trading signal based on news sentiment

        Args:
            sentiment_data: Sentiment analysis results
            symbol: Optional trading pair symbol to filter news

        Returns:
            Dictionary with signal and strength
        """
        if not sentiment_data:
            return {'signal': 'neutral', 'strength': 0.0, 'reason': 'No news data'}

        overall = sentiment_data.get('overall_sentiment', 'neutral')
        score = sentiment_data.get('average_score', 0.0)
        bullish = sentiment_data.get('bullish_count', 0)
        bearish = sentiment_data.get('bearish_count', 0)
        total = sentiment_data.get('total_analyzed', 0)

        # Calculate signal strength (0 to 1)
        strength = min(abs(score), 1.0)

        # Generate signal
        if overall == 'bullish' and bullish > bearish * 1.5:
            signal = 'buy'
            reason = f"Strong bullish news flow ({bullish} bullish vs {bearish} bearish)"
        elif overall == 'bearish' and bearish > bullish * 1.5:
            signal = 'sell'
            reason = f"Strong bearish news flow ({bearish} bearish vs {bullish} bullish)"
        elif overall == 'bullish':
            signal = 'buy'
            reason = f"Bullish sentiment ({bullish} bullish news)"
        elif overall == 'bearish':
            signal = 'sell'
            reason = f"Bearish sentiment ({bearish} bearish news)"
        else:
            signal = 'neutral'
            reason = f"Mixed or neutral sentiment ({bullish} bullish, {bearish} bearish)"

        return {
            'signal': signal,
            'strength': strength,
            'reason': reason,
            # More news = higher confidence
            'confidence': strength * (total / 10.0) if total > 0 else 0.0
        }

    def get_position_size_adjustment(self, sentiment_data: Dict) -> float:
        """
        Get position size adjustment based on news sentiment

        Args:
            sentiment_data: Sentiment analysis results

        Returns:
            Adjustment multiplier (0.5 to 1.5)
        """
        if not sentiment_data:
            return 1.0

        overall = sentiment_data.get('overall_sentiment', 'neutral')
        score = abs(sentiment_data.get('average_score', 0.0))

        # Adjust position size based on sentiment strength
        if overall in ['bullish', 'bearish'] and score > 0.5:
            # Strong sentiment: increase position size by up to 50%
            return 1.0 + (score * 0.5)
        elif overall == 'neutral' or score < 0.2:
            # Weak/neutral sentiment: reduce position size
            return 0.7
        else:
            # Moderate sentiment: normal position size
            return 1.0

    def should_avoid_trading(self, sentiment_data: Dict) -> tuple[bool, str]:
        """
        Determine if trading should be avoided based on news

        Args:
            sentiment_data: Sentiment analysis results

        Returns:
            Tuple of (should_avoid, reason)
        """
        if not sentiment_data:
            return False, ""

        bearish = sentiment_data.get('bearish_count', 0)
        total = sentiment_data.get('total_analyzed', 0)
        score = sentiment_data.get('average_score', 0.0)

        # Avoid trading if overwhelming negative news
        if bearish > 5 and score < -0.6:
            return True, f"Overwhelming negative news ({bearish} bearish articles, score: {score:.2f})"

        # Avoid trading if too few news items for reliable signal
        if total < 2:
            return False, ""  # Don't block trading, just no signal

        return False, ""

    def get_recommendation(
            self,
            sentiment_data: Dict,
            current_position: Optional[Dict] = None) -> str:
        """
        Get trading recommendation based on news and current position

        Args:
            sentiment_data: Sentiment analysis results
            current_position: Optional current position info

        Returns:
            Human-readable recommendation string
        """
        if not sentiment_data:
            return "No news data available - rely on technical analysis"

        signal_data = self.get_news_signal(sentiment_data)
        signal = signal_data['signal']
        strength = signal_data['strength']
        reason = signal_data['reason']

        should_avoid, avoid_reason = self.should_avoid_trading(sentiment_data)

        if should_avoid:
            return f"⚠️ Avoid trading: {avoid_reason}"

        if signal == 'buy' and strength > 0.5:
            return f"💡 {reason} - favorable for longs"
        elif signal == 'sell' and strength > 0.5:
            return f"⚠️ {reason} - caution on longs"
        elif signal == 'neutral':
            return f"📊 {reason} - follow technical signals"
        else:
            return f"📰 {reason}"
