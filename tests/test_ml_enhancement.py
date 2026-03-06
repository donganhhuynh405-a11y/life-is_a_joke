"""
Tests for ML Signal Enhancement components.
"""
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ml.news_sentiment import NewsSentimentAnalyzer  # noqa: E402
from ml.pattern_matcher import PatternMatcher  # noqa: E402
from ml.signal_enhancer import MLSignalEnhancer  # noqa: E402


# ---------------------------------------------------------------------------
# NewsSentimentAnalyzer tests
# ---------------------------------------------------------------------------

class TestNewsSentimentAnalyzer:
    def _make_analyzer(self, news_items=None):
        """Helper: create analyzer with mocked news_aggregator."""
        aggregator = MagicMock()
        aggregator.get_recent_news_sync.return_value = news_items or []
        return NewsSentimentAnalyzer(db_path=':memory:', news_aggregator=aggregator)

    def test_empty_news_returns_zero_boost(self):
        analyzer = self._make_analyzer(news_items=[])
        result = analyzer.get_sentiment_boost('BTCUSDT', hours=6)
        assert result['confidence_boost'] == 0
        assert result['news_count'] == 0

    def test_bullish_news_gives_positive_boost(self):
        news = [
            {'title': 'Bitcoin surges to all-time high rally gains', 'content': ''},
            {'title': 'Bullish breakout detected in crypto market', 'content': ''},
            {'title': 'BTC adoption partnership positive growth', 'content': ''},
        ]
        analyzer = self._make_analyzer(news_items=news)
        result = analyzer.get_sentiment_boost('BTCUSDT', hours=6)
        assert result['confidence_boost'] > 0
        assert result['bullish_count'] > 0

    def test_bearish_news_gives_negative_boost(self):
        news = [
            {'title': 'Bitcoin crash dump plunge massive selloff', 'content': ''},
            {'title': 'Bearish sentiment fear panic in crypto', 'content': ''},
            {'title': 'Regulatory ban crackdown scam concerns', 'content': ''},
        ]
        analyzer = self._make_analyzer(news_items=news)
        result = analyzer.get_sentiment_boost('BTCUSDT', hours=6)
        assert result['confidence_boost'] < 0
        assert result['bearish_count'] > 0

    def test_boost_capped_at_max(self):
        news = [
            {'title': 'bullish rally surge pump moon breakout gains soar upgrade', 'content': ''}
            for _ in range(20)
        ]
        analyzer = self._make_analyzer(news_items=news)
        result = analyzer.get_sentiment_boost('BTCUSDT', hours=6)
        assert result['confidence_boost'] <= NewsSentimentAnalyzer.MAX_BOOST

    def test_boost_capped_at_min(self):
        news = [
            {'title': 'bearish crash dump plunge selloff fear panic ban fraud hack', 'content': ''}
            for _ in range(20)
        ]
        analyzer = self._make_analyzer(news_items=news)
        result = analyzer.get_sentiment_boost('BTCUSDT', hours=6)
        assert result['confidence_boost'] >= NewsSentimentAnalyzer.MIN_BOOST

    def test_single_article_returns_zero_boost(self):
        """Require at least 2 articles for a boost."""
        news = [{'title': 'Bitcoin surges rally gains breakout', 'content': ''}]
        analyzer = self._make_analyzer(news_items=news)
        result = analyzer.get_sentiment_boost('BTCUSDT', hours=6)
        assert result['confidence_boost'] == 0

    def test_aggregator_failure_returns_neutral(self):
        """If aggregator raises, result should be neutral (no boost)."""
        aggregator = MagicMock()
        aggregator.get_recent_news_sync.side_effect = RuntimeError("network error")
        analyzer = NewsSentimentAnalyzer(db_path=':memory:', news_aggregator=aggregator)
        result = analyzer.get_sentiment_boost('BTCUSDT', hours=6)
        assert result['confidence_boost'] == 0

    def test_result_has_required_keys(self):
        analyzer = self._make_analyzer()
        result = analyzer.get_sentiment_boost('BTCUSDT')
        assert 'sentiment_score' in result
        assert 'confidence_boost' in result
        assert 'news_count' in result
        assert 'bullish_count' in result
        assert 'bearish_count' in result


# ---------------------------------------------------------------------------
# PatternMatcher tests
# ---------------------------------------------------------------------------

class TestPatternMatcher:
    def _make_matcher(self, db_rows=None):
        """Helper: create matcher with patched DB fetch."""
        matcher = PatternMatcher(db_path=':memory:')
        matcher._fetch_closed_positions = MagicMock(return_value=db_rows or [])
        return matcher

    def _make_positions(self, rsi, macd, trend, volatility, pnl, count):
        return [
            {'rsi': rsi, 'macd': macd, 'trend': trend, 'volatility': volatility, 'pnl': pnl}
            for _ in range(count)
        ]

    def test_no_history_returns_zero_boost(self):
        matcher = self._make_matcher(db_rows=[])
        result = matcher.find_similar_patterns({'rsi': 40, 'macd': 0.5, 'trend': 'bullish', 'volatility': 100})
        assert result['confidence_boost'] == 0
        assert result['matches'] == 0

    def test_winning_patterns_give_positive_boost(self):
        positions = self._make_positions(42, 0.5, 'bullish', 100, pnl=50, count=5)
        matcher = self._make_matcher(db_rows=positions)
        current = {'rsi': 40, 'macd': 0.3, 'trend': 'bullish', 'volatility': 100}
        result = matcher.find_similar_patterns(current)
        assert result['matches'] >= PatternMatcher.MIN_MATCHES
        assert result['confidence_boost'] > 0

    def test_losing_patterns_give_negative_boost(self):
        positions = self._make_positions(42, 0.5, 'bullish', 100, pnl=-50, count=5)
        matcher = self._make_matcher(db_rows=positions)
        current = {'rsi': 40, 'macd': 0.3, 'trend': 'bullish', 'volatility': 100}
        result = matcher.find_similar_patterns(current)
        assert result['matches'] >= PatternMatcher.MIN_MATCHES
        assert result['confidence_boost'] < 0

    def test_boost_within_bounds(self):
        positions = self._make_positions(40, 1.0, 'bullish', 100, pnl=100, count=10)
        matcher = self._make_matcher(db_rows=positions)
        current = {'rsi': 40, 'macd': 1.0, 'trend': 'bullish', 'volatility': 100}
        result = matcher.find_similar_patterns(current)
        assert PatternMatcher.MIN_BOOST <= result['confidence_boost'] <= PatternMatcher.MAX_BOOST

    def test_fewer_than_min_matches_returns_zero_boost(self):
        # Only 2 similar patterns (below MIN_MATCHES=3)
        positions = self._make_positions(42, 0.5, 'bullish', 100, pnl=50, count=2)
        matcher = self._make_matcher(db_rows=positions)
        current = {'rsi': 40, 'macd': 0.3, 'trend': 'bullish', 'volatility': 100}
        result = matcher.find_similar_patterns(current)
        assert result['confidence_boost'] == 0

    def test_rsi_dissimilar_not_matched(self):
        """Patterns where RSI and MACD both differ should not reach similarity threshold."""
        # RSI differs by 50, MACD sign opposite → only trend + vol match (2/4 = 50% < 70%)
        positions = self._make_positions(80, -0.5, 'bullish', 100, pnl=50, count=5)
        matcher = self._make_matcher(db_rows=positions)
        current = {'rsi': 30, 'macd': 0.3, 'trend': 'bullish', 'volatility': 100}
        result = matcher.find_similar_patterns(current)
        assert result['confidence_boost'] == 0

    def test_result_has_required_keys(self):
        matcher = self._make_matcher()
        result = matcher.find_similar_patterns({'rsi': 50, 'macd': 0, 'trend': 'neutral'})
        assert 'matches' in result
        assert 'wins' in result
        assert 'avg_pnl' in result
        assert 'confidence_boost' in result

    def test_caching(self):
        positions = self._make_positions(42, 0.5, 'bullish', 100, pnl=50, count=5)
        matcher = self._make_matcher(db_rows=positions)
        current = {'rsi': 40, 'macd': 0.3, 'trend': 'bullish', 'volatility': 100}
        result1 = matcher.find_similar_patterns(current)
        result2 = matcher.find_similar_patterns(current)
        # DB should only be fetched once due to caching
        assert matcher._fetch_closed_positions.call_count == 1
        assert result1 == result2


# ---------------------------------------------------------------------------
# MLSignalEnhancer tests
# ---------------------------------------------------------------------------

class TestMLSignalEnhancer:
    def _make_enhancer(self, news_boost=0, pattern_boost=0, symbol_boost=0):
        """Create enhancer with all ML sub-components mocked."""
        enhancer = MLSignalEnhancer(db_path=':memory:')
        enhancer.news_sentiment = MagicMock()
        enhancer.news_sentiment.get_sentiment_boost.return_value = {
            'confidence_boost': news_boost,
            'news_count': 5,
            'bullish_count': max(0, news_boost),
            'bearish_count': max(0, -news_boost),
            'sentiment_score': news_boost / 10.0,
        }
        enhancer.pattern_matcher = MagicMock()
        enhancer.pattern_matcher.find_similar_patterns.return_value = {
            'confidence_boost': pattern_boost,
            'matches': 4,
            'wins': 3,
            'avg_pnl': 45.0,
        }
        enhancer.pattern_matcher.get_symbol_stats_boost.return_value = symbol_boost
        return enhancer

    def test_basic_enhancement(self):
        enhancer = self._make_enhancer(news_boost=5, pattern_boost=7, symbol_boost=0)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 63}
        result = enhancer.enhance_signal(signal)
        assert result['base_confidence'] == 63
        assert result['ml_adjustment'] == 12
        assert result['final_confidence'] == 75

    def test_adjustment_capped_at_plus_20(self):
        enhancer = self._make_enhancer(news_boost=10, pattern_boost=10, symbol_boost=10)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 70}
        result = enhancer.enhance_signal(signal)
        assert result['ml_adjustment'] <= 20
        assert result['final_confidence'] <= 100

    def test_adjustment_capped_at_minus_20(self):
        enhancer = self._make_enhancer(news_boost=-10, pattern_boost=-10, symbol_boost=-10)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 60}
        result = enhancer.enhance_signal(signal)
        assert result['ml_adjustment'] >= -20

    def test_final_confidence_never_exceeds_100(self):
        enhancer = self._make_enhancer(news_boost=10, pattern_boost=10, symbol_boost=0)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 95}
        result = enhancer.enhance_signal(signal)
        assert result['final_confidence'] <= 100

    def test_final_confidence_never_below_zero(self):
        enhancer = self._make_enhancer(news_boost=-10, pattern_boost=-10, symbol_boost=0)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 50}
        result = enhancer.enhance_signal(signal)
        assert result['final_confidence'] >= 0

    def test_low_confidence_skips_ml(self):
        """Signals below MIN_TECHNICAL_SCORE are not enhanced."""
        enhancer = self._make_enhancer(news_boost=10, pattern_boost=10, symbol_boost=5)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 40}
        result = enhancer.enhance_signal(signal)
        assert result['ml_adjustment'] == 0
        assert result['final_confidence'] == 40
        assert result['ml_reasoning'] is None

    def test_fallback_on_ml_failure(self):
        """If ML fails, passthrough with original confidence."""
        enhancer = MLSignalEnhancer(db_path=':memory:')
        enhancer.news_sentiment = MagicMock()
        enhancer.news_sentiment.get_sentiment_boost.side_effect = RuntimeError("fail")
        enhancer.pattern_matcher = MagicMock()
        enhancer.pattern_matcher.find_similar_patterns.return_value = {
            'confidence_boost': 5, 'matches': 3, 'wins': 2, 'avg_pnl': 10.0
        }
        enhancer.pattern_matcher.get_symbol_stats_boost.return_value = 0
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 65}
        result = enhancer.enhance_signal(signal)
        assert result['ml_adjustment'] == 0
        assert result['final_confidence'] == 65
        assert result['ml_reasoning'] is None

    def test_ml_reasoning_present_when_enhanced(self):
        enhancer = self._make_enhancer(news_boost=5, pattern_boost=7, symbol_boost=0)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 63}
        result = enhancer.enhance_signal(signal)
        reasoning = result['ml_reasoning']
        assert reasoning is not None
        assert 'news_sentiment' in reasoning
        assert 'pattern_match' in reasoning
        assert 'symbol_stats' in reasoning

    def test_scenario_bullish(self):
        """Technical 63 + News +8 + Patterns +5 = capped at +13 = 76."""
        enhancer = self._make_enhancer(news_boost=8, pattern_boost=5, symbol_boost=0)
        signal = {'symbol': 'SOLUSDT', 'action': 'BUY', 'confidence': 63}
        result = enhancer.enhance_signal(signal)
        assert result['final_confidence'] == 76

    def test_scenario_bearish_news(self):
        """Technical 65 + News -10 + Patterns -3 = -13 adjustment → 52."""
        enhancer = self._make_enhancer(news_boost=-10, pattern_boost=-3, symbol_boost=0)
        signal = {'symbol': 'ETHUSDT', 'action': 'BUY', 'confidence': 65}
        result = enhancer.enhance_signal(signal)
        assert result['final_confidence'] == 52

    def test_scenario_no_news(self):
        """Technical 70 + Pattern +5 = 75."""
        enhancer = self._make_enhancer(news_boost=0, pattern_boost=5, symbol_boost=0)
        signal = {'symbol': 'BTCUSDT', 'action': 'BUY', 'confidence': 70}
        result = enhancer.enhance_signal(signal)
        assert result['final_confidence'] == 75

    def test_market_state_passed_to_pattern_matcher(self):
        enhancer = self._make_enhancer()
        market_state = {'rsi': 38, 'macd': 0.5, 'trend': 'bullish', 'volatility': 150}
        signal = {
            'symbol': 'BTCUSDT',
            'action': 'BUY',
            'confidence': 63,
            'market_state': market_state,
        }
        enhancer.enhance_signal(signal)
        call_args = enhancer.pattern_matcher.find_similar_patterns.call_args
        assert call_args is not None
        passed_state = call_args[0][0]
        assert passed_state.get('rsi') == 38
