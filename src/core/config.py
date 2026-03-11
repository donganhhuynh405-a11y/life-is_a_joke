"""
Configuration Manager
Loads and validates configuration from environment variables
"""

import os
from utils.env import strip_comment, getenv as _env


def _strip_comment(value: str) -> str:
    """Alias for backward compatibility; delegates to utils.env.strip_comment."""
    return strip_comment(value)


class Config:
    """Application configuration"""

    def __init__(self):
        """Initialize configuration from environment variables"""
        # Application settings
        self.app_name = os.getenv('APP_NAME', 'trading-bot')
        self.app_env = _env('APP_ENV', 'production')
        self.debug = _env('DEBUG', 'false').lower() == 'true'
        self.log_level = _env('LOG_LEVEL', 'INFO')

        # Exchange configuration (supports multiple exchanges via CCXT)
        self.use_ccxt = _env('USE_CCXT', 'false').lower() == 'true'
        self.exchange_id = _env('EXCHANGE_ID', 'binance')
        self.exchange_api_key = os.getenv('EXCHANGE_API_KEY', os.getenv('BINANCE_API_KEY', ''))
        self.exchange_api_secret = os.getenv(
            'EXCHANGE_API_SECRET', os.getenv(
                'BINANCE_API_SECRET', ''))
        self.exchange_testnet = _env(
            'EXCHANGE_TESTNET', _env('BINANCE_TESTNET', 'false')).lower() == 'true'

        # Binance API (for backward compatibility)
        self.binance_api_key = os.getenv('BINANCE_API_KEY', '')
        self.binance_api_secret = os.getenv('BINANCE_API_SECRET', '')
        self.binance_testnet = _env('BINANCE_TESTNET', 'false').lower() == 'true'

        # Database
        self.db_type = _env('DB_TYPE', 'sqlite')
        self.db_path = os.getenv('DB_PATH', '/var/lib/trading-bot/trading_bot.db')
        self.db_host = os.getenv('DB_HOST', 'localhost')
        self.db_port = int(_env('DB_PORT', '5432'))
        self.db_name = os.getenv('DB_NAME', 'trading_bot')
        self.db_user = os.getenv('DB_USER', 'trading_bot_user')
        self.db_password = os.getenv('DB_PASSWORD', '')

        # Trading settings
        self.trading_enabled = _env('TRADING_ENABLED', 'true').lower() == 'true'
        self.trading_mode = _env('TRADING_MODE', 'live')

        # Parse trading symbols from comma-separated string to list
        symbols_str = _env('TRADING_SYMBOLS', '')
        default_symbol_str = _env('DEFAULT_SYMBOL', 'BTCUSDT')

        # Ensure default_symbol is a single symbol (take first if comma-separated)
        self.default_symbol = default_symbol_str.split(',')[0].strip(
        ) if ',' in default_symbol_str else default_symbol_str.strip()

        # Parse trading symbols list - if empty, use default_symbol
        self.trading_symbols = [s.strip() for s in symbols_str.split(
            ',') if s.strip()] if symbols_str else [self.default_symbol]

        self.active_strategy = _env('ACTIVE_STRATEGY', 'enhanced')
        self.max_position_size = float(_env('MAX_POSITION_SIZE', '0.1'))
        self.stop_loss_percentage = float(_env('STOP_LOSS_PERCENTAGE', '2.0'))
        self.take_profit_percentage = float(_env('TAKE_PROFIT_PERCENTAGE', '5.0'))

        # Risk management
        self.max_daily_trades = int(_env('MAX_DAILY_TRADES', '10'))
        self.max_open_positions = int(_env('MAX_OPEN_POSITIONS', '3'))
        self.max_daily_loss_percentage = float(_env('MAX_DAILY_LOSS_PERCENTAGE', '5.0'))
        self.position_size_percentage = float(_env('POSITION_SIZE_PERCENTAGE', '2.0'))

        # Confidence-based position sizing
        self.use_confidence_sizing = _env('USE_CONFIDENCE_SIZING', 'true').lower() == 'true'
        self.min_position_size_pct = float(_env('MIN_POSITION_SIZE_PCT', '0.5'))  # % of balance
        self.max_position_size_pct = float(_env('MAX_POSITION_SIZE_PCT', '5.0'))  # % of balance

        # Notifications
        self.enable_notifications = _env('ENABLE_NOTIFICATIONS', 'false').lower() == 'true'
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

        # Web interface
        self.web_enabled = _env('WEB_ENABLED', 'false').lower() == 'true'
        self.web_host = _env('WEB_HOST', '127.0.0.1')
        self.web_port = int(_env('WEB_PORT', '8080'))

        # Monitoring
        self.health_check_enabled = _env('HEALTH_CHECK_ENABLED', 'true').lower() == 'true'
        self.health_check_interval = int(_env('HEALTH_CHECK_INTERVAL', '300'))

        # Logging
        self.log_dir = os.getenv('LOG_DIR', '/var/log/trading-bot')
        self.log_file = os.getenv('LOG_FILE', 'trading-bot.log')
        self.log_to_file = _env('LOG_TO_FILE', 'true').lower() == 'true'
        self.log_to_console = _env('LOG_TO_CONSOLE', 'true').lower() == 'true'

        # System paths
        self.app_dir = os.getenv('APP_DIR', '/opt/trading-bot')
        self.data_dir = os.getenv('DATA_DIR', '/var/lib/trading-bot')
        self.config_dir = os.getenv('CONFIG_DIR', '/etc/trading-bot')
        self.models_dir = os.getenv('ML_MODELS_DIR', '/var/lib/trading-bot/models')

    def validate(self) -> bool:
        """Validate configuration"""
        errors = []

        # Only require valid exchange credentials when trading is actually enabled.
        # When trading is disabled the bot runs in monitoring/reporting mode and
        # does not need to place or manage orders, so missing credentials are fine.
        if self.trading_enabled:
            api_key = self.exchange_api_key if self.use_ccxt else self.binance_api_key
            api_secret = self.exchange_api_secret if self.use_ccxt else self.binance_api_secret

            if not api_key or api_key.startswith('your_'):
                errors.append("Exchange API key not configured")

            if not api_secret or api_secret.startswith('your_'):
                errors.append("Exchange API secret not configured")

        if self.max_position_size <= 0:
            errors.append("MAX_POSITION_SIZE must be greater than 0")

        if errors:
            for error in errors:
                print(f"Configuration error: {error}")
            return False

        return True

    def get(self, key: str, default=None):
        """
        Get configuration value by key with optional default

        Args:
            key: Configuration key (attribute name)
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return getattr(self, key, default)

    def __repr__(self):
        """String representation"""
        return f"Config(app_name={self.app_name}, env={self.app_env}, trading_enabled={self.trading_enabled})"
