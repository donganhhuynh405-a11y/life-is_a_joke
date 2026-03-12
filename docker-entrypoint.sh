#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Wait for dependent services to be ready.
# docker-compose v1 on Docker Engine ≥ 25 does not support
# "condition: service_healthy" in depends_on (raises 'ContainerConfig' error),
# so we perform the readiness check here in the entrypoint instead.
# ---------------------------------------------------------------------------
WAIT_RETRIES=${WAIT_RETRIES:-30}
WAIT_INTERVAL=${WAIT_INTERVAL:-2}
REDIS_PORT=${REDIS_PORT:-6379}
POSTGRES_PORT=${POSTGRES_PORT:-5432}

wait_for_tcp() {
    local host="$1" port="$2" label="$3"
    echo "Waiting for $label ($host:$port) – up to $((WAIT_RETRIES * WAIT_INTERVAL))s..."
    for i in $(seq 1 "$WAIT_RETRIES"); do
        if python3 -c "import socket; socket.create_connection(('$host', $port), timeout=2)" 2>/dev/null; then
            echo "$label is ready."
            return 0
        fi
        echo "  attempt $i/$WAIT_RETRIES – $label not ready, retrying in ${WAIT_INTERVAL}s..."
        sleep "$WAIT_INTERVAL"
    done
    echo "ERROR: $label ($host:$port) did not become ready after $((WAIT_RETRIES * WAIT_INTERVAL))s." >&2
    exit 1
}

# Only wait when running inside the Compose stack (hosts exist in the network).
# When running standalone (e.g. unit tests) the hosts are absent so we skip.
if getent hosts redis >/dev/null 2>&1; then
    wait_for_tcp redis "$REDIS_PORT" Redis
fi
if getent hosts postgres >/dev/null 2>&1; then
    wait_for_tcp postgres "$POSTGRES_PORT" PostgreSQL
fi

# ---------------------------------------------------------------------------
# Drop privileges: if started as root, switch to the 'trader' user.
# ---------------------------------------------------------------------------
if [ "$(id -u)" = '0' ]; then
    chown -R trader:trader /app /var/lib/trading-bot 2>/dev/null || true
    exec gosu trader "$@"
fi

exec "$@"
