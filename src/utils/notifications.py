"""
Telegram Notifications Module
Sends trading alerts and notifications via Telegram with multilingual support
"""

import os
import logging
import requests
from typing import Optional, Dict, Any
from datetime import datetime

# Import translation manager
try:
    from utils.translations import get_translation_manager
    TRANSLATIONS_AVAILABLE = True
except ImportError:
    TRANSLATIONS_AVAILABLE = False


class TelegramNotifier:
    """Telegram notification handler for trading bot with multilingual support"""

    def __init__(
            self,
            bot_token: Optional[str] = None,
            chat_id: Optional[str] = None,
            enabled: bool = True,
            language: str = 'en'):
        """
        Initialize Telegram notifier

        Args:
            bot_token: Telegram bot token
            chat_id: Telegram chat ID
            enabled: Whether notifications are enabled
            language: Notification language code (default: 'en')
        """
        self.logger = logging.getLogger(__name__)
        self.enabled = enabled
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID', '')

        # Initialize deduplication cache - prevents sending duplicate notifications
        # Key: (notification_type, symbol, side), Value: timestamp of last notification
        self._notification_cache: Dict[tuple, float] = {}
        self._cache_timeout = 60  # seconds - notifications for same position within this time are considered duplicates

        # Snapshot of key metrics from the previous hourly report for change detection
        # Stores (open_positions_count, daily_pnl, usdt_balance) to detect unchanged reports
        self._last_hourly_snapshot: Optional[tuple] = None

        # Initialize translation manager
        self.language = language or os.getenv('NOTIFICATION_LANGUAGE', 'en')
        if TRANSLATIONS_AVAILABLE:
            self.translator = get_translation_manager(self.language)
            self.logger.info(f"Notifications language: {self.language}")
        else:
            self.translator = None
            self.logger.warning("Translations module not available, using English")

        if self.enabled:
            if not self.bot_token or not self.chat_id:
                self.logger.warning(
                    "Telegram bot token or chat ID not configured. Notifications disabled.")
                self.enabled = False
            else:
                self.logger.info("Telegram notifier initialized successfully (using requests)")

    def t(self, key, default=None):
        """
        Get translation for a key

        Args:
            key: Translation key
            default: Default value if translator not available

        Returns:
            Translated string
        """
        if self.translator:
            return self.translator.get(key, default)
        return default or key

    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """
        Send a message to Telegram using direct HTTP request

        Args:
            message: Message text
            parse_mode: Parse mode (HTML or Markdown)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            return False

        try:
            # Truncate message to Telegram's limit
            if len(message) > 4096:
                message = message[:4093] + "..."

            # Send via direct HTTP request to Telegram API
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            self.logger.info("Telegram message sent successfully")
            return True

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}", exc_info=True)
            return False

    def _is_duplicate_notification(self, notification_type: str, symbol: str, side: str) -> bool:
        """
        Check if this notification was recently sent (within cache timeout)

        Args:
            notification_type: Type of notification (e.g., 'position_opened', 'position_closed')
            symbol: Trading symbol
            side: BUY or SELL

        Returns:
            True if this is a duplicate notification, False otherwise
        """
        import time
        cache_key = (notification_type, symbol, side)
        current_time = time.time()

        # Check if notification exists in cache and is still fresh
        if cache_key in self._notification_cache:
            last_notification_time = self._notification_cache[cache_key]
            time_since_last = current_time - last_notification_time

            # Reduce timeout to 10 seconds for position_opened to allow multiple positions
            # on the same symbol to be notified properly
            timeout = 10 if notification_type == 'position_opened' else self._cache_timeout

            if time_since_last < timeout:
                self.logger.warning(
                    f"Duplicate notification blocked: {notification_type} for {symbol} {side} "
                    f"(last sent {time_since_last:.1f}s ago, timeout: {timeout}s)"
                )
                return True

        # Update cache with current time
        self._notification_cache[cache_key] = current_time

        # Clean old entries from cache (older than 2x timeout)
        expired_keys = [
            key for key, timestamp in self._notification_cache.items()
            if current_time - timestamp > (self._cache_timeout * 2)
        ]
        for key in expired_keys:
            del self._notification_cache[key]

        return False

    def notify_position_opened(self, symbol: str, side: str, quantity: float,
                               price: float, strategy: str = "Unknown", score: int = None,
                               open_positions_count: int = None) -> bool:
        """
        Notify about opened position with duplicate prevention

        Args:
            symbol: Trading pair symbol
            side: BUY or SELL
            quantity: Position quantity
            price: Entry price
            strategy: Strategy name
            score: Signal confidence score (0-100)
            open_positions_count: Number of currently open positions

        Returns:
            True if sent successfully, False if duplicate or failed
        """
        # Check for duplicate notification
        if self._is_duplicate_notification('position_opened', symbol, side):
            self.logger.info(f"Skipping duplicate position opened notification for {symbol} {side}")
            return False
        emoji = "🟢" if str(side).upper() == "BUY" else "🔴"  # Define early for except block

        try:
            # SAFELY convert all numeric values to float with fallback
            try:
                price = float(price) if price not in [None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                self.logger.warning(f"Could not convert price '{price}' to float, using 0.0")
                price = 0.0

            try:
                quantity = float(quantity) if quantity not in [None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                self.logger.warning(f"Could not convert quantity '{quantity}' to float, using 0.0")
                quantity = 0.0

            # Build message with safe string formatting
            score_text = f"\n⭐ Signal Score: <b>{score}/100</b>" if score is not None else ""
            positions_text = (
                f"\n📋 Open Positions: <b>{open_positions_count}</b>"
                if open_positions_count is not None else ""
            )

            # Generate AI commentary
            ai_commentary = ""
            try:
                from mi.ai_commentary import get_commentary_generator
                commentary_gen = get_commentary_generator(self.logger, language=self.language)
                confidence_normalized = score / 100 if score is not None else None
                ai_commentary = commentary_gen.generate_position_open_commentary(
                    symbol, side, confidence_normalized
                )
            except Exception as e:
                self.logger.error(f"Could not generate AI commentary: {e}", exc_info=True)
                # Add visible error to notification instead of silently failing
                ai_commentary = "\n\n⚠️ <i>AI Commentary unavailable</i>"

            message = f"""
{emoji} <b>Position Opened</b>

📊 Symbol: <code>{symbol}</code>
📈 Side: <b>{side.upper()}</b>
💰 Quantity: <code>{quantity}</code>
💵 Price: <code>${price:,.2f}</code>
🎯 Strategy: <i>{strategy}</i>{score_text}{positions_text}{ai_commentary}

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            return self.send_message(message.strip())
        except Exception as e:
            self.logger.error(
                f"Error formatting position opened notification: {e}. price={price}, quantity={quantity}",
                exc_info=True)
            # Send simplified notification without formatting
            try:
                simplified_message = f"""
{emoji} <b>Position Opened</b>

📊 Symbol: <code>{symbol}</code>
📈 Side: <b>{side.upper()}</b>
🎯 Strategy: <i>{strategy}</i>

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                return self.send_message(simplified_message.strip())
            except Exception as e2:
                self.logger.error(f"Failed to send even simplified notification: {e2}")
                return False

    def notify_position_closed(self, symbol: str, side: str, quantity: float,
                               entry_price: float, exit_price: float,
                               pnl: float, pnl_percent: float,
                               strategy: str = "Unknown", score: int = None,
                               open_positions_count: int = None) -> bool:
        """
        Notify about closed position with duplicate prevention

        Args:
            symbol: Trading pair symbol
            side: BUY or SELL (original position)
            quantity: Position quantity
            entry_price: Entry price
            exit_price: Exit price
            pnl: Profit/Loss amount
            pnl_percent: Profit/Loss percentage
            strategy: Strategy name
            score: Signal confidence score (0-100)
            open_positions_count: Number of currently open positions

        Returns:
            True if sent successfully, False if duplicate or failed
        """
        # Check for duplicate notification
        if self._is_duplicate_notification('position_closed', symbol, side):
            self.logger.info(f"Skipping duplicate position closed notification for {symbol} {side}")
            return False

        try:
            # SAFELY convert all numeric values to float with fallback
            try:
                entry_price = float(entry_price) if entry_price not in [
                    None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                self.logger.warning(
                    f"Could not convert entry_price '{entry_price}' to float, using 0.0")
                entry_price = 0.0

            try:
                exit_price = float(exit_price) if exit_price not in [
                    None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                self.logger.warning(
                    f"Could not convert exit_price '{exit_price}' to float, using 0.0")
                exit_price = 0.0

            try:
                quantity = float(quantity) if quantity not in [None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                self.logger.warning(f"Could not convert quantity '{quantity}' to float, using 0.0")
                quantity = 0.0

            try:
                pnl = float(pnl) if pnl not in [None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                self.logger.warning(f"Could not convert pnl '{pnl}' to float, using 0.0")
                pnl = 0.0

            try:
                pnl_percent = float(pnl_percent) if pnl_percent not in [
                    None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                self.logger.warning(
                    f"Could not convert pnl_percent '{pnl_percent}' to float, using 0.0")
                pnl_percent = 0.0

            profit = pnl > 0
            emoji = "✅" if profit else "❌"
            pnl_emoji = "💰" if profit else "💸"

            score_text = f"\n⭐ Signal Score: <b>{score}/100</b>" if score is not None else ""
            positions_text = (
                f"\n📋 Open Positions: <b>{open_positions_count}</b>"
                if open_positions_count is not None else ""
            )

            # Format P&L with adaptive decimal places for small values
            # Use more decimals for values < $0.01 to show actual loss/profit
            if abs(pnl) < 0.01:
                pnl_str = f"${pnl:+.6f}".rstrip('0').rstrip('.')
            elif abs(pnl) < 1:
                pnl_str = f"${pnl:+.4f}".rstrip('0').rstrip('.')
            else:
                pnl_str = f"${pnl:+,.2f}"

            # Generate AI commentary
            ai_commentary = ""
            try:
                from mi.ai_commentary import get_commentary_generator
                commentary_gen = get_commentary_generator(self.logger, language=self.language)
                ai_commentary = commentary_gen.generate_position_close_commentary(
                    symbol, side, pnl, pnl_percent
                )
            except Exception as e:
                self.logger.error(f"Could not generate AI commentary: {e}", exc_info=True)
                # Add visible error to notification instead of silently failing
                ai_commentary = "\n\n⚠️ <i>AI Commentary unavailable</i>"

            message = f"""
{emoji} <b>Position Closed</b>

📊 Symbol: <code>{symbol}</code>
📈 Side: <b>{side.upper()}</b>
💰 Quantity: <code>{quantity}</code>
📥 Entry: <code>${entry_price:,.2f}</code>
📤 Exit: <code>${exit_price:,.2f}</code>

{pnl_emoji} P&L: <b>{pnl_str}</b> ({pnl_percent:+.2f}%)
🎯 Strategy: <i>{strategy}</i>{score_text}{positions_text}{ai_commentary}

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            return self.send_message(message.strip())
        except Exception as e:
            self.logger.error(f"Error formatting position closed notification: {e}", exc_info=True)
            # Send simplified notification
            try:
                emoji = "✅" if pnl > 0 else "❌"
                simplified_message = f"""
{emoji} <b>Position Closed</b>

📊 Symbol: <code>{symbol}</code>
📈 Side: <b>{side.upper()}</b>
🎯 Strategy: <i>{strategy}</i>

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                return self.send_message(simplified_message.strip())
            except Exception as e2:
                self.logger.error(f"Failed to send even simplified notification: {e2}")
                return False

    def notify_stop_loss_triggered(self, symbol: str, side: str, quantity: float,
                                   entry_price: float, stop_price: float,
                                   loss: float, loss_percent: float) -> bool:
        """
        Notify about stop-loss trigger

        Args:
            symbol: Trading pair symbol
            side: Original position side
            quantity: Position quantity
            entry_price: Entry price
            stop_price: Stop-loss price
            loss: Loss amount
            loss_percent: Loss percentage

        Returns:
            True if sent successfully
        """
        try:
            # Ensure all numeric values are valid floats
            entry_price = float(entry_price) if entry_price is not None else 0.0
            stop_price = float(stop_price) if stop_price is not None else 0.0
            quantity = float(quantity) if quantity is not None else 0.0
            loss = float(loss) if loss is not None else 0.0
            loss_percent = float(loss_percent) if loss_percent is not None else 0.0

            message = f"""
⚠️ <b>Stop-Loss Triggered</b>

📊 Symbol: <code>{symbol}</code>
📈 Side: <b>{side.upper()}</b>
💰 Quantity: <code>{quantity}</code>
📥 Entry: <code>${entry_price:,.2f}</code>
🛑 Stop: <code>${stop_price:,.2f}</code>

💸 Loss: <b>${loss:,.2f}</b> ({loss_percent:.2f}%)

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            return self.send_message(message.strip())
        except (ValueError, TypeError) as e:
            self.logger.error(f"Error formatting stop-loss notification: {e}")
            return False

    def notify_take_profit_triggered(self, symbol: str, side: str, quantity: float,
                                     entry_price: float, tp_price: float,
                                     profit: float, profit_percent: float) -> bool:
        """
        Notify about take-profit trigger

        Args:
            symbol: Trading pair symbol
            side: Original position side
            quantity: Position quantity
            entry_price: Entry price
            tp_price: Take-profit price
            profit: Profit amount
            profit_percent: Profit percentage

        Returns:
            True if sent successfully
        """
        try:
            # Ensure all numeric values are valid floats
            entry_price = float(entry_price) if entry_price is not None else 0.0
            tp_price = float(tp_price) if tp_price is not None else 0.0
            quantity = float(quantity) if quantity is not None else 0.0
            profit = float(profit) if profit is not None else 0.0
            profit_percent = float(profit_percent) if profit_percent is not None else 0.0

            message = f"""
🎯 <b>Take-Profit Triggered</b>

📊 Symbol: <code>{symbol}</code>
📈 Side: <b>{side.upper()}</b>
💰 Quantity: <code>{quantity}</code>
📥 Entry: <code>${entry_price:,.2f}</code>
✅ Target: <code>${tp_price:,.2f}</code>

💰 Profit: <b>${profit:,.2f}</b> (+{profit_percent:.2f}%)

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            return self.send_message(message.strip())
        except (ValueError, TypeError) as e:
            self.logger.error(f"Error formatting take-profit notification: {e}")
            return False

    def notify_daily_summary(self, total_trades: int, winning_trades: int,
                             losing_trades: int, total_pnl: float,
                             win_rate: float, largest_win: float,
                             largest_loss: float, strategy: str = "Unknown") -> bool:
        """
        Send daily trading summary

        Args:
            total_trades: Total number of trades
            winning_trades: Number of winning trades
            losing_trades: Number of losing trades
            total_pnl: Total profit/loss
            win_rate: Win rate percentage
            largest_win: Largest winning trade
            largest_loss: Largest losing trade
            strategy: Active trading strategy

        Returns:
            True if sent successfully
        """
        pnl_emoji = "💰" if total_pnl > 0 else "💸" if total_pnl < 0 else "➖"

        message = f"""
📊 <b>Daily Summary</b>

🎯 Strategy: <i>{strategy}</i>
📈 Trades: <b>{total_trades}</b>
✅ Wins: <b>{winning_trades}</b>
❌ Losses: <b>{losing_trades}</b>
🎯 Win Rate: <b>{win_rate:.1f}%</b>

{pnl_emoji} Total P&L: <b>${total_pnl:,.2f}</b>
💰 Largest Win: <code>${largest_win:,.2f}</code>
💸 Largest Loss: <code>${largest_loss:,.2f}</code>

📅 Date: {datetime.now().strftime('%Y-%m-%d')}
"""
        return self.send_message(message.strip())

    def notify_error(self, error_type: str, error_message: str,
                     details: Optional[str] = None) -> bool:
        """
        Notify about critical error

        Args:
            error_type: Type of error
            error_message: Error message
            details: Additional details

        Returns:
            True if sent successfully
        """
        message = f"""
❌ <b>Error Alert</b>

⚠️ Type: <b>{error_type}</b>
📝 Message: <code>{error_message}</code>
"""
        if details:
            message += f"\n📋 Details:\n<code>{details}</code>\n"

        message += f"\n⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        return self.send_message(message.strip())

    def notify_risk_limit_warning(self, limit_type: str, current_value: float,
                                  max_value: float, unit: str = "") -> bool:
        """
        Notify about risk limit warning

        Args:
            limit_type: Type of limit (e.g., "Daily Loss", "Max Positions")
            current_value: Current value
            max_value: Maximum allowed value
            unit: Unit of measurement (e.g., "%", "$")

        Returns:
            True if sent successfully
        """
        percentage = (current_value / max_value * 100) if max_value > 0 else 0

        message = f"""
⚠️ <b>Risk Limit Warning</b>

📊 Limit: <b>{limit_type}</b>
📈 Current: <code>{current_value}{unit}</code>
🎯 Maximum: <code>{max_value}{unit}</code>
📉 Usage: <b>{percentage:.1f}%</b>

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message.strip())

    def notify_bot_started(self, exchange: str, trading_enabled: bool,
                           max_positions: int, max_daily_trades: int,
                           strategy: str = "Unknown") -> bool:
        """
        Notify about bot startup

        Args:
            exchange: Exchange name
            trading_enabled: Whether trading is enabled
            max_positions: Maximum open positions
            max_daily_trades: Maximum daily trades
            strategy: Active trading strategy

        Returns:
            True if sent successfully
        """
        status = "🟢 ENABLED" if trading_enabled else "🟡 MONITORING ONLY"

        message = f"""
{self.t('bot_started', '🤖 <b>Trading Bot Started</b>')}

🏦 Exchange: <b>{exchange}</b>
⚡ Trading: {status}
🎯 {self.t('strategy', 'Strategy')}: <i>{strategy}</i>
📊 Max Positions: <b>{max_positions}</b>
📈 Max Daily Trades: <b>{max_daily_trades}</b>

⏰ {self.t('time', 'Time')}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message.strip())

    def notify_hourly_summary(self, open_positions_count: int,
                              balance_data: Dict[str, float],
                              daily_pnl: float,
                              total_pnl: float = None,
                              ai_tactics: Dict[str, Any] = None,
                              trends: Dict[str, Dict] = None,
                              strategy_adjustments: Dict[str, Any] = None,
                              elite_ai_data: Dict[str, Any] = None,
                              news_summary: Dict[str, Any] = None,
                              daily_trades: int = None,
                              ml_status: Dict[str, Any] = None,
                              roi: float = None) -> bool:
        """
        Send hourly status summary with trend analysis

        Args:
            open_positions_count: Number of currently open positions
            balance_data: Dictionary of currency balances (e.g., {'USDT': 1000, 'BTC': 0.5})
            daily_pnl: Daily profit/loss in USDT
            total_pnl: Total profit/loss (optional)
            ai_tactics: Current AI adaptive tactics settings (optional)
            trends: Trend analysis data for all symbols (optional)
            strategy_adjustments: Strategy adjustments from advisor (optional)
            elite_ai_data: Elite AI analysis data (optional)
            news_summary: Crypto news summary with AI analysis (optional)
            daily_trades: Number of trades made today (optional)
            ml_status: ML model metrics per symbol, e.g.
                {'BTCUSDT': {'accuracy': 0.63, 'f1_score': 0.61,
                             'train_samples': 8000, 'training_date': '...'},
                 '_training_active': True, '_training_symbol': 'ETHUSDT'}
            roi: Monthly ROI in percent (e.g. 5.3 means +5.3%). Optional.

        Returns:
            True if sent successfully
        """
        try:
            # Format balance data
            balance_lines = []
            for currency, amount in balance_data.items():
                try:
                    amount_float = float(amount) if amount not in [
                        None, 'None', 'none', ''] else 0.0
                except (ValueError, TypeError, AttributeError):
                    amount_float = 0.0

                # Skip zero balances or add them with symbol
                if amount_float > 0:
                    if currency == 'USDT' or currency.endswith('USD'):
                        balance_lines.append(f"💵 {currency}: <code>${amount_float:,.2f}</code>")
                    else:
                        balance_lines.append(f"🪙 {currency}: <code>{amount_float:.8f}</code>")

            # If no balances, show message
            if not balance_lines:
                balance_lines.append("💵 No significant balances")

            # Safe P/L conversion
            try:
                daily_pnl = float(daily_pnl) if daily_pnl not in [None, 'None', 'none', ''] else 0.0
            except (ValueError, TypeError, AttributeError):
                daily_pnl = 0.0

            # P/L emoji and formatting
            if daily_pnl > 0:
                pnl_emoji = "💰"
                pnl_sign = "+"
            elif daily_pnl < 0:
                pnl_emoji = "💸"
                pnl_sign = ""
            else:
                pnl_emoji = "➖"
                pnl_sign = ""

            # Build message
            balance_text = "\n".join(balance_lines)

            # Detect whether key metrics have changed since the last hourly report
            # Snapshot: (open_positions, daily_pnl rounded to cents, USDT/BUSD balance rounded to cents)
            stable_balance_raw = balance_data.get('USDT') or balance_data.get('BUSD') or 0
            try:
                usdt_balance = round(float(stable_balance_raw), 2)
            except (ValueError, TypeError, AttributeError):
                usdt_balance = 0.0
            current_snapshot = (open_positions_count, round(daily_pnl, 2), usdt_balance)
            data_unchanged = (self._last_hourly_snapshot is not None
                              and current_snapshot == self._last_hourly_snapshot)

            # Generate AI daily commentary
            ai_commentary = ""
            try:
                from mi.ai_commentary import get_commentary_generator
                commentary_gen = get_commentary_generator(self.logger, language=self.language)
                ai_commentary = commentary_gen.generate_daily_summary_commentary(
                    daily_pnl, open_positions_count
                )
            except Exception as e:
                self.logger.error(f"Could not generate AI commentary: {e}", exc_info=True)
                # Add visible error to notification instead of silently failing
                ai_commentary = "\n\n⚠️ <i>AI Commentary unavailable</i>"

            message = f"""
{self.t('hourly_summary', '📊 <b>Hourly Status Summary</b>')}

📋 {self.t('open_positions', 'Open Positions')}: <b>{open_positions_count}</b>

💰 <b>{self.t('balances', 'Balances')}:</b>
{balance_text}

{pnl_emoji} <b>{self.t('daily_pnl', 'Daily P&L')}:</b> <code>{pnl_sign}${daily_pnl:,.2f}</code>
"""

            # Add daily trade count if provided
            if daily_trades is not None:
                message += f"📊 <b>{self.t('daily_trades', 'Сделок сегодня')}:</b> <code>{daily_trades}</code>\n"

            # Add ROI if provided
            if roi is not None:
                try:
                    roi_float = float(roi)
                    roi_sign = "+" if roi_float > 0 else ""
                    roi_emoji = "📈" if roi_float > 0 else "📉" if roi_float < 0 else "➖"
                    message += f"{roi_emoji} <b>{self.t('roi', 'ROI (месяц)')}:</b> <code>{roi_sign}{roi_float:.2f}%</code>\n"
                except (ValueError, TypeError):
                    pass

            # Indicate when key metrics are unchanged since the last hourly report.
            # This is expected and normal when the bot is in scanning mode with no open
            # positions.  The message is informational — it confirms the bot is running
            # correctly and simply waiting for a high-quality setup.
            if data_unchanged:
                message += (
                    f"\n📋 <i>{self.t('data_unchanged', 'Данные не изменились с прошлого отчёта — '
                                     'бот работает в штатном режиме и сканирует рынок.')}</i>\n"
                )

            # Add total P/L if provided
            if total_pnl is not None:
                try:
                    total_pnl = float(total_pnl) if total_pnl not in [
                        None, 'None', 'none', ''] else 0.0
                except (ValueError, TypeError, AttributeError):
                    total_pnl = 0.0

                total_emoji = "💰" if total_pnl > 0 else "💸" if total_pnl < 0 else "➖"
                total_sign = "+" if total_pnl > 0 else ""
                message += f"{total_emoji} <b>{self.t('pnl', 'P&L')} Total:</b> <code>{total_sign}${total_pnl:,.2f}</code>\n"

            # Add AI commentary if available
            if ai_commentary:
                message += ai_commentary + "\n"

            # Add TREND ANALYSIS section if available
            if trends:
                try:
                    bullish = sum(1 for t in trends.values() if t.get('trend') == 'BULLISH')
                    bearish = sum(1 for t in trends.values() if t.get('trend') == 'BEARISH')
                    sideways = sum(1 for t in trends.values() if t.get('trend') == 'SIDEWAYS')
                    total_symbols = len(trends)

                    message += f"\n📈 <b>{self.t('trend_analysis', 'Trend Analysis')}:</b>\n"

                    # Market overview
                    if bullish > bearish and bullish > sideways:
                        market_sentiment = f"Бычий рынок 🟢 ({bullish}/{total_symbols})"
                    elif bearish > bullish and bearish > sideways:
                        market_sentiment = f"Медвежий рынок 🔴 ({bearish}/{total_symbols})"
                    else:
                        market_sentiment = f"Смешанный рынок 🟡 ({bullish}↑ {bearish}↓ {sideways}↔️)"

                    message += f"  📊 {self.t('market_sentiment', 'Market Sentiment')}: <b>{market_sentiment}</b>\n\n"

                    # Show top 3 symbols with trends
                    message += "  <b>Топ символы:</b>\n"
                    trend_count = 0
                    for symbol, trend_info in list(trends.items())[:3]:
                        if trend_count >= 3:
                            break

                        trend_type = trend_info.get('trend', 'SIDEWAYS')
                        strength = trend_info.get('strength', 0)
                        adx = trend_info.get('adx', 0)

                        # Emoji based on trend
                        if trend_type == 'BULLISH':
                            trend_emoji = "📈"
                        elif trend_type == 'BEARISH':
                            trend_emoji = "📉"
                        else:
                            trend_emoji = "↔️"

                        # Generate trading strategy
                        if trend_type == 'BULLISH':
                            if strength > 0.7 and adx > 30:
                                strategy = "Активно покупать"
                            elif strength > 0.5:
                                strategy = "Покупать на сигналах"
                            else:
                                strategy = "Осторожно"
                        elif trend_type == 'BEARISH':
                            if strength > 0.7 and adx > 30:
                                strategy = "Избегать покупок"
                            elif strength > 0.5:
                                strategy = "Не покупать"
                            else:
                                strategy = "Минимальные позиции"
                        else:
                            strategy = "Ждать прорыва" if adx < 20 else "Range-торговля"

                        strength_pct = strength * 100
                        message += (
                            f"  {trend_emoji} <code>{symbol}</code>: "
                            f"{strength_pct:.0f}% ADX:{adx:.0f} - <i>{strategy}</i>\n"
                        )
                        trend_count += 1

                    # Trading plan summary
                    strong_bullish = [s for s, t in trends.items()
                                      if t.get('trend') == 'BULLISH' and t.get('strength', 0) > 0.6]
                    strong_bearish = [s for s, t in trends.items()
                                      if t.get('trend') == 'BEARISH' and t.get('strength', 0) > 0.6]

                    message += "\n  <b>📋 План на час:</b>\n"
                    if strong_bullish:
                        symbols_list = ", ".join(strong_bullish[:2])
                        if len(strong_bullish) > 2:
                            symbols_list += f" +{len(strong_bullish) - 2}"
                        message += f"  ✅ Покупать: <code>{symbols_list}</code>\n"
                    if strong_bearish:
                        symbols_list = ", ".join(strong_bearish[:2])
                        if len(strong_bearish) > 2:
                            symbols_list += f" +{len(strong_bearish) - 2}"
                        message += f"  ⛔ Избегать: <code>{symbols_list}</code>\n"
                    if not strong_bullish and not strong_bearish:
                        message += "  ⏸️ Режим ожидания: слабые тренды\n"

                    message += "  💡 Адаптация размера под тренд\n"

                except Exception as e:
                    self.logger.error(f"Error formatting trend analysis: {e}")
                    message += "\n📈 Анализ трендов недоступен\n"

            # Add AI Adaptive Tactics section if available
            if ai_tactics:
                try:
                    position_mult = ai_tactics.get('position_size_multiplier', 1.0)
                    confidence_threshold = ai_tactics.get(
                        'confidence_threshold', 0.5) * 100  # Convert to percentage
                    max_pos = ai_tactics.get('max_positions', 'N/A')
                    blocked = ai_tactics.get('blocked_symbols', [])

                    message += "\n" + self.t('ai_adaptive_strategy') + "\n"
                    message += f"  📊 Position Size: <b>{position_mult:.0%}</b>\n"
                    message += f"  🎯 Min Confidence: <b>{confidence_threshold:.0f}%</b>\n"
                    message += f"  📋 Max Positions: <b>{max_pos}</b>\n"

                    if blocked:
                        blocked_str = ", ".join(blocked[:3])  # Show first 3
                        if len(blocked) > 3:
                            blocked_str += f" +{len(blocked) - 3} more"
                        message += f"  ⛔ Blocked Pairs: <code>{blocked_str}</code>\n"
                    else:
                        message += "  ✅ All pairs active\n"
                except Exception as e:
                    self.logger.error(f"Error formatting AI tactics: {e}")

            # Add Strategy Adjustments section if available
            if strategy_adjustments is not None:
                self.logger.info(
                    f"📊 Displaying strategy adjustments in notification: {strategy_adjustments}")
                try:
                    adjustments = strategy_adjustments.get('adjustments', {})
                    reasoning = strategy_adjustments.get('reasoning', [])
                    risk_level = strategy_adjustments.get('risk_level', 'normal')

                    # Risk level emoji
                    risk_emoji = {
                        'very_low': '🟢',
                        'low': '🟢',
                        'normal': '🟡',
                        'high': '🟠',
                        'critical': '🔴'
                    }.get(risk_level, '⚪')

                    # Translated risk level
                    risk_level_text = {
                        'very_low': self.t('risk_very_low', 'Very Low'),
                        'low': self.t('risk_low', 'Low'),
                        'normal': self.t('risk_normal', 'Normal'),
                        'high': self.t('risk_high', 'High'),
                        'critical': self.t('risk_critical', 'Critical')
                    }.get(risk_level, risk_level)

                    message += f"\n\n📊 <b>{self.t('strategy_status', 'AI Strategy Status')}:</b>\n"

                    # Always show risk level
                    message += f"  {risk_emoji} {self.t('risk_level', 'Risk Level')}: <b>{risk_level_text}</b>\n"

                    # Show adjustments section
                    message += f"\n  <b>{self.t('adjustments', 'Current Adjustments')}:</b>\n"

                    if adjustments:
                        if 'position_size_multiplier' in adjustments:
                            mult = adjustments['position_size_multiplier']
                            message += f"  📊 Position Size: <b>{mult:.0%}</b>\n"

                        # Support both 'confidence_threshold_adjustment' (StrategyAdvisor)
                        # and 'confidence_threshold' (AdaptiveTactics) key names
                        if 'confidence_threshold_adjustment' in adjustments:
                            base_conf = 50.0
                            conf = base_conf + adjustments['confidence_threshold_adjustment']
                            conf = max(30.0, min(95.0, conf))
                            message += f"  🎯 Min Confidence: <b>{conf:.0f}%</b>\n"
                        elif 'confidence_threshold' in adjustments:
                            conf = adjustments['confidence_threshold'] * 100
                            message += f"  🎯 Min Confidence: <b>{conf:.0f}%</b>\n"

                        # Support both 'max_positions_multiplier' and 'max_positions'
                        if 'max_positions_multiplier' in adjustments:
                            base_max = 5
                            max_pos = max(1, int(base_max * adjustments['max_positions_multiplier']))
                            message += f"  📋 Max Positions: <b>{max_pos}</b>\n"
                        elif 'max_positions' in adjustments:
                            max_pos = adjustments['max_positions']
                            message += f"  📋 Max Positions: <b>{max_pos}</b>\n"
                    else:
                        message += f"  ✅ {self.t('optimal_conditions', 'Optimal trading conditions - no adjustments needed')}\n"

                    # Always show reasoning if available (independent of adjustments)
                    if reasoning and len(reasoning) > 0:
                        message += f"\n  <b>{self.t('reasoning', 'Reasoning')}:</b>\n"
                        for reason in reasoning[:3]:
                            message += f"  • {reason}\n"

                except Exception as e:
                    self.logger.error(f"Error formatting strategy adjustments: {e}")

            # Add ML Model Status section if available
            if ml_status:
                try:
                    training_active = ml_status.get('_training_active', False)
                    training_symbol = ml_status.get('_training_symbol', '')
                    summary = ml_status.get('_summary', {})
                    # Filter out private keys — only symbol-keyed metrics remain
                    model_entries = {k: v for k, v in ml_status.items()
                                     if not k.startswith('_') and isinstance(v, dict)}

                    trained_count = summary.get('trained_count', len(model_entries))
                    avg_acc = summary.get('avg_accuracy', 0.0)

                    # Overall knowledge-level label
                    if avg_acc >= 0.70:
                        knowledge_label = "🧠 Expert"
                    elif avg_acc >= 0.60:
                        knowledge_label = "📚 Intermediate"
                    elif avg_acc >= 0.50:
                        knowledge_label = "🌱 Learning"
                    else:
                        knowledge_label = "⏳ Initializing"

                    # Simple ASCII progress bar (10 chars wide) based on avg accuracy
                    _bar_fill = min(10, int(avg_acc * 10))
                    _bar = "█" * _bar_fill + "░" * (10 - _bar_fill)

                    message += "\n\n🤖 <b>AI/ML Training Status:</b>\n"

                    if training_active and training_symbol:
                        message += f"  🔄 <i>Training in progress: <b>{training_symbol}</b></i>\n"

                    if model_entries:
                        message += (
                            f"  📊 Models trained: <b>{trained_count}</b> symbols\n"
                            f"  {knowledge_label}  |  Avg accuracy: <b>{avg_acc:.1%}</b>\n"
                            f"  Knowledge: <code>[{_bar}]</code>\n\n"
                        )

                        for symbol, m in list(model_entries.items())[:5]:
                            acc = m.get('accuracy', 0)
                            f1 = m.get('f1_score', 0)
                            prec = m.get('precision', 0)
                            rec = m.get('recall', 0)
                            samples = m.get('train_samples', 0)
                            test_samples = m.get('test_samples', 0)
                            days_old = m.get('days_old')
                            model_ver = m.get('model_version', '1.0')

                            # Quality emoji
                            if acc >= 0.65:
                                quality = "🟢"
                            elif acc >= 0.55:
                                quality = "🟡"
                            else:
                                quality = "🔴"

                            # Age label (days_old is clamped to ≥0 by _collect_ml_status)
                            if days_old is None:
                                age_label = "unknown"
                            elif days_old <= 0:
                                age_label = "today"
                            elif days_old == 1:
                                age_label = "1d ago"
                            else:
                                age_label = f"{days_old}d ago"

                            message += (
                                f"  {quality} <code>{symbol}</code> v{model_ver}\n"
                                f"     Acc={acc:.1%}  F1={f1:.1%}  "
                                f"P={prec:.1%}  R={rec:.1%}\n"
                                f"     Trained on {samples:,} samples "
                                f"(test: {test_samples:,})  ·  {age_label}\n"
                            )
                    else:
                        message += "  ⏳ No models trained yet\n"

                except Exception as e:
                    self.logger.error(f"Error formatting ML status: {e}")

            # Add Elite AI section if available
            if elite_ai_data:
                try:
                    self.logger.info("📊 Processing Elite AI data for notification: "
                                     f"Regimes: {len(elite_ai_data.get('regimes', {}))}, "
                                     f"MTF: {len(elite_ai_data.get('mtf_analysis', {}))}")

                    message += "\n\n🌟 <b>Elite AI Status:</b>\n"

                    # Market Regimes
                    regimes = elite_ai_data.get('regimes', {})
                    if regimes:
                        message += "\n  <b>📊 Market Regimes:</b>\n"
                        for symbol, regime_info in list(regimes.items())[:3]:
                            regime = regime_info.get('regime', 'UNKNOWN')
                            confidence = regime_info.get('confidence', 0)
                            trending = regime_info.get('trending', False)
                            volatile = regime_info.get('volatile', False)

                            # Emoji based on regime
                            if 'UPTREND' in regime or 'BULLISH' in regime:
                                regime_emoji = "📈"
                            elif 'DOWNTREND' in regime or 'BEARISH' in regime:
                                regime_emoji = "📉"
                            else:
                                regime_emoji = "↔️"

                            trend_marker = "🔥" if trending else "💤"
                            vol_marker = "⚡" if volatile else "🌊"

                            message += (
                                f"  {regime_emoji} <code>{symbol}</code>: "
                                f"{regime} ({confidence:.0f}%) {trend_marker}{vol_marker}\n"
                            )

                    # MTF Analysis
                    mtf_analysis = elite_ai_data.get('mtf_analysis', {})
                    if mtf_analysis:
                        message += "\n  <b>📈 MTF Alignment:</b>\n"
                        for symbol, mtf_info in list(mtf_analysis.items())[:3]:
                            alignment = mtf_info.get('alignment', 0)
                            recommendation = mtf_info.get('recommendation', 'NEUTRAL')
                            is_valid = mtf_info.get('is_valid', False)

                            # Emoji based on recommendation
                            if recommendation == 'BULLISH':
                                rec_emoji = "🟢"
                            elif recommendation == 'BEARISH':
                                rec_emoji = "🔴"
                            else:
                                rec_emoji = "🟡"

                            align_marker = "✅" if is_valid else "❌"

                            message += (
                                f"  {rec_emoji} <code>{symbol}</code>: "
                                f"{alignment:.0f}% {recommendation} {align_marker}\n"
                            )

                    # Risk & Position Management Status
                    status_items = []
                    if elite_ai_data.get('risk_management'):
                        status_items.append("💼 Kelly Criterion Active")
                    if elite_ai_data.get('position_management'):
                        monitored = elite_ai_data.get('monitored_positions', 0)
                        status_items.append(f"🎯 Positions Managed: {monitored}")

                    if status_items:
                        message += "\n  <b>🛡️ Active Features:</b>\n"
                        for item in status_items:
                            message += f"  • {item}\n"

                except Exception as e:
                    self.logger.error(f"Error formatting Elite AI data: {e}")

            # Add CRYPTO NEWS section if available or show status
            if news_summary is not None:
                try:
                    total = news_summary.get('total_count', 0)

                    if total > 0:
                        message += "\n\n📰 <b>Crypto News (Last Hour):</b>\n"

                        bullish = news_summary.get('bullish_count', 0)
                        bearish = news_summary.get('bearish_count', 0)
                        neutral = news_summary.get('neutral_count', 0)

                        # News sentiment overview
                        (bullish / total) * 100 if total > 0 else 0
                        (bearish / total) * 100 if total > 0 else 0

                        # Market sentiment from news
                        if bullish > bearish and bullish > neutral:
                            sentiment_emoji = "🟢"
                            sentiment_text = "Bullish"
                        elif bearish > bullish and bearish > neutral:
                            sentiment_emoji = "🔴"
                            sentiment_text = "Bearish"
                        else:
                            sentiment_emoji = "🟡"
                            sentiment_text = "Neutral"

                        message += f"  📊 Sentiment: {sentiment_emoji} <b>{sentiment_text}</b> "
                        message += f"({bullish}↑ {bearish}↓ {neutral}↔️)\n"

                        # Top symbols mentioned in news
                        by_symbol = news_summary.get('by_symbol', {})
                        if by_symbol:
                            message += "\n  <b>🔥 Trending Coins:</b>\n"
                            # Sort by count and show top 5
                            sorted_symbols = sorted(
                                by_symbol.items(),
                                key=lambda x: x[1],
                                reverse=True)[
                                :5]
                            for symbol, count in sorted_symbols:
                                message += f"  • <code>{symbol}</code>: {count} mentions\n"

                        # Latest news items
                        news_items = news_summary.get('news_items', [])
                        if news_items:
                            message += "\n  <b>📋 Latest Headlines:</b>\n"
                            for idx, item in enumerate(news_items[:3], 1):  # Show top 3
                                title = item.get('title', 'No title')
                                # Truncate long titles
                                if len(title) > 80:
                                    title = title[:77] + '...'

                                source = item.get('source', 'Unknown')
                                # Clean source name
                                if ':' in source:
                                    source = source.split(':')[1]

                                # Add link if available
                                url = item.get('url', '')
                                if url:
                                    message += f"  {idx}. <a href=\"{url}\">{title}</a>\n"
                                    message += f"     <i>Source: {source}</i>\n"
                                else:
                                    message += f"  {idx}. {title}\n"
                                    message += f"     <i>Source: {source}</i>\n"

                        # AI News Analysis
                        message += "\n  <b>🤖 AI Analysis:</b>\n"
                        if bullish > bearish * 1.5:
                            message += "  💡 Strong bullish news flow - favorable for longs\n"
                        elif bearish > bullish * 1.5:
                            message += "  ⚠️ Bearish news dominance - caution advised\n"
                        elif total >= 3:
                            message += "  📊 Mixed sentiment - watch for price action\n"
                        else:
                            message += "  🔇 Low news activity this hour\n"
                    else:
                        # No news in the last hour
                        message += "\n\n📰 <b>Crypto News (Last Hour):</b>\n"
                        message += "  🔇 <i>No significant news in the last hour</i>\n"
                        message += "  💡 Market is quiet - good for technical analysis\n"

                except Exception as e:
                    self.logger.error(f"Error formatting news summary: {e}")
                    message += "\n\n📰 <i>News analysis unavailable</i>\n"
            else:
                # News aggregator not enabled or error occurred
                message += "\n\n📰 <b>Crypto News:</b>\n"
                # Check if bot has news_error_message attribute
                if hasattr(
                        self,
                        'bot_instance') and hasattr(
                        self.bot_instance,
                        'news_error_message') and self.bot_instance.news_error_message:
                    message += f"  ⚙️ <i>News analysis disabled: {self.bot_instance.news_error_message}</i>\n"
                    if 'Missing dependencies' in self.bot_instance.news_error_message:
                        message += "  🔧 <b>FIX:</b> Run: <code>pip install aiohttp feedparser</code>\n"
                    elif 'Disabled in .env' in self.bot_instance.news_error_message:
                        message += "  💡 Enable with ENABLE_NEWS_ANALYSIS=true in .env\n"
                else:
                    message += "  ⚙️ <i>News analysis disabled or unavailable</i>\n"
                    message += "  💡 Enable with ENABLE_NEWS_ANALYSIS=true in .env\n"

            message += f"\n⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            sent = self.send_message(message.strip())
            # Update the snapshot only after a successful send so the next hourly
            # report can reliably detect whether key data has changed.
            if sent:
                self._last_hourly_snapshot = current_snapshot
            return sent

        except Exception as e:
            self.logger.error(f"Error formatting hourly summary notification: {e}", exc_info=True)
            # Send simplified notification
            try:
                simplified_message = f"""
📊 <b>Hourly Status Summary</b>

📋 Open Positions: <b>{open_positions_count}</b>
💰 Daily P&amp;L: <code>${daily_pnl:,.2f}</code>

⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                return self.send_message(simplified_message.strip())
            except Exception as e2:
                self.logger.error(f"Failed to send even simplified hourly summary: {e2}")
                return False

    def notify_bot_stopped(self, reason: str = "Manual stop") -> bool:
        """
        Notify about bot shutdown

        Args:
            reason: Reason for shutdown

        Returns:
            True if sent successfully
        """
        message = f"""
🛑 <b>Trading Bot Stopped</b>

📝 Reason: <i>{reason}</i>

⏰ Stopped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message.strip())


# Global instance (initialized by config)
_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> Optional[TelegramNotifier]:
    """Get global notifier instance"""
    return _notifier


def init_notifier(bot_token: Optional[str] = None, chat_id: Optional[str] = None,
                  enabled: bool = True, language: str = None) -> TelegramNotifier:
    """
    Initialize global notifier instance

    Args:
        bot_token: Telegram bot token
        chat_id: Telegram chat ID
        enabled: Whether notifications are enabled
        language: Notification language code (default: from env or 'en')

    Returns:
        TelegramNotifier instance
    """
    global _notifier
    language = language or os.getenv('NOTIFICATION_LANGUAGE', 'en')
    _notifier = TelegramNotifier(bot_token, chat_id, enabled, language)
    return _notifier
