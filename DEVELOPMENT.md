# Instagram to RSS - Development Guide

## Overview

This guide covers setting up a local development environment for ig2rss, running tests, and contributing to the project.

---

## Prerequisites

### Required Software
- **Python 3.11+**: [Download](https://www.python.org/downloads/)
- **Podman or Docker**: For containerization
  - macOS: `brew install podman`
  - Linux: Use your package manager
- **Git**: Version control
- **SQLite3**: Usually pre-installed, for database inspection

### Optional Tools
- **VS Code** or **PyCharm**: Recommended IDEs
- **httpie** or **curl**: For API testing
- **RSS reader**: For testing RSS feeds (NetNewsWire, Feedly, etc.)

---

## Initial Setup

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/ig2rss.git
cd ig2rss
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development dependencies
```

**requirements.txt**:
```
instagrapi>=2.0.0
flask>=3.0.0
apscheduler>=3.10.0
python-dotenv>=1.0.0
```

**requirements-dev.txt**:
```
pytest>=7.4.0
pytest-cov>=4.1.0
pytest-mock>=3.11.0
black>=23.7.0
flake8>=6.1.0
mypy>=1.5.0
requests>=2.31.0
```

### 4. Configure Environment

Create `.env` file for local development (note: add to .gitignore!)

### 5. Create Data Directory

```bash
mkdir -p data/media
```

---

## Project Structure

The project follows standard Python application structure with source code in `src/`, tests in `tests/`, Kubernetes manifests in `k8s/`, and documentation in `docs/`.

---

## Running Locally

### Option 1: Direct Python Execution

```bash
# Activate virtual environment
source venv/bin/activate

# Run application
python -m src.main
```

Application will:
1. Load configuration from environment variables
2. Initialize database
3. Start HTTP server on http://localhost:8080
4. Begin polling Instagram every 10 minutes (default)

### Option 2: Docker/Podman

```bash
# Start podman machine (if on macOS)
podman machine start

# Build image
podman build -t ig2rss:dev .

# Run container
podman run --rm \
  -e INSTAGRAM_USERNAME=your_username \
  -e INSTAGRAM_PASSWORD=your_password \
  -v $(pwd)/data:/data \
  -p 8080:8080 \
  ig2rss:dev
```

---

## Testing the Application

### Access RSS Feed

**Web browser**:
```
http://localhost:8080/feed.xml
```

**curl**:
```bash
curl http://localhost:8080/feed.xml

# With query parameters
curl "http://localhost:8080/feed.xml?limit=10&days=7"
```

### Access Media Files

```bash
curl http://localhost:8080/media/<post_id>/image_0.jpg -o test.jpg
```

### Health Checks

```bash
curl http://localhost:8080/health   # Liveness
curl http://localhost:8080/ready    # Readiness
```

### Inspect Database

```bash
sqlite3 data/ig2rss.db

# Inside SQLite prompt:
.tables
.schema posts
.schema media

SELECT COUNT(*) FROM posts;
SELECT COUNT(*) FROM media;

# View recent posts with authors (home feed includes all followed accounts)
SELECT id, author_username, posted_at, caption FROM posts ORDER BY posted_at DESC LIMIT 10;

# View posts by a specific author
SELECT id, posted_at, caption FROM posts WHERE author_username = 'specific_user' ORDER BY posted_at DESC;

.quit
```

---

## Running Tests

### Unit Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_storage.py

# Run with coverage
pytest --cov=src --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Integration Tests

```bash
# Run only integration tests
pytest tests/test_integration.py -v

# Skip integration tests
pytest -m "not integration"
```

---

## Code Quality

### Formatting with Black

```bash
# Format all code
black src/ tests/

# Check formatting without changes
black --check src/ tests/
```

### Linting with Flake8

```bash
# Lint all code
flake8 src/ tests/
```

### Type Checking with mypy

```bash
# Type check all code
mypy src/
```

---

## Debugging

### VS Code Configuration

Create `.vscode/launch.json` to enable debugging with F5.

### Logging Configuration

For detailed debugging, set environment variable:
```
LOG_LEVEL=DEBUG
```

---

## Common Development Tasks

### Reset Database

```bash
rm -rf data/ig2rss.db data/media/*
# Restart application to recreate
```

### Mock Instagram API

For testing without hitting Instagram, use pytest fixtures with mocking.

---

## Contribution Guidelines

### Git Workflow

1. Create feature branch
2. Make changes and commit
3. Run tests before pushing
4. Push and create PR

### Commit Message Convention

```
<type>: <subject>

<body>
```

**Types**: feat, fix, docs, test, refactor, style, chore

---

## Troubleshooting

### Import Errors
Ensure virtual environment is activated and dependencies installed.

### Instagram Login Fails
Check credentials, 2FA settings, and Instagram account status.

### Database Locked
Close all connections to the database file.

### Port Already in Use
Find and kill process using port 8080, or use different port.

---

## Resources

- [instagrapi Documentation](https://instagrapi.readthedocs.io/)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [RSS 2.0 Specification](https://www.rssboard.org/rss-specification)
- [SQLite Documentation](https://www.sqlite.org/docs.html)

---

## Next Steps

After setting up your development environment:

1. Familiarize yourself with the codebase structure
2. Run the test suite to ensure everything works
3. Try making a small change and see tests pass
4. Review ROADMAP.md for implementation phases
5. Pick a task from Phase 0 and start coding!

Happy coding! 🚀
