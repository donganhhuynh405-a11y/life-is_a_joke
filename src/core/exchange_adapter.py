"""
Exchange Adapter
Provides a unified interface for multiple cryptocurrency exchanges using CCXT
"""

import logging
import ccxt
from typing import Optional, List
from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException


class ExchangeAdapter:
    """
    Unified exchange interface supporting multiple exchanges via CCXT

    Supports both direct Binance client (for backward compatibility)
    and CCXT unified API for multi-exchange support
    """

    def __init__(self, config):
        """
        Initialize exchange adapter

        Args:
            config: Configuration object with exchange settings
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.exchange = None
        self.exchange_id = config.exchange_id.lower()
        self.use_ccxt = config.use_ccxt

        if self.use_ccxt:
            self._init_ccxt_exchange()
        else:
            self._init_binance_legacy()

    def _init_ccxt_exchange(self):
        """Initialize exchange using CCXT"""
        self.logger.info(f"Initializing {self.exchange_id} exchange via CCXT...")

        try:
            exchange_class = getattr(ccxt, self.exchange_id)

            exchange_config = {
                'apiKey': self.config.exchange_api_key,
                'secret': self.config.exchange_api_secret,
                'enableRateLimit': True,
                'timeout': 30000,
                'options': {
                    'defaultType': 'spot',
                }
            }

            if self.exchange_id == 'bybit':
                exchange_config['options']['createMarketBuyOrderRequiresPrice'] = False

            if self.config.exchange_testnet:
                if self.exchange_id == 'binance':
                    exchange_config['options']['defaultType'] = 'spot'
                    exchange_config['options']['test'] = True
                elif self.exchange_id in ['bybit', 'okx']:
                    exchange_config['sandbox'] = True

            self.exchange = exchange_class(exchange_config)
            self._load_markets_with_retry()

            self.logger.info(f"Connected to {self.exchange_id} via CCXT")
            self.logger.info(f"Supported markets: {len(self.exchange.markets)}")

        except Exception as e:
            self.logger.error(f"Failed to initialize {self.exchange_id}: {str(e)}")
            raise

    def _load_markets_with_retry(self, max_retries: int = 3, base_delay: float = 5.0):
        """Load exchange markets with retry logic for transient network errors.

        Args:
            max_retries: Maximum number of retry attempts after the first try.
            base_delay: Initial delay in seconds between retries (doubles each attempt).
        """
        import time
        delay = base_delay
        for attempt in range(max_retries + 1):
            try:
                self.exchange.load_markets()
                return
            except (ccxt.RequestTimeout, ccxt.NetworkError) as e:
                if attempt < max_retries:
                    self.logger.warning(
                        f"load_markets() timed out (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.0f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    self.logger.error(
                        f"load_markets() failed after {max_retries + 1} attempts: {e}"
                    )
                    raise

    def _init_binance_legacy(self):
        """Initialize Binance using legacy python-binance client (backward compatibility)"""
        self.logger.info("Initializing Binance (legacy mode)...")

        try:
            self.exchange = BinanceClient(
                self.config.exchange_api_key,
                self.config.exchange_api_secret,
                testnet=self.config.exchange_testnet
            )
            self.exchange.ping()
            self.logger.info("Connected to Binance (legacy mode)")
        except BinanceAPIException as e:
            self.logger.error(f"Failed to connect to Binance: {e}")
            raise

    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol format for the exchange

        CCXT uses unified format with slash (BTC/USDT)
        Legacy Binance uses no slash (BTCUSDT)

        Args:
            symbol: Symbol in any format (BTCUSDT or BTC/USDT)

        Returns:
            Symbol in the correct format for the exchange
        """
        if self.use_ccxt:
            # CCXT needs slash format
            if '/' not in symbol:
                # Try to find matching market by checking all possibilities
                # Common quote currencies
                for quote in ['USDT', 'USD', 'BUSD', 'BTC', 'ETH', 'BNB']:
                    if symbol.endswith(quote):
                        base = symbol[:-len(quote)]
                        normalized = f"{base}/{quote}"
                        if normalized in self.exchange.markets:
                            return normalized

                # If no match found, try the most common quote currency
                if symbol.endswith('USDT'):
                    return f"{symbol[:-4]}/USDT"
                elif symbol.endswith('USD'):
                    return f"{symbol[:-3]}/USD"
                else:
                    # Default fallback - try to split intelligently
                    # Most symbols are like BTCUSDT, ETHUSDT, etc.
                    for i in range(2, len(symbol) - 2):
                        possible_base = symbol[:i]
                        possible_quote = symbol[i:]
                        test_symbol = f"{possible_base}/{possible_quote}"
                        if test_symbol in self.exchange.markets:
                            return test_symbol
            return symbol
        else:
            # Legacy Binance needs no slash
            if '/' in symbol:
                return symbol.replace('/', '')
            return symbol

    def ping(self):
        """Test connection to exchange"""
        try:
            if self.use_ccxt:
                # Try fetch_status first, but not all exchanges support it
                try:
                    return self.exchange.fetch_status()
                except Exception:
                    # Fallback: try to fetch a ticker for a common trading pair
                    # This confirms the exchange is reachable and API keys are valid
                    # Use first symbol from trading_symbols list to ensure single symbol
                    test_symbol = self.config.trading_symbols[0] if self.config.trading_symbols else 'BTC/USDT'
                    self.exchange.fetch_ticker(test_symbol)
                    return {'status': 'ok', 'updated': None}
            else:
                return self.exchange.ping()
        except Exception as e:
            self.logger.error(f"Ping failed: {str(e)}")
            raise

    def get_account(self):
        """Get account information"""
        try:
            if self.use_ccxt:
                balance = self.exchange.fetch_balance()
                # Convert to similar format as Binance
                return {
                    'canTrade': True,  # CCXT doesn't provide this directly
                    'canWithdraw': True,
                    'canDeposit': True,
                    'balances': [
                        {
                            'asset': asset,
                            'free': str(balance['free'].get(asset, 0)),
                            'locked': str(balance['used'].get(asset, 0))
                        }
                        for asset in balance['total'].keys() if balance['total'][asset] > 0
                    ]
                }
            else:
                return self.exchange.get_account()
        except Exception as e:
            self.logger.error(f"Failed to get account info: {str(e)}")
            raise

    def get_symbol_ticker(self, symbol: str):
        """Get ticker for a symbol"""
        try:
            if self.use_ccxt:
                symbol = self.normalize_symbol(symbol)
                ticker = self.exchange.fetch_ticker(symbol)
                return {
                    'symbol': symbol,
                    'price': str(ticker['last'])
                }
            else:
                return self.exchange.get_symbol_ticker(symbol=symbol)
        except Exception as e:
            self.logger.error(f"Failed to get ticker for {symbol}: {str(e)}")
            raise

    def get_klines(
            self,
            symbol: str,
            interval: str = '1h',
            limit: int = 100,
            startTime: Optional[int] = None,
            endTime: Optional[int] = None):
        """Get candlestick data

        Args:
            symbol: Trading pair symbol
            interval: Candle interval (e.g. '1h', '4h', '1d')
            limit: Maximum number of candles to return
            startTime: Start time in milliseconds (inclusive)
            endTime: End time in milliseconds (inclusive)
        """
        try:
            if self.use_ccxt:
                symbol = self.normalize_symbol(symbol)
                # Convert Binance-style interval to CCXT timeframe
                timeframe_map = {
                    '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
                    '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '12h': '12h',
                    '1d': '1d', '3d': '3d', '1w': '1w', '1M': '1M'
                }
                timeframe = timeframe_map.get(interval, '1h')

                # CCXT uses 'since' (ms) for the start timestamp
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol, timeframe, since=startTime, limit=limit)

                # Convert to Binance format
                # CCXT returns: [timestamp, open, high, low, close, volume]
                # Binance expects: [timestamp, open, high, low, close, volume, close_time, ...]
                return [
                    [
                        candle[0],  # timestamp
                        str(candle[1]),  # open
                        str(candle[2]),  # high
                        str(candle[3]),  # low
                        str(candle[4]),  # close
                        str(candle[5]),  # volume
                        candle[0] + self.exchange.parse_timeframe(timeframe) * 1000,  # close_time
                        '0',  # quote_asset_volume
                        0,  # number_of_trades
                        '0',  # taker_buy_base_volume
                        '0',  # taker_buy_quote_volume
                        '0'  # ignore
                    ]
                    for candle in ohlcv
                ]
            else:
                kwargs = {'symbol': symbol, 'interval': interval, 'limit': limit}
                if startTime is not None:
                    kwargs['startTime'] = startTime
                if endTime is not None:
                    kwargs['endTime'] = endTime
                return self.exchange.get_klines(**kwargs)
        except Exception as e:
            self.logger.error(f"Failed to get klines for {symbol}: {str(e)}")
            raise

    def create_order(
            self,
            symbol: str,
            side: str,
            order_type: str,
            quantity: float,
            price: Optional[float] = None):
        """
        Create an order

        Args:
            symbol: Trading pair symbol (will be normalized to exchange format)
            side: 'buy' or 'sell'
            order_type: 'market' or 'limit'
            quantity: Amount to trade
            price: Price (required for limit orders)
        """
        try:
            if self.use_ccxt:
                # Normalize symbol to CCXT format
                symbol = self.normalize_symbol(symbol)

                # Validate market exists
                if symbol not in self.exchange.markets:
                    raise ValueError(f"Symbol {symbol} not available on {self.exchange_id}")

                market = self.exchange.markets[symbol]

                # Validate and adjust quantity to meet exchange limits
                min_qty = market.get('limits', {}).get('amount', {}).get('min', 0)
                max_qty = market.get('limits', {}).get('amount', {}).get('max', float('inf'))

                if quantity < min_qty:
                    self.logger.warning(
                        f"Quantity {quantity} below minimum {min_qty}, adjusting to minimum")
                    quantity = min_qty
                elif quantity > max_qty:
                    self.logger.warning(
                        f"Quantity {quantity} above maximum {max_qty}, adjusting to maximum")
                    quantity = max_qty

                # Apply precision rules
                precision = market.get('precision', {})
                if 'amount' in precision and precision['amount'] is not None:
                    # Round to exchange precision (convert to int for round function)
                    precision_decimals = int(precision['amount'])
                    rounded_qty = round(quantity, precision_decimals)
                    # Ensure rounding doesn't reduce quantity to zero or too small
                    if rounded_qty == 0 and quantity > 0:
                        # If precision rounding results in 0, keep original quantity
                        # The exchange will reject if it's truly invalid
                        self.logger.warning(
                            f"Precision rounding resulted in 0, keeping original quantity {quantity}")
                        # Don't change quantity - let exchange handle it or reject with clear error
                    else:
                        quantity = rounded_qty

                self.logger.info(f"Creating {order_type} {side} order: {quantity} {symbol}")

                params = {}

                # Special handling for Bybit market orders
                if self.exchange_id == 'bybit' and order_type.lower() == 'market':
                    # Bybit UTA (Unified Trading Account) market order handling
                    # Market orders on Bybit use base currency quantity for both buy and sell
                    if side.lower() == 'buy':
                        # Fetch current market price to validate order value
                        ticker = self.exchange.fetch_ticker(symbol)
                        current_price = ticker['last']
                        # Calculate quote currency amount (USDT value to spend)
                        quote_amount = quantity * current_price

                        # Bybit typically requires minimum $5-10 order value
                        min_order_value = 5.0  # Minimum $5 USD
                        if quote_amount < min_order_value:
                            self.logger.warning(
                                f"Order value ${quote_amount:.2f} below minimum ${min_order_value}, adjusting")
                            quote_amount = min_order_value
                            quantity = quote_amount / current_price

                        self.logger.info(
                            f"Bybit market buy: {quantity:.6f} {symbol.split('/')[0]} "
                            f"= ${quote_amount:.2f} USDT at price ${current_price:.4f}")

                    # Use standard create_market_order for both buy and sell
                    # Bybit UTA accepts base currency amount for market orders
                    order = self.exchange.create_market_order(symbol, side.lower(), quantity)
                elif order_type.lower() == 'market':
                    order = self.exchange.create_market_order(
                        symbol, side.lower(), quantity, params)
                else:
                    if price is None:
                        raise ValueError("Price required for limit orders")
                    order = self.exchange.create_limit_order(
                        symbol, side.lower(), quantity, price, params)

                self.logger.info(
                    f"Order created successfully: ID={order.get('id')}, "
                    f"Status={order.get('status')}, Filled={order.get('filled', 0)}")

                return {
                    'orderId': order['id'],
                    'symbol': symbol,
                    'status': order['status'],
                    'side': side.upper(),
                    'type': order_type.upper(),
                    'price': str(order.get('price', price)),
                    'origQty': str(quantity),
                    'executedQty': str(order.get('filled', 0)),
                    'transactTime': order.get('timestamp', 0)
                }
            else:
                # Legacy Binance client
                if order_type.lower() == 'market':
                    return self.exchange.order_market(
                        symbol=symbol,
                        side=side.upper(),
                        quantity=quantity
                    )
                else:
                    return self.exchange.order_limit(
                        symbol=symbol,
                        side=side.upper(),
                        quantity=quantity,
                        price=price
                    )
        except Exception as e:
            error_msg = f"Failed to create order: {type(e).__name__}: {str(e)}"
            self.logger.error(error_msg)
            self.logger.error(
                f"Order details - Symbol: {symbol}, Side: {side}, "
                f"Type: {order_type}, Quantity: {quantity}, Price: {price}")
            raise Exception(error_msg)

    def get_min_order_size(self, symbol: str) -> float:
        """
        Get minimum order size for a symbol

        Args:
            symbol: Trading pair symbol (will be normalized)

        Returns:
            Minimum order size in base currency
        """
        try:
            if self.use_ccxt:
                symbol = self.normalize_symbol(symbol)
                if symbol in self.exchange.markets:
                    market = self.exchange.markets[symbol]
                    min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.001)
                    return min_amount
                else:
                    # Default fallback
                    return 0.001
            else:
                # Default fallback
                return 0.001
        except Exception as e:
            self.logger.warning(
                f"Could not get min order size for {symbol}: {e}, using default 0.001")
            return 0.001

    def get_exchange_info(self):
        """Get exchange information"""
        try:
            if self.use_ccxt:
                markets = self.exchange.markets
                return {
                    'symbols': [
                        {
                            'symbol': symbol,
                            'status': 'TRADING',
                            'baseAsset': market['base'],
                            'quoteAsset': market['quote']
                        }
                        for symbol, market in markets.items()
                    ]
                }
            else:
                return self.exchange.get_exchange_info()
        except Exception as e:
            self.logger.error(f"Failed to get exchange info: {str(e)}")
            raise

    def get_supported_exchanges(self) -> List[str]:
        """Get list of supported exchanges"""
        return ccxt.exchanges

    def fetch_balance(self):
        """
        Fetch account balance

        Returns:
            Dictionary with balance information
        """
        try:
            if self.use_ccxt:
                # CCXT unified balance fetch
                balance = self.exchange.fetch_balance()
                return balance
            else:
                # Binance legacy API
                return self.exchange.get_account()
        except Exception as e:
            self.logger.error(f"Failed to fetch balance: {str(e)}")
            raise
