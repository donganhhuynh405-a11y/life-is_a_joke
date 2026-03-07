#!/bin/sh
# docker-entrypoint.sh
# Runs as root at container start-up to fix ownership of the data directory
# (Docker named volumes are created with root ownership by default, so the
# non-root "trader" user would otherwise be unable to write SQLite databases
# or model files).  After fixing permissions the script drops privileges and
# exec's the bot as trader.
set -e

DATA_DIR=/var/lib/trading-bot

# Create the directory if it is somehow missing (fresh container, no volume)
mkdir -p "$DATA_DIR"

# Ensure trader owns the directory so it can write SQLite / model files.
# The chown is a no-op when permissions are already correct, so it is safe to
# run on every container start-up, including when PostgreSQL is the primary DB.
chown -R trader:trader "$DATA_DIR"

# Drop to the non-root user and exec the application.
exec gosu trader "$@"
