"""
News Aggregator for Crypto Trading Bot
Collects news from multiple sources and stores them for analysis
"""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sqlite3
import json
import hashlib
from news.news_sentiment_analyzer import NewsSentimentAnalyzer

logger = logging.getLogger('bot.news_aggregator')


class NewsAggregator:
    """
    Aggregates crypto news from multiple sources

    Supported sources:
    - CryptoPanic API (https://cryptopanic.com/developers/api/)
    - NewsAPI (https://newsapi.org/)
    - RSS Feeds (CoinDesk, CoinTelegraph)
    """

    def __init__(self, db_path: str = '/var/lib/trading-bot/trading_bot.db',
                 config: Optional[Dict] = None):
        self.db_path = db_path
        self.config = config or {}

        # API keys from config
        self.cryptopanic_key = self.config.get('CRYPTOPANIC_API_KEY', '')
        self.newsapi_key = self.config.get('NEWSAPI_API_KEY', '')

        # Initialize sentiment analyzer
        self.sentiment_analyzer = NewsSentimentAnalyzer()

        # Sources configuration
        self.sources = {
            'cryptopanic': {
                'enabled': bool(self.cryptopanic_key),
                'url': 'https://cryptopanic.com/api/v1/posts/',
                'priority': 1
            },
            'newsapi': {
                'enabled': bool(self.newsapi_key),
                'url': 'https://newsapi.org/v2/everything',
                'priority': 2
            },
            'rss': {
                'enabled': True,
                'feeds': [
                    'https://cointelegraph.com/rss',
                    'https://www.coindesk.com/arc/outboundfeeds/rss/',
                ],
                'priority': 3
            }
        }

        self.running = False
        self.update_interval = 300  # 5 minutes

        # Initialize database
        self._init_database()

    def _init_database(self):
        """Initialize news table in database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS crypto_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT,
                    url TEXT,
                    source TEXT NOT NULL,
                    published_at TIMESTAMP NOT NULL,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    symbols TEXT,
                    sentiment_score REAL,
                    importance_score REAL,
                    category TEXT,
                    metadata TEXT
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_news_published
                ON crypto_news(published_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_news_symbols
                ON crypto_news(symbols)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_news_sentiment
                ON crypto_news(sentiment_score)
            ''')

            conn.commit()
            conn.close()

            logger.info("News database initialized")
        except Exception as e:
            logger.error(f"Error initializing news database: {e}")

    async def start(self):
        """Start news aggregation loop"""
        self.running = True
        logger.info("News aggregator started")
        # Store the task so we can cancel it later
        self._aggregation_task = asyncio.create_task(self._aggregation_loop())

    def stop(self):
        """Stop news aggregation (synchronous)"""
        self.running = False

        # Cancel the aggregation task if it exists
        if hasattr(
                self,
                '_aggregation_task') and self._aggregation_task and not self._aggregation_task.done():
            self._aggregation_task.cancel()

        logger.info("News aggregator stopped")

    async def _aggregation_loop(self):
        """Main aggregation loop"""
        # Analyze existing news on first run
        await self._analyze_existing_news()

        while self.running:
            try:
                await self.fetch_all_news()
                await self._cleanup_old_news()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"Error in aggregation loop: {e}")
                await asyncio.sleep(60)

    async def fetch_all_news(self) -> List[Dict]:
        """Fetch news from all enabled sources"""
        all_news = []

        tasks = []
        if self.sources['cryptopanic']['enabled']:
            tasks.append(self._fetch_cryptopanic())
        if self.sources['newsapi']['enabled']:
            tasks.append(self._fetch_newsapi())
        if self.sources['rss']['enabled']:
            tasks.append(self._fetch_rss_feeds())

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    all_news.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error fetching news: {result}")

        saved_count = await self._save_news(all_news)
        logger.info(f"Fetched {len(all_news)} news, saved {saved_count} new items")

        return all_news

    async def _fetch_cryptopanic(self) -> List[Dict]:
        """Fetch news from CryptoPanic API"""
        if not self.cryptopanic_key:
            return []

        try:
            url = self.sources['cryptopanic']['url']
            params = {
                'auth_token': self.cryptopanic_key,
                'public': 'true',
                'kind': 'news',  # Only news, not social posts
                'filter': 'hot'   # Hot/trending news
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        news_items = []

                        for item in data.get('results', []):
                            news_item = {
                                'news_id': self._generate_id(item['url']),
                                'title': item.get('title', ''),
                                'content': item.get('title', ''),
                                'url': item.get('url', ''),
                                'source': 'cryptopanic',
                                'published_at': item.get('published_at', ''),
                                'symbols': ','.join([c['code'] for c in item.get('currencies', [])]),
                                'metadata': json.dumps({
                                    'votes': item.get('votes', {}),
                                    'domain': item.get('domain', '')
                                })
                            }
                            news_items.append(news_item)

                        return news_items
                    else:
                        logger.warning(f"CryptoPanic API returned status {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching from CryptoPanic: {e}")
            return []

    async def _fetch_newsapi(self) -> List[Dict]:
        """Fetch news from NewsAPI"""
        if not self.newsapi_key:
            return []

        try:
            url = self.sources['newsapi']['url']

            query = 'cryptocurrency OR bitcoin OR ethereum OR crypto OR blockchain'

            params = {
                'apiKey': self.newsapi_key,
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': 50,
                'from': (datetime.now() - timedelta(hours=24)).isoformat()
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        news_items = []

                        for article in data.get('articles', []):
                            source_name = article.get('source', {}).get('name', 'unknown')
                            news_item = {
                                'news_id': self._generate_id(article['url']),
                                'title': article.get('title', ''),
                                'content': (article.get('description', '')
                                            or article.get('content', '')),
                                'url': article.get('url', ''),
                                'source': f"newsapi:{source_name}",
                                'published_at': article.get('publishedAt', ''),
                                'symbols': self._extract_symbols(
                                    article.get('title', '') + ' '
                                    + article.get('description', '')),
                                'metadata': json.dumps({
                                    'author': article.get('author', ''),
                                    'source_name': article.get(
                                        'source', {}).get('name', ''),
                                }),
                            }
                            news_items.append(news_item)

                        return news_items
                    else:
                        logger.warning(f"NewsAPI returned status {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching from NewsAPI: {e}")
            return []

    async def _fetch_rss_feeds(self) -> List[Dict]:
        """Fetch news from RSS feeds"""
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser not installed, RSS feeds disabled")
            return []

        news_items = []

        for feed_url in self.sources['rss']['feeds']:
            try:
                loop = asyncio.get_event_loop()
                feed = await loop.run_in_executor(None, feedparser.parse, feed_url)

                for entry in feed.entries[:20]:
                    news_item = {
                        'news_id': self._generate_id(entry.get('link', entry.get('id', ''))),
                        'title': entry.get('title', ''),
                        'content': entry.get('summary', '') or entry.get('description', ''),
                        'url': entry.get('link', ''),
                        'source': f"rss:{feed.feed.get('title', feed_url)}",
                        'published_at': entry.get('published', entry.get('updated', '')),
                        'symbols': self._extract_symbols(entry.get('title', '') + ' ' + entry.get('summary', '')),
                        'metadata': json.dumps({
                            'feed_url': feed_url
                        })
                    }
                    news_items.append(news_item)
            except Exception as e:
                logger.error(f"Error fetching RSS feed {feed_url}: {e}")

        return news_items

    def _generate_id(self, url: str) -> str:
        """Generate unique ID for news item"""
        return hashlib.md5(url.encode()).hexdigest()

    def _extract_symbols(self, text: str) -> str:
        """Extract cryptocurrency symbols from text"""
        text_lower = text.lower()

        symbol_map = {
            'bitcoin': 'BTC',
            'btc': 'BTC',
            'ethereum': 'ETH',
            'eth': 'ETH',
            'solana': 'SOL',
            'sol': 'SOL',
            'cardano': 'ADA',
            'ada': 'ADA',
            'ripple': 'XRP',
            'xrp': 'XRP',
            'polkadot': 'DOT',
            'dot': 'DOT',
            'dogecoin': 'DOGE',
            'doge': 'DOGE',
            'shiba': 'SHIB',
            'shib': 'SHIB',
            'avalanche': 'AVAX',
            'avax': 'AVAX',
            'polygon': 'MATIC',
            'matic': 'MATIC',
        }

        found_symbols = set()
        for keyword, symbol in symbol_map.items():
            if keyword in text_lower:
                found_symbols.add(symbol)

        return ','.join(sorted(found_symbols))

    async def _save_news(self, news_items: List[Dict]) -> int:
        """Save news items to database with sentiment analysis"""
        if not news_items:
            return 0

        saved_count = 0
        sentiment_stats = {'bullish': 0, 'bearish': 0, 'neutral': 0}

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            for item in news_items:
                try:
                    # Analyze sentiment before saving
                    text_to_analyze = f"{item['title']} {item.get('content', '')}"
                    sentiment_result = self.sentiment_analyzer.analyze_sentiment(text_to_analyze)

                    sentiment_score = sentiment_result['score']
                    sentiment_stats[sentiment_result['sentiment']] += 1

                    cursor.execute('''
                        INSERT OR IGNORE INTO crypto_news
                        (news_id, title, content, url, source, published_at, symbols, sentiment_score, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        item['news_id'],
                        item['title'],
                        item['content'],
                        item['url'],
                        item['source'],
                        item['published_at'],
                        item['symbols'],
                        sentiment_score,
                        item.get('metadata', '')
                    ))

                    if cursor.rowcount > 0:
                        saved_count += 1
                except Exception as e:
                    logger.error(f"Error saving news item: {e}")

            conn.commit()
            conn.close()

            if saved_count > 0:
                logger.info(
                    f"Sentiment analysis: {sentiment_stats['bullish']} bullish, "
                    f"{sentiment_stats['bearish']} bearish, {sentiment_stats['neutral']} neutral")
        except Exception as e:
            logger.error(f"Error saving news to database: {e}")

        return saved_count

    async def _cleanup_old_news(self):
        """Remove news older than 7 days"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff_date = (datetime.now() - timedelta(days=7)).isoformat()
            cursor.execute('''
                DELETE FROM crypto_news
                WHERE published_at < ?
            ''', (cutoff_date,))

            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old news items")

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error cleaning up old news: {e}")

    async def _analyze_existing_news(self):
        """Analyze sentiment for existing news without sentiment scores"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Find news without sentiment scores
            cursor.execute('''
                SELECT id, title, content FROM crypto_news
                WHERE sentiment_score IS NULL
                LIMIT 100
            ''')

            rows = cursor.fetchall()
            if not rows:
                return

            logger.info(f"Analyzing sentiment for {len(rows)} existing news items...")

            for row in rows:
                news_id, title, content = row
                text_to_analyze = f"{title} {content or ''}"
                sentiment_result = self.sentiment_analyzer.analyze_sentiment(text_to_analyze)

                cursor.execute('''
                    UPDATE crypto_news
                    SET sentiment_score = ?
                    WHERE id = ?
                ''', (sentiment_result['score'], news_id))

            conn.commit()
            conn.close()

            logger.info(f"Updated sentiment for {len(rows)} existing news items")
        except Exception as e:
            logger.error(f"Error analyzing existing news: {e}")

    async def get_recent_news(self, hours: int = 24, symbol: Optional[str] = None) -> List[Dict]:
        """Get recent news from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cutoff_date = (datetime.now() - timedelta(hours=hours)).isoformat()

            if symbol:
                cursor.execute('''
                    SELECT * FROM crypto_news
                    WHERE published_at >= ?
                    AND (symbols LIKE ? OR symbols LIKE ? OR symbols LIKE ?)
                    ORDER BY published_at DESC
                ''', (cutoff_date, f'%{symbol}%', f'{symbol},%', f'%,{symbol}'))
            else:
                cursor.execute('''
                    SELECT * FROM crypto_news
                    WHERE published_at >= ?
                    ORDER BY published_at DESC
                ''', (cutoff_date,))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting recent news: {e}")
            return []

    async def get_news_summary(self, hours: int = 24) -> Dict:
        """Get summary statistics of recent news"""
        news = await self.get_recent_news(hours)

        if not news:
            return {
                'total_count': 0,
                'bullish_count': 0,
                'bearish_count': 0,
                'neutral_count': 0,
                'by_symbol': {}
            }

        summary = {
            'total_count': len(news),
            'bullish_count': sum(1 for n in news if n.get('sentiment_score', 0) > 0.2),
            'bearish_count': sum(1 for n in news if n.get('sentiment_score', 0) < -0.2),
            'neutral_count': sum(1 for n in news if -0.2 <= n.get('sentiment_score', 0) <= 0.2),
            'by_symbol': {}
        }

        # Count by symbol
        for item in news:
            symbols = item.get('symbols', '').split(',')
            for symbol in symbols:
                if symbol:
                    summary['by_symbol'][symbol] = summary['by_symbol'].get(symbol, 0) + 1

        return summary

    def get_recent_news_sync(self, hours: int = 24, symbol: Optional[str] = None) -> List[Dict]:
        """Synchronous wrapper for get_recent_news"""
        try:
            try:
                asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(self.get_recent_news(hours, symbol))
                    )
                    return future.result(timeout=10)
            except RuntimeError:
                return asyncio.run(self.get_recent_news(hours, symbol))
        except Exception as e:
            logger.error(f"Error in get_recent_news_sync: {e}")
            return []

    def get_news_summary_sync(self, hours: int = 24) -> Dict:
        """Synchronous wrapper for get_news_summary"""
        try:
            try:
                asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(self.get_news_summary(hours))
                    )
                    return future.result(timeout=10)
            except RuntimeError:
                return asyncio.run(self.get_news_summary(hours))
        except Exception as e:
            logger.error(f"Error in get_news_summary_sync: {e}")
            return {
                'total_count': 0,
                'bullish_count': 0,
                'bearish_count': 0,
                'neutral_count': 0,
                'by_symbol': {}
            }
