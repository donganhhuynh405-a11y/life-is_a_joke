#!/usr/bin/env python3
"""
scripts/run_training.py — Standalone ML Training Launcher

Starts the full historical pre-training pipeline directly from the command
line.  Useful for running training manually, in a cron job or in CI.

Usage
-----
    # Train default symbols (from TRAINING_SYMBOLS env var or hard-coded list)
    python scripts/run_training.py

    # Force re-train even if models already exist
    python scripts/run_training.py --force

    # Train specific symbols only
    python scripts/run_training.py --symbols BTCUSDT ETHUSDT SOLUSDT

    # Use a different timeframe
    python scripts/run_training.py --timeframe 4h

    # Watch progress in another terminal while this runs:
    #   python scripts/watch_training.py
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure the src directory is on the path when run from the project root
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ── Default values ────────────────────────────────────────────────────────────

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "MATICUSDT",
]

DEFAULT_MODELS_DIR = os.getenv("MODELS_DIR", "/var/lib/trading-bot/models")
DEFAULT_TIMEFRAME = "1h"


# ── Logging setup ─────────────────────────────────────────────────────────────

def _setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> int:
    """Run the training pipeline and return an exit code (0 = OK)."""
    logger = logging.getLogger("run_training")

    # Resolve symbols
    symbols = args.symbols or (
        [s.strip() for s in os.getenv("TRAINING_SYMBOLS", "").split(",") if s.strip()]
        or DEFAULT_SYMBOLS
    )

    logger.info("=" * 70)
    logger.info("🚀  ML HISTORICAL PRE-TRAINING LAUNCHER")
    logger.info("=" * 70)
    logger.info("Symbols    : %s", ", ".join(symbols))
    logger.info("Timeframe  : %s", args.timeframe)
    logger.info("Models dir : %s", args.models_dir)
    logger.info("Force      : %s", args.force)
    logger.info("=" * 70)

    try:
        from core.exchange_adapter import ExchangeAdapter
        from mi.training_pipeline import MLTrainingPipeline
        from mi.training_progress import DEFAULT_PROGRESS_FILE

        exchange = ExchangeAdapter()

        pipeline = MLTrainingPipeline(
            exchange=exchange,
            symbols=symbols,
            timeframe=args.timeframe,
            force_retrain=args.force,
            models_dir=args.models_dir,
            progress_file=DEFAULT_PROGRESS_FILE,
        )

        logger.info("📊 Progress is written to: %s", DEFAULT_PROGRESS_FILE)
        logger.info("   Watch it live with:  python scripts/watch_training.py")
        logger.info("   Or via the REST API: GET /api/v1/ml/training/status")
        logger.info("")

        stats = await pipeline.train_all_symbols()

        successful = stats.get("successful", 0)
        failed = stats.get("failed", 0)
        skipped = stats.get("skipped", 0)

        logger.info("=" * 70)
        logger.info("✅  TRAINING COMPLETE")
        logger.info("   Successful : %d", successful)
        logger.info("   Skipped    : %d", skipped)
        logger.info("   Failed     : %d", failed)
        logger.info("=" * 70)

        return 1 if failed > 0 and successful == 0 else 0

    except KeyboardInterrupt:
        logger.info("⏹  Training interrupted by user.")
        return 130
    except Exception as exc:
        logger.error("💥  Training launcher crashed: %s", exc, exc_info=True)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start the ML historical pre-training pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_training.py
  python scripts/run_training.py --force
  python scripts/run_training.py --symbols BTCUSDT ETHUSDT
  python scripts/run_training.py --timeframe 4h --force
        """,
    )
    parser.add_argument(
        "--symbols", "-s",
        nargs="+",
        metavar="SYMBOL",
        default=None,
        help="Symbols to train (default: uses TRAINING_SYMBOLS env var or built-in list)",
    )
    parser.add_argument(
        "--timeframe", "-t",
        default=DEFAULT_TIMEFRAME,
        help=f"Candle timeframe (default: {DEFAULT_TIMEFRAME})",
    )
    parser.add_argument(
        "--models-dir", "-m",
        dest="models_dir",
        default=DEFAULT_MODELS_DIR,
        help=f"Directory to store trained models (default: {DEFAULT_MODELS_DIR})",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force re-training even if a model already exists",
    )
    parser.add_argument(
        "--log-level", "-l",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    _setup_logging(args.log_level)

    exit_code = asyncio.run(run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
