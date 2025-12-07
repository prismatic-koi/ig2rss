#!/bin/bash
# Local testing script for ig2rss
# This script helps you run ig2rss locally with secure credentials

set -e

echo "=== ig2rss Local Testing Setup ==="
echo

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo
    echo "Please create a .env file with your Instagram credentials:"
    echo "  cp .env.example .env"
    echo "  # Edit .env and add your test Instagram credentials"
    echo
    exit 1
fi

# Check if credentials are set
source .env

if [ -z "$INSTAGRAM_USERNAME" ] || [ -z "$INSTAGRAM_PASSWORD" ]; then
    echo "❌ Instagram credentials not set in .env file!"
    echo
    echo "Please edit .env and set:"
    echo "  INSTAGRAM_USERNAME=your_test_username"
    echo "  INSTAGRAM_PASSWORD=your_test_password"
    echo
    exit 1
fi

if [ "$INSTAGRAM_USERNAME" = "your_instagram_username" ]; then
    echo "❌ Please update .env with real credentials (not the example values)"
    exit 1
fi

echo "✓ Found .env file with credentials"
echo "  Username: $INSTAGRAM_USERNAME"
echo "  Base URL: ${BASE_URL:-http://localhost:8080}"
echo

# Check Docker
if command -v docker &> /dev/null; then
    echo "✓ Docker found: $(docker --version)"
elif command -v podman &> /dev/null; then
    echo "✓ Podman found: $(podman --version)"
    # Start podman machine if needed
    if ! podman machine info &> /dev/null; then
        echo "  Starting podman machine..."
        podman machine start
    fi
else
    echo "❌ Docker/Podman not found!"
    echo "  Please install Docker Desktop or Podman"
    exit 1
fi

# Determine which container runtime to use
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
else
    CONTAINER_CMD="docker"
fi

echo

# Offer choice: Docker or direct Python
echo "Choose how to run ig2rss:"
echo "  1) Docker container (recommended for production-like testing)"
echo "  2) Direct Python (faster for development/debugging)"
echo
read -p "Enter choice [1-2]: " choice

if [ "$choice" = "1" ]; then
    echo
    echo "=== Building and Running Docker Container ==="
    echo
    
    # Build image
    echo "Building Docker image..."
    $CONTAINER_CMD build -t ig2rss:test .
    
    echo
    echo "Starting container..."
    
    # Stop existing container if running
    $CONTAINER_CMD stop ig2rss-test 2>/dev/null || true
    $CONTAINER_CMD rm ig2rss-test 2>/dev/null || true
    
    # Run container
    $CONTAINER_CMD run -d \
        --name ig2rss-test \
        -p 8080:8080 \
        --env-file .env \
        -v ig2rss-test-data:/data \
        ig2rss:test
    
    echo
    echo "✓ Container started!"
    echo
    echo "Waiting for service to be ready..."
    sleep 5
    
    # Check health
    for i in {1..10}; do
        if curl -s http://localhost:8080/health > /dev/null 2>&1; then
            echo "✓ Service is healthy!"
            break
        fi
        echo "  Waiting... ($i/10)"
        sleep 2
    done
    
    echo
    echo "=== Container Logs (last 20 lines) ==="
    $CONTAINER_CMD logs ig2rss-test --tail 20
    
    echo
    echo "=== Useful Commands ==="
    echo "  View logs:        $CONTAINER_CMD logs -f ig2rss-test"
    echo "  Check health:     curl http://localhost:8080/health | jq"
    echo "  View RSS feed:    curl http://localhost:8080/feed.rss"
    echo "  Stop container:   $CONTAINER_CMD stop ig2rss-test"
    echo "  Remove container: $CONTAINER_CMD rm ig2rss-test"
    echo "  Shell access:     $CONTAINER_CMD exec -it ig2rss-test /bin/bash"
    echo

elif [ "$choice" = "2" ]; then
    echo
    echo "=== Running with Python (Direct) ==="
    echo
    
    # Check if virtual environment exists
    if [ ! -d .venv ]; then
        echo "Creating virtual environment..."
        python3 -m venv .venv
    fi
    
    # Activate and install dependencies
    echo "Installing dependencies..."
    source .venv/bin/activate
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    
    echo
    echo "Starting ig2rss server..."
    echo "Press Ctrl+C to stop"
    echo
    
    # Load env vars and run
    export $(cat .env | grep -v '^#' | xargs)
    python -m src.main

else
    echo "Invalid choice. Exiting."
    exit 1
fi
