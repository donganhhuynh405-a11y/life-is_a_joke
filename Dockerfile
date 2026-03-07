FROM python:3.11-slim as builder

WORKDIR /app
COPY requirements.txt .

# Install CPU-only PyTorch BEFORE requirements.txt.
# The default PyPI wheel for torch on Linux bundles CUDA libraries (nvidia-cublas-cu12,
# nvidia-cudnn-cu12, nvidia-nccl-cu12, etc.) that add ~2 GB to the build layer and
# cause "No space left on device" on servers without a GPU.
# Installing from the PyTorch CPU wheel index first satisfies the torch>=2.6.0
# constraint in requirements.txt so pip will not re-download the CUDA variant.
RUN pip install --user --no-cache-dir \
        "torch>=2.6.0" \
        --index-url https://download.pytorch.org/whl/cpu

RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim as runtime

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY . .

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app:$PYTHONPATH

# Create non-root user
RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 8001), timeout=2)" || exit 1

CMD ["python", "-m", "src.main"]
