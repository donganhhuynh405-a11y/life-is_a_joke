FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .

# Install dependencies in separate steps to avoid index conflicts
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir tensorflow-cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app:$PYTHONPATH

# Install runtime dependencies
RUN apt-get update && apt-get install -y gosu && rm -rf /var/lib/apt/lists/*

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
