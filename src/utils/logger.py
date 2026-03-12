"""
Logging Utility
Configures application logging to file and console
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from utils.env import getenv as _env


def parse_size(size_str: str) -> int:
    """
    Parse human-readable size string to bytes

    Args:
        size_str: Size string like '100M', '1G', '500K', or plain number

    Returns:
        Size in bytes
    """
    size_str = str(size_str).strip().upper()

    # If it's already a plain number, return it
    if size_str.isdigit():
        return int(size_str)

    # Parse size with suffix
    units = {
        'K': 1024,
        'M': 1024 * 1024,
        'G': 1024 * 1024 * 1024,
        'KB': 1024,
        'MB': 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
    }

    for suffix, multiplier in units.items():
        if size_str.endswith(suffix):
            try:
                number = float(size_str[:-len(suffix)])
                return int(number * multiplier)
            except ValueError:
                pass

    # Fallback: try to parse as int
    try:
        return int(size_str)
    except ValueError:
        # Return default 100MB if parsing fails
        return 104857600


def setup_logger(name: str = None) -> logging.Logger:
    """
    Setup application logger

    Args:
        name: Logger name (default: root logger)

    Returns:
        Configured logger instance
    """
    log_level = _env('LOG_LEVEL', 'INFO').upper()
    log_dir = os.getenv('LOG_DIR', '/var/log/trading-bot')
    log_file = os.getenv('LOG_FILE', 'trading-bot.log')
    log_to_file = _env('LOG_TO_FILE', 'true').lower() == 'true'
    log_to_console = _env('LOG_TO_CONSOLE', 'true').lower() == 'true'
    log_max_size = parse_size(_env('LOG_MAX_SIZE', '104857600'))
    log_backup_count = int(_env('LOG_BACKUP_COUNT', '10'))

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level, logging.INFO))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_to_file:
        try:
            log_path = Path(log_dir)
            if not log_path.exists():
                log_path = Path('./logs')
                log_path.mkdir(exist_ok=True)
                log_dir = str(log_path)

            log_file_path = os.path.join(log_dir, log_file)

            file_handler = RotatingFileHandler(
                log_file_path,
                maxBytes=log_max_size,
                backupCount=log_backup_count
            )
            file_handler.setLevel(getattr(logging, log_level, logging.INFO))
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        except Exception as e:
            logger.warning(f"Could not setup file logging: {e}")

    return logger
