import asyncio
import logging
from typing import List, Dict, Optional
import ccxt.async_support as ccxt
from utils import retry_async

logger = logging.getLogger('bot.executor')


class Executor:
    def __init__(self, cfg, redis_url=None):
        self.cfg = cfg
        self.redis_url = redis_url
        self.running = False
        self.exchange = None
        self.open_positions = {}  # Track open positions
        self.exchange_rules = {}  # Cache exchange rules

    async def start(self):
        """Initialize exchange connection"""
        self.running = True
        await self._initialize_exchange()

    async def _initialize_exchange(self):
        """Initialize CCXT exchange instance"""
        try:
            # Get exchange config
            exchange_name = 'binance'  # Default

            # Get API credentials from config
            api_key = ''
            api_secret = ''

            if hasattr(self.cfg, 'secrets'):
                api_key = self.cfg.secrets.get('binance_api_key', '')
                api_secret = self.cfg.secrets.get('binance_api_secret', '')
            elif isinstance(self.cfg, dict):
                api_key = self.cfg.get('secrets', {}).get('binance_api_key', '')
                api_secret = self.cfg.get('secrets', {}).get('binance_api_secret', '')

            # Create exchange instance
            exchange_class = getattr(ccxt, exchange_name)
            self.exchange = exchange_class({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',
                },
            })

            # Use testnet if in paper/test mode
            env = getattr(self.cfg, 'environment', self.cfg.get('environment', 'paper'))
            if env in ['paper', 'test']:
                self.exchange.set_sandbox_mode(True)
                logger.info("Exchange initialized in TESTNET mode")
            else:
                logger.info("Exchange initialized in LIVE mode")

            # Load markets
            await self.exchange.load_markets()
            logger.info(f"✓ {exchange_name} exchange initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize exchange: {e}")
            self.exchange = None

    async def stop(self):
        """Stop executor and close exchange connection"""
        self.running = False
        if self.exchange:
            try:
                await self.exchange.close()
                logger.info("Exchange connection closed")
            except Exception as e:
                logger.error(f"Error closing exchange: {e}")

    async def shutdown(self):
        """Alias for stop()"""
        await self.stop()

    async def has_open_position(self, symbol: str) -> bool:
        """Check if there's an open position for symbol"""
        # Check in-memory tracking
        if symbol in self.open_positions:
            return True

        # For spot trading, check account balances
        if self.exchange:
            try:
                # Extract base currency from symbol (e.g., BTC from BTC/USDT)
                base_currency = symbol.split('/')[0] if '/' in symbol else symbol[:3]
                balance = await self.exchange.fetch_balance()

                # Check if we have any of this asset
                if base_currency in balance['total']:
                    amount = balance['total'][base_currency]
                    if amount > 0:
                        logger.info(f"Found existing {base_currency} balance: {amount}")
                        self.open_positions[symbol] = {'amount': amount}
                        return True
            except Exception as e:
                logger.warning(f"Error checking position for {symbol}: {e}")

        return False

    async def adjust_amount_to_exchange_rules(self, symbol: str, amount: float) -> float:
        """Adjust amount according to exchange precision rules"""
        if not self.exchange or not self.exchange.markets:
            logger.warning("Exchange not initialized, returning raw amount")
            return round(amount, 8)

        try:
            # Get market info
            if symbol not in self.exchange.markets:
                logger.warning(f"Symbol {symbol} not found in markets")
                return round(amount, 8)

            market = self.exchange.markets[symbol]
            precision = market.get('precision', {})

            # Get amount precision
            amount_precision = precision.get('amount', 8)

            # Round to appropriate precision
            adjusted_amount = round(amount, amount_precision)

            # Check minimum amount
            limits = market.get('limits', {})
            min_amount = limits.get('amount', {}).get('min', 0)

            if adjusted_amount < min_amount:
                logger.warning(f"Amount {adjusted_amount} below minimum {min_amount} for {symbol}")
                return min_amount

            return adjusted_amount

        except Exception as e:
            logger.error(f"Error adjusting amount for {symbol}: {e}")
            return round(amount, 8)

    @retry_async(retries=3, delay=1)
    async def place_order(self, exchange_client, symbol, side, amount, price=None, params=None):
        # exchange_client expected to be ccxt instance or wrapper
        try:
            loop = asyncio.get_event_loop()
            order_type = 'market' if price is None else 'limit'
            resp = await loop.run_in_executor(
                None,
                lambda: exchange_client.create_order(symbol, order_type, side, amount, price, params)
            )
            return resp
        except Exception as e:
            logger.exception('Order failed: %s', e)
            raise

    async def execute_classic_strategy(self, signals: List[Dict]):
        """Execute trades based on classic strategy signals"""
        executed_orders = []

        for signal in signals:
            if signal['confidence'] < 0.5:  # Минимальный порог уверенности
                continue

            symbol = signal['symbol']
            action = signal['signal']

            # Проверяем, нет ли уже открытой позиции
            if await self.has_open_position(symbol):
                logger.info(f"Позиция {symbol} уже открыта, пропускаем")
                continue

            # Рассчитываем параметры ордера
            order_params = await self.prepare_classic_order(signal)

            if order_params:
                try:
                    # Выставляем ордер
                    if action == 'BUY':
                        order = await self.exchange.create_order(
                            symbol=symbol,
                            type='limit',
                            side='buy',
                            amount=order_params['amount'],
                            price=order_params['price']
                        )
                    else:  # SELL
                        order = await self.exchange.create_order(
                            symbol=symbol,
                            type='limit',
                            side='sell',
                            amount=order_params['amount'],
                            price=order_params['price']
                        )

                    # Устанавливаем стоп-лосс и тейк-профит
                    await self.place_stop_loss_take_profit(order, signal)

                    executed_orders.append(order)
                    logger.info(f"Исполнен {action} ордер для {symbol}: {order}")

                except Exception as e:
                    logger.error(f"Ошибка исполнения ордера {symbol}: {str(e)}")

        return executed_orders

    async def prepare_classic_order(self, signal: Dict) -> Optional[Dict]:

        symbol = signal['symbol']
        action = signal['signal']
        position_size = signal.get('position_size', {})

        if not position_size or position_size['size'] <= 0:
            return None

        # Получаем текущие рыночные данные
        ticker = await self.exchange.fetch_ticker(symbol)

        # Определяем цену входа
        if action == 'BUY':
            # Для покупки берем цену ask (или чуть выше для быстрого исполнения)
            price = ticker['ask'] * 1.001  # +0.1% для быстрого исполнения
        else:
            # Для продажи берем цену bid
            price = ticker['bid'] * 0.999  # -0.1% для быстрого исполнения

        # Округляем количество согласно правилам биржи
        amount = await self.adjust_amount_to_exchange_rules(symbol, position_size['size'])

        # Минимальная проверка
        min_cost = 10  # Минимальная сумма ордера в USDT
        if amount * price < min_cost:
            logger.warning(f"Слишком маленький ордер для {symbol}: {amount * price:.2f} USDT")
            return None

        return {
            'amount': amount,
            'price': price,
            'symbol': symbol,
            'side': 'buy' if action == 'BUY' else 'sell'
        }

    async def place_stop_loss_take_profit(self, order: Dict, signal: Dict):

        symbol = signal['symbol']
        entry_price = order['price']
        action = order['side']

        # Параметры риск-менеджмента
        stop_loss_pct = 0.03  # 3% стоп-лосс
        take_profit_pct = 0.06  # 6% тейк-профит (риск/прибыль = 1:2)

        if action == 'buy':
            stop_price = entry_price * (1 - stop_loss_pct)
            take_profit_price = entry_price * (1 + take_profit_pct)
        else:  # sell
            stop_price = entry_price * (1 + stop_loss_pct)
            take_profit_price = entry_price * (1 - take_profit_pct)

        try:
            # Для фьючерсов можно использовать стоп-лосс ордер
            # Для спота нужно отслеживать вручную или использовать брекет-ордера
            if 'future' in symbol.lower():
                await self.exchange.create_order(
                    symbol=symbol,
                    type='stop_market',
                    side='sell' if action == 'buy' else 'buy',
                    amount=order['amount'],
                    params={'stopPrice': stop_price}
                )
                logger.info(f"Установлен стоп-лосс для {symbol} на {stop_price}")

            # Логируем тейк-профит для ручного отслеживания
            logger.info(
                f"Тейк-профит для {symbol}: {take_profit_price:.2f} "
                f"(стоп: {stop_price:.2f}, вход: {entry_price:.2f})"
            )

        except Exception as e:
            logger.warning(f"Не удалось установить стоп-лосс для {symbol}: {str(e)}")
