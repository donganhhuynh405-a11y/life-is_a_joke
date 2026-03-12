"""
Telegram Notifier Module

This module provides functionality for sending notifications to Telegram.
"""

import logging
import os
from typing import Optional
import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Telegram notification handler.
    Sends notifications to Telegram channels/chats via Bot API.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram Notifier.

        Args:
            bot_token: Telegram Bot API token (if None, reads from TELEGRAM_BOT_TOKEN env var)
            chat_id: Telegram chat ID to send messages to (if None, reads from TELEGRAM_CHAT_ID env var)
        """
        self.bot_token = bot_token if bot_token else os.environ.get('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id if chat_id else os.environ.get('TELEGRAM_CHAT_ID')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

        if not self.bot_token or not self.chat_id:
            logger.warning(
                "Telegram notifier not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.")
            self.enabled = False
        else:
            self.enabled = True
            logger.debug("Telegram notifier initialized")

    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """
        Send a message to Telegram.

        Args:
            message: Message text to send
            parse_mode: Parse mode for the message ('HTML', 'Markdown', or None)

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        if not self.enabled:
            logger.debug("Telegram notifier disabled, skipping message")
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }

            # Use system CA bundle from environment (set by start_bot.sh) when
            # certifi's cacert.pem is missing after a disk-full venv rebuild.
            ca_bundle = (
                os.environ.get('REQUESTS_CA_BUNDLE') or
                os.environ.get('CURL_CA_BUNDLE') or
                True
            )

            response = requests.post(url, json=payload, timeout=10, verify=ca_bundle)
            response.raise_for_status()

            logger.debug("Telegram message sent successfully")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram message: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {str(e)}")
            return False

    def send_error_notification(self, operation: str, error: Exception,
                                context: Optional[dict] = None) -> bool:
        """
        Send an error notification with details.

        Args:
            operation: Name of the operation that failed
            error: The exception that occurred
            context: Optional additional context (e.g., symbol, amount, etc.)

        Returns:
            bool: True if notification sent successfully, False otherwise
        """
        if not self.enabled:
            return False

        error_type = type(error).__name__
        error_message = str(error)

        # Build notification message
        message_lines = [
            "🚨 <b>Ошибка операции</b> 🚨",
            "",
            f"<b>Операция:</b> {operation}",
            f"<b>Тип ошибки:</b> {error_type}",
            f"<b>Причина:</b> {error_message}",
        ]

        # Add context if provided
        if context:
            message_lines.append("")
            message_lines.append("<b>Дополнительная информация:</b>")
            for key, value in context.items():
                message_lines.append(f"  • {key}: {value}")

        message = "\n".join(message_lines)

        return self.send_message(message)

    def send_success_notification(self, operation: str, details: Optional[dict] = None) -> bool:
        """
        Send a success notification.

        Args:
            operation: Name of the operation that succeeded
            details: Optional details about the operation

        Returns:
            bool: True if notification sent successfully, False otherwise
        """
        if not self.enabled:
            return False

        message_lines = [
            "✅ <b>Операция выполнена успешно</b> ✅",
            "",
            f"<b>Операция:</b> {operation}",
        ]

        if details:
            message_lines.append("")
            message_lines.append("<b>Детали:</b>")
            for key, value in details.items():
                message_lines.append(f"  • {key}: {value}")

        message = "\n".join(message_lines)

        return self.send_message(message)


# Global notifier instance
_notifier_instance: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    """
    Get or create the global Telegram notifier instance.

    Returns:
        TelegramNotifier instance
    """
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = TelegramNotifier()
    return _notifier_instance


def send_error_notification(
        operation: str,
        error: Exception,
        context: Optional[dict] = None) -> bool:
    """
    Convenience function to send error notification using the global notifier.

    Args:
        operation: Name of the operation that failed
        error: The exception that occurred
        context: Optional additional context

    Returns:
        bool: True if notification sent successfully, False otherwise
    """
    return get_notifier().send_error_notification(operation, error, context)


def send_success_notification(operation: str, details: Optional[dict] = None) -> bool:
    """
    Convenience function to send success notification using the global notifier.

    Args:
        operation: Name of the operation that succeeded
        details: Optional details about the operation

    Returns:
        bool: True if notification sent successfully, False otherwise
    """
    return get_notifier().send_success_notification(operation, details)
