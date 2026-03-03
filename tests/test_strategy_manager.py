"""
Unit tests for StrategyManager._close_position guard logic.

Tests that the stop-loss / take-profit guard behaves correctly:
- losing position + ordinary signal → skipped
- losing position + stop-loss reason  → proceeds
- losing position + take-profit reason → proceeds
"""
import sys
import os
import types
from unittest.mock import MagicMock

# Ensure src is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Stub heavy optional dependencies before import
for _mod in ('utils.notifications', 'trend_analyzer', 'core.confidence_position_sizer'):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules['utils.notifications'].get_notifier = MagicMock(return_value=None)
sys.modules['trend_analyzer'].TrendAnalyzer = MagicMock
sys.modules['core.confidence_position_sizer'].ConfidencePositionSizer = MagicMock


def _make_manager(position_status='open', entry_price=100.0, quantity=1.0):
    """Construct a minimal StrategyManager with mocked dependencies."""
    from strategies.strategy_manager import StrategyManager

    config = MagicMock()
    config.use_confidence_sizing = False   # avoid ConfidencePositionSizer(config) call
    config.active_strategy = 'enhanced'
    config.trading_enabled = False  # disable exchange calls
    client = MagicMock()
    db = MagicMock()
    db.get_position.return_value = {
        'status': position_status,
        'entry_price': entry_price,
        'quantity': quantity,
        'side': 'BUY',
        'symbol': 'BTC/USDT',
        'strategy': 'test',
    }
    db.get_open_positions.return_value = []
    risk_manager = MagicMock()
    mgr = StrategyManager(config, client, db, risk_manager)
    return mgr, db


class TestClosePositionGuard:
    """Verify the is_stop_loss / is_take_profit guard in _close_position."""

    def _close(self, reason, exit_price=90.0, entry_price=100.0):
        """Helper: run _close_position and return (was_db_updated, db_mock)."""
        mgr, db = _make_manager(entry_price=entry_price)
        signal = {
            'position_id': 1,
            'price': exit_price,  # < entry_price → negative PnL for BUY
            'reason': reason,
            'confidence': 0.8,
        }
        mgr._close_position(signal, strategy=MagicMock())
        return db.update_position.called, db

    def test_skips_losing_position_with_ordinary_signal(self):
        called, _ = self._close(reason='new opposing signal')
        assert not called, "Should skip closing a losing position on ordinary signal"

    def test_closes_losing_position_with_stop_loss(self):
        called, _ = self._close(reason='stop loss triggered')
        assert called, "Should close a losing position when stop-loss is the reason"

    def test_closes_losing_position_with_tp_reason(self):
        called, _ = self._close(reason='take profit triggered')
        assert called, "Should close a position when take-profit is the reason"

    def test_closes_losing_position_with_sl_abbreviation(self):
        called, _ = self._close(reason='SL hit')
        assert called, "Should recognise 'sl' abbreviation as stop-loss"

    def test_closes_losing_position_with_tp_abbreviation(self):
        called, _ = self._close(reason='TP reached')
        assert called, "Should recognise 'tp' abbreviation as take-profit"

    def test_skips_already_closed_position(self):
        mgr, db = _make_manager(position_status='closed')
        signal = {'position_id': 1, 'price': 90.0, 'reason': 'stop loss', 'confidence': 0.8}
        mgr._close_position(signal, strategy=MagicMock())
        db.update_position.assert_not_called()

    def test_closes_profitable_position_always(self):
        """Profitable close (exit > entry for BUY) should always proceed."""
        called, _ = self._close(reason='new opposing signal', exit_price=110.0, entry_price=100.0)
        assert called, "Profitable close should always proceed"
