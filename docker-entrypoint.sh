#!/bin/bash
set -e

if [ "$(id -u)" = '0' ]; then
    chown -R trader:trader /app /var/lib/trading-bot 2>/dev/null || true
    exec gosu trader "$@"
fi

exec "$@"
