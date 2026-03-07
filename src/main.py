#!/usr/bin/env python3
"""
Trading Bot - Main Application Entry Point
A Binance trading bot with automated trading strategies, risk management, and monitoring.
"""

import os
import sys
import time
import signal
import logging
from pathlib import Path
from dotenv import load_dotenv

# Add src directory and parent directory to Python path
src_dir = Path(__file__).parent
parent_dir = src_dir.parent
sys.path.insert(0, str(src_dir))
sys.path.insert(0, str(parent_dir))

# Now import from the package
try:
    from core.bot import TradingBot
    from core.config import Config
    from utils.logger import setup_logger
except ImportError as e:
    # A missing dependency at import time would cause the container to exit
    # instantly with code 1, making Docker restart it in a tight loop before
    # any backoff can take effect.  Sleep 30s so the restart policy has time
    # to slow down retries while the operator investigates the issue.
    print(f"Import error: {e}")
    print(f"Python path: {sys.path}")
    print(f"Current directory: {os.getcwd()}")
    print(f"Script location: {Path(__file__).parent}")
    print("Sleeping 30s before exit so Docker restart policy can apply…")
    time.sleep(30)
    sys.exit(1)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger = logging.getLogger(__name__)
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    sys.exit(0)


def main():
    """Main application entry point"""
    # Load environment variables
    env_file = os.environ.get('CONFIG_DIR', '/etc/trading-bot') + '/.env'
    if not os.path.exists(env_file):
        env_file = '.env'

    if os.path.exists(env_file):
        load_dotenv(env_file)
        print(f"Loaded environment from: {env_file}")
    else:
        print(f"Warning: No .env file found at {env_file}")

    # Setup logging
    logger = setup_logger()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("=" * 70)
    logger.info("Trading Bot - Starting")
    logger.info("=" * 70)

    try:
        # Load configuration
        config = Config()
        logger.info(f"Configuration loaded: {config.app_name}")
        logger.info(f"Environment: {config.app_env}")
        logger.info(f"Trading enabled: {config.trading_enabled}")

        # Initialize bot
        bot = TradingBot(config)

        # Start bot
        logger.info("Starting trading bot...")
        bot.start()

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        # Sleep before exiting so Docker's restart backoff policy has time to
        # kick in.  Without this the container immediately re-exits and Docker
        # can reach its restart limit very quickly, causing the container to
        # enter the "Restarting" state indefinitely.
        logger.info("Sleeping 30s before exit so Docker restart policy can apply…")
        time.sleep(30)
        sys.exit(1)
    finally:
        logger.info("Trading bot stopped")
        logger.info("=" * 70)


if __name__ == "__main__":
    main()
