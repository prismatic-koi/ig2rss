# Phase 1: Smart Post Fetching - Implementation Plan

## Executive Summary

Replace timeline feed polling (with ads/suggestions) with intelligent profile-based fetching:
- ✅ Fetch posts directly from followed accounts (ad-free, chronological)
- ✅ Hybrid approach: cold start with intelligent defaults + refinement over 24 hours
- ✅ Adaptive polling frequency based on account activity
- ✅ Efficient new-post detection (1-3 API calls per account)
- ✅ First sync on startup (automatic initialization)
- ✅ Default `MAX_ACCOUNTS_TO_FETCH=10` for safe testing
- ✅ INFO-level logging for each account checked
- ✅ Seamless migration (reuses existing database)
- ✅ Priority override support via config

**Estimated Implementation Time**: 18-25 hours

---

## Problem Statement

Current timeline feed polling issues:
- ❌ Scrolling through 20 pages to find 3 real posts
- ❌ Most items are ads or suggestions
- ❌ Algorithmic sorting (not chronological)
- ❌ Inefficient (many API calls for little content)

With ~80 followed accounts where most never post:
- Need efficient checking (don't fetch 20 posts from dormant accounts)
- Need smart prioritization (check active accounts more often)
- Need to respect account activity patterns

---

## Solution Architecture

### Core Concept: Three-Tier Polling

**Priority Levels** (based on last post date):
- **High**: Posted ≤7 days ago → Poll every cycle (20 min)
- **Normal**: Posted ≤30 days ago → Poll every cycle (20 min)
- **Low**: Posted ≤180 days ago → Poll every 3rd cycle (60 min)
- **Dormant**: Posted >180 days ago or never → Poll every 12th cycle (4 hours)

**Efficient New-Post Detection**:
1. Get `user_info` (media_count) - 1 API call
2. Fetch latest post only - 1 API call
3. Compare with last known post ID
4. If new, fetch 20 recent posts - 1 API call

**For 80 accounts**:
- 10 active accounts: 3 calls × 10 = 30 calls
- 70 dormant accounts: 2 calls × 70 = 140 calls
- **Total: ~170 calls** (vs 240+ with naive approach)

---

## Database Schema Changes

### New Tables (Additive Only)

```sql
-- Following accounts cache (replaces fetching list every cycle)
CREATE TABLE following_accounts (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    full_name TEXT,
    is_private BOOLEAN DEFAULT 0,
    last_checked TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_following_username ON following_accounts(username);
CREATE INDEX idx_following_last_checked ON following_accounts(last_checked);

-- Account activity tracking for smart polling
CREATE TABLE account_activity (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    
    -- Activity metrics
    media_count INTEGER DEFAULT 0,              -- Total posts (from user_info)
    last_post_id TEXT,                          -- ID of most recent post we've seen
    last_post_date TIMESTAMP,                   -- Date of most recent post
    last_checked TIMESTAMP NOT NULL,            -- When we last checked this account
    
    -- Polling strategy
    poll_priority TEXT DEFAULT 'normal',        -- 'high', 'normal', 'low', 'dormant'
    consecutive_no_new_posts INTEGER DEFAULT 0, -- Times checked with no new posts
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES following_accounts(user_id)
);

CREATE INDEX idx_activity_last_checked ON account_activity(last_checked);
CREATE INDEX idx_activity_priority ON account_activity(poll_priority);
CREATE INDEX idx_activity_last_post_date ON account_activity(last_post_date DESC);

-- Sync cycle tracking (persists across restarts)
CREATE TABLE sync_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Migration Strategy**:
- Existing `posts` and `media` tables are **100% reusable**
- No data migration needed
- Safe to roll back to timeline mode
- Post IDs are identical (profile vs timeline)

---

## Configuration

### New Environment Variables

```bash
#######################
# Polling Configuration
#######################
POLL_INTERVAL=1200                      # 20 minutes (changed from 600)

#######################
# Smart Polling
#######################
SMART_POLLING_ENABLED=true              # Enable adaptive polling
FETCH_STRATEGY=profile                  # 'profile' or 'timeline' (legacy)

# Account Activity Thresholds (days since last post)
PRIORITY_HIGH_DAYS=7                    # ≤7 days → high priority
PRIORITY_NORMAL_DAYS=30                 # ≤30 days → normal priority
PRIORITY_LOW_DAYS=180                   # ≤180 days → low priority

# Polling Frequencies (how often to check each priority)
POLL_HIGH_EVERY_N_CYCLES=1              # Every cycle (20 min)
POLL_NORMAL_EVERY_N_CYCLES=1            # Every cycle (20 min)
POLL_LOW_EVERY_N_CYCLES=3               # Every 3rd cycle (60 min)
POLL_DORMANT_EVERY_N_CYCLES=12          # Every 12th cycle (4 hours)

# Content Fetching
POSTS_PER_USER=20                       # Max posts when new content detected
MAX_ACCOUNTS_TO_FETCH=10                # Testing limit (0=unlimited)

# Following List Cache
FOLLOWING_CACHE_HOURS=24                # Refresh following list every N hours

# Priority Overrides (comma-separated usernames)
PRIORITY_OVERRIDE_ACCOUNTS=             # Force accounts to HIGH priority
                                        # Example: user1,user2
```

---

## Implementation Phases

### Phase 1A: Database & Storage (~2-3 hours)

**Files**:
- `src/migrations/001_add_smart_polling.py` (new)
- `src/storage.py` (modified)

**Tasks**:
- [ ] Create migration script
- [ ] Update `StorageManager._init_database()` with new tables
- [ ] Implement following accounts methods:
  - [ ] `save_following_accounts(accounts)`
  - [ ] `get_following_accounts()`
  - [ ] `get_following_cache_age()`
- [ ] Implement account activity methods:
  - [ ] `save_account_activity(user_id, **kwargs)`
  - [ ] `update_account_activity(user_id, **kwargs)`
  - [ ] `get_account_activity(user_id)`
  - [ ] `get_all_account_activity()`
  - [ ] `get_accounts_by_priority(priority)`
  - [ ] `get_priority_distribution()` (for stats)
- [ ] Implement sync metadata methods:
  - [ ] `save_sync_metadata(key, value)`
  - [ ] `get_sync_metadata(key, default=None)`
- [ ] Write unit tests for storage methods

**Success Criteria**:
- All new tables created successfully
- Methods tested with mock data
- No impact on existing `posts`/`media` tables

---

### Phase 1B: Following Manager (~2-3 hours)

**Files**:
- `src/following_manager.py` (new)

**Tasks**:
- [ ] Create `FollowedAccount` dataclass
- [ ] Implement `FollowingManager` class:
  - [ ] `__init__(storage, instagram_client)`
  - [ ] `get_following_list(refresh=False)` - Get cached or fetch from API
  - [ ] `refresh_following_list()` - Force refresh from Instagram
  - [ ] `_is_cache_fresh()` - Check if cache is within FOLLOWING_CACHE_HOURS
- [ ] Handle API errors gracefully (use stale cache if refresh fails)
- [ ] Add logging for cache hits/misses
- [ ] Write unit tests

**Success Criteria**:
- Following list cached for 24 hours by default
- Graceful fallback to stale cache on API errors
- Unit tests pass

---

### Phase 1C: Instagram Client Enhancements (~3-4 hours)

**Files**:
- `src/instagram_client.py` (modified)

**Tasks**:
- [ ] Add `check_account_for_new_posts()` method:
  - [ ] Step 1: Get `user_info(user_id)` for media_count
  - [ ] Step 2: If media_count > 0, fetch latest post (amount=1)
  - [ ] Step 3: Compare latest_post.pk with last_known_post_id
  - [ ] Step 4: If new, fetch recent posts (amount=20)
  - [ ] Return: `(has_new_posts, posts_list, metadata_dict)`
- [ ] Add deprecation warning to `get_timeline_feed()`
- [ ] Test with real Instagram account (10 accounts)
- [ ] Verify rate limiting behavior
- [ ] Write unit tests with mocked API

**Method Signature**:
```python
def check_account_for_new_posts(
    self, 
    user_id: str, 
    username: str,
    last_known_post_id: Optional[str] = None
) -> Tuple[bool, List[InstagramPost], Dict[str, Any]]:
    """Efficiently check if account has new posts.
    
    Returns:
        (has_new_posts, new_posts_list, account_metadata)
    """
```

**Success Criteria**:
- Accounts with no posts: 1 API call → Skip
- Accounts with no NEW posts: 2 API calls → Skip
- Accounts with new posts: 3 API calls → Fetch
- Unit tests pass

---

### Phase 1D: Account Polling Manager (~3-4 hours)

**Files**:
- `src/account_polling_manager.py` (new)

**Tasks**:
- [ ] Implement `AccountPollingManager` class:
  - [ ] `__init__(storage, client, config)`
  - [ ] `_load_cycle_number()` - Load from database
  - [ ] `increment_cycle()` - Increment and persist
  - [ ] `initialize_activity_profiles(accounts)` - Cold start logic
  - [ ] `get_accounts_to_poll_this_cycle()` - Priority-based filtering
  - [ ] `update_account_priority(user_id, has_new_posts, metadata)` - Hybrid refinement
  - [ ] `_calculate_initial_priority(last_post_date)` - Based on post age
  - [ ] `_refine_priority(account, days_observed)` - After 24h observation
- [ ] Implement priority override logic (PRIORITY_OVERRIDE_ACCOUNTS)
- [ ] Add comprehensive logging
- [ ] Write unit tests

**Priority Logic**:
```python
def _calculate_initial_priority(last_post_date: Optional[datetime]) -> str:
    """Conservative initial priority based on last post date."""
    if last_post_date is None:
        return 'dormant'
    
    days_since_post = (datetime.now() - last_post_date).days
    
    if days_since_post <= 30:
        return 'normal'  # Conservative: recent posters start as normal
    elif days_since_post <= 180:
        return 'low'
    else:
        return 'dormant'
```

**Success Criteria**:
- Cold start: Fetches 1 post from each account
- Cycle-based polling: Different accounts each cycle
- Priority refinement: Upgrades active accounts after 24h
- Unit tests pass

---

### Phase 1E: Configuration & Integration (~2 hours)

**Files**:
- `src/config.py` (modified)
- `.env.example` (modified)

**Tasks**:
- [ ] Add all new config options to `Config` class
- [ ] Add validation for new options
- [ ] Update `.env.example` with comprehensive comments
- [ ] Parse `PRIORITY_OVERRIDE_ACCOUNTS` (comma-separated)
- [ ] Test config parsing
- [ ] Write unit tests for config validation

**Success Criteria**:
- All new config options available
- Validation catches invalid values
- `.env.example` documented clearly

---

### Phase 1F: Sync Logic Rewrite (~2-3 hours)

**Files**:
- `src/api.py` (modified)

**Tasks**:
- [ ] Rewrite `sync_instagram()` function:
  - [ ] Add first-sync detection (`initialized` metadata flag)
  - [ ] Implement initialization flow (on startup)
  - [ ] Integrate `FollowingManager`
  - [ ] Integrate `AccountPollingManager`
  - [ ] Implement smart polling loop
  - [ ] Apply `MAX_ACCOUNTS_TO_FETCH` limit
  - [ ] Add INFO-level logging per account
  - [ ] Add summary statistics
- [ ] Implement `_legacy_timeline_sync()` as fallback
- [ ] Add feature flag checks (SMART_POLLING_ENABLED, FETCH_STRATEGY)
- [ ] Handle rate limiting with delays

**Expected First Sync Output**:
```
======================================================================
🚀 FIRST SYNC DETECTED - Initializing activity profiles...
======================================================================
📋 Following 80 accounts
⚠️  Testing mode: Limiting to 10 accounts
🔍 Fetching 1 post from each account to determine activity levels...
[1/10] @account1 - Last post: 2 days ago → HIGH priority
[2/10] @account2 - Last post: 3 years ago → DORMANT priority
...
✅ Activity profiles initialized:
   📈 High priority: 3 accounts
   📊 Normal priority: 2 accounts
   📉 Low priority: 1 accounts
   💤 Dormant: 4 accounts
======================================================================
```

**Success Criteria**:
- First sync initializes activity profiles
- Subsequent syncs use adaptive polling
- Legacy fallback works
- Comprehensive logging

---

### Phase 1G: Testing & Validation (~3-4 hours)

**Test Scenarios**:

1. **First Sync (10 Accounts)**
   ```bash
   MAX_ACCOUNTS_TO_FETCH=10
   docker-compose up -d
   docker logs -f ig2rss
   ```
   - [ ] First sync completes (~1-2 minutes)
   - [ ] Activity profiles created
   - [ ] Priority distribution logged
   - [ ] No errors

2. **Subsequent Syncs**
   - [ ] Cycle #2: Polls high+normal accounts only
   - [ ] Cycle #3: Polls high+normal+low accounts
   - [ ] Cycle #12: Polls ALL accounts (including dormant)

3. **Priority Refinement (24 Hours)**
   ```bash
   # After 72 cycles @ 20 min
   docker exec ig2rss sqlite3 /data/ig2rss.db \
     "SELECT poll_priority, COUNT(*) FROM account_activity GROUP BY poll_priority"
   ```
   - [ ] Active accounts upgraded to 'high'
   - [ ] Inactive accounts downgraded

4. **Priority Override**
   ```bash
   PRIORITY_OVERRIDE_ACCOUNTS=user1,user2
   ```
   - [ ] Override accounts polled every cycle

5. **Unlimited Accounts**
   ```bash
   MAX_ACCOUNTS_TO_FETCH=0
   ```
   - [ ] First sync processes all 80 accounts (~4 minutes)
   - [ ] Subsequent syncs adaptive (~2-3 minutes)

6. **Rollback to Timeline**
   ```bash
   FETCH_STRATEGY=timeline
   ```
   - [ ] Falls back to legacy timeline fetching
   - [ ] RSS feed still works

**Unit Tests**:
- [ ] `tests/test_following_manager.py`
- [ ] `tests/test_account_polling_manager.py`
- [ ] `tests/test_instagram_client_smart_fetch.py`
- [ ] `tests/test_storage_smart_polling.py`

**Integration Tests**:
- [ ] `tests/test_integration_smart_polling.py`

**Success Criteria**:
- All unit tests pass
- All integration tests pass
- Manual tests successful
- No rate limiting warnings

---

### Phase 1H: Documentation (~1-2 hours)

**Files**:
- `ARCHITECTURE.md` (modified)
- `PROJECT_REQUIREMENTS.md` (modified)
- `DEVELOPMENT.md` (modified)
- `README.md` (modified)
- `.env.example` (modified)
- `ROADMAP.md` (modified)

**Tasks**:
- [ ] Update `ARCHITECTURE.md` with smart polling section
- [ ] Update `PROJECT_REQUIREMENTS.md` scope
- [ ] Update `DEVELOPMENT.md` with development notes
- [ ] Update README with feature description
- [ ] Add troubleshooting section
- [ ] Update `ROADMAP.md` (move to completed)

**Success Criteria**:
- All documentation updated
- Clear instructions for users
- Troubleshooting guide included

---

## Rollout Strategy

### Day 1: Limited Testing
```bash
MAX_ACCOUNTS_TO_FETCH=10
SMART_POLLING_ENABLED=true
FETCH_STRATEGY=profile
```
- Monitor for issues
- Verify first sync works
- Check subsequent syncs

### Day 2: Expand to 30 Accounts
```bash
MAX_ACCOUNTS_TO_FETCH=30
```
- Monitor performance
- Watch for rate limiting
- Verify priority adjustments

### Day 3: Full Deployment
```bash
MAX_ACCOUNTS_TO_FETCH=0  # All 80 accounts
```
- Full production mode
- Monitor for 48 hours
- Verify all expected behavior

### Rollback Plan
```bash
FETCH_STRATEGY=timeline  # Quick rollback
# Or
SMART_POLLING_ENABLED=false  # Disable feature
```

---

## Success Criteria

### Immediate (After First Sync)
- ✅ First sync completes successfully
- ✅ Activity profiles created for all accounts
- ✅ Priority distribution looks reasonable
- ✅ No errors in logs
- ✅ RSS feed displays posts correctly

### Short-term (After 2-4 Hours)
- ✅ Multiple sync cycles complete
- ✅ Adaptive polling working (different accounts each cycle)
- ✅ No rate limiting warnings
- ✅ New posts detected and saved
- ✅ Average sync time ~2-3 minutes

### Long-term (After 24-48 Hours)
- ✅ Priority refinement working (high priority for active accounts)
- ✅ Dormant accounts polled less frequently (every 4 hours)
- ✅ API call efficiency improved (~60% reduction)
- ✅ Zero ads in RSS feed
- ✅ All posts from followed accounts captured

---

## Expected Performance

### For 80 Followed Accounts

**Assumptions**:
- 10 accounts post regularly (weekly)
- 20 accounts post occasionally (monthly)
- 50 accounts dormant (no posts in 6+ months)

**API Call Efficiency**:
- Naive: 80 accounts × 3 calls = 240 calls every 20 min
- Smart: ~80 calls every 20 min = **67% reduction!**

**Sync Time**:
- First sync: ~4 minutes (one-time learning)
- Typical sync: ~2 minutes (adaptive polling)
- Full sync (every 4 hours): ~4 minutes (all accounts)

**Average**: ~2.2 minutes per sync, ~80 API calls

---

## Phase 2 Preview: Stories Integration

Once Phase 1 is stable (after 1 week):

**Stories additions**:
- Add `is_stories_muted` to `following_accounts` table
- Add `stories` and `story_media` tables
- Add story fetching to sync loop (same account iteration)
- Update RSS generator for combined feed
- Stories polled same frequency as posts (lightweight check)

**Decision point**: After observing Phase 1 performance, determine:
- Should stories use same priority system?
- Or always check all accounts (stories are cheap)?
- Combined RSS feed vs separate feeds?

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| First sync takes 4 minutes | Medium | Document expected behavior, runs once only |
| Rate limiting during first sync | Medium | Add retry logic, spread over multiple cycles if needed |
| Priority logic too aggressive | Low | Tunable via config (PRIORITY_*_DAYS) |
| Following list API fails | Medium | Use stale cache, log warning |
| Cycle counter reset on restart | Low | Persist in database (not in-memory) |
| User follows >200 accounts | Low | MAX_ACCOUNTS_TO_FETCH safety limit |

---

## Notes

- Existing `posts` and `media` tables are fully reusable (no migration needed)
- Post IDs are identical whether fetched from timeline or profile
- Seamless transition: `post_exists()` prevents duplicates
- Safe rollback: Set `FETCH_STRATEGY=timeline`
- Phase 2 (Stories) deferred until Phase 1 stable

---

## Implementation Status

**Current Phase**: Implementation Complete - Ready for Testing
**Last Updated**: 2026-02-01

### Phase Progress
- [x] Phase 1A: Database & Storage
- [x] Phase 1B: Following Manager
- [x] Phase 1C: Instagram Client Enhancements
- [x] Phase 1D: Account Polling Manager
- [x] Phase 1E: Configuration & Integration
- [x] Phase 1F: Sync Logic Rewrite
- [x] Phase 1G: Testing & Validation (94 unit tests passing)
- [ ] Phase 1H: Documentation (in progress)

---

## Getting Started

1. Review this plan thoroughly
2. Start with Phase 1A (Database & Storage)
3. Test each phase before moving to next
4. Use `MAX_ACCOUNTS_TO_FETCH=10` for initial testing
5. Monitor logs closely for first sync
6. Scale up gradually (10 → 30 → 80 accounts)
7. Phase 2 (Stories) after 1 week of stable operation
