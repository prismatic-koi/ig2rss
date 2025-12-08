# ig2rss (Instagram to RSS)

**ig2rss** is a Python application that converts your Instagram home feed into an RSS feed. It authenticates with your Instagram account, polls your timeline every 10 minutes for posts from accounts you follow, stores them indefinitely in a local SQLite database with cached media, and serves them via an HTTP RSS feed that you can subscribe to in any RSS reader.

## Key Features

- Automatically fetches posts from all accounts you follow
- Downloads and caches images/videos locally for offline viewing
- Generates RSS 2.0-compliant feeds with embedded media
- Archives all content indefinitely (even if deleted from Instagram)
- Tracks post authors so you know who posted what
- Runs as a containerized service designed for private Kubernetes deployment

## Tech Stack

- Python 3.11+
- Flask (HTTP server)
- instagrapi (unofficial Instagram API)
- SQLite (data storage)
- APScheduler (background polling)

## Quick Start

### Local Development

1. Clone the repository:
```bash
git clone <repository-url>
cd ig2rss
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your Instagram credentials:
```bash
cp .env.example .env
# Edit .env and add your Instagram username/password
```

4. Run the application:
```bash
python -m src.main
```

5. Subscribe to your feed in an RSS reader:
```
http://localhost:8080/feed.xml
```

### Docker Deployment

```bash
podman build -t ig2rss .
podman run -d \
  -e INSTAGRAM_USERNAME=your_username \
  -e INSTAGRAM_PASSWORD=your_password \
  -v ./data:/data \
  -p 8080:8080 \
  ig2rss
```

## Configuration

Configure via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `INSTAGRAM_USERNAME` | Instagram account username | (required) |
| `INSTAGRAM_PASSWORD` | Instagram account password | (required) |
| `POLL_INTERVAL` | Polling interval in seconds | 600 (10 min) |
| `RSS_FEED_LIMIT` | Number of posts in RSS feed | 50 |
| `RSS_FEED_DAYS` | Days of posts to include | 30 |
| `DATABASE_PATH` | Path to SQLite database | `/data/ig2rss.db` |
| `MEDIA_CACHE_PATH` | Path to media cache | `/data/media` |
| `LOG_LEVEL` | Logging level | INFO |
| `PORT` | HTTP server port | 8080 |

## Testing

Run the test suite:
```bash
# All tests with coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# Single test
pytest tests/test_instagram_client.py::TestInstagramClient::test_login -v

# Lint and format
flake8 src/ tests/
black src/ tests/
mypy src/
```

## Documentation

- [Project Requirements](PROJECT_REQUIREMENTS.md) - Detailed feature requirements and scope
- [Architecture](ARCHITECTURE.md) - Technical architecture and design decisions
- [Roadmap](ROADMAP.md) - Implementation phases and timeline
- [Development Guide](DEVELOPMENT.md) - Development setup and workflows
- [Deployment Guide](DEPLOYMENT.md) - Kubernetes deployment instructions
- [Agent Guidelines](AGENTS.md) - AI agent coding conventions

## Current Status

The core Instagram integration and storage layers are implemented (Phases 1-2 complete per the roadmap), with RSS generation, HTTP server, and scheduler integration in progress.

## Use Case

This project is designed for personal use to consume your Instagram feed in an RSS reader rather than the Instagram app. It provides:

- A cleaner, ad-free reading experience
- Offline access to your feed
- Permanent archival of content from accounts you follow
- Integration with your existing RSS workflow

## Important Notes

- This uses an unofficial Instagram API (instagrapi) and is intended for personal use only
- Instagram may rate limit or ban accounts that use unofficial APIs
- Designed for single-user deployment in a private environment
- Not intended for commercial use or public access

## License

This project is for personal use. Please respect Instagram's Terms of Service.
