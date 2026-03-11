"""
src/mi/online_learner.py — Real-time Online Learning Engine

Continuously adapts pre-trained models using:
  1. Fresh candle data fetched from the exchange every cycle
  2. News sentiment scores read from the local SQLite database

How it works
------------
Every *interval* seconds the engine:
  a. Fetches the last ~200 candles for each symbol via
     HistoricalDataFetcher.update_cached_data().
  b. Reads recent news from the news DB and computes a per-symbol
     sentiment score in [-1, 1].
  c. Combines the price direction over the last cycle with the news
     sentiment to derive a *training signal* (outcome):
       +1 → price went up  AND sentiment ≥ threshold  → BUY correct
       -1 → price went down AND sentiment ≤ -threshold → SELL correct
        0 → conflicting / weak signal → HOLD / skip
  d. Calls MarketSpecificTrainer.fine_tune_from_trade() with that signal
     so the model accumulates verified real-market outcomes in its
     fine-tune buffer and triggers a warm-start update every 50 samples.
  e. Logs per-symbol outcomes and a running update counter so operators
     can confirm real learning is happening (not mock data).

Usage (from scripts/run_online_learning.py):

    learner = OnlineLearner(exchange, symbols, db_path, models_dir)
    await learner.run()          # blocks indefinitely (Ctrl-C to stop)
"""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .historical_data_fetcher import HistoricalDataFetcher
from .market_specific_trainer import MarketSpecificTrainer

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum sentiment score magnitude to count as a directional signal
SENTIMENT_THRESHOLD = 0.15

# Number of candles to use as the "look-back" window for price direction
PRICE_LOOKBACK_CANDLES = 3

# Default interval between adaptation cycles (seconds)
DEFAULT_INTERVAL = 3600  # 1 hour


# ── News helpers ───────────────────────────────────────────────────────────────

def _fetch_sentiment_from_db(
    db_path: str,
    symbol: str,
    hours: int = 2,
) -> float:
    """
    Read the average news sentiment score for *symbol* from the SQLite DB
    created by news.news_aggregator.NewsAggregator.

    Returns a score in [-1, 1]:
        positive → bullish news dominates
        negative → bearish news dominates
        0.0      → no news found or neutral

    This function is synchronous and safe to call from an async context via
    asyncio.to_thread().
    """
    try:
        db_file = Path(db_path)
        if not db_file.exists():
            return 0.0

        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()

        # Convert the symbol base asset to a search term (e.g. BTCUSDT → BTC)
        base = symbol.replace("USDT", "").replace("BTC", "").strip()
        if not base:
            base = symbol[:3]

        since = (
            datetime.now(tz=timezone.utc) - timedelta(hours=hours)
        ).isoformat()

        # crypto_news table has columns: title, content, sentiment_score, symbols, published_at
        cursor.execute(
            """
            SELECT sentiment_score
            FROM   crypto_news
            WHERE  (symbols LIKE ? OR title LIKE ?)
               AND published_at >= ?
               AND sentiment_score IS NOT NULL
            """,
            (f"%{base}%", f"%{base}%", since),
        )

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return 0.0

        scores = [r[0] for r in rows if r[0] is not None]
        return float(sum(scores) / len(scores)) if scores else 0.0

    except Exception as exc:
        logger.debug(f"_fetch_sentiment_from_db({symbol}): {exc}")
        return 0.0


# ── Core engine ────────────────────────────────────────────────────────────────

class OnlineLearner:
    """
    Real-time continuous model adaptation using candles + news sentiment.

    Parameters
    ----------
    exchange : ExchangeAdapter
        Live exchange connection (used only for candle fetching).
    symbols : list[str]
        Symbols to adapt (e.g. ["BTCUSDT", "ETHUSDT"]).
    db_path : str
        Path to the SQLite database used by NewsAggregator.
    models_dir : str
        Directory where MarketSpecificTrainer stores model files.
    timeframe : str
        Candle interval passed to the data fetcher (default "1h").
    interval : int
        Seconds between adaptation cycles (default 3600 = 1 hour).
    news_hours : int
        Look-back window for news sentiment (default 2 hours).
    """

    def __init__(
        self,
        exchange,
        symbols: List[str],
        db_path: str = "/var/lib/trading-bot/trading_bot.db",
        models_dir: str = "/var/lib/trading-bot/models",
        timeframe: str = "1h",
        interval: int = DEFAULT_INTERVAL,
        news_hours: int = 2,
    ):
        self.exchange = exchange
        self.symbols = symbols
        self.db_path = db_path
        self.models_dir = models_dir
        self.timeframe = timeframe
        self.interval = interval
        self.news_hours = news_hours

        self.fetcher = HistoricalDataFetcher(exchange)
        self.trainer = MarketSpecificTrainer(models_dir=models_dir)

        # Running counters exposed for monitoring
        self.cycle_count: int = 0
        self.total_updates: int = 0  # successful fine-tune calls across all cycles
        self.per_symbol_updates: Dict[str, int] = {s: 0 for s in symbols}
        self.last_cycle_at: Optional[datetime] = None

        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the adaptation loop indefinitely until cancelled."""
        self._running = True
        logger.info("=" * 70)
        logger.info("🔄 ONLINE LEARNING ENGINE STARTED")
        logger.info(f"   Symbols  : {', '.join(self.symbols)}")
        logger.info(f"   Timeframe: {self.timeframe}")
        logger.info(f"   Interval : {self.interval}s")
        logger.info(f"   News look-back: {self.news_hours}h")
        logger.info("=" * 70)

        try:
            while self._running:
                await self._run_one_cycle()
                if self._running:
                    logger.info(
                        f"💤 Sleeping {self.interval}s until next cycle "
                        f"(Cycle #{self.cycle_count} done, total updates={self.total_updates})"
                    )
                    await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            logger.info("Online learner cancelled.")
        finally:
            self._running = False
            logger.info(
                f"🏁 Online learner stopped. Cycles={self.cycle_count}, "
                f"Total fine-tune calls={self.total_updates}"
            )

    def stop(self) -> None:
        """Signal the run loop to stop after the current cycle."""
        self._running = False

    async def run_once(self) -> Dict:
        """Run a single adaptation cycle and return a summary dict."""
        return await self._run_one_cycle()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_one_cycle(self) -> Dict:
        """Execute one full adaptation cycle across all symbols."""
        self.cycle_count += 1
        started = datetime.now()
        logger.info(
            f"\n{'─' * 60}"
            f"\n🔄 ONLINE LEARNING CYCLE #{self.cycle_count}  [{started:%Y-%m-%d %H:%M:%S}]"
            f"\n{'─' * 60}"
        )

        cycle_results: Dict[str, str] = {}

        for symbol in self.symbols:
            result = await self._adapt_symbol(symbol)
            cycle_results[symbol] = result

        self.last_cycle_at = datetime.now()
        elapsed = (self.last_cycle_at - started).total_seconds()

        updated = sum(1 for v in cycle_results.values() if v == "updated")
        logger.info(
            f"✅ Cycle #{self.cycle_count} complete in {elapsed:.1f}s — "
            f"updated {updated}/{len(self.symbols)} symbols"
        )

        summary = {
            "cycle": self.cycle_count,
            "timestamp": self.last_cycle_at.isoformat(),
            "elapsed_s": elapsed,
            "updated": updated,
            "skipped": sum(1 for v in cycle_results.values() if v == "skipped"),
            "failed": sum(1 for v in cycle_results.values() if "failed" in v),
            "details": cycle_results,
        }

        self._write_status(summary)
        return summary

    async def _adapt_symbol(self, symbol: str) -> str:
        """
        Perform one adaptation step for a single symbol.
        Returns "updated", "skipped", or "failed:<reason>".
        """
        # ── 1. Check model exists ────────────────────────────────────────
        model_info = self.trainer.get_model_info(symbol)
        if model_info is None:
            logger.debug(f"[{symbol}] No trained model — skipping online adaptation")
            return "skipped:no_model"

        # ── 2. Fetch recent candles ──────────────────────────────────────
        try:
            df = await self.fetcher.update_cached_data(symbol, self.timeframe)
        except Exception as exc:
            logger.warning(f"[{symbol}] Candle fetch failed: {exc}")
            return f"failed:candle_fetch({exc})"

        if df is None or len(df) < self.trainer.lookback_period + PRICE_LOOKBACK_CANDLES:
            logger.debug(f"[{symbol}] Insufficient candle data ({len(df) if df is not None else 0} rows)")
            return "skipped:insufficient_data"

        # ── 3. Compute price direction over last N candles ───────────────
        close = df["close"]
        base_price = close.iloc[-1 - PRICE_LOOKBACK_CANDLES] or 1e-9
        price_change_pct = (close.iloc[-1] - base_price) / base_price

        # ── 4. Fetch news sentiment ──────────────────────────────────────
        sentiment_score = await asyncio.to_thread(
            _fetch_sentiment_from_db,
            self.db_path,
            symbol,
            self.news_hours,
        )

        # ── 5. Derive training signal ────────────────────────────────────
        # We only produce a high-confidence signal when candle direction and
        # news sentiment both point the same way.
        outcome = _derive_outcome(price_change_pct, sentiment_score)

        logger.info(
            f"[{symbol}] Δprice={price_change_pct:+.4f}  "
            f"sentiment={sentiment_score:+.3f}  outcome={outcome:+d}"
        )

        if outcome == 0:
            return "skipped:no_clear_signal"

        # ── 6. Fine-tune ─────────────────────────────────────────────────
        ok = self.trainer.fine_tune_from_trade(
            symbol=symbol,
            recent_df=df,
            trade_outcome=outcome,
        )

        if ok:
            self.total_updates += 1
            self.per_symbol_updates[symbol] = self.per_symbol_updates.get(symbol, 0) + 1
            logger.info(
                f"[{symbol}] ✅ Fine-tune sample added "
                f"(symbol total={self.per_symbol_updates[symbol]}, "
                f"engine total={self.total_updates})"
            )
            return "updated"
        else:
            return "failed:fine_tune"

    def _write_status(self, summary: Dict) -> None:
        """Persist latest cycle summary to disk for monitoring."""
        try:
            status_path = Path(self.models_dir) / "online_learning_status.json"
            status_path.parent.mkdir(parents=True, exist_ok=True)

            payload = {
                **summary,
                "per_symbol_updates": dict(self.per_symbol_updates),
                "total_updates": self.total_updates,
            }
            status_path.write_text(json.dumps(payload, indent=2, default=str))
        except Exception as exc:
            logger.debug(f"Could not write online learning status: {exc}")


# Minimum price change magnitude (as a fraction) to count as a directional move
PRICE_CHANGE_THRESHOLD = 0.002  # 0.2 %


# ── Signal derivation ──────────────────────────────────────────────────────────

def _derive_outcome(price_change_pct: float, sentiment_score: float) -> int:
    """
    Map (price_change_pct, sentiment_score) → training signal.

    Returns:
         1  — BUY direction was correct (price up + bullish OR just price up)
        -1  — SELL direction was correct (price down + bearish OR just price down)
         0  — signal too weak or conflicting
    """
    price_bullish = price_change_pct > PRICE_CHANGE_THRESHOLD
    price_bearish = price_change_pct < -PRICE_CHANGE_THRESHOLD
    news_bullish = sentiment_score >= SENTIMENT_THRESHOLD
    news_bearish = sentiment_score <= -SENTIMENT_THRESHOLD

    if price_bullish and news_bullish:
        return 1   # Strong BUY confirmation from both sources
    if price_bearish and news_bearish:
        return -1  # Strong SELL confirmation from both sources
    if price_bullish and not news_bearish:
        return 1   # Price up, no bearish news to contradict
    if price_bearish and not news_bullish:
        return -1  # Price down, no bullish news to contradict

    return 0  # Conflicting / too weak
