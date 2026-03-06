"""
Database Manager
Handles all database operations for trading history, positions, and analytics
"""

import logging
import sqlite3
from typing import List, Dict, Optional
from pathlib import Path


class Database:
    """Database manager for SQLite"""

    def __init__(self, config):
        """Initialize database connection"""
        self.config = config
        self.logger = logging.getLogger(__name__)

        if config.db_type == 'sqlite':
            # Ensure directory exists
            db_path = Path(config.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            # Connect to database with proper settings for persistence
            self.conn = sqlite3.connect(
                config.db_path,
                check_same_thread=False,
                isolation_level=None  # Autocommit mode for immediate persistence
            )
            self.conn.row_factory = sqlite3.Row

            # Enable WAL mode for better concurrency and persistence
            self.conn.execute('PRAGMA journal_mode=WAL')
            # Ensure data is written to disk immediately
            self.conn.execute('PRAGMA synchronous=FULL')

            self.logger.info(f"Connected to SQLite database: {config.db_path}")
        else:
            raise NotImplementedError(f"Database type {config.db_type} not implemented")

        # Initialize schema
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema"""
        cursor = self.conn.cursor()

        # Trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_id TEXT UNIQUE,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                commission REAL,
                commission_asset TEXT,
                profit_loss REAL,
                strategy TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'completed'
            )
        ''')

        # Positions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                stop_loss REAL,
                take_profit REAL,
                current_price REAL,
                profit_loss REAL,
                status TEXT DEFAULT 'open',
                opened_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME,
                exit_price REAL,
                strategy TEXT
            )
        ''')

        try:
            cursor.execute("ALTER TABLE positions ADD COLUMN exit_price REAL")
            self.logger.info("Added exit_price column to positions table")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE positions ADD COLUMN pnl REAL")
            self.logger.info("Added pnl column to positions table")
        except sqlite3.OperationalError:
            pass

        # Fix invalid zero-date timestamps written by older bot versions
        try:
            cursor.execute(
                "UPDATE positions SET closed_at = NULL WHERE closed_at = '0000-00-00 00:00:00'"
            )
            if cursor.rowcount > 0:
                self.logger.info(
                    f"Fixed {cursor.rowcount} position(s) with invalid closed_at timestamp"
                )
        except sqlite3.OperationalError:
            pass

        # Daily stats table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                total_trades INTEGER DEFAULT 0,
                profitable_trades INTEGER DEFAULT 0,
                total_profit_loss REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0
            )
        ''')

        # Balance snapshots table - records USDT balance at a point in time
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                balance_usdt REAL NOT NULL,
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        self.conn.commit()
        self.logger.info("Database schema initialized")

    def save_balance_snapshot(self, balance_usdt: float) -> None:
        """Save a USDT balance snapshot (at most once per day)"""
        cursor = self.conn.cursor()
        # Only insert if we don't already have a record for today
        cursor.execute('''
            INSERT INTO balance_snapshots (balance_usdt)
            SELECT ?
            WHERE NOT EXISTS (
                SELECT 1 FROM balance_snapshots
                WHERE DATE(recorded_at) = DATE('now', 'localtime')
            )
        ''', (balance_usdt,))
        self.conn.commit()

    def get_start_of_month_balance(self) -> Optional[float]:
        """Get the earliest USDT balance recorded in the current calendar month.

        Returns None if no snapshot exists for the current month.
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT balance_usdt
            FROM balance_snapshots
            WHERE strftime('%Y-%m', recorded_at, 'localtime') = strftime('%Y-%m', 'now', 'localtime')
            ORDER BY recorded_at ASC
            LIMIT 1
        ''')
        row = cursor.fetchone()
        return row[0] if row else None

    def record_trade(self, trade_data: Dict) -> int:
        """Record a trade"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO trades (symbol, side, order_id, price, quantity, commission,
                              commission_asset, profit_loss, strategy, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade_data['symbol'],
            trade_data['side'],
            trade_data.get('order_id'),
            trade_data['price'],
            trade_data['quantity'],
            trade_data.get('commission', 0),
            trade_data.get('commission_asset', 'USDT'),
            trade_data.get('profit_loss', 0),
            trade_data.get('strategy', 'unknown'),
            trade_data.get('status', 'completed')
        ))
        self.conn.commit()
        return cursor.lastrowid

    def create_position(self, position_data: Dict) -> int:
        """Create a new position"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO positions (symbol, side, entry_price, quantity, stop_loss,
                                 take_profit, strategy, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
        ''', (
            position_data['symbol'],
            position_data['side'],
            position_data['entry_price'],
            position_data['quantity'],
            position_data.get('stop_loss'),
            position_data.get('take_profit'),
            position_data.get('strategy', 'unknown')
        ))
        self.conn.commit()
        return cursor.lastrowid

    def update_position(self, position_id: int, **kwargs):
        """Update a position"""
        updates = []
        values = []

        for key, value in kwargs.items():
            # Handle CURRENT_TIMESTAMP as SQL function, not string
            if value == 'CURRENT_TIMESTAMP':
                updates.append(f"{key} = CURRENT_TIMESTAMP")
            else:
                updates.append(f"{key} = ?")
                values.append(value)

        values.append(position_id)

        cursor = self.conn.cursor()
        cursor.execute(f'''
            UPDATE positions
            SET {', '.join(updates)}
            WHERE id = ?
        ''', values)
        self.conn.commit()

    def get_position(self, position_id: int) -> Optional[Dict]:
        """Get a specific position by ID"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE status = 'open'")
        return [dict(row) for row in cursor.fetchall()]

    def get_daily_trade_count(self) -> int:
        """Get number of trades today"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM trades
            WHERE DATE(timestamp) = DATE('now')
        ''')
        return cursor.fetchone()[0]

    def get_daily_profit_loss(self) -> float:
        """Get total P/L for today from closed positions"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COALESCE(SUM(pnl), 0) as total
            FROM positions
            WHERE status = 'closed'
            AND DATE(closed_at) = DATE('now', 'localtime')
            AND pnl IS NOT NULL
        ''')
        return cursor.fetchone()[0]

    def health_check(self) -> bool:
        """Check database health"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1")
            return True
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            return False

    def get_performance_metrics(self):
        """
        Get trading performance metrics

        Returns:
            dict: Performance metrics including win rate, profit, etc.
        """
        try:
            cursor = self.conn.cursor()

            # Get closed positions
            cursor.execute('''
                SELECT COUNT(*) as total_trades,
                       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                       SUM(pnl) as total_profit,
                       AVG(pnl) as avg_profit,
                       MAX(pnl) as max_profit,
                       MIN(pnl) as min_profit
                FROM positions
                WHERE status = 'closed' AND pnl IS NOT NULL
            ''')

            row = cursor.fetchone()

            total_trades = row[0] or 0
            winning_trades = row[1] or 0
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': total_trades - winning_trades,
                'win_rate': win_rate,
                'total_profit': row[2] or 0,
                'avg_profit': row[3] or 0,
                'max_profit': row[4] or 0,
                'min_profit': row[5] or 0
            }
        except Exception as e:
            self.logger.error(f"Error getting performance metrics: {e}")
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_profit': 0,
                'avg_profit': 0,
                'max_profit': 0,
                'min_profit': 0
            }

    def close(self):
        """Close database connection"""
        if self.conn:
            # Ensure all pending transactions are committed
            try:
                self.conn.commit()
            except Exception:
                pass  # In autocommit mode, this might raise

            self.conn.close()
            self.logger.info("Database connection closed")
