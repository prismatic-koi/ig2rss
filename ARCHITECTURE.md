# Instagram to RSS - Technical Architecture

## System Overview

ig2rss is a containerized Python application that polls the authenticated user's Instagram home feed (posts from all followed accounts), stores them indefinitely in a local SQLite database with cached media and author attribution, and serves an RSS feed via HTTP endpoints.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     ig2rss Container                         │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Scheduler  │───▶│ IG API Client│───▶│  Instagram   │  │
│  │  (10 min)    │    │  (instagrapi)│    │   (External) │  │
│  └──────────────┘    └──────┬───────┘    └──────────────┘  │
│         │                   │                               │
│         │                   ▼                               │
│         │          ┌──────────────┐                         │
│         │          │   Storage    │                         │
│         │          │   Manager    │                         │
│         │          └──────┬───────┘                         │
│         │                 │                                 │
│         │        ┌────────┴────────┐                        │
│         │        ▼                 ▼                        │
│         │   ┌─────────┐      ┌──────────┐                  │
│         │   │ SQLite  │      │  Media   │                  │
│         │   │ Database│      │  Cache   │                  │
│         │   └─────────┘      └──────────┘                  │
│         │        │                 │                        │
│         │        └────────┬────────┘                        │
│         │                 ▼                                 │
│         │          ┌──────────────┐                         │
│         └─────────▶│ RSS Generator│                         │
│                    └──────┬───────┘                         │
│                           │                                 │
│                           ▼                                 │
│                    ┌──────────────┐                         │
│                    │  HTTP Server │                         │
│                    │ (Flask/Fast) │                         │
│                    └──────┬───────┘                         │
└───────────────────────────┼─────────────────────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  RSS Reader  │
                    │   (Client)   │
                    └──────────────┘
```

## Component Design

### 1. Scheduler
**Responsibility**: Orchestrate periodic Instagram polling

**Implementation**:
- Background thread or async task (using `APScheduler` or similar)
- Configurable interval (default: 10 minutes)
- Triggers Instagram API client on schedule
- Handles graceful shutdown

**Key Functions**:
```python
class Scheduler:
    def start(self):
        """Start the polling scheduler"""
    
    def stop(self):
        """Gracefully stop the scheduler"""
    
    def trigger_poll(self):
        """Execute one polling cycle"""
```

### 2. Instagram API Client
**Responsibility**: Interface with Instagram via instagrapi

**Implementation**:
- Wrapper around instagrapi Client
- Handle authentication and session management
- Fetch user's home feed/timeline (posts from all followed accounts)
- Extract post author information for each post
- Download media files
- Error handling and retry logic

**Key Functions**:
```python
class InstagramClient:
    def __init__(self, username: str, password: str):
        """Initialize with credentials"""
    
    def login(self) -> bool:
        """Authenticate with Instagram"""
    
    def get_timeline_feed(self, count: int = 50) -> List[Post]:
        """Fetch recent posts from user's home feed (all followed accounts)"""
    
    def download_media(self, media_url: str, local_path: str) -> bool:
        """Download media file to local storage"""
    
    def handle_rate_limit(self, error: Exception):
        """Handle rate limiting with backoff"""
```

**Error Handling**:
- Login failures: Log and retry with exponential backoff
- Rate limiting: Implement backoff strategy
- Network errors: Retry with configurable attempts
- Invalid credentials: Log critical error and exit

### 3. Storage Manager
**Responsibility**: Manage SQLite database and media filesystem

**Database Schema**:
```sql
CREATE TABLE posts (
    id TEXT PRIMARY KEY,              -- Instagram post ID
    posted_at TIMESTAMP NOT NULL,     -- When posted to Instagram
    fetched_at TIMESTAMP NOT NULL,    -- When we fetched it
    caption TEXT,                     -- Post caption/text
    post_type TEXT NOT NULL,          -- 'photo', 'video', 'carousel'
    permalink TEXT NOT NULL,          -- Instagram URL
    author_username TEXT NOT NULL     -- Username of account that posted (required)
);

CREATE TABLE media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,            -- Foreign key to posts
    media_type TEXT NOT NULL,         -- 'image' or 'video'
    media_index INTEGER NOT NULL,     -- Position in carousel (0 for single)
    original_url TEXT NOT NULL,       -- Instagram CDN URL
    local_path TEXT NOT NULL,         -- Local filesystem path
    mime_type TEXT NOT NULL,          -- e.g., 'image/jpeg', 'video/mp4'
    file_size INTEGER,                -- Bytes
    downloaded_at TIMESTAMP NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE INDEX idx_posts_posted_at ON posts(posted_at DESC);
CREATE INDEX idx_posts_author ON posts(author_username);
CREATE INDEX idx_media_post_id ON media(post_id);
```

**Key Functions**:
```python
class StorageManager:
    def __init__(self, db_path: str, media_path: str):
        """Initialize storage with paths"""
    
    def save_post(self, post: Post) -> bool:
        """Save post metadata to database"""
    
    def save_media(self, post_id: str, media_url: str, 
                   local_path: str, media_type: str, index: int) -> bool:
        """Save media metadata to database"""
    
    def get_recent_posts(self, limit: int = 50, days: int = 30) -> List[Post]:
        """Retrieve posts for RSS feed generation"""
    
    def post_exists(self, post_id: str) -> bool:
        """Check if post already stored (avoid duplicates)"""
    
    def get_media_path(self, post_id: str, filename: str) -> str:
        """Resolve media file path"""
    
    def cleanup_old_data(self, days: int = None):
        """Optional cleanup for very old data"""
```

**Filesystem Structure**:
```
/data/
├── ig2rss.db                    # SQLite database
└── media/                       # Media cache
    ├── <post_id_1>/
    │   ├── image_0.jpg
    │   └── image_1.jpg          # Carousel
    ├── <post_id_2>/
    │   └── video_0.mp4
    └── ...
```

### 4. RSS Generator
**Responsibility**: Generate RSS 2.0 compliant XML feed

**Implementation**:
- Query recent posts from StorageManager
- Build RSS XML with HTML-embedded media
- Handle text encoding and CDATA wrapping
- Generate proper timestamps (RFC 822 format)

**RSS Feed Structure**:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Instagram Feed - {username}</title>
    <link>https://instagram.com/{username}</link>
    <description>Home feed for {username} - Posts from all followed accounts</description>
    <lastBuildDate>{timestamp}</lastBuildDate>
    
    <item>
      <title>@{author_username}: {caption_preview or "Instagram Post"}</title>
      <link>{permalink}</link>
      <guid isPermaLink="true">{permalink}</guid>
      <pubDate>{posted_at_rfc822}</pubDate>
      <author>{author_username}@instagram.com ({author_username})</author>
      <description>
        <![CDATA[
          <p><strong>@{author_username}</strong></p>
          <p>{caption}</p>
          <img src="http://{service_url}/media/{post_id}/image_0.jpg" 
               style="max-width: 100%; height: auto;" 
               alt="Instagram post by @{author_username}" />
          <!-- Additional images for carousels -->
          <video controls style="max-width: 100%;">
            <source src="http://{service_url}/media/{post_id}/video_0.mp4" 
                    type="video/mp4" />
          </video>
          <p><a href="{permalink}">View on Instagram</a></p>
        ]]>
      </description>
    </item>
    
    <!-- More items... -->
  </channel>
</rss>
```

**Key Functions**:
```python
class RSSGenerator:
    def __init__(self, storage: StorageManager, base_url: str):
        """Initialize with storage and service base URL"""
    
    def generate_feed(self, limit: int = 50, days: int = 30) -> str:
        """Generate RSS XML feed"""
    
    def format_post_item(self, post: Post) -> str:
        """Convert single post to RSS item XML"""
    
    def build_media_html(self, media_list: List[Media], 
                         post_id: str) -> str:
        """Generate HTML for images/videos"""
    
    def escape_html(self, text: str) -> str:
        """Escape HTML entities in captions"""
```

### 5. HTTP Server
**Responsibility**: Serve RSS feed and media files via HTTP

**Implementation**: Flask or FastAPI

**Endpoints**:

```python
# RSS Feed Endpoints
GET /feed.xml
GET /feed.xml?limit=100
GET /feed.xml?days=90
GET /feed.xml?limit=100&days=90

# Media Endpoints
GET /media/<post_id>/<filename>

# Health Check
GET /health
GET /ready

# Optional: Metrics/Status
GET /status
```

**Endpoint Details**:

```python
@app.route('/feed.xml')
def get_feed():
    """
    Generate and return RSS feed
    Query params:
      - limit: Max posts (default: 50)
      - days: Days to include (default: 30)
    Returns: RSS XML with content-type application/rss+xml
    """

@app.route('/media/<post_id>/<filename>')
def get_media(post_id: str, filename: str):
    """
    Serve cached media file
    Returns: File with appropriate content-type
    Handles: 404 if file not found
    """

@app.route('/health')
def health_check():
    """
    Kubernetes liveness probe
    Returns: 200 OK if service running
    """

@app.route('/ready')
def readiness_check():
    """
    Kubernetes readiness probe
    Checks: Database accessible, last poll successful
    Returns: 200 OK if ready, 503 if not
    """

@app.route('/status')
def status():
    """
    Optional status endpoint
    Returns: JSON with last poll time, post count, etc.
    """
```

## Data Flow

### Polling Cycle Flow
```
1. Scheduler triggers poll (every 10 minutes)
   ↓
2. InstagramClient.login() if needed
   ↓
3. InstagramClient.get_timeline_feed(count=50)
   ↓
4. For each post:
   a. Extract author_username from post metadata
   b. Check StorageManager.post_exists(post_id)
   c. If new:
      - Download media via InstagramClient.download_media()
      - Save to filesystem: /data/media/<post_id>/<filename>
      - StorageManager.save_post(post_metadata including author_username)
      - StorageManager.save_media(media_metadata)
   ↓
5. Log summary (X new posts from Y accounts, Z media files downloaded)
```

### RSS Request Flow
```
1. Client requests GET /feed.xml
   ↓
2. HTTP Server receives request
   ↓
3. Parse query params (limit, days)
   ↓
4. RSSGenerator.generate_feed(limit, days)
   ↓
5. StorageManager.get_recent_posts(limit, days)
   ↓
6. For each post, build RSS item with media URLs
   ↓
7. Return XML with content-type application/rss+xml
```

### Media Request Flow
```
1. RSS Reader requests GET /media/<post_id>/<filename>
   ↓
2. HTTP Server validates post_id and filename
   ↓
3. StorageManager.get_media_path(post_id, filename)
   ↓
4. Check file exists on filesystem
   ↓
5. Return file with appropriate content-type
   (or 404 if not found)
```

## Configuration Management

**Environment Variables**:
```python
import os

class Config:
    # Instagram credentials
    INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')  # Required
    INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')  # Required
    
    # Polling configuration
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '600'))  # seconds
    
    # RSS feed configuration
    RSS_FEED_LIMIT = int(os.getenv('RSS_FEED_LIMIT', '50'))
    RSS_FEED_DAYS = int(os.getenv('RSS_FEED_DAYS', '30'))
    
    # Storage paths
    DATABASE_PATH = os.getenv('DATABASE_PATH', '/data/ig2rss.db')
    MEDIA_CACHE_PATH = os.getenv('MEDIA_CACHE_PATH', '/data/media')
    
    # HTTP server
    PORT = int(os.getenv('PORT', '8080'))
    HOST = os.getenv('HOST', '0.0.0.0')
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
```

## Error Handling Strategy

### Error Categories

**1. Transient Errors (Retry)**:
- Network timeouts
- Instagram API rate limits
- Temporary Instagram unavailability

**Strategy**: Exponential backoff with max retries

```python
def retry_with_backoff(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except TransientError as e:
            wait = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(f"Retry {attempt+1}/{max_retries} after {wait}s: {e}")
            time.sleep(wait)
    raise MaxRetriesExceeded()
```

**2. Permanent Errors (Alert & Continue)**:
- Invalid credentials
- Account banned
- Post deleted before download

**Strategy**: Log error, continue operation, expose in status endpoint

**3. Critical Errors (Exit)**:
- Database corruption
- Filesystem full
- Invalid configuration

**Strategy**: Log critical error, exit gracefully (k8s will restart)

### Logging Strategy

**Structured Logging**:
```python
import logging
import json

class StructuredLogger:
    def log(self, level, message, **context):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': level,
            'message': message,
            **context
        }
        logger.log(level, json.dumps(log_entry))
```

**Log Levels**:
- **DEBUG**: Detailed API responses, SQL queries
- **INFO**: Poll cycles, new posts, RSS requests
- **WARNING**: Retries, rate limits, missing media
- **ERROR**: Failed downloads, auth failures
- **CRITICAL**: Database errors, config errors

**Key Log Events**:
```python
# Poll cycle
logger.info("Poll cycle started", cycle_id=uuid4())
logger.info("Poll cycle completed", new_posts=5, duration_ms=1234)

# Instagram API
logger.info("Instagram login successful", username=username)
logger.warning("Rate limit encountered", retry_after=300)

# Storage
logger.info("New post saved", post_id=post_id, media_count=3)
logger.error("Media download failed", post_id=post_id, url=url, error=str(e))

# RSS
logger.info("RSS feed generated", posts=50, duration_ms=123)
logger.info("Media served", post_id=post_id, filename=filename, size_bytes=12345)
```

## Performance Considerations

### Optimization Strategies

**1. Database Indexing**:
- Index on `posts.posted_at DESC` for fast recent post queries
- Index on `media.post_id` for fast joins

**2. Lazy Media Loading**:
- Don't load all media into memory
- Stream files directly from filesystem in HTTP responses

**3. RSS Caching (Optional Future Enhancement)**:
- Cache generated RSS XML for 1-2 minutes
- Invalidate cache after new poll cycle

**4. Async Media Downloads**:
- Download media files concurrently (e.g., asyncio or thread pool)
- Don't block poll cycle on slow downloads

**5. Connection Pooling**:
- Reuse Instagram session across polls
- Reuse database connections

## Security Considerations

**1. Credential Management**:
- Never log passwords
- Load from environment variables only
- No default credentials

**2. File Serving**:
- Validate post_id and filename (prevent path traversal)
- Only serve files from media cache directory
- Set appropriate content-type headers

**3. Container Security**:
- Run as non-root user (UID 1000)
- Read-only root filesystem (except /data mount)
- Drop unnecessary capabilities

**4. Input Validation**:
- Validate RSS query parameters (limit, days)
- Sanitize Instagram captions for RSS XML

## Scalability Considerations

**Current Design (Single User)**:
- Single container instance
- SQLite sufficient for one user's posts
- No horizontal scaling needed

**Future Multi-User Scaling**:
- Switch to PostgreSQL for concurrent writes
- Separate media storage (S3-compatible)
- Queue-based polling (Celery + Redis/Valkey)
- Multiple worker containers

## Technology Stack Recommendations

### Core Dependencies
```
instagrapi==2.0.0+       # Instagram API client
flask==3.0.0+            # HTTP server (or fastapi)
apscheduler==3.10.0+     # Scheduling
python==3.11+            # Runtime
```

### Why Flask over FastAPI?
- Simpler for this use case
- Synchronous is fine (not high traffic)
- Smaller footprint

**Alternative: FastAPI** if you prefer:
- Better async support
- Auto-generated API docs
- Type hints validation

### Project Structure
```
ig2rss/
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── config.py               # Configuration
│   ├── scheduler.py            # Polling scheduler
│   ├── instagram_client.py    # Instagram API wrapper
│   ├── storage.py              # Storage manager
│   ├── rss_generator.py        # RSS generation
│   ├── http_server.py          # Flask/FastAPI server
│   └── models.py               # Data models
├── tests/
│   ├── test_instagram_client.py
│   ├── test_storage.py
│   ├── test_rss_generator.py
│   └── test_integration.py
├── Dockerfile
├── requirements.txt
├── README.md
└── docs/
    ├── PROJECT_REQUIREMENTS.md
    ├── ARCHITECTURE.md
    ├── ROADMAP.md
    ├── DEPLOYMENT.md
    └── DEVELOPMENT.md
```

## Monitoring & Observability

### Health Checks
- `/health`: Always returns 200 (liveness)
- `/ready`: Returns 200 if last poll succeeded, 503 otherwise (readiness)

### Metrics (Future Enhancement)
```python
# Potential metrics to expose
total_posts_stored
total_media_files
last_poll_timestamp
last_poll_duration_seconds
last_poll_new_posts
rss_requests_total
media_requests_total
errors_total (by type)
```

### Alerting Considerations
- Alert if no successful poll in 60+ minutes
- Alert if database size exceeds threshold
- Alert on repeated Instagram auth failures

## Disaster Recovery

### Backup Strategy
- Persistent volume contains all data (database + media)
- Regular k8s volume snapshots recommended
- Database export: `sqlite3 ig2rss.db .dump > backup.sql`

### Recovery Procedures
1. **Lost credentials**: Update k8s secret, restart pod
2. **Database corruption**: Restore from volume snapshot
3. **Missing media**: Re-download from Instagram (if still available)
4. **Full data loss**: Fresh start (posts re-fetched from Instagram feed)

## Future Architecture Enhancements

### Stories Support (Stretch Goal)
- New table: `stories` (similar to `posts`)
- Stories expire after 24h on Instagram
- Separate polling cycle for stories
- Archive stories locally even after Instagram expires them

### Multi-Account Support
- Add `accounts` table
- Foreign key from `posts` to `accounts`
- Separate RSS feeds per account: `/feed/<username>.xml`
- Single container polls multiple accounts

### Web UI
- React/Vue frontend for browsing archive
- View posts, search, filter by date
- Export functionality
- Configuration management

### Webhook Notifications
- Optional webhook on new posts
- Integrate with Discord, Slack, etc.
- Push notifications to mobile devices
