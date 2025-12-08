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

# Copy requirements and install dependencies globally (not --user)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Test (optional stage for CI/CD)
FROM builder AS test

WORKDIR /app

# Install test dependencies globally
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy application code and tests
COPY src/ /app/src/
COPY tests/ /app/tests/

# Set dummy env vars for tests
ENV INSTAGRAM_USERNAME=test_user
ENV INSTAGRAM_PASSWORD=test_pass
ENV PYTHONPATH=/app

# Run tests with python -m to ensure proper path handling
RUN python -m pytest tests/ -v --cov=src --cov-report=term-missing

# Stage 3: Runtime
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder (system-wide install)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Verify critical dependencies are present
RUN python -c "from dotenv import load_dotenv" || \
    (echo "ERROR: dotenv package not found!" && exit 1)

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash ig2rss

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ /app/src/

# Create data directory with correct permissions
RUN mkdir -p /data && \
    chown -R ig2rss:ig2rss /data && \
    chown -R ig2rss:ig2rss /app

# Switch to non-root user
USER ig2rss

# Environment variables
ENV PYTHONUNBUFFERED=1

# Expose HTTP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()" || exit 1

# Run the application
CMD ["python", "-m", "src.main"]
