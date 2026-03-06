"""
Tests for ExchangeAdapter._load_markets_with_retry and timeout configuration.
"""
import sys
import os
import types
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Stub heavy dependencies before importing exchange_adapter
_binance_stub = types.ModuleType('binance')
_binance_client_stub = types.ModuleType('binance.client')
_binance_client_stub.Client = MagicMock
_binance_exc_stub = types.ModuleType('binance.exceptions')
_binance_exc_stub.BinanceAPIException = Exception
sys.modules.setdefault('binance', _binance_stub)
sys.modules.setdefault('binance.client', _binance_client_stub)
sys.modules.setdefault('binance.exceptions', _binance_exc_stub)

import ccxt
from core.exchange_adapter import ExchangeAdapter


@pytest.fixture
def config():
    cfg = MagicMock()
    cfg.exchange_id = 'bybit'
    cfg.exchange_api_key = 'test_key'
    cfg.exchange_api_secret = 'test_secret'
    cfg.exchange_testnet = True
    cfg.use_ccxt = True
    cfg.trading_symbols = ['BTC/USDT']
    return cfg


def _make_adapter_without_init(config):
    """Create ExchangeAdapter instance bypassing __init__ for unit testing."""
    adapter = object.__new__(ExchangeAdapter)
    adapter.config = config
    import logging
    adapter.logger = logging.getLogger('test')
    adapter.exchange = MagicMock()
    adapter.exchange_id = config.exchange_id
    adapter.use_ccxt = config.use_ccxt
    return adapter


class TestLoadMarketsWithRetry:
    def test_succeeds_on_first_try(self, config):
        adapter = _make_adapter_without_init(config)
        adapter.exchange.load_markets = MagicMock(return_value=None)

        adapter._load_markets_with_retry()

        adapter.exchange.load_markets.assert_called_once()

    def test_retries_on_request_timeout(self, config):
        adapter = _make_adapter_without_init(config)
        timeout_error = ccxt.RequestTimeout('timed out')
        adapter.exchange.load_markets = MagicMock(
            side_effect=[timeout_error, timeout_error, None]
        )

        with patch('time.sleep') as mock_sleep:
            adapter._load_markets_with_retry(max_retries=3, base_delay=1.0)

        assert adapter.exchange.load_markets.call_count == 3
        assert mock_sleep.call_count == 2
        # Exponential backoff: first 1s, then 2s
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    def test_retries_on_network_error(self, config):
        adapter = _make_adapter_without_init(config)
        network_error = ccxt.NetworkError('connection failed')
        adapter.exchange.load_markets = MagicMock(
            side_effect=[network_error, None]
        )

        with patch('time.sleep'):
            adapter._load_markets_with_retry(max_retries=3, base_delay=1.0)

        assert adapter.exchange.load_markets.call_count == 2

    def test_raises_after_max_retries_exceeded(self, config):
        adapter = _make_adapter_without_init(config)
        timeout_error = ccxt.RequestTimeout('timed out')
        adapter.exchange.load_markets = MagicMock(side_effect=timeout_error)

        with patch('time.sleep'):
            with pytest.raises(ccxt.RequestTimeout):
                adapter._load_markets_with_retry(max_retries=2, base_delay=1.0)

        assert adapter.exchange.load_markets.call_count == 3  # 1 initial attempt + 2 retries

    def test_does_not_retry_on_other_errors(self, config):
        adapter = _make_adapter_without_init(config)
        auth_error = ccxt.AuthenticationError('bad key')
        adapter.exchange.load_markets = MagicMock(side_effect=auth_error)

        with pytest.raises(ccxt.AuthenticationError):
            adapter._load_markets_with_retry(max_retries=3, base_delay=1.0)

        # Should not retry – only called once
        adapter.exchange.load_markets.assert_called_once()


class TestInitCcxtExchangeTimeout:
    def test_timeout_included_in_exchange_config(self, config):
        """Verify that a 30-second timeout is set in the CCXT exchange config."""
        captured_config = {}

        def fake_exchange_class(cfg):
            captured_config.update(cfg)
            instance = MagicMock()
            instance.load_markets = MagicMock(return_value=None)
            instance.markets = {'BTC/USDT': {}}
            return instance

        with patch.object(ccxt, config.exchange_id, fake_exchange_class, create=True):
            with patch('core.exchange_adapter.ExchangeAdapter._load_markets_with_retry'):
                adapter = ExchangeAdapter(config)

        assert captured_config.get('timeout') == 30000
