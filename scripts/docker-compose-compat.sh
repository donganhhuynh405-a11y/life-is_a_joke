#!/bin/bash
# scripts/docker-compose-compat.sh
#
# Helper that prints the correct Docker Compose command for the current host.
# Source this file or call it directly:
#
#   source scripts/docker-compose-compat.sh
#   $DC up -d --build
#
# Or use it as a one-liner in other scripts:
#   DC=$(bash scripts/docker-compose-compat.sh)
#   $DC down

set -e

# Prefer the standalone 'docker-compose' binary (v1) if present.
# Fall back to the 'docker compose' plugin (v2).
if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
elif docker compose version >/dev/null 2>&1; then
    echo "docker compose"
else
    echo "ERROR: Neither 'docker-compose' nor 'docker compose' found." >&2
    echo "Install Docker Compose: https://docs.docker.com/compose/install/" >&2
    exit 1
fi
