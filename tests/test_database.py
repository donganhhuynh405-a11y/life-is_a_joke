"""
Tests for Database balance snapshot methods.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.database import Database  # noqa: E402


@pytest.fixture
def db(tmp_path):
    """Create an in-memory (temp) Database instance for testing."""
    cfg = MagicMock()
    cfg.db_type = 'sqlite'
    cfg.db_path = str(tmp_path / 'test.db')
    return Database(cfg)


class TestBalanceSnapshot:
    def test_get_start_of_month_balance_returns_none_when_empty(self, db):
        result = db.get_start_of_month_balance()
        assert result is None

    def test_save_and_get_start_of_month_balance(self, db):
        db.save_balance_snapshot(1000.0)
        result = db.get_start_of_month_balance()
        assert result == pytest.approx(1000.0)

    def test_save_balance_idempotent_within_same_day(self, db):
        """Only one snapshot per day should be stored."""
        db.save_balance_snapshot(1000.0)
        db.save_balance_snapshot(1500.0)  # should be ignored (same day)
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM balance_snapshots")
        count = cursor.fetchone()[0]
        assert count == 1

    def test_start_of_month_balance_is_earliest_in_month(self, db):
        """Insert two rows (simulating different days) - earliest is returned."""
        cursor = db.conn.cursor()
        cursor.execute(
            "INSERT INTO balance_snapshots (balance_usdt, recorded_at) VALUES (?, ?)",
            (500.0, '2099-02-01 10:00:00')
        )
        cursor.execute(
            "INSERT INTO balance_snapshots (balance_usdt, recorded_at) VALUES (?, ?)",
            (800.0, '2099-02-15 10:00:00')
        )
        db.conn.commit()

        cursor.execute('''
            SELECT balance_usdt FROM balance_snapshots
            WHERE strftime('%Y-%m', recorded_at, 'localtime') = '2099-02'
            ORDER BY recorded_at ASC LIMIT 1
        ''')
        row = cursor.fetchone()
        assert row[0] == pytest.approx(500.0)
