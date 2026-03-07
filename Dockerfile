FROM python:3.11-slim as builder

WORKDIR /app
COPY requirements.txt .

# Pre-install CPU-only versions of heavy ML packages to avoid CUDA libraries
# that cause "No space left on device" on CPU-only VPS servers.
#
# torch: the default PyPI wheel on Linux bundles nvidia-cublas-cu12, nvidia-cudnn-cu12,
#   nvidia-nccl-cu12, triton, etc. (~2.3 GB). The CPU wheel from PyTorch's own index
#   is ~200 MB and satisfies the torch>=2.6.0 constraint in requirements.txt.
#
# tensorflow-cpu: the standard tensorflow wheel on Linux installs cuda-bindings and
#   cuda-pathfinder even on CPU-only hosts. tensorflow-cpu is the CPU-only variant
#   (available for versions 2.15.x – 2.16.x) and provides the same Python API.
#
# NOTE: Do NOT use "pip install --user" here. User-local packages are installed into
#   /root/.local which is inaccessible to the non-root "trader" user in the runtime
#   stage, causing every Python import to fail and the container to restart instantly.
#   Install into the system site-packages (/usr/local/lib/python3.11/site-packages/)
#   so that any user can import them.
RUN pip install --no-cache-dir \
        "torch>=2.6.0" \
        --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir "tensorflow-cpu>=2.15.0"

RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim as runtime

WORKDIR /app
# Copy the packages installed into the system site-packages in the builder stage.
# This makes them available to all users (including the non-root "trader" user below).
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

ENV PYTHONPATH=/app:$PYTHONPATH

# Create non-root user
RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

# Health check: verify the bot's Prometheus metrics server is responding.
# start-period gives the bot time to connect to the exchange and PostgreSQL
# before the first check fires; failures within this window are not counted.
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 8001), timeout=2)" || exit 1

CMD ["python", "-m", "src.main"]
