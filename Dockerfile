# ── Stage 1: builder ─────────────────────────────────────────────────────────
# Installs all Python dependencies. Used by docker-compose.dev.yml as a base
# for development (with hot-reload source mounts).
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .

# Install dependencies — use --no-cache-dir to avoid writing pip's download
# cache to disk (saves ~300 MB on a VPS with limited storage).
# Heavy ML packages (torch, tensorflow) are NOT in requirements.txt to keep
# the image lean; install them separately via requirements-ml.txt only when
# the host has ≥ 10 GB free.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    # Remove pip cache that may have been created despite --no-cache-dir
    rm -rf /root/.cache/pip /tmp/pip-*

COPY . .

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app:$PYTHONPATH

# Install runtime dependencies
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create user and set permissions
RUN useradd -m -u 1000 trader && \
    chown -R trader:trader /app && \
    mkdir -p /var/lib/trading-bot && \
    chown -R trader:trader /var/lib/trading-bot

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
  CMD python -c "import socket;socket.create_connection(('localhost',8001),timeout=2)" || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python","-m","src.main"]

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
# Lean production image built on top of builder.  docker-compose.prod.yml uses
# this target to get a smaller, security-hardened container.
FROM builder AS runtime

# Drop any leftover build artefacts and test files to reduce image size
RUN find /app -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /app -name '*.pyc' -delete && \
    rm -rf /app/tests /app/notebooks /app/tools

# Switch to the unprivileged user for all subsequent commands
USER trader
