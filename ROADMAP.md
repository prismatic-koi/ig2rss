# Instagram to RSS - Implementation Roadmap

## Overview

This roadmap outlines the phased implementation approach for ig2rss, from MVP to stretch goals. Each phase includes specific milestones, deliverables, and success criteria.

## Phase 0: Project Setup (Week 1)

### Goals
- Establish development environment
- Set up project structure
- Configure tooling and dependencies

### Tasks
- [ ] Initialize Python project structure
- [ ] Create virtual environment and requirements.txt
- [ ] Set up Git repository and .gitignore
- [ ] Create Dockerfile (initial version)
- [ ] Set up logging configuration
- [ ] Create basic configuration management (config.py)
- [ ] Set up unit testing framework (pytest)

### Deliverables
- Project skeleton with proper structure
- Working local development environment
- Basic Docker container that runs
- Documentation: DEVELOPMENT.md

### Success Criteria
- `pip install -r requirements.txt` works
- Docker container builds successfully
- Tests run with `pytest`

---

## Phase 1: Instagram Integration (Week 2)

### Goals
- Authenticate with Instagram
- Fetch user feed posts
- Handle basic error cases

### Tasks
- [x] Implement InstagramClient class
- [x] Add instagrapi integration
- [x] Implement login/authentication
- [x] Implement get_timeline_feed() method
- [x] Add retry logic with exponential backoff
- [x] Handle rate limiting
- [x] Add comprehensive logging
- [x] Write unit tests for InstagramClient
- [ ] Test with real Instagram credentials (dev account)

### Deliverables
- Working InstagramClient module
- Ability to fetch posts from test account
- Error handling for common failures
- Unit tests with mocked Instagram API

### Success Criteria
- Successfully authenticate with test Instagram account
- Fetch at least 20 posts from feed
- Handle network errors gracefully
- 80%+ test coverage for instagram_client.py

### Testing Checklist
- [x] Valid credentials authenticate successfully
- [x] Invalid credentials fail gracefully
- [x] Network timeout handled with retry
- [x] Rate limiting triggers backoff
- [x] Feed fetch returns expected data structure

---

## Phase 2: Storage Layer (Week 3)

### Goals
- Implement SQLite database
- Store post metadata
- Set up media filesystem cache
- Handle media downloads

### Tasks
- [ ] Design database schema (posts, media tables)
- [ ] Implement StorageManager class
- [ ] Create database initialization/migration
- [ ] Implement save_post() method
- [ ] Implement save_media() method
- [ ] Implement get_recent_posts() query
- [ ] Implement post_exists() duplicate check
- [ ] Add media file download to InstagramClient
- [ ] Organize media filesystem structure
- [ ] Add database indexes for performance
- [ ] Write unit tests for StorageManager
- [ ] Test with sample posts and media

### Deliverables
- Working StorageManager module
- SQLite database with proper schema
- Media files organized in filesystem
- Ability to persist Instagram posts

### Success Criteria
- Posts stored in database without errors
- Media downloaded to correct filesystem paths
- Query for recent posts returns correct results
- Duplicate posts not re-inserted
- 80%+ test coverage for storage.py

### Testing Checklist
- [ ] Database schema created correctly
- [ ] Posts inserted and retrieved accurately
- [ ] Media metadata linked to posts (foreign keys work)
- [ ] Duplicate post detection works
- [ ] File paths resolved correctly
- [ ] Database survives container restart (persistent volume)

---

## Phase 3: RSS Feed Generation (Week 4)

### Goals
- Generate valid RSS 2.0 XML
- Embed media using HTML
- Support configurable feed limits

### Tasks
- [ ] Implement RSSGenerator class
- [ ] Build RSS channel structure
- [ ] Implement format_post_item() for single post
- [ ] Build HTML for embedded images
- [ ] Build HTML for embedded videos
- [ ] Handle carousel posts (multiple images)
- [ ] Escape HTML entities in captions
- [ ] Format timestamps as RFC 822
- [ ] Support limit and days parameters
- [ ] Validate RSS against RSS 2.0 spec
- [ ] Write unit tests for RSSGenerator
- [ ] Test RSS in actual RSS readers

### Deliverables
- Working RSSGenerator module
- Valid RSS 2.0 XML output
- Media embedded as HTML in descriptions

### Success Criteria
- RSS validates against RSS 2.0 spec
- Images display in RSS readers (Feedly, NetNewsWire)
- Videos play in RSS readers with HTML5 support
- Captions render correctly with special characters
- 80%+ test coverage for rss_generator.py

### Testing Checklist
- [ ] RSS XML validates (use online validator)
- [ ] Images display in Feedly
- [ ] Images display in NetNewsWire (or similar)
- [ ] Videos play in supported readers
- [ ] Special characters in captions handled (emojis, HTML entities)
- [ ] Carousels show all images
- [ ] Instagram permalinks work

---

## Phase 4: HTTP Server (Week 5)

### Goals
- Serve RSS feed via HTTP
- Serve media files via HTTP
- Implement health checks

### Tasks
- [ ] Choose web framework (Flask or FastAPI)
- [ ] Implement HTTP server module
- [ ] Create GET /feed.xml endpoint
- [ ] Add query parameter support (limit, days)
- [ ] Create GET /media/<post_id>/<filename> endpoint
- [ ] Validate and sanitize media file paths (prevent path traversal)
- [ ] Set appropriate content-type headers
- [ ] Implement GET /health endpoint
- [ ] Implement GET /ready endpoint
- [ ] Add request logging
- [ ] Handle 404s gracefully
- [ ] Write integration tests for endpoints
- [ ] Test with curl/httpie

### Deliverables
- Working HTTP server
- All endpoints functional
- Proper HTTP status codes and headers

### Success Criteria
- `/feed.xml` returns valid RSS XML
- `/media/<post_id>/<filename>` serves images/videos
- `/health` and `/ready` work for k8s probes
- All endpoints logged appropriately
- 80%+ test coverage for http_server.py

### Testing Checklist
- [ ] GET /feed.xml returns RSS with correct content-type
- [ ] Query params ?limit=10 and ?days=7 work
- [ ] Images served with correct content-type (image/jpeg, etc.)
- [ ] Videos served with correct content-type (video/mp4, etc.)
- [ ] 404 returned for non-existent media
- [ ] Path traversal attempts blocked (../../etc/passwd)
- [ ] Health checks return expected status codes

---

## Phase 5: Scheduler Integration (Week 6)

### Goals
- Implement periodic polling
- Orchestrate end-to-end flow
- Handle graceful shutdown

### Tasks
- [ ] Implement Scheduler class
- [ ] Integrate APScheduler or similar
- [ ] Create trigger_poll() orchestration method
- [ ] Wire together: Instagram → Storage → Log
- [ ] Implement graceful shutdown handling
- [ ] Add signal handlers (SIGTERM, SIGINT)
- [ ] Test poll cycle end-to-end
- [ ] Verify duplicate posts not re-fetched
- [ ] Add polling metrics to logs
- [ ] Test continuous operation (24+ hours)

### Deliverables
- Working scheduler with configurable interval
- End-to-end polling cycle functional
- Graceful shutdown on SIGTERM

### Success Criteria
- Polls execute every 10 minutes (configurable)
- New posts detected and stored
- Existing posts skipped (no duplicates)
- RSS feed updates with new posts
- Container shuts down gracefully on SIGTERM
- 80%+ test coverage for scheduler.py

### Testing Checklist
- [ ] Poll executes on schedule
- [ ] New Instagram posts appear in RSS within 10 minutes
- [ ] No duplicate posts created
- [ ] Logs show poll summary (X new posts, Y media files)
- [ ] Graceful shutdown works (SIGTERM)
- [ ] Container restart doesn't lose data

---

## Phase 6: Containerization & Deployment (Week 7)

### Goals
- Finalize Docker image
- Deploy to Kubernetes
- Configure persistent storage

### Tasks
- [ ] Optimize Dockerfile (multi-stage build)
- [ ] Set container to run as non-root user
- [ ] Add health check to Dockerfile
- [ ] Build and push to container registry
- [ ] Create k8s Deployment manifest
- [ ] Create k8s Service manifest
- [ ] Create k8s Secret for credentials
- [ ] Create PersistentVolumeClaim for data
- [ ] Configure volume mounts (/data)
- [ ] Set resource limits (CPU, memory)
- [ ] Configure liveness and readiness probes
- [ ] Deploy to k8s cluster
- [ ] Test pod restarts and data persistence
- [ ] Write deployment documentation

### Deliverables
- Production-ready Docker image
- Kubernetes manifests for deployment
- Deployed service running in k8s
- Documentation: DEPLOYMENT.md

### Success Criteria
- Container runs as non-root user
- Pod starts successfully in k8s
- Liveness and readiness probes working
- Persistent volume mounts correctly
- Credentials loaded from k8s secret
- RSS feed accessible within cluster
- Pod restarts don't lose data
- Service runs continuously for 7+ days

### Testing Checklist
- [ ] Image builds with `podman build`
- [ ] Container runs with `podman run`
- [ ] Pod deploys with `kubectl apply`
- [ ] Credentials from secret work
- [ ] Volume persistence works (delete pod, redeploy, data intact)
- [ ] RSS accessible at `http://ig2rss-service:8080/feed.xml`
- [ ] Media accessible from within cluster
- [ ] Logs visible with `kubectl logs`
- [ ] Restart policy works (pod crashes and recovers)

---

## Phase 7: Testing & Hardening (Week 8)

### Goals
- Comprehensive testing
- Bug fixes and improvements
- Documentation completion

### Tasks
- [ ] Write integration tests (full end-to-end)
- [ ] Load testing (RSS endpoint under load)
- [ ] Test various Instagram post types (photo, video, carousel)
- [ ] Test edge cases (empty feed, deleted posts, etc.)
- [ ] Test failure scenarios (Instagram down, network issues)
- [ ] Code review and refactoring
- [ ] Improve error messages
- [ ] Optimize performance bottlenecks
- [ ] Complete all documentation
- [ ] Create README with quick start guide
- [ ] Test RSS in multiple RSS readers

### Deliverables
- Comprehensive test suite
- Production-ready code
- Complete documentation suite
- README with usage instructions

### Success Criteria
- 80%+ overall test coverage
- All edge cases handled gracefully
- RSS works in 3+ different RSS readers
- Documentation complete and accurate
- No critical or high-priority bugs
- Performance acceptable (RSS < 1s, polls < 30s)

### Testing Checklist
- [ ] Integration tests pass
- [ ] RSS tested in Feedly
- [ ] RSS tested in NetNewsWire
- [ ] RSS tested in another reader (Inoreader, The Old Reader, etc.)
- [ ] Empty Instagram feed handled
- [ ] Very old posts (6+ months) render correctly
- [ ] Large captions (2000+ chars) work
- [ ] Instagram unavailable handled gracefully
- [ ] Network disconnect during poll handled
- [ ] Container OOM scenario tested

---

## Phase 8: MVP Launch (End of Week 8)

### Goals
- Deploy to production (private k8s)
- Monitor for issues
- Validate success criteria

### Tasks
- [ ] Deploy final version to k8s
- [ ] Configure real Instagram credentials
- [ ] Monitor logs for 48 hours
- [ ] Verify RSS feed in personal RSS reader
- [ ] Document any issues or improvements
- [ ] Create maintenance runbook

### Deliverables
- Live production service
- Working RSS feed in personal RSS reader
- Maintenance runbook

### Success Criteria (MVP)
- Service runs for 7+ days without issues
- New posts appear in RSS within 10 minutes
- Images and videos display correctly
- No data loss on restarts
- All MVP requirements met (see PROJECT_REQUIREMENTS.md)

### Launch Checklist
- [ ] Real credentials configured
- [ ] Monitoring in place
- [ ] RSS feed subscribed in reader
- [ ] Test post from Instagram appears in RSS
- [ ] Service stable for 48 hours minimum

---

## Phase 9: Stretch Goal - Instagram Stories (Future)

### Goals
- Add support for Instagram Stories
- Archive stories before they expire
- Separate RSS feed for stories

### Tasks
- [ ] Research instagrapi stories API
- [ ] Design stories database schema
- [ ] Implement stories fetching
- [ ] Implement stories storage
- [ ] Generate separate RSS feed for stories
- [ ] Handle 24-hour expiration
- [ ] Create GET /stories.xml endpoint
- [ ] Test stories in RSS readers
- [ ] Document stories feature

### Deliverables
- Stories support in ig2rss
- Separate stories RSS feed
- Stories archived locally even after expiration

### Success Criteria
- Stories fetched before they expire (within 24h)
- Stories archived locally
- Stories RSS feed functional
- Stories media (images/videos) work in RSS

### Implementation Notes
- Stories expire after 24 hours on Instagram
- Need to poll more frequently for stories (every 4-6 hours?)
- Stories often have different media formats
- May need separate table structure
- Consider combined feed option (posts + stories)

---

## Long-Term Enhancements (Post-MVP)

### Potential Future Features

**Web UI**
- Browse archived posts via web interface
- Search and filter functionality
- Configuration management UI
- Export functionality (JSON, HTML archive)

**Advanced RSS Features**
- Categories/tags from Instagram hashtags
- Comments as RSS extensions
- Likes/engagement metrics in feed

**Performance Optimizations**
- RSS feed caching
- Async media downloads
- Image resizing/optimization
- Video transcoding to web-friendly formats

**Monitoring & Alerting**
- Prometheus metrics export
- Grafana dashboards
- Alert on poll failures
- Alert on storage usage

**Reels Support**
- Fetch Instagram Reels
- Video handling optimization
- Separate or combined feed

**Backup & Export**
- Automated backup script
- Export to standard formats (JSON, Archive)
- Migration tool for moving data

---

## Risk Management

### Technical Risks

| Risk | Mitigation | Status |
|------|------------|--------|
| Instagram changes API | Monitor instagrapi updates, pin versions | Ongoing |
| Account gets banned | Use personal account carefully, respect rate limits | Ongoing |
| instagrapi breaks | Have fallback plan, consider alternative libraries | Planned |
| Storage fills up | Monitor volume usage, implement cleanup if needed | Planned |

### Schedule Risks

| Risk | Mitigation | Status |
|------|------------|--------|
| Development takes longer | MVP scope is flexible, prioritize core features | Ongoing |
| Testing reveals issues | Buffer time in Phase 7 for fixes | Planned |
| Deployment complexity | Start deployment testing early (Phase 6) | Planned |

---

## Success Metrics

### MVP Success
- ✅ Service runs continuously for 30+ days
- ✅ RSS feed updates within 10 minutes of new posts
- ✅ Images display correctly in RSS readers
- ✅ Videos play in RSS readers
- ✅ Zero data loss on container restarts
- ✅ All posts archived indefinitely

### Quality Metrics
- ✅ 80%+ test coverage
- ✅ Zero unhandled exceptions in production
- ✅ RSS feed generation < 1 second
- ✅ Poll cycle < 30 seconds
- ✅ Comprehensive logging for all operations

### User Satisfaction
- ✅ RSS feed works in primary RSS reader (Feedly/NetNewsWire/etc.)
- ✅ Media quality acceptable
- ✅ Post captions formatted correctly
- ✅ Service requires no manual intervention

---

## Timeline Summary

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 0: Project Setup | 1 week | Week 1 |
| Phase 1: Instagram Integration | 1 week | Week 2 |
| Phase 2: Storage Layer | 1 week | Week 3 |
| Phase 3: RSS Generation | 1 week | Week 4 |
| Phase 4: HTTP Server | 1 week | Week 5 |
| Phase 5: Scheduler | 1 week | Week 6 |
| Phase 6: Deployment | 1 week | Week 7 |
| Phase 7: Testing & Hardening | 1 week | Week 8 |
| **Phase 8: MVP Launch** | **End Week 8** | **~2 months** |
| Phase 9: Stories (Stretch) | 1-2 weeks | Week 9-10 |

**Estimated MVP Timeline**: 8 weeks  
**With Stretch Goals**: 10 weeks

---

## Next Steps

After completing this roadmap planning:

1. **Review and approve** this roadmap
2. **Begin Phase 0**: Project setup
3. **Set up development environment** (see DEVELOPMENT.md)
4. **Create initial project structure**
5. **Start implementing Phase 1**: Instagram integration

Ready to start building! 🚀
