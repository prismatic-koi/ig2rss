# Multi-stage Dockerfile for ig2rss
# Builds a minimal production image running as non-root user

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash ig2rss

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/ig2rss/.local

# Copy application code
COPY src/ /app/src/

# Create data directory with correct permissions
RUN mkdir -p /data && \
    chown -R ig2rss:ig2rss /data && \
    chown -R ig2rss:ig2rss /app

# Switch to non-root user
USER ig2rss

# Add user packages to PATH
ENV PATH=/home/ig2rss/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# Expose HTTP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()" || exit 1

# Run the application
CMD ["python", "-m", "src.main"]
