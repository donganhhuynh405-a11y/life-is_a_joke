#!/usr/bin/env python3
"""
Reset Bot News Cache

Clears all accumulated news items from the crypto_news table so that
sentiment analysis starts from scratch on the next bot run.

Usage:
    python3 scripts/reset_news.py [--db /path/to/db] [--yes]

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


def reset_news(db_path: str, skip_confirm: bool = False) -> None:
    """Wipe all cached news items so analysis starts fresh."""
    print("=" * 60)
    print("  TRADING BOT — NEWS CACHE RESET")
    print("=" * 60)
    print(f"\n  Database: {db_path}")
    print(f"  Reset date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not skip_confirm:
        print(
            "\n  ⚠️  This will permanently delete ALL cached news items\n"
            "  from the crypto_news table.\n"
            "  The bot will re-fetch and re-analyze news from scratch.\n"
        )
        answer = input("  Type 'YES' to confirm: ").strip()
        if answer != 'YES':
            print("\n  Cancelled — nothing was changed.")
            sys.exit(0)

    conn = sqlite3.connect(db_path)
    conn.isolation_level = None  # autocommit
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT COUNT(*) FROM crypto_news')
        count = cursor.fetchone()[0]
        cursor.execute('DELETE FROM crypto_news')
        print(f"  ✅ Cleared {count} news items from table: crypto_news")
    except sqlite3.OperationalError as exc:
        print(f"  ⚠️  Could not clear crypto_news table: {exc}")

    conn.close()

    print("\n" + "=" * 60)
    print("  ✅ News cache reset complete.")
    print("  Restart the bot to begin fresh news analysis.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Reset bot news cache')
    parser.add_argument('--db', default=DEFAULT_DB, help='Path to SQLite database')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    reset_news(args.db, skip_confirm=args.yes)


if __name__ == '__main__':
    main()
