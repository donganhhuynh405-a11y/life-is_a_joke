"""
Strategy Manager
Manages and executes trading strategies with trend analysis
"""

import logging
from typing import List, Dict
from strategies.base_strategy import BaseStrategy
from strategies.simple_trend import SimpleTrendStrategy
from strategies.enhanced_multi_indicator import EnhancedMultiIndicatorStrategy
from core.confidence_position_sizer import ConfidencePositionSizer
from trend_analyzer import TrendAnalyzer
from utils.notifications import get_notifier


class StrategyManager:
    """Manages multiple trading strategies with trend analysis"""

    def __init__(self, config, client, database, risk_manager):
        """
        Initialize strategy manager

        Args:
            config: Configuration object
            client: Binance client
            database: Database instance
            risk_manager: Risk manager instance
        """
        self.config = config
        self.client = client
        self.db = database
        self.risk_manager = risk_manager
        self.logger = logging.getLogger(__name__)

        self.trend_analyzer = TrendAnalyzer()
        self.logger.info("Trend analyzer initialized")

        self.current_trends = {}

        self.use_confidence_sizing = getattr(config, 'use_confidence_sizing', True)
        if self.use_confidence_sizing:
            self.position_sizer = ConfidencePositionSizer(config)
            self.logger.info("Confidence-based position sizing ENABLED")
        else:
            self.position_sizer = None
            self.logger.info("Confidence-based position sizing DISABLED - using fixed sizing")

        self.trade_with_trend_only = getattr(config, 'trade_with_trend_only', False)
        self.min_trend_strength = getattr(config, 'min_trend_strength', 0.3)

        self.strategies: List[BaseStrategy] = []
        self._load_strategies()

        self.adaptive_tactics = None

        self.logger.info(f"Strategy manager initialized with {len(self.strategies)} strategies")
        if self.trade_with_trend_only:
            self.logger.info(
                f"Trading WITH TREND ONLY - minimum strength: {self.min_trend_strength}")

    def _load_strategies(self):
        """Load and initialize trading strategies"""
        active_strategy = getattr(self.config, 'active_strategy', 'enhanced').lower()

        if active_strategy == 'simple':
            strategy = SimpleTrendStrategy(
                self.config,
                self.client,
                self.db,
                self.risk_manager
            )
            self.strategies.append(strategy)
            self.logger.info(f"Loaded strategy: {strategy.name}")
        else:
            strategy = EnhancedMultiIndicatorStrategy(
                self.config,
                self.client,
                self.db,
                self.risk_manager
            )
            self.strategies.append(strategy)
            self.logger.info(f"Loaded strategy: {strategy.name}")

    def evaluate_strategies(self):
        """Evaluate all active strategies"""
        self.logger.debug("Evaluating strategies...")

        for strategy in self.strategies:
            if not strategy.enabled:
                continue

            try:
                signals = strategy.analyze()

                for signal in signals:
                    self._execute_signal(signal, strategy)

            except Exception as e:
                self.logger.error(f"Error in strategy {strategy.name}: {str(e)}", exc_info=True)

    def _execute_signal(self, signal: Dict, strategy: BaseStrategy):
        """Execute a trading signal"""
        action = signal.get('action')
        symbol = signal.get('symbol')

        self.logger.info(f"Signal from {strategy.name}: {action} {symbol} at {signal.get('price')}")

        if action == 'BUY':
            self._execute_buy(signal, strategy)
        elif action == 'SELL':
            self._execute_sell(signal, strategy)
        elif action == 'CLOSE':
            self._close_position(signal, strategy)

    def _execute_buy(self, signal: Dict, strategy: BaseStrategy):
        """Execute buy order"""
        symbol = signal.get('symbol')
        price = signal.get('price')

        try:
            # ============================================================================
            # CRITICAL: CHECK RISK LIMITS FIRST - BEFORE ANY OTHER OPERATIONS
            # ============================================================================
            # This MUST happen before balance checks, calculations, or any other logic
            # to prevent unlimited position opening when limits are exceeded
            # ============================================================================

            self.logger.debug(f"Checking risk limits for BUY {symbol}...")

            # Check daily trade limit
            if not self.risk_manager.check_daily_limits():
                self.logger.warning(f"🚫 SKIPPING BUY {symbol}: Daily trade limits reached")
                return

            # Check open position limit
            if not self.risk_manager.check_position_limits():
                self.logger.warning(f"🚫 SKIPPING BUY {symbol}: Position limits reached")
                return

            self.logger.debug(f"✅ Risk limits OK for BUY {symbol}")

            # ============================================================================
            # CHECK ADAPTIVE TACTICS - Apply AI-powered trading adjustments
            # ============================================================================
            should_trade, adj_confidence, reason = self._check_adaptive_tactics(symbol, signal)

            if not should_trade:
                self.logger.warning(f"🤖 Adaptive Tactics BLOCKED BUY {symbol}: {reason}")
                return

            self.logger.info(f"🤖 Adaptive Tactics approved BUY {symbol}: {reason}")

            # ============================================================================
            # Get signal details
            # ============================================================================
            confidence_score = signal.get('confidence', 70)  # Get signal confidence score
            self.logger.info(f"Signal confidence score: {confidence_score}/100")

            # Get account balance
            usdt_balance = 0
            try:
                if self.config.use_ccxt:
                    # CCXT balance fetch
                    balance = self.client.fetch_balance()
                    self.logger.debug(f"Balance structure keys: {list(balance.keys())}")

                    # CCXT standard structure: balance['free'][currency_code]
                    # balance['free'] contains available balances by currency
                    # balance['total'] contains total balances (free + locked)
                    try:
                        if 'free' in balance and isinstance(balance['free'], dict):
                            # Log all available currencies and their balances for debugging
                            self.logger.info(
                                f"Available currencies: {list(balance['free'].keys())}")
                            currencies_with_balance = {
                                k: v for k, v in balance['free'].items() if v > 0}
                            if currencies_with_balance:
                                self.logger.info(f"Non-zero balances: {currencies_with_balance}")
                            else:
                                self.logger.warning("No currencies with non-zero balance found!")

                            # Check for USDT in free balances
                            usdt_balance = float(balance['free'].get('USDT', 0))
                            self.logger.info(f"USDT balance from balance['free']: {usdt_balance}")

                            # If USDT is 0, check total balance (might be locked/in orders)
                            if usdt_balance == 0 and 'total' in balance and isinstance(
                                    balance['total'], dict):
                                total_usdt = float(balance['total'].get('USDT', 0))
                                if total_usdt > 0:
                                    self.logger.warning(
                                        f"USDT total balance is {total_usdt} but free balance is 0 "
                                        f"(funds may be locked in orders)")
                        elif 'USDT' in balance and isinstance(balance['USDT'], dict):
                            # Alternative structure: some exchanges may use balance[currency][type]
                            usdt_balance = float(balance['USDT'].get('free', 0))
                            self.logger.info(
                                f"USDT balance from balance['USDT']['free']: {usdt_balance}")
                        else:
                            self.logger.warning(
                                f"Unexpected balance structure. Balance keys: {list(balance.keys())}")
                            if 'free' in balance:
                                self.logger.warning(
                                    f"Type of balance['free']: {type(balance.get('free'))}")
                    except (TypeError, ValueError, AttributeError) as e:
                        self.logger.error(f"Error extracting USDT balance: {e}", exc_info=True)

                    self.logger.info(f"Available USDT balance: ${usdt_balance:.2f}")
                else:
                    # Binance legacy API
                    account = self.client.get_account()
                    for bal in account['balances']:
                        if bal['asset'] == 'USDT':
                            usdt_balance = float(bal['free'])
                            break
                    self.logger.info(f"Available USDT balance: ${usdt_balance:.2f}")
            except Exception as e:
                self.logger.warning(f"Failed to fetch balance: {e}. Using default position size.")
                usdt_balance = 0

            # ============================================================================
            # Calculate position size with confidence-based sizing
            # ============================================================================
            if usdt_balance > 0:
                # Check if confidence-based sizing is enabled
                if self.use_confidence_sizing and self.position_sizer:
                    # Use confidence-based position sizing

                    # Calculate volatility indicator (simplified - can be enhanced)
                    # TODO: Implement proper volatility calculation from recent price data
                    volatility = None  # Will use default behavior

                    # Calculate trend strength (simplified - can be enhanced)
                    # TODO: Implement proper trend strength calculation
                    trend_strength = None  # Will use default behavior

                    quantity, position_size_usdt = self.position_sizer.calculate_position_size(
                        balance=usdt_balance,
                        price=price,
                        confidence_score=confidence_score,
                        trend_strength=trend_strength,
                        volatility=volatility
                    )

                    self.logger.info(
                        f"📊 Confidence-based sizing: score={confidence_score:.1f}/100, "
                        f"quantity={quantity:.8f}, size=${position_size_usdt:.2f}"
                    )
                else:
                    # Use traditional fixed percentage sizing
                    quantity = self.risk_manager.calculate_position_size(
                        symbol, price, usdt_balance)
                    self.logger.info(
                        f"Calculated position size based on balance (fixed %): {quantity}")
            else:
                # Fallback to configured max position size if balance unavailable
                quantity = self.config.max_position_size
                self.logger.warning(
                    f"Balance is 0 or unavailable, using configured MAX_POSITION_SIZE: {quantity}")

            # Check minimum order size requirements
            try:
                min_order_size = self.client.get_min_order_size(symbol)
                if quantity < min_order_size:
                    self.logger.warning(
                        f"Calculated quantity {quantity} is below minimum {min_order_size}, adjusting")
                    quantity = min_order_size
            except Exception as e:
                self.logger.warning(f"Could not check minimum order size: {e}")

            # ============================================================================
            # APPLY ADAPTIVE TACTICS POSITION SIZE ADJUSTMENT
            # ============================================================================
            # Calculate position value for adjustment
            position_value = quantity * price
            adjusted_value = self._apply_position_size_adjustment(position_value)

            # Recalculate quantity based on adjusted value
            if adjusted_value != position_value:
                quantity = adjusted_value / price
                self.logger.info(f"Adjusted quantity: {quantity:.8f} {symbol}")

                # Re-check minimum order size
                try:
                    if quantity < min_order_size:
                        self.logger.warning(
                            f"Adjusted quantity {quantity} below minimum {min_order_size}, using minimum")
                        quantity = min_order_size
                except BaseException:
                    pass

            # Validate trade
            trade_data = {
                'symbol': symbol,
                'side': 'BUY',
                'price': price,
                'quantity': quantity,
                'is_opening': True
            }

            is_valid, error = self.risk_manager.validate_trade(trade_data)
            if not is_valid:
                self.logger.warning(f"Trade validation failed: {error}")
                return

            # Calculate stop loss and take profit
            stop_loss = self.risk_manager.calculate_stop_loss(price, 'BUY')
            take_profit = self.risk_manager.calculate_take_profit(price, 'BUY')

            self.logger.info(
                f"Executing BUY: {quantity} {symbol} at {price} (SL: {stop_loss}, TP: {take_profit})")

            # Place order
            order_id = None
            if self.config.trading_enabled:
                try:
                    # Place market buy order
                    order = self.client.create_order(
                        symbol=symbol,
                        side='buy',
                        order_type='market',
                        quantity=quantity
                    )
                    order_id = order.get('orderId')

                    # SAFELY convert order response values with comprehensive fallback
                    raw_price = order.get('price', price)
                    raw_qty = order.get('executedQty', quantity)

                    try:
                        executed_price = float(raw_price) if raw_price not in [
                            None, 'None', 'none', ''] else float(price)
                    except (ValueError, TypeError, AttributeError):
                        self.logger.warning(
                            f"Could not convert price '{raw_price}' to float, using signal price {price}")
                        executed_price = float(price)

                    try:
                        executed_qty = float(raw_qty) if raw_qty not in [
                            None, 'None', 'none', ''] else float(quantity)
                    except (ValueError, TypeError, AttributeError):
                        self.logger.warning(
                            f"Could not convert quantity '{raw_qty}' to float, using calculated quantity {quantity}")
                        executed_qty = float(quantity)

                    self.logger.info(
                        f"BUY order executed: Order ID {order_id}, Price: {executed_price}, Quantity: {executed_qty}")

                    # Update values with actual execution data
                    price = executed_price
                    quantity = executed_qty

                except Exception as e:
                    self.logger.error(f"Failed to place BUY order: {str(e)}")
                    # Send error notification - isolated in try-except
                    try:
                        notifier = get_notifier()
                        if notifier:
                            notifier.notify_error("Order Execution Failed", str(e), f"BUY {symbol}")
                    except Exception as notif_error:
                        self.logger.error(
                            f"Failed to send error notification: {notif_error}", exc_info=True)
                    return
            else:
                self.logger.warning("Trading disabled - simulating order")

            # Record position in database
            position_id = self.db.create_position({
                'symbol': symbol,
                'side': 'BUY',
                'entry_price': price,
                'quantity': quantity,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'strategy': strategy.name
            })

            # Record trade
            self.db.record_trade({
                'symbol': symbol,
                'side': 'BUY',
                'price': price,
                'quantity': quantity,
                'strategy': strategy.name
            })

            self.logger.info(f"Position opened: ID {position_id}")

            # Get current open positions count for notification
            open_positions = self.db.get_open_positions()
            open_positions_count = len(open_positions)
            self.logger.info(
                f"Open positions count after creating position {position_id}: {open_positions_count}")
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Open positions details: {[p['id'] for p in open_positions]}")

            # Send Telegram notification with score and open positions count -
            # isolated in try-except
            try:
                notifier = get_notifier()
                if notifier:
                    self.logger.info(f"Sending position opened notification for {symbol}...")
                    success = notifier.notify_position_opened(
                        symbol=symbol,
                        side='BUY',
                        quantity=quantity,
                        price=price,
                        strategy=strategy.name,
                        score=confidence_score,
                        open_positions_count=open_positions_count
                    )
                    if success:
                        self.logger.info("Position opened notification sent successfully")
                    else:
                        self.logger.warning("Position opened notification returned False")
                else:
                    self.logger.warning(
                        "Notifier is None, cannot send position opened notification")
            except Exception as notif_error:
                self.logger.error(
                    f"Failed to send position opened notification: {notif_error}",
                    exc_info=True)

        except Exception as e:
            self.logger.error(f"Error executing buy order: {str(e)}", exc_info=True)
            # Send error notification - also wrap in try-except
            try:
                notifier = get_notifier()
                if notifier:
                    notifier.notify_error("Buy Order Failed", str(e), f"Symbol: {symbol}")
            except Exception as notif_error:
                self.logger.error(
                    f"Failed to send error notification: {notif_error}",
                    exc_info=True)

    def _execute_sell(self, signal: Dict, strategy: BaseStrategy):
        """Execute sell order (short position)"""
        symbol = signal.get('symbol')
        price = signal.get('price')

        try:
            # ============================================================================
            # CRITICAL: CHECK RISK LIMITS FIRST - BEFORE ANY OTHER OPERATIONS
            # ============================================================================
            # This MUST happen before balance checks, calculations, or any other logic
            # to prevent unlimited position opening when limits are exceeded
            # ============================================================================

            self.logger.debug(f"Checking risk limits for SELL {symbol}...")

            # Check daily trade limit
            if not self.risk_manager.check_daily_limits():
                self.logger.warning(f"🚫 SKIPPING SELL {symbol}: Daily trade limits reached")
                return

            # Check open position limit
            if not self.risk_manager.check_position_limits():
                self.logger.warning(f"🚫 SKIPPING SELL {symbol}: Position limits reached")
                return

            self.logger.debug(f"✅ Risk limits OK for SELL {symbol}")

            # ============================================================================
            # CHECK ADAPTIVE TACTICS - Apply AI-powered trading adjustments
            # ============================================================================
            should_trade, adj_confidence, reason = self._check_adaptive_tactics(symbol, signal)

            if not should_trade:
                self.logger.warning(f"🤖 Adaptive Tactics BLOCKED SELL {symbol}: {reason}")
                return

            self.logger.info(f"🤖 Adaptive Tactics approved SELL {symbol}: {reason}")

            # ============================================================================
            # Get signal details
            # ============================================================================
            confidence_score = signal.get('confidence', 70)  # Get signal confidence score
            self.logger.info(f"Signal confidence score: {confidence_score}/100")

            # Get account balance
            usdt_balance = 0
            try:
                if self.config.use_ccxt:
                    # CCXT balance fetch
                    balance = self.client.fetch_balance()
                    self.logger.debug(f"Balance structure keys: {list(balance.keys())}")

                    # CCXT standard structure: balance['free'][currency_code]
                    # balance['free'] contains available balances by currency
                    # balance['total'] contains total balances (free + locked)
                    try:
                        if 'free' in balance and isinstance(balance['free'], dict):
                            # Log all available currencies and their balances for debugging
                            self.logger.info(
                                f"Available currencies: {list(balance['free'].keys())}")
                            currencies_with_balance = {
                                k: v for k, v in balance['free'].items() if v > 0}
                            if currencies_with_balance:
                                self.logger.info(f"Non-zero balances: {currencies_with_balance}")
                            else:
                                self.logger.warning("No currencies with non-zero balance found!")

                            # Check for USDT in free balances
                            usdt_balance = float(balance['free'].get('USDT', 0))
                            self.logger.info(f"USDT balance from balance['free']: {usdt_balance}")

                            # If USDT is 0, check total balance (might be locked/in orders)
                            if usdt_balance == 0 and 'total' in balance and isinstance(
                                    balance['total'], dict):
                                total_usdt = float(balance['total'].get('USDT', 0))
                                if total_usdt > 0:
                                    self.logger.warning(
                                        f"USDT total balance is {total_usdt} but free balance is 0 "
                                        f"(funds may be locked in orders)")
                        elif 'USDT' in balance and isinstance(balance['USDT'], dict):
                            # Alternative structure: some exchanges may use balance[currency][type]
                            usdt_balance = float(balance['USDT'].get('free', 0))
                            self.logger.info(
                                f"USDT balance from balance['USDT']['free']: {usdt_balance}")
                        else:
                            self.logger.warning(
                                f"Unexpected balance structure. Balance keys: {list(balance.keys())}")
                            if 'free' in balance:
                                self.logger.warning(
                                    f"Type of balance['free']: {type(balance.get('free'))}")
                    except (TypeError, ValueError, AttributeError) as e:
                        self.logger.error(f"Error extracting USDT balance: {e}", exc_info=True)

                    self.logger.info(f"Available USDT balance: ${usdt_balance:.2f}")
                else:
                    # Binance legacy API
                    account = self.client.get_account()
                    for bal in account['balances']:
                        if bal['asset'] == 'USDT':
                            usdt_balance = float(bal['free'])
                            break
                    self.logger.info(f"Available USDT balance: ${usdt_balance:.2f}")
            except Exception as e:
                self.logger.warning(f"Failed to fetch balance: {e}. Using default position size.")
                usdt_balance = 0

            # Calculate position size
            if usdt_balance > 0:
                quantity = self.risk_manager.calculate_position_size(symbol, price, usdt_balance)
                self.logger.info(f"Calculated position size based on balance: {quantity}")
            else:
                # Fallback to configured max position size if balance unavailable
                quantity = self.config.max_position_size
                self.logger.warning(
                    f"Balance is 0 or unavailable, using configured MAX_POSITION_SIZE: {quantity}")

            # Check minimum order size requirements
            try:
                min_order_size = self.client.get_min_order_size(symbol)
                if quantity < min_order_size:
                    self.logger.warning(
                        f"Calculated quantity {quantity} is below minimum {min_order_size}, adjusting")
                    quantity = min_order_size
            except Exception as e:
                self.logger.warning(f"Could not check minimum order size: {e}")

            # Validate trade
            trade_data = {
                'symbol': symbol,
                'side': 'SELL',
                'price': price,
                'quantity': quantity,
                'is_opening': True
            }

            is_valid, error = self.risk_manager.validate_trade(trade_data)
            if not is_valid:
                self.logger.warning(f"Trade validation failed: {error}")
                return

            # Calculate stop loss and take profit
            stop_loss = self.risk_manager.calculate_stop_loss(price, 'SELL')
            take_profit = self.risk_manager.calculate_take_profit(price, 'SELL')

            self.logger.info(
                f"Executing SELL: {quantity} {symbol} at {price} (SL: {stop_loss}, TP: {take_profit})")

            # Place order
            order_id = None
            if self.config.trading_enabled:
                try:
                    # Place market sell order
                    order = self.client.create_order(
                        symbol=symbol,
                        side='sell',
                        order_type='market',
                        quantity=quantity
                    )
                    order_id = order.get('orderId')

                    # SAFELY convert order response values with comprehensive fallback
                    raw_price = order.get('price', price)
                    raw_qty = order.get('executedQty', quantity)

                    try:
                        executed_price = float(raw_price) if raw_price not in [
                            None, 'None', 'none', ''] else float(price)
                    except (ValueError, TypeError, AttributeError):
                        self.logger.warning(
                            f"Could not convert price '{raw_price}' to float, using signal price {price}")
                        executed_price = float(price)

                    try:
                        executed_qty = float(raw_qty) if raw_qty not in [
                            None, 'None', 'none', ''] else float(quantity)
                    except (ValueError, TypeError, AttributeError):
                        self.logger.warning(
                            f"Could not convert quantity '{raw_qty}' to float, using calculated quantity {quantity}")
                        executed_qty = float(quantity)

                    self.logger.info(
                        f"SELL order executed: Order ID {order_id}, Price: {executed_price}, Quantity: {executed_qty}")

                    # Update values with actual execution data
                    price = executed_price
                    quantity = executed_qty

                except Exception as e:
                    self.logger.error(f"Failed to place SELL order: {str(e)}")
                    # Send error notification - isolated in try-except
                    try:
                        notifier = get_notifier()
                        if notifier:
                            notifier.notify_error(
                                "Order Execution Failed", str(e), f"SELL {symbol}")
                    except Exception as notif_error:
                        self.logger.error(
                            f"Failed to send error notification: {notif_error}", exc_info=True)
                    return
            else:
                self.logger.warning("Trading disabled - simulating order")

            # Record position in database
            position_id = self.db.create_position({
                'symbol': symbol,
                'side': 'SELL',
                'entry_price': price,
                'quantity': quantity,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'strategy': strategy.name
            })

            # Record trade
            self.db.record_trade({
                'symbol': symbol,
                'side': 'SELL',
                'price': price,
                'quantity': quantity,
                'strategy': strategy.name
            })

            self.logger.info(f"Position opened: ID {position_id}")

            # Get current open positions count for notification
            open_positions = self.db.get_open_positions()
            open_positions_count = len(open_positions)
            self.logger.info(
                f"Open positions count after creating position {position_id}: {open_positions_count}")
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Open positions details: {[p['id'] for p in open_positions]}")

            # Send Telegram notification with score and open positions count - wrap in
            # try-except to prevent exceptions
            try:
                notifier = get_notifier()
                if notifier:
                    self.logger.info(f"Sending position opened notification for {symbol}...")
                    success = notifier.notify_position_opened(
                        symbol=symbol,
                        side='SELL',
                        quantity=quantity,
                        price=price,
                        strategy=strategy.name,
                        score=confidence_score,
                        open_positions_count=open_positions_count
                    )
                    if success:
                        self.logger.info("Position opened notification sent successfully")
                    else:
                        self.logger.warning("Position opened notification returned False")
                else:
                    self.logger.warning(
                        "Notifier is None, cannot send position opened notification")
            except Exception as notif_error:
                self.logger.error(
                    f"Failed to send position opened notification: {notif_error}",
                    exc_info=True)

        except Exception as e:
            self.logger.error(f"Error executing sell order: {str(e)}", exc_info=True)
            # Send error notification - also wrap in try-except
            try:
                notifier = get_notifier()
                if notifier:
                    notifier.notify_error(
                        "Sell Order Failed", str(e), f"Symbol: {signal.get('symbol')}")
            except Exception as notif_error:
                self.logger.error(
                    f"Failed to send error notification: {notif_error}",
                    exc_info=True)

    def _close_position(self, signal: Dict, strategy: BaseStrategy):
        """Close an open position"""
        position_id = signal.get('position_id')
        score = signal.get('confidence')  # Get signal score

        if not position_id:
            self.logger.warning("No position ID in close signal")
            return

        try:
            # Get position details before closing
            position = self.db.get_position(position_id)
            if not position:
                self.logger.warning(f"Position {position_id} not found")
                return

            if position.get('status') == 'closed':
                self.logger.warning(f"Position {position_id} is already closed, skipping close operation")
                return

            exit_price = signal.get('price', 0)
            entry_price = position.get('entry_price', 0)
            quantity = position.get('quantity', 0)
            side = position.get('side', 'BUY')
            symbol = position.get('symbol', '')
            reason = signal.get('reason', '')

            # Calculate potential P&L before closing
            if side == 'BUY':
                potential_pnl = (exit_price - entry_price) * quantity
            else:
                potential_pnl = (entry_price - exit_price) * quantity

            # Check if this is a stop-loss or take-profit trigger
            is_stop_loss = 'stop loss' in reason.lower() or 'sl' in reason.lower()
            is_take_profit = 'take profit' in reason.lower() or 'tp' in reason.lower()

            # Avoid closing positions at a loss unless it's a stop-loss or take-profit trigger
            if potential_pnl < 0 and not is_stop_loss and not is_take_profit:
                self.logger.info(
                    f"Skipping close of {symbol} position {position_id} - "
                    f"would result in loss of ${potential_pnl:.2f}. Reason: {reason}")
                return

            self.logger.info(
                f"Closing {symbol} position {position_id} with potential P&L: ${potential_pnl:.2f}")

            # Close position on exchange
            order_id = None

            # Store original quantity for notifications and P&L calculation
            # We need to use the original quantity to match what was opened
            original_quantity = quantity

            if self.config.trading_enabled:
                try:
                    # Verify actual balance before closing to avoid InsufficientFunds errors
                    base_asset = symbol.replace('USDT', '').replace('USD', '').replace('BUSD', '')
                    close_side = 'sell' if side == 'BUY' else 'buy'

                    # Get actual balance for the asset we're selling
                    if close_side == 'sell':
                        try:
                            balance_data = self.client.fetch_balance()
                            actual_balance = balance_data.get(base_asset, {}).get('free', 0)

                            # Use the minimum of stored quantity and actual balance
                            if actual_balance <= 0:
                                self.logger.warning(
                                    f"No {base_asset} balance to close position {position_id}. "
                                    f"Marking as closed in database.")
                                # Mark position as closed even though we can't close on exchange
                                # (position was likely already closed manually or doesn't exist)
                                # Use entry_price to record zero PnL since we don't know the actual exit
                                exit_price = entry_price
                            elif actual_balance < quantity:
                                self.logger.warning(
                                    f"Actual {base_asset} balance {actual_balance} "
                                    f"< stored quantity {quantity}. Using stored quantity for close order.")
                                # Use the original quantity for the close order to match the open
                                # The exchange will handle any rounding/dust issues
                        except Exception as balance_err:
                            self.logger.warning(
                                f"Could not fetch balance, using stored quantity: {balance_err}")

                    # Only attempt to close if we have balance or it's a buy order
                    if close_side == 'buy' or (close_side == 'sell' and quantity > 0):
                        # Validate minimum order value before placing order
                        estimated_value = quantity * exit_price if exit_price > 0 else 0
                        min_order_value = 5.0  # $5 minimum for most exchanges

                        if estimated_value > 0 and estimated_value < min_order_value:
                            self.logger.warning(
                                f"Order value ${estimated_value:.2f} below minimum ${min_order_value}. "
                                f"Marking position as closed without exchange order.")
                            # Use entry_price to record zero PnL since we can't close on exchange
                            exit_price = entry_price
                        else:
                            # Attempt to close position on exchange
                            order = self.client.create_order(
                                symbol=symbol,
                                side=close_side,
                                order_type='market',
                                quantity=quantity
                            )
                            order_id = order.get('orderId')
                            # Handle case where price might be None or 'None' string
                            order_price = order.get('price')
                            if order_price and order_price != 'None':
                                try:
                                    exit_price = float(order_price)
                                except (ValueError, TypeError):
                                    # If conversion fails, keep the signal exit_price
                                    pass

                            self.logger.info(
                                f"Position closed: Order ID {order_id}, Exit price: {exit_price}")

                except Exception as e:
                    error_str = str(e).lower()
                    # Check if error is due to position not existing on exchange
                    if 'insufficient' in error_str or 'balance' in error_str or 'exceeded lower limit' in error_str:
                        self.logger.warning(
                            f"Position {position_id} cannot be closed on exchange ({str(e)}). "
                            f"Marking as closed in database.")
                        # Use entry_price to record zero PnL since trade failed to execute
                        exit_price = entry_price
                    else:
                        self.logger.error(f"Failed to close position on exchange: {str(e)}")
                        # Send error notification - isolated in try-except
                        try:
                            notifier = get_notifier()
                            if notifier:
                                notifier.notify_error(
                                    "Position Close Failed", str(e), f"{symbol} Position ID: {position_id}")
                        except Exception as notif_error:
                            self.logger.error(
                                f"Failed to send error notification: {notif_error}", exc_info=True)
                        return
            else:
                self.logger.warning("Trading disabled - simulating position close")

            # Calculate P&L using ORIGINAL quantity to match what was opened
            if side == 'BUY':
                pnl = (exit_price - entry_price) * original_quantity
            else:
                pnl = (entry_price - exit_price) * original_quantity

            pnl_percent = (pnl / (entry_price * original_quantity) *
                           100) if (entry_price * original_quantity) > 0 else 0

            # Update position status
            self.db.update_position(
                position_id,
                status='closed',
                closed_at='CURRENT_TIMESTAMP',
                exit_price=exit_price,
                pnl=pnl
            )

            self.logger.info(
                f"Position {position_id} closed with P&L: ${pnl:.2f} ({pnl_percent:+.2f}%)")

            # Get current open positions count for notification
            open_positions_count = len(self.db.get_open_positions())

            # Send Telegram notification with score and open positions count
            # Use ORIGINAL quantity to match what was opened
            try:
                notifier = get_notifier()
                if notifier:
                    self.logger.info(f"Sending position closed notification for {symbol}...")
                    success = notifier.notify_position_closed(
                        symbol=symbol,
                        side=side,
                        quantity=original_quantity,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl=pnl,
                        pnl_percent=pnl_percent,
                        strategy=position.get('strategy', 'Unknown'),
                        score=score,
                        open_positions_count=open_positions_count
                    )
                    if success:
                        self.logger.info("Position closed notification sent successfully")
                    else:
                        self.logger.warning("Position closed notification returned False")
                else:
                    self.logger.warning(
                        "Notifier is None, cannot send position closed notification")
            except Exception as notif_error:
                self.logger.error(
                    f"Failed to send position closed notification: {notif_error}",
                    exc_info=True)
        except Exception as e:
            self.logger.error(f"Error closing position {position_id}: {str(e)}", exc_info=True)

    def set_tactical_overrides(self, adaptive_tactics):
        """Set adaptive tactics manager for automatic adjustments"""
        self.adaptive_tactics = adaptive_tactics
        self.logger.info("Adaptive tactics manager connected to strategy manager")

    def _check_adaptive_tactics(self, symbol: str, signal: Dict) -> tuple:
        """
        Check adaptive tactics and apply adjustments

        Returns:
            (should_trade: bool, adjusted_confidence: float, reason: str)
        """
        if not self.adaptive_tactics:
            return (True, signal.get('confidence', 0.5) * 100, "No adaptive tactics")

        # Check if symbol is paused
        if not self.adaptive_tactics.should_trade_symbol(symbol):
            return (False, 0, f"{symbol} trading paused due to poor performance")

        # Check confidence threshold
        signal_confidence = (signal.get('confidence', 0.5) * 100)  # Convert to percentage
        min_confidence = self.adaptive_tactics.get_min_confidence()

        if signal_confidence < min_confidence:
            return (
                False,
                signal_confidence,
                f"Signal confidence {signal_confidence:.0f}% below threshold {min_confidence:.0f}%")

        # Check max positions
        max_positions = self.adaptive_tactics.get_max_positions()
        current_positions = len(self.db.get_open_positions())

        if current_positions >= max_positions:
            return (
                False,
                signal_confidence,
                f"Max positions reached ({current_positions}/{max_positions})")

        return (True, signal_confidence, "Adaptive tactics approved")

    def _apply_position_size_adjustment(self, base_size: float) -> float:
        """Apply adaptive tactics position size multiplier"""
        if not self.adaptive_tactics:
            return base_size

        adjusted_size = self.adaptive_tactics.get_adjusted_position_size(base_size)

        if adjusted_size != base_size:
            multiplier = self.adaptive_tactics.tactical_overrides.get(
                'position_size_multiplier', 1.0)
            self.logger.info(
                f"🤖 Adaptive tactics: Adjusting position size by {multiplier}x "
                f"(${base_size:.2f} → ${adjusted_size:.2f})")

        return adjusted_size

    def close_all_positions(self):
        """Close all open positions"""
        self.logger.info("Closing all open positions...")

        open_positions = self.db.get_open_positions()

        for position in open_positions:
            try:
                symbol = position.get('symbol')
                quantity = position.get('quantity', 0)
                side = position.get('side', 'BUY')

                # Close position on exchange
                if self.config.trading_enabled:
                    try:
                        # Close position with opposite order
                        close_side = 'sell' if side == 'BUY' else 'buy'
                        order = self.client.create_order(
                            symbol=symbol,
                            side=close_side,
                            order_type='market',
                            quantity=quantity
                        )
                        self.logger.info(
                            f"Closed position {position['id']} on exchange: Order ID {order.get('orderId')}")
                    except Exception as e:
                        self.logger.error(
                            f"Failed to close position {position['id']} on exchange: {str(e)}")

                # Update database
                self.db.update_position(
                    position['id'],
                    status='closed',
                    closed_at='CURRENT_TIMESTAMP'
                )
                self.logger.info(f"Closed position in database: {position['symbol']}")
            except Exception as e:
                self.logger.error(f"Error closing position {position['id']}: {str(e)}")

        self.logger.info(f"Closed {len(open_positions)} positions")

    def analyze_market_trends(self) -> Dict[str, Dict]:
        """
        Analyze market trends for all trading symbols

        Returns:
            Dictionary mapping symbol to trend analysis
        """
        trends = {}

        try:
            # Get trading symbols
            trading_symbols = self._get_trading_symbols()

            for symbol in trading_symbols:
                try:
                    # Get klines for trend analysis
                    klines = self._get_klines_for_trend(symbol)

                    if klines and len(klines) >= 50:
                        # Analyze trend
                        trend_info = self.trend_analyzer.analyze_trend(
                            klines,
                            symbol=symbol,
                            timeframe='1h'
                        )
                        trends[symbol] = trend_info

                        self.logger.info(
                            f"Trend for {symbol}: {trend_info['trend']} "
                            f"(strength: {trend_info['strength'] * 100:.1f}%, "
                            f"ADX: {trend_info['adx']:.1f})"
                        )
                    else:
                        self.logger.warning(f"Insufficient data for trend analysis on {symbol}")

                except Exception as e:
                    self.logger.error(f"Error analyzing trend for {symbol}: {str(e)}")

            # Store current trends
            self.current_trends = trends

            # Log summary
            if trends:
                summary = self.trend_analyzer.get_trend_summary(trends)
                self.logger.info(f"Market trends summary:\n{summary}")

        except Exception as e:
            self.logger.error(f"Error in market trend analysis: {str(e)}", exc_info=True)

        return trends

    def _get_trading_symbols(self) -> List[str]:
        """Get list of trading symbols"""
        trading_symbols = getattr(self.config, 'trading_symbols', None)

        if trading_symbols and isinstance(trading_symbols, list) and len(trading_symbols) > 0:
            return trading_symbols

        default_symbol = getattr(self.config, 'default_symbol', 'BTCUSDT')
        return [default_symbol]

    def _get_klines_for_trend(self, symbol: str, limit: int = 200):
        """Get klines data for trend analysis"""
        try:
            if self.strategies:
                # Use first strategy's method to get klines
                return self.strategies[0].get_klines(symbol, interval='1h', limit=limit)
            return None
        except Exception as e:
            self.logger.error(f"Error getting klines for {symbol}: {str(e)}")
            return None

    def get_current_trends(self) -> Dict[str, Dict]:
        """Get current trend analysis for all symbols"""
        return self.current_trends
