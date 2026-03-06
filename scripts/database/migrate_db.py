#!/usr/bin/env python3
"""
migrate_db.py - Database migration script for the trading bot.

Usage:
    python scripts/migrate_db.py [--up | --down | --status]
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_db")

# ---------------------------------------------------------------------------
# Migration definitions
# ---------------------------------------------------------------------------

MIGRATIONS: list[dict] = [
    {
        "version": "001",
        "description": "Create trades table",
        "up": """
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(4) NOT NULL CHECK (side IN ('buy', 'sell')),
                amount NUMERIC(18, 8) NOT NULL,
                price NUMERIC(18, 8) NOT NULL,
                fee NUMERIC(18, 8) DEFAULT 0,
                pnl NUMERIC(18, 8),
                strategy VARCHAR(100),
                exchange VARCHAR(50),
                order_id VARCHAR(100),
                status VARCHAR(20) DEFAULT 'open',
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);
            CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades (created_at);
            CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
        """,
        "down": "DROP TABLE IF EXISTS trades CASCADE;",
    },
    {
        "version": "002",
        "description": "Create positions table",
        "up": """
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(5) NOT NULL CHECK (side IN ('long', 'short')),
                entry_price NUMERIC(18, 8) NOT NULL,
                current_price NUMERIC(18, 8),
                amount NUMERIC(18, 8) NOT NULL,
                stop_loss NUMERIC(18, 8),
                take_profit NUMERIC(18, 8),
                leverage NUMERIC(5, 2) DEFAULT 1,
                unrealized_pnl NUMERIC(18, 8) DEFAULT 0,
                strategy VARCHAR(100),
                exchange VARCHAR(50),
                is_open BOOLEAN DEFAULT TRUE,
                opened_at TIMESTAMPTZ DEFAULT NOW(),
                closed_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions (symbol);
            CREATE INDEX IF NOT EXISTS idx_positions_is_open ON positions (is_open);
        """,
        "down": "DROP TABLE IF EXISTS positions CASCADE;",
    },
    {
        "version": "003",
        "description": "Create ML model registry table",
        "up": """
            CREATE TABLE IF NOT EXISTS model_registry (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                version VARCHAR(50) NOT NULL,
                description TEXT,
                metrics JSONB DEFAULT '{}',
                hyperparams JSONB DEFAULT '{}',
                artifact_path VARCHAR(500),
                tags VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR[],
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (name, version)
            );
            CREATE INDEX IF NOT EXISTS idx_model_registry_name ON model_registry (name);
            CREATE INDEX IF NOT EXISTS idx_model_registry_active ON model_registry (is_active);
        """,
        "down": "DROP TABLE IF EXISTS model_registry CASCADE;",
    },
    {
        "version": "004",
        "description": "Create performance metrics table",
        "up": """
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id SERIAL PRIMARY KEY,
                period_start TIMESTAMPTZ NOT NULL,
                period_end TIMESTAMPTZ NOT NULL,
                total_trades INTEGER DEFAULT 0,
                win_rate NUMERIC(5, 4),
                total_pnl NUMERIC(18, 8) DEFAULT 0,
                sharpe_ratio NUMERIC(8, 4),
                max_drawdown NUMERIC(8, 4),
                profit_factor NUMERIC(8, 4),
                strategy VARCHAR(100),
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_perf_period ON performance_metrics (period_start, period_end);
        """,
        "down": "DROP TABLE IF EXISTS performance_metrics CASCADE;",
    },
    {
        "version": "005",
        "description": "Create audit log table",
        "up": """
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                event_type VARCHAR(100) NOT NULL,
                actor VARCHAR(100),
                resource_type VARCHAR(100),
                resource_id VARCHAR(200),
                details JSONB DEFAULT '{}',
                ip_address INET,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log (event_type);
            CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at);
        """,
        "down": "DROP TABLE IF EXISTS audit_log CASCADE;",
    },
]

SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(20) PRIMARY KEY,
    description VARCHAR(500),
    applied_at TIMESTAMPTZ DEFAULT NOW()
);
"""


def get_db_connection():
    """Get database connection from environment."""
    try:
        import psycopg2

        database_url = os.getenv("DATABASE_URL")
        if database_url:
            return psycopg2.connect(database_url)

        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "trading"),
            user=os.getenv("DB_USER", "trader"),
            password=os.getenv("DB_PASSWORD", ""),
        )
    except ImportError:
        logger.error("psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        sys.exit(1)


def get_applied_migrations(conn) -> set[str]:
    """Get set of already applied migration versions."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_TABLE)
        cur.execute("SELECT version FROM schema_migrations ORDER BY version;")
        return {row[0] for row in cur.fetchall()}


def run_up(conn, dry_run: bool = False) -> int:
    """Apply pending migrations."""
    applied = get_applied_migrations(conn)
    pending = [m for m in MIGRATIONS if m["version"] not in applied]

    if not pending:
        logger.info("All migrations are up to date.")
        return 0

    logger.info("Found %d pending migration(s).", len(pending))
    applied_count = 0

    for migration in pending:
        ver = migration["version"]
        desc = migration["description"]
        logger.info("[%s] %s", ver, desc)

        if dry_run:
            logger.info("  DRY RUN - would execute:\n%s", migration["up"])
            continue

        try:
            with conn.cursor() as cur:
                cur.execute(migration["up"])
                cur.execute(
                    "INSERT INTO schema_migrations (version, description) VALUES (%s, %s);",
                    (ver, desc),
                )
            conn.commit()
            logger.info("  ✓ Applied")
            applied_count += 1
        except Exception as e:
            conn.rollback()
            logger.error("  ✗ Failed: %s", e)
            raise

    return applied_count


def run_down(conn, steps: int = 1, dry_run: bool = False) -> int:
    """Rollback the last N migrations."""
    applied = get_applied_migrations(conn)
    to_rollback = [m for m in reversed(MIGRATIONS) if m["version"] in applied][:steps]

    if not to_rollback:
        logger.info("Nothing to rollback.")
        return 0

    rolled_back = 0
    for migration in to_rollback:
        ver = migration["version"]
        desc = migration["description"]
        logger.info("[%s] Rolling back: %s", ver, desc)

        if dry_run:
            logger.info("  DRY RUN - would execute:\n%s", migration["down"])
            continue

        try:
            with conn.cursor() as cur:
                cur.execute(migration["down"])
                cur.execute("DELETE FROM schema_migrations WHERE version = %s;", (ver,))
            conn.commit()
            logger.info("  ✓ Rolled back")
            rolled_back += 1
        except Exception as e:
            conn.rollback()
            logger.error("  ✗ Failed: %s", e)
            raise

    return rolled_back


def show_status(conn) -> None:
    """Show migration status."""
    applied = get_applied_migrations(conn)
    print(f"\n{'Version':<10} {'Status':<12} {'Description'}")
    print("-" * 60)
    for m in MIGRATIONS:
        status = "✓ applied" if m["version"] in applied else "✗ pending"
        print(f"{m['version']:<10} {status:<12} {m['description']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Database migration tool")
    parser.add_argument("--up", action="store_true", help="Apply all pending migrations")
    parser.add_argument("--down", type=int, nargs="?", const=1, metavar="N",
                        help="Rollback N migrations (default: 1)")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--dry-run", action="store_true", help="Show SQL without executing")
    args = parser.parse_args()

    if not any([args.up, args.down is not None, args.status]):
        parser.print_help()
        sys.exit(1)

    conn = get_db_connection()
    try:
        if args.status:
            show_status(conn)
        elif args.up:
            count = run_up(conn, dry_run=args.dry_run)
            if count:
                logger.info("Applied %d migration(s).", count)
        elif args.down is not None:
            count = run_down(conn, steps=args.down, dry_run=args.dry_run)
            if count:
                logger.info("Rolled back %d migration(s).", count)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
