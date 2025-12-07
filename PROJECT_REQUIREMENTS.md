# Instagram to RSS - Project Requirements

## Project Overview

**Project Name**: ig2rss (Instagram to RSS)  
**Purpose**: Convert a user's Instagram home feed (posts from all followed accounts) to RSS format for consumption in RSS reader applications  
**Target User**: Single Instagram user wanting to view their home feed in an RSS reader  
**Deployment**: Private Kubernetes cluster (not publicly exposed)

## Goals

- Enable RSS reader access to Instagram home feed (all posts from followed accounts)
- Maintain indefinite archive of Instagram content with author attribution
- Provide reliable, automated polling of Instagram feed
- Deliver media-rich RSS feed with embedded images and videos

## Scope

### MVP (Minimum Viable Product)
- Fetch user's Instagram home feed (posts from all followed accounts)
- Store post author information to identify who posted what
- Generate RSS feed with posts from last 30 days or 50 posts (whichever is more)
- Download and cache media (images/videos)
- Serve RSS via HTTP endpoint with author attribution
- Store all posts indefinitely for archival purposes
- Run as containerized service in Kubernetes

### Stretch Goals (Future Enhancements)
- Instagram Stories support (from followed accounts)
- Configurable retention/RSS window
- Web UI for configuration and browsing archive
- Webhook notifications for new posts
- Filter by specific followed accounts

### Out of Scope
- Public access/multi-tenant support
- Multiple Instagram account credentials (single login only)
- Legal/ToS compliance for commercial use
- Authentication for RSS endpoint (deployed in private cluster)
- Posting or interacting with Instagram content

## User Stories

### Core Functionality
1. As a user, I want posts from all accounts I follow to be automatically fetched every 10 minutes so my RSS reader stays current
2. As a user, I want to see who posted each item (author username) in the RSS feed
3. As a user, I want images to display inline in my RSS reader so I can view content without leaving the app
4. As a user, I want videos to be playable from the RSS feed
5. As a user, I want the RSS feed to show the most recent 50 posts or 30 days of content from my home feed
6. As a user, I want all Instagram content from accounts I follow archived indefinitely for personal reference

### Operational
6. As a developer, I want comprehensive logging so I can troubleshoot issues
7. As a developer, I want the service to gracefully handle Instagram API errors
8. As a developer, I want the container to be stateless except for persistent storage
9. As a developer, I want to configure credentials via environment variables

## Functional Requirements

### Instagram Integration
- **FR-1**: Authenticate with Instagram using username/password credentials
- **FR-2**: Poll Instagram home feed (timeline) every 10 minutes for new posts
- **FR-3**: Download post metadata (author username, caption, timestamp, permalink)
- **FR-4**: Download associated media (images, videos, carousels)
- **FR-5**: Handle Instagram API errors gracefully with retry logic

### Data Storage
- **FR-6**: Store post metadata in SQLite database
- **FR-7**: Store media files in local filesystem cache
- **FR-8**: Maintain indefinite retention of all posts and media
- **FR-9**: Track processing state to avoid duplicate fetching
- **FR-10**: Support persistent volume mounting for data durability

### RSS Generation
- **FR-11**: Generate RSS 2.0 compliant feed
- **FR-12**: Include last 50 posts or 30 days (whichever yields more posts)
- **FR-13**: Display post author (username) prominently in each RSS item
- **FR-14**: Embed images using HTML in `<description>` field
- **FR-15**: Embed videos using HTML5 `<video>` tags
- **FR-16**: Include post captions, timestamps, author, and Instagram permalinks
- **FR-17**: Serve media via HTTP endpoints referenced in RSS

### HTTP Interface
- **FR-18**: Expose `/feed.xml` endpoint for RSS feed
- **FR-19**: Expose `/media/<post_id>/<filename>` for cached media
- **FR-20**: Support optional query parameters (e.g., `?limit=100`, `?days=90`)
- **FR-21**: Return appropriate HTTP status codes and error messages

## Non-Functional Requirements

### Performance
- **NFR-1**: RSS feed generation completes in < 1 second
- **NFR-2**: Media download doesn't block polling cycle
- **NFR-3**: Database queries optimized with appropriate indexes

### Reliability
- **NFR-4**: Service auto-recovers from Instagram API failures
- **NFR-5**: Persistent storage ensures no data loss on container restart
- **NFR-6**: Graceful handling of network timeouts

### Observability
- **NFR-7**: Comprehensive structured logging (INFO level minimum)
- **NFR-8**: Log all Instagram API interactions (success/failure)
- **NFR-9**: Log media download operations
- **NFR-10**: Log RSS feed requests
- **NFR-11**: Include timestamps and context in all log entries

### Security
- **NFR-12**: Credentials provided via environment variables only
- **NFR-13**: No hardcoded secrets in code or images
- **NFR-14**: Media files served with appropriate content-type headers

### Maintainability
- **NFR-15**: Clean separation of concerns (API client, storage, RSS generation, HTTP server)
- **NFR-16**: Configuration via environment variables
- **NFR-17**: Code follows Python best practices (PEP 8)
- **NFR-18**: Comprehensive documentation for future developers

### Deployment
- **NFR-19**: Single Docker container deployment
- **NFR-20**: Container runs as non-root user
- **NFR-21**: Health check endpoint for Kubernetes liveness/readiness probes
- **NFR-22**: Graceful shutdown handling

## Configuration Requirements

### Environment Variables
- `INSTAGRAM_USERNAME`: Instagram account username (required)
- `INSTAGRAM_PASSWORD`: Instagram account password (required)
- `POLL_INTERVAL`: Polling interval in seconds (default: 600)
- `RSS_FEED_LIMIT`: Number of posts in RSS feed (default: 50)
- `RSS_FEED_DAYS`: Days of posts to include (default: 30)
- `DATABASE_PATH`: Path to SQLite database file (default: `/data/ig2rss.db`)
- `MEDIA_CACHE_PATH`: Path to media cache directory (default: `/data/media`)
- `LOG_LEVEL`: Logging level (default: INFO)
- `PORT`: HTTP server port (default: 8080)

## Success Criteria

### MVP Success Metrics
1. Successfully authenticates with Instagram
2. Polls Instagram every 10 minutes without errors
3. RSS feed validates against RSS 2.0 specification
4. Images display correctly in popular RSS readers (Feedly, NetNewsWire, etc.)
5. Videos play correctly in RSS readers that support HTML5 video
6. Service runs continuously for 30+ days without intervention
7. Container restarts without data loss

### Quality Metrics
1. Zero unhandled exceptions in production
2. All Instagram API calls logged
3. 99%+ uptime in private cluster
4. RSS feed generation < 1 second response time

## Constraints & Assumptions

### Constraints
- Single Instagram account login (monitors all accounts that user follows)
- Private deployment only (no external exposure)
- Dependent on unofficial Instagram API (instagrapi)
- Subject to Instagram rate limiting (unknown limits)
- Read-only access (no posting or interaction)

### Assumptions
- Instagram credentials remain valid
- Instagram doesn't block/ban the account
- Persistent volume storage available in k8s cluster
- 10-minute polling interval acceptable to Instagram
- Single container instance (no horizontal scaling needed)
- Personal use exempts from strict ToS compliance

## Dependencies

### External Services
- Instagram (via instagrapi unofficial API)

### Technology Stack
- Python 3.11+
- instagrapi library
- SQLite3
- Flask or FastAPI (web framework)
- Docker/Podman
- Kubernetes

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Instagram blocks account | High | Medium | Good logging to detect; reduce polling frequency if needed |
| Instagram API changes break instagrapi | High | Medium | Monitor instagrapi updates; pin versions |
| Rate limiting | Medium | Low | Implement backoff strategy; configurable polling interval |
| Storage fills up | Low | Low | Monitor volume usage; implement cleanup for very old media if needed |
| Container crashes lose data | Medium | Low | Persistent volume for SQLite + media cache |

## Future Considerations

- Stories archival (from followed accounts)
- Web UI for browsing archive
- Export functionality (JSON, HTML)
- Search/filtering of archived content by author or keyword
- Instagram Reels support
- Filter RSS feed by specific followed accounts
- Direct message archival (if possible)
