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
# Use "pip install --user" so packages land in /root/.local (not the system
# site-packages).  The runtime stage then copies that single directory and
# exports it via PYTHONPATH/PATH, which keeps the runtime layer small and
# avoids "no space left on device" errors that occur when copying the entire
# system site-packages tree (several GB including tensorflow native libs).
RUN pip install --user --no-cache-dir \
        "torch>=2.6.0" \
        --index-url https://download.pytorch.org/whl/cpu

RUN pip install --user --no-cache-dir "tensorflow-cpu>=2.15.0"

RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim as runtime

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .

# Make /root/.local packages and scripts accessible to every user, including
# the non-root "trader" user created below.  Without PYTHONPATH, Python's
# site module resolves user-site-packages relative to the current user's HOME
# (~/.local/…), so "trader" would look in /home/trader/.local — not /root/.local
# — and every import would fail, causing an instant restart loop.
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/root/.local/lib/python3.11/site-packages:/app:$PYTHONPATH

# Create non-root user
RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

# Health check: verify the bot's Prometheus metrics server is responding.
# start-period gives the bot time to connect to the exchange and PostgreSQL
# before the first check fires; failures within this window are not counted.
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 8001), timeout=2)" || exit 1

CMD ["python", "-m", "src.main"]
