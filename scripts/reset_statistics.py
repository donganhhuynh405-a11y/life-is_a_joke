#!/usr/bin/env python3
"""
Reset Bot Statistics

Wipes all trading history (trades, positions, daily_stats, balance_snapshots)
and records a fresh balance snapshot so statistics start from today.

Usage:
    python3 scripts/reset_statistics.py [--db /path/to/db] [--yes]

Options:
    --db PATH    Path to the SQLite database
                 (default: /var/lib/trading-bot/trading_bot.db)
    --yes        Skip the confirmation prompt (for automated use)
"""

import argparse
import sqlite3
import sys
from datetime import datetime


DEFAULT_DB = '/var/lib/trading-bot/trading_bot.db'


def reset_statistics(db_path: str, skip_confirm: bool = False) -> None:
    """Wipe trading statistics and start fresh from today."""
    print("=" * 60)
    print("  TRADING BOT — STATISTICS RESET")
    print("=" * 60)
    print(f"\n  Database: {db_path}")
    print(f"  Reset date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not skip_confirm:
        print(
            "\n  ⚠️  This will permanently delete ALL historical trades,\n"
            "  positions, daily stats and balance snapshots.\n"
            "  The bot will start counting from scratch.\n"
        )
        answer = input("  Type 'YES' to confirm: ").strip()
        if answer != 'YES':
            print("\n  Cancelled — nothing was changed.")
            sys.exit(0)

    conn = sqlite3.connect(db_path)
    conn.isolation_level = None  # autocommit
    cursor = conn.cursor()

    tables = ['trades', 'positions', 'daily_stats', 'balance_snapshots']
    for table in tables:
        try:
            cursor.execute(f'DELETE FROM {table}')
            print(f"  ✅ Cleared table: {table}")
        except sqlite3.OperationalError as exc:
            # Table may not exist yet — that's fine.
            print(f"  ⚠️  Skipped table '{table}': {exc}")

    # Do not insert an artificial 0-balance snapshot here.
    # The trading bot will record the first real balance snapshot
    # on its next run, ensuring ROI calculations use a correct
    # opening balance for the day/month.
    print("  ℹ️  All balance snapshots cleared — the bot will record a new snapshot on next run.")

    conn.close()

    print("\n" + "=" * 60)
    print("  ✅ Statistics reset complete.")
    print("  Restart the bot to begin a fresh trading session.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Reset bot trading statistics')
    parser.add_argument('--db', default=DEFAULT_DB, help='Path to SQLite database')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    reset_statistics(args.db, skip_confirm=args.yes)


if __name__ == '__main__':
    main()
