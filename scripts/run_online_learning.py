#!/usr/bin/env python3
"""
scripts/run_online_learning.py — Continuous Real-Time ML Adaptation

Keeps pre-trained models fresh by adapting them every hour (configurable)
using the latest candle data from the exchange AND news sentiment scores
from the local SQLite database populated by NewsAggregator.

Unlike run_training.py (which does a full historical pre-training run taking
hours), this script runs indefinitely in the background and performs fast
incremental fine-tuning cycles that take only a few seconds per symbol.

Usage
-----
    # Start the online learner (runs forever; Ctrl-C to stop)
    docker exec -it trading-bot python scripts/run_online_learning.py

    # Custom interval (e.g. every 30 minutes)
    docker exec -it trading-bot python scripts/run_online_learning.py --interval 1800

    # Specific symbols only
    docker exec -it trading-bot python scripts/run_online_learning.py \\
        --symbols BTCUSDT ETHUSDT

    # Run one cycle and exit (useful for cron / testing)
    docker exec -it trading-bot python scripts/run_online_learning.py --once

When to run
-----------
The online learner should be started ONCE after the initial run_training.py
has completed.  It can be left running permanently; the main bot process
already starts a 7-day retraining loop internally, but this script adds
HOURLY adaptation from fresh candles + news without needing a full retrain.

You do NOT need to restart the online learner after a bot code update unless
you also rebuild the Docker image (see verify_learning.py for guidance).
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow running from the project root without installing the package
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ── Default values ─────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
    "TRXUSDT", "LINKUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT",
    "NEARUSDT", "XLMUSDT", "SHIBUSDT", "ARBUSDT", "OPUSDT",
]

DEFAULT_INTERVAL = int(os.getenv("ONLINE_LEARNING_INTERVAL", "3600"))  # 1 hour
DEFAULT_DB_PATH = os.getenv("DB_PATH", "/var/lib/trading-bot/trading_bot.db")
DEFAULT_MODELS_DIR = os.getenv("ML_MODELS_DIR", "/var/lib/trading-bot/models")
DEFAULT_TIMEFRAME = "1h"


# ── Logging ────────────────────────────────────────────────────────────────────

def _setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ── Main ───────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> int:
    logger = logging.getLogger("run_online_learning")

    symbols = args.symbols or (
        [s.strip() for s in os.getenv("TRAINING_SYMBOLS", "").split(",") if s.strip()]
        or DEFAULT_SYMBOLS
    )

    logger.info("=" * 70)
    logger.info("🔄  ONLINE LEARNING LAUNCHER")
    logger.info("=" * 70)
    logger.info("Symbols    : %s", ", ".join(symbols))
    logger.info("Timeframe  : %s", args.timeframe)
    logger.info("Interval   : %ds", args.interval)
    logger.info("DB path    : %s", args.db_path)
    logger.info("Models dir : %s", args.models_dir)
    logger.info("Mode       : %s", "single cycle" if args.once else "continuous")
    logger.info("=" * 70)
    logger.info("")
    logger.info("ℹ️  This script adapts pre-trained models with fresh candle + news data.")
    logger.info("   Run  scripts/run_training.py  FIRST if models don't exist yet.")
    logger.info("   Use  scripts/verify_learning.py  to confirm real learning is happening.")
    logger.info("")

    try:
        from core.config import Config
        from core.exchange_adapter import ExchangeAdapter
        from mi.online_learner import OnlineLearner

        exchange = ExchangeAdapter(Config())

        learner = OnlineLearner(
            exchange=exchange,
            symbols=symbols,
            db_path=args.db_path,
            models_dir=args.models_dir,
            timeframe=args.timeframe,
            interval=args.interval,
        )

        if args.once:
            summary = await learner.run_once()
            logger.info("Single-cycle summary: %s", summary)
            return 0

        await learner.run()
        return 0

    except KeyboardInterrupt:
        logger.info("⏹  Online learner stopped by user.")
        return 0
    except Exception as exc:
        logger.error("💥  Online learner crashed: %s", exc, exc_info=True)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously adapt ML models with fresh candles + news sentiment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run indefinitely (recommended — leave this running in a tmux session)
  python scripts/run_online_learning.py

  # Run one cycle and exit (useful for cron)
  python scripts/run_online_learning.py --once

  # Adapt every 30 minutes instead of hourly
  python scripts/run_online_learning.py --interval 1800

  # Only adapt BTC and ETH
  python scripts/run_online_learning.py --symbols BTCUSDT ETHUSDT
        """,
    )
    parser.add_argument(
        "--symbols", "-s",
        nargs="+",
        metavar="SYMBOL",
        default=None,
        help="Symbols to adapt (default: TRAINING_SYMBOLS env var or built-in list)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Seconds between adaptation cycles (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--timeframe", "-t",
        default=DEFAULT_TIMEFRAME,
        help=f"Candle timeframe (default: {DEFAULT_TIMEFRAME})",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"SQLite DB path used by NewsAggregator (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--models-dir", "-m",
        dest="models_dir",
        default=DEFAULT_MODELS_DIR,
        help=f"Directory with trained models (default: {DEFAULT_MODELS_DIR})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single adaptation cycle and exit",
    )
    parser.add_argument(
        "--log-level", "-l",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )

    args = parser.parse_args()
    _setup_logging(args.log_level)

    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
