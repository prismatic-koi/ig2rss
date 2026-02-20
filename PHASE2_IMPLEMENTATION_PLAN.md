# PHASE2: Instagram Stories Support - Implementation Plan

## Overview

Add Instagram Stories support to ig2rss with the following characteristics:
- **Unified feed**: Stories and posts in the same `/feed.rss` endpoint
- **Polling frequency**: Same as posts (every cycle)
- **Smart polling**: Applied to stories BUT with separate tracking (story activity ≠ post activity)
- **Presentation**: `[STORY]` prefix in RSS feed titles
- **Archival**: Stories stored permanently even after 24h Instagram expiration
- **Mute detection**: Automatically skip accounts with muted stories
- **Text preservation**: Extract and display text from polls, links, and stickers

---

## Requirements Summary

1. ✅ Unified feed (stories + posts in `/feed.rss`)
2. ✅ Poll every cycle (same frequency as posts)
3. ✅ Smart polling with **independent** story activity tracking
4. ✅ `[STORY]` prefix in RSS titles
5. ✅ Skip accounts with muted stories (`is_muting_reel = true`)
6. ✅ Preserve text content from stories where possible (polls, link text, stickers)
7. ✅ Each story is a separate RSS item
8. ✅ Ignore story replies/reactions

---

## Database Schema Changes

### New Table: `stories`

```sql
CREATE TABLE stories (
    id TEXT PRIMARY KEY,                -- Instagram story media ID
    user_id TEXT NOT NULL,              -- Story author's user ID
    username TEXT NOT NULL,             -- Story author's username
    full_name TEXT,                     -- Story author's full name
    taken_at TIMESTAMP NOT NULL,        -- When story was posted
    expires_at TIMESTAMP NOT NULL,      -- When story expires on Instagram (24h)
    media_url TEXT NOT NULL,            -- Story media URL
    media_type TEXT NOT NULL,           -- 'image' or 'video'
    local_path TEXT,                    -- Local cached file path
    file_size INTEGER,                  -- File size in bytes
    downloaded_at TIMESTAMP,            -- When we downloaded it
    
    -- Text content fields (from stickers/polls)
    poll_question TEXT,                 -- Poll question text
    poll_options TEXT,                  -- JSON array of poll options
    link_text TEXT,                     -- "Swipe up" link text
    sticker_text TEXT,                  -- Text from other stickers (JSON)
    
    permalink TEXT,                     -- Instagram story URL
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_stories_username ON stories(username);
CREATE INDEX idx_stories_taken_at ON stories(taken_at DESC);
CREATE INDEX idx_stories_expires_at ON stories(expires_at);
```

### New Table: `account_story_activity`

This is separate from `account_activity` to track story-specific patterns:

```sql
CREATE TABLE account_story_activity (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    
    -- Story mute status (CRITICAL)
    is_muting_stories BOOLEAN DEFAULT 0,    -- If true, SKIP this account for stories
    
    last_story_id TEXT,                     -- ID of last story we fetched
    last_story_date TIMESTAMP,              -- When last story was posted
    last_checked TIMESTAMP NOT NULL,        -- Last time we checked for stories
    story_poll_priority TEXT DEFAULT 'normal', -- 'high', 'normal', 'low', 'dormant'
    consecutive_no_new_stories INTEGER DEFAULT 0, -- Count of consecutive empty checks
    stories_fetched_count INTEGER DEFAULT 0,    -- Total stories fetched from this account
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES following_accounts(user_id)
);

CREATE INDEX idx_story_activity_muted ON account_story_activity(is_muting_stories);
CREATE INDEX idx_story_activity_last_checked ON account_story_activity(last_checked);
CREATE INDEX idx_story_activity_priority ON account_story_activity(story_poll_priority);
CREATE INDEX idx_story_activity_last_story_date ON account_story_activity(last_story_date DESC);
```

---

## Implementation Plan (Test-Driven Development)

### **Step 1: Database Schema (Storage Layer)**

#### 1.1 Write Tests First
**File**: `tests/test_storage_stories.py`

```python
"""Tests for story storage functionality."""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from src.storage import StorageManager
from src.instagram_client import InstagramStory


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def storage(temp_db):
    """Create a StorageManager with temporary database."""
    return StorageManager(db_path=temp_db, media_dir=tempfile.mkdtemp())


class TestStorageStories:
    """Tests for story storage."""
    
    def test_stories_table_created(self, storage):
        """Test stories table exists with correct schema."""
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='stories'
            """)
            assert cursor.fetchone() is not None
    
    def test_account_story_activity_table_created(self, storage):
        """Test account_story_activity table exists with correct schema."""
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='account_story_activity'
            """)
            assert cursor.fetchone() is not None
    
    def test_story_exists_false(self, storage):
        """Test checking for non-existent story."""
        assert storage.story_exists("nonexistent_id") is False
    
    def test_save_story(self, storage):
        """Test saving a story to database."""
        story = InstagramStory(
            id="story123",
            user_id="user456",
            username="testuser",
            full_name="Test User",
            taken_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=24),
            media_url="https://example.com/story.jpg",
            media_type="image",
            permalink="https://instagram.com/stories/testuser/story123/",
            poll_question="What's your favorite?",
            poll_options=["Option A", "Option B"],
            link_text="Swipe up!",
            sticker_text={"type": "gif", "data": "test"}
        )
        
        result = storage.save_story(story)
        assert result is True
        assert storage.story_exists("story123") is True
    
    def test_get_story_by_id(self, storage):
        """Test fetching single story by ID."""
        story = InstagramStory(
            id="story789",
            user_id="user456",
            username="testuser",
            full_name="Test User",
            taken_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=24),
            media_url="https://example.com/story.jpg",
            media_type="image",
            permalink="https://instagram.com/stories/testuser/story789/"
        )
        
        storage.save_story(story)
        
        retrieved = storage.get_story_by_id("story789")
        assert retrieved is not None
        assert retrieved['id'] == "story789"
        assert retrieved['username'] == "testuser"
    
    def test_get_recent_stories(self, storage):
        """Test querying recent stories."""
        # Save multiple stories
        for i in range(5):
            story = InstagramStory(
                id=f"story{i}",
                user_id="user456",
                username="testuser",
                full_name="Test User",
                taken_at=datetime.now() - timedelta(hours=i),
                expires_at=datetime.now() + timedelta(hours=24-i),
                media_url=f"https://example.com/story{i}.jpg",
                media_type="image",
                permalink=f"https://instagram.com/stories/testuser/story{i}/"
            )
            storage.save_story(story)
        
        stories = storage.get_recent_stories(limit=3)
        assert len(stories) == 3
        # Most recent first
        assert stories[0]['id'] == "story0"
    
    def test_save_story_activity_with_mute_status(self, storage):
        """Test saving story activity with is_muting_stories flag."""
        # Need following_accounts entry first for FK constraint
        storage.save_following_accounts([{
            'user_id': 'user123',
            'username': 'testuser',
            'full_name': 'Test User',
            'is_private': False
        }])
        
        result = storage.save_account_story_activity(
            user_id="user123",
            username="testuser",
            is_muting_stories=True
        )
        
        assert result is True
        
        activity = storage.get_account_story_activity("user123")
        assert activity is not None
        assert activity['is_muting_stories'] == 1  # SQLite stores as int
    
    def test_get_unmuted_accounts_for_stories(self, storage):
        """Test querying only accounts that haven't muted stories."""
        # Setup: Add following accounts
        storage.save_following_accounts([
            {'user_id': 'user1', 'username': 'user1', 'full_name': 'User 1', 'is_private': False},
            {'user_id': 'user2', 'username': 'user2', 'full_name': 'User 2', 'is_private': False},
            {'user_id': 'user3', 'username': 'user3', 'full_name': 'User 3', 'is_private': False},
        ])
        
        # Add story activities with different mute statuses
        storage.save_account_story_activity('user1', 'user1', is_muting_stories=False)
        storage.save_account_story_activity('user2', 'user2', is_muting_stories=True)
        storage.save_account_story_activity('user3', 'user3', is_muting_stories=False)
        
        unmuted = storage.get_unmuted_accounts_for_stories()
        
        assert len(unmuted) == 2
        usernames = [a['username'] for a in unmuted]
        assert 'user1' in usernames
        assert 'user3' in usernames
        assert 'user2' not in usernames
    
    def test_update_story_activity(self, storage):
        """Test updating story activity fields."""
        # Setup
        storage.save_following_accounts([{
            'user_id': 'user123',
            'username': 'testuser',
            'full_name': 'Test User',
            'is_private': False
        }])
        
        storage.save_account_story_activity('user123', 'testuser')
        
        # Update
        result = storage.update_account_story_activity(
            user_id='user123',
            last_story_id='story999',
            consecutive_no_new_stories=5
        )
        
        assert result is True
        
        activity = storage.get_account_story_activity('user123')
        assert activity['last_story_id'] == 'story999'
        assert activity['consecutive_no_new_stories'] == 5
```

#### 1.2 Implement Storage Methods
**File**: `src/storage.py`

Add these methods to `StorageManager`:

```python
# In _init_database() method, add:

# Stories table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS stories (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        full_name TEXT,
        taken_at TIMESTAMP NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        media_url TEXT NOT NULL,
        media_type TEXT NOT NULL,
        local_path TEXT,
        file_size INTEGER,
        downloaded_at TIMESTAMP,
        poll_question TEXT,
        poll_options TEXT,
        link_text TEXT,
        sticker_text TEXT,
        permalink TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Account story activity table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS account_story_activity (
        user_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        is_muting_stories BOOLEAN DEFAULT 0,
        last_story_id TEXT,
        last_story_date TIMESTAMP,
        last_checked TIMESTAMP NOT NULL,
        story_poll_priority TEXT DEFAULT 'normal',
        consecutive_no_new_stories INTEGER DEFAULT 0,
        stories_fetched_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES following_accounts(user_id)
    )
""")

# Indexes
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_stories_username 
    ON stories(username)
""")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_stories_taken_at 
    ON stories(taken_at DESC)
""")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_story_activity_muted 
    ON account_story_activity(is_muting_stories)
""")

# Story-related methods:

def story_exists(self, story_id: str) -> bool:
    """Check if a story already exists in the database."""
    with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM stories WHERE id = ?", (story_id,))
        return cursor.fetchone() is not None

def save_story(self, story) -> bool:
    """Save a story to the database."""
    import json
    
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO stories
                (id, user_id, username, full_name, taken_at, expires_at,
                 media_url, media_type, permalink, poll_question, poll_options,
                 link_text, sticker_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                story.id,
                story.user_id,
                story.username,
                story.full_name,
                story.taken_at,
                story.expires_at,
                story.media_url,
                story.media_type,
                story.permalink,
                story.poll_question,
                json.dumps(story.poll_options) if story.poll_options else None,
                story.link_text,
                json.dumps(story.sticker_text) if story.sticker_text else None
            ))
            
            logger.info(f"Saved story {story.id} from @{story.username}")
            return True
            
    except Exception as e:
        logger.error(f"Failed to save story {story.id}: {e}")
        return False

def get_story_by_id(self, story_id: str) -> Optional[Dict[str, Any]]:
    """Get a single story by ID."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stories WHERE id = ?", (story_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get story {story_id}: {e}")
        return None

def get_recent_stories(self, limit: int = 50, days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Query recent stories from the database."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM stories WHERE 1=1"
            params = []
            
            if days is not None:
                cutoff_date = datetime.now() - timedelta(days=days)
                query += " AND taken_at >= ?"
                params.append(cutoff_date)
            
            query += " ORDER BY taken_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            stories = [dict(row) for row in cursor.fetchall()]
            
            logger.info(f"Retrieved {len(stories)} stories (limit={limit}, days={days})")
            return stories
            
    except Exception as e:
        logger.error(f"Failed to query recent stories: {e}")
        return []

def update_story_media(self, story_id: str, local_path: str, file_size: int) -> bool:
    """Update story with local file information after download."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE stories
                SET local_path = ?, file_size = ?, downloaded_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (local_path, file_size, story_id))
            
            if cursor.rowcount == 0:
                logger.warning(f"No story record found to update for {story_id}")
                return False
            
            logger.debug(f"Updated story media for {story_id}")
            return True
    except Exception as e:
        logger.error(f"Failed to update story media for {story_id}: {e}")
        return False

def save_account_story_activity(self, user_id: str, username: str, **kwargs) -> bool:
    """Save or update account story activity data."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now()
            cursor.execute("""
                INSERT OR REPLACE INTO account_story_activity
                (user_id, username, is_muting_stories, last_story_id, 
                 last_story_date, last_checked, story_poll_priority,
                 consecutive_no_new_stories, stories_fetched_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                username,
                kwargs.get('is_muting_stories', False),
                kwargs.get('last_story_id'),
                kwargs.get('last_story_date'),
                kwargs.get('last_checked', now),
                kwargs.get('story_poll_priority', 'normal'),
                kwargs.get('consecutive_no_new_stories', 0),
                kwargs.get('stories_fetched_count', 0),
                now
            ))
            
            logger.debug(f"Saved story activity for {username}")
            return True
            
    except Exception as e:
        logger.error(f"Failed to save story activity for {username}: {e}")
        return False

def update_account_story_activity(self, user_id: str, **kwargs) -> bool:
    """Update specific fields of an account story activity record."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Build dynamic UPDATE query
            update_fields = []
            values = []
            for key, value in kwargs.items():
                if key in ['is_muting_stories', 'last_story_id', 'last_story_date',
                          'last_checked', 'story_poll_priority', 
                          'consecutive_no_new_stories', 'stories_fetched_count']:
                    update_fields.append(f"{key} = ?")
                    values.append(value)
            
            if not update_fields:
                logger.warning(f"No valid fields to update for user {user_id}")
                return False
            
            update_fields.append("updated_at = ?")
            values.append(datetime.now())
            values.append(user_id)
            
            query = f"UPDATE account_story_activity SET {', '.join(update_fields)} WHERE user_id = ?"
            cursor.execute(query, values)
            
            if cursor.rowcount == 0:
                logger.warning(f"No story activity record found to update for user {user_id}")
                return False
            
            logger.debug(f"Updated story activity for user {user_id}")
            return True
            
    except Exception as e:
        logger.error(f"Failed to update story activity for user {user_id}: {e}")
        return False

def get_account_story_activity(self, user_id: str) -> Optional[Dict[str, Any]]:
    """Get account story activity data for a specific user."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM account_story_activity WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get story activity for user {user_id}: {e}")
        return None

def get_all_account_story_activity(self) -> List[Dict[str, Any]]:
    """Get all account story activity records."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM account_story_activity ORDER BY last_checked DESC")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get all story activity: {e}")
        return []

def get_unmuted_accounts_for_stories(self) -> List[Dict[str, Any]]:
    """Get all accounts where is_muting_stories = False."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM account_story_activity
                WHERE is_muting_stories = 0
                ORDER BY last_checked ASC
            """)
            accounts = [dict(row) for row in cursor.fetchall()]
            logger.debug(f"Retrieved {len(accounts)} unmuted accounts for stories")
            return accounts
    except Exception as e:
        logger.error(f"Failed to get unmuted accounts for stories: {e}")
        return []

def get_accounts_by_story_priority(self, priority: str) -> List[Dict[str, Any]]:
    """Get all accounts with a specific story priority level."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM account_story_activity
                WHERE story_poll_priority = ?
                ORDER BY last_checked ASC
            """, (priority,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get accounts by story priority {priority}: {e}")
        return []

def get_story_priority_distribution(self) -> Dict[str, int]:
    """Get count of accounts by story priority level."""
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT story_poll_priority, COUNT(*) as count
                FROM account_story_activity
                GROUP BY story_poll_priority
            """)
            distribution = {row['story_poll_priority']: row['count'] for row in cursor.fetchall()}
            logger.debug(f"Story priority distribution: {distribution}")
            return distribution
    except Exception as e:
        logger.error(f"Failed to get story priority distribution: {e}")
        return {}
```

---

### **Step 2: Instagram Client Stories Support**

#### 2.1 Write Tests First
**File**: `tests/test_instagram_client_stories.py`

```python
"""Tests for Instagram client story functionality."""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta

from src.instagram_client import InstagramClient, InstagramStory


@pytest.fixture
def mock_client():
    """Create a mock Instagram client."""
    client = Mock(spec=InstagramClient)
    client.client = Mock()
    client._is_authenticated = True
    return client


class TestInstagramClientStories:
    """Tests for story-related methods."""
    
    def test_check_story_mute_status_not_muted(self, mock_client):
        """Test detecting non-muted stories."""
        # Mock relationship response
        mock_relationship = Mock()
        mock_relationship.is_muting_reel = False
        mock_client.client.user_friendship_v1.return_value = mock_relationship
        
        # Test
        client = InstagramClient("user", "pass")
        client.client = mock_client.client
        client._is_authenticated = True
        
        is_muted = client.check_story_mute_status("user123")
        assert is_muted is False
    
    def test_check_story_mute_status_muted(self, mock_client):
        """Test detecting muted stories."""
        mock_relationship = Mock()
        mock_relationship.is_muting_reel = True
        mock_client.client.user_friendship_v1.return_value = mock_relationship
        
        client = InstagramClient("user", "pass")
        client.client = mock_client.client
        client._is_authenticated = True
        
        is_muted = client.check_story_mute_status("user123")
        assert is_muted is True
    
    def test_fetch_user_stories(self, mock_client):
        """Test fetching stories from user."""
        # Mock story response
        mock_story = Mock()
        mock_story.pk = "story123"
        mock_story.media_type = 1  # Image
        mock_story.taken_at = datetime.now()
        mock_story.thumbnail_url = "https://example.com/story.jpg"
        mock_story.video_url = None
        mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
        mock_story.polls = []
        mock_story.stickers = []
        
        mock_client.client.user_stories.return_value = [mock_story]
        
        client = InstagramClient("user", "pass")
        client.client = mock_client.client
        client._is_authenticated = True
        
        stories = client.fetch_user_stories("user123", "testuser")
        assert len(stories) == 1
        assert stories[0].id == "story123"
        assert stories[0].username == "testuser"
    
    def test_convert_story_with_poll(self):
        """Test extracting poll question and options."""
        client = InstagramClient("user", "pass")
        
        # Mock story with poll
        mock_story = Mock()
        mock_story.pk = "story456"
        mock_story.media_type = 1
        mock_story.taken_at = datetime.now()
        mock_story.thumbnail_url = "https://example.com/story.jpg"
        mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
        
        # Poll
        mock_poll = Mock()
        mock_poll.question = "What's your favorite?"
        mock_poll.options = [{"text": "Option A"}, {"text": "Option B"}]
        mock_story.polls = [mock_poll]
        mock_story.stickers = []
        
        story = client._convert_story_to_instagram_story(mock_story)
        
        assert story is not None
        assert story.poll_question == "What's your favorite?"
        assert story.poll_options == ["Option A", "Option B"]
    
    def test_convert_story_with_link_text(self):
        """Test extracting link text from stickers."""
        client = InstagramClient("user", "pass")
        
        # Mock story with link sticker
        mock_story = Mock()
        mock_story.pk = "story789"
        mock_story.media_type = 1
        mock_story.taken_at = datetime.now()
        mock_story.thumbnail_url = "https://example.com/story.jpg"
        mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
        mock_story.polls = []
        
        # Link sticker
        mock_sticker = Mock()
        mock_sticker.type = "story_link"
        mock_sticker.story_link = Mock(link_title="Swipe up!")
        mock_sticker.extra = None
        mock_story.stickers = [mock_sticker]
        
        story = client._convert_story_to_instagram_story(mock_story)
        
        assert story is not None
        assert story.link_text == "Swipe up!"
```

#### 2.2 Add InstagramStory Dataclass
**File**: `src/instagram_client.py`

Add after the `InstagramPost` dataclass:

```python
@dataclass
class InstagramStory:
    """Represents an Instagram story."""
    
    id: str                           # Story media ID
    user_id: str                      # Author's user ID
    username: str                     # Author's username
    full_name: Optional[str]          # Author's full name
    taken_at: datetime                # When story was posted
    expires_at: datetime              # When story expires (taken_at + 24h)
    media_url: str                    # Story media URL
    media_type: str                   # 'image' or 'video'
    permalink: str                    # Instagram story URL
    
    # Text content fields
    poll_question: Optional[str] = None
    poll_options: Optional[List[str]] = None
    link_text: Optional[str] = None
    sticker_text: Optional[Dict[str, Any]] = None
```

#### 2.3 Implement Client Methods
**File**: `src/instagram_client.py`

Add these methods to the `InstagramClient` class:

```python
def check_story_mute_status(self, user_id: str) -> bool:
    """Check if stories are muted for a user.
    
    Args:
        user_id: Instagram user ID
        
    Returns:
        True if stories are muted, False otherwise
    """
    try:
        relationship = self.client.user_friendship_v1(user_id)
        is_muted = relationship.is_muting_reel
        logger.debug(f"User {user_id} story mute status: {is_muted}")
        return is_muted
    except Exception as e:
        logger.error(f"Failed to check mute status for {user_id}: {e}")
        # Assume not muted on error (err on side of fetching)
        return False

def fetch_user_stories(
    self, 
    user_id: str, 
    username: str
) -> List[InstagramStory]:
    """Fetch all current stories from a user.
    
    Args:
        user_id: Instagram user ID
        username: Instagram username (for logging)
        
    Returns:
        List of InstagramStory objects
    """
    logger.debug(f"Fetching stories from @{username}")
    
    def _fetch():
        try:
            # Use instagrapi's user_stories method
            stories = self.client.user_stories(user_id)
            
            if not stories:
                logger.debug(f"@{username} has no current stories")
                return []
            
            instagram_stories = []
            for story in stories:
                converted = self._convert_story_to_instagram_story(story)
                if converted:
                    instagram_stories.append(converted)
            
            logger.info(f"@{username}: Fetched {len(instagram_stories)} stories")
            return instagram_stories
            
        except Exception as e:
            logger.error(f"Failed to fetch stories for @{username}: {e}")
            return []
    
    return self._retry_with_backoff(_fetch)

def _convert_story_to_instagram_story(self, story) -> Optional[InstagramStory]:
    """Convert instagrapi Story object to InstagramStory.
    
    Extracts text content from polls, links, and stickers.
    
    Args:
        story: instagrapi Story object
        
    Returns:
        InstagramStory or None if conversion fails
    """
    try:
        # Determine media URL and type
        if story.media_type == 1:  # Image
            media_url = str(story.thumbnail_url) if story.thumbnail_url else ""
            media_type = "image"
        elif story.media_type == 2:  # Video
            media_url = str(story.video_url) if story.video_url else ""
            media_type = "video"
        else:
            logger.warning(f"Unknown story media type: {story.media_type}")
            return None
        
        # Calculate expiration (24 hours from taken_at)
        expires_at = story.taken_at + timedelta(hours=24)
        
        # Build permalink
        permalink = f"https://www.instagram.com/stories/{story.user.username}/{story.pk}/"
        
        # Extract text content from polls
        poll_question = None
        poll_options = None
        if story.polls and len(story.polls) > 0:
            poll = story.polls[0]  # First poll
            poll_question = poll.question
            poll_options = [opt.get('text', '') for opt in poll.options] if poll.options else None
        
        # Extract text content from link stickers
        link_text = None
        sticker_text = {}
        if story.stickers:
            for sticker in story.stickers:
                # Link sticker
                if sticker.story_link and sticker.story_link.link_title:
                    link_text = sticker.story_link.link_title
                
                # Other stickers with text in 'extra'
                if sticker.extra and isinstance(sticker.extra, dict):
                    sticker_type = sticker.type or "unknown"
                    sticker_text[sticker_type] = sticker.extra
        
        return InstagramStory(
            id=str(story.pk),
            user_id=str(story.user.pk),
            username=story.user.username,
            full_name=story.user.full_name if story.user.full_name else None,
            taken_at=story.taken_at,
            expires_at=expires_at,
            media_url=media_url,
            media_type=media_type,
            permalink=permalink,
            poll_question=poll_question,
            poll_options=poll_options,
            link_text=link_text,
            sticker_text=sticker_text if sticker_text else None
        )
        
    except Exception as e:
        logger.error(f"Failed to convert story to InstagramStory: {e}")
        return None

def check_account_for_new_stories(
    self,
    user_id: str,
    username: str,
    last_known_story_id: Optional[str] = None
) -> Tuple[bool, List[InstagramStory], Dict[str, Any]]:
    """Efficiently check if account has new stories.
    
    CRITICAL: This should ONLY be called if stories are NOT muted.
    
    Args:
        user_id: Instagram user ID
        username: Instagram username
        last_known_story_id: ID of last story we fetched
        
    Returns:
        Tuple of (has_new_stories, new_stories_list, metadata)
    """
    logger.debug(f"Checking @{username} for new stories")
    
    def _check():
        metadata = {
            'latest_story_id': None,
            'latest_story_date': None,
            'story_count': 0
        }
        
        # Fetch current stories
        stories = self.fetch_user_stories(user_id, username)
        
        if not stories:
            return False, [], metadata
        
        # Update metadata
        # Stories are ordered by taken_at (newest first from Instagram)
        latest_story = stories[0]
        metadata['latest_story_id'] = latest_story.id
        metadata['latest_story_date'] = latest_story.taken_at
        metadata['story_count'] = len(stories)
        
        # Check if we have new stories
        if last_known_story_id and latest_story.id == last_known_story_id:
            logger.debug(f"@{username}: No new stories")
            return False, [], metadata
        
        logger.info(f"@{username}: {len(stories)} stories detected")
        return True, stories, metadata
    
    return self._retry_with_backoff(_check)
```

---

### **Step 3: Story Polling Manager**

This step involves creating a new module `src/story_polling_manager.py` similar to `account_polling_manager.py` but for stories.

**Key differences:**
- Separate activity tracking (story activity ≠ post activity)
- Mute status filtering (skip muted accounts)
- Conservative initialization (all start as 'normal')

**File**: `src/story_polling_manager.py`

See the detailed implementation in the full plan document.

---

### **Step 4: RSS Feed Integration**

Update `src/rss_generator.py` to:
1. Accept both posts and stories
2. Format stories with `[STORY]` prefix
3. Display text content from polls/links/stickers
4. Sort combined feed by date

---

### **Step 5: API Integration**

Update `src/api.py` to:
1. Add story sync to background scheduler
2. Check mute status periodically (every 24h)
3. Fetch stories alongside posts
4. Serve unified feed with both

---

## Implementation Timeline

**Week 1**: Storage layer + database schema  
**Week 2**: Instagram client + mute detection + text extraction  
**Week 3**: Story polling manager  
**Week 4**: RSS feed integration + API updates  
**Week 5**: Testing, debugging, documentation  

---

## Testing Strategy

### Unit Tests
- All storage methods
- All Instagram client methods
- Story polling logic
- Mute detection
- Text extraction from polls/stickers

### Integration Tests
- End-to-end story sync
- Mute status filtering
- Unified feed generation
- Database integrity (FK constraints)

### Manual Testing
- Mute stories for test account → verify skipped
- Unmute stories → verify fetched
- Test with `@taniawaikatolawyer` (known story poster)
- Verify poll text appears in RSS
- Verify `[STORY]` prefix in RSS reader

---

## Configuration

Add to `src/config.py`:

```python
# Story polling
STORY_POLLING_ENABLED: bool = env_bool('STORY_POLLING_ENABLED', True)
STORY_ACTIVE_DAYS: int = env_int('STORY_ACTIVE_DAYS', 3)
STORY_INACTIVE_DAYS: int = env_int('STORY_INACTIVE_DAYS', 14)
STORY_DORMANT_DAYS: int = env_int('STORY_DORMANT_DAYS', 90)
STORY_MUTE_REFRESH_HOURS: int = env_int('STORY_MUTE_REFRESH_HOURS', 24)
```

Add to `.env.example`:

```bash
# Story polling (PHASE2)
STORY_POLLING_ENABLED=true
STORY_ACTIVE_DAYS=3
STORY_INACTIVE_DAYS=14
STORY_DORMANT_DAYS=90
STORY_MUTE_REFRESH_HOURS=24
```

---

## Success Criteria

### Functionality
- [ ] Stories fetched from followed accounts
- [ ] Muted accounts automatically skipped
- [ ] Stories stored with text content (polls, links)
- [ ] Stories appear in `/feed.rss` with `[STORY]` prefix
- [ ] Story media cached locally
- [ ] Stories persist after 24h expiration
- [ ] Unified feed sorted by date (posts + stories)

### Performance
- [ ] Story fetching < 2s per account
- [ ] Mute check < 1s per account
- [ ] Feed generation with stories < 2s
- [ ] No duplicate stories

### Quality
- [ ] 80%+ test coverage for new code
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Type checking passes: `mypy src/`
- [ ] Linting passes: `flake8 src/`
- [ ] Code formatted: `black src/ tests/`

---

## Key Implementation Notes

### 1. **Mute Status Sync Frequency**

```python
# Check mute status:
# - On first story sync (initialization)
# - Every 24 hours (periodic refresh)
# - User can manually trigger refresh (future feature)

# Why 24 hours?
# - Balance between freshness and API calls
# - Users don't frequently change mute settings
# - 24h ensures we catch changes within reasonable time
```

### 2. **Text Content Extraction**

```python
# Text content sources (in order of priority):
# 1. Poll question + options (most useful, structured)
# 2. Link text (swipe up text)
# 3. Sticker extra data (may contain text)
# 4. Manual text overlays (NOT available via API)

# Note: Text overlays are baked into the image/video file
# Would require OCR to extract
```

### 3. **Story Priority Independence**

```python
# Example scenario:
# Account posts once per month (post priority: LOW)
# BUT posts stories daily (story priority: HIGH)

# Result:
# - account_activity.poll_priority = 'low'
# - account_story_activity.story_poll_priority = 'high'

# This ensures we don't miss frequent story posters
# just because they rarely post regular content
```

### 4. **Error Handling for Mute Status**

```python
# If mute status check fails:
# - Assume NOT muted (err on side of fetching content)
# - Log error for investigation
# - Will be corrected on next 24h refresh

# Rationale:
# - Better to fetch unnecessarily than miss content
# - Mute check is non-critical
# - Self-corrects within 24 hours
```

---

## Rollout Strategy

### Phase 2A: Storage & Client (Week 1-2)
- Merge storage layer changes
- Merge Instagram client story support
- Deploy with `STORY_POLLING_ENABLED=false`

### Phase 2B: Polling Manager (Week 3)
- Merge story polling manager
- Still disabled by default
- Ready for testing

### Phase 2C: RSS Integration (Week 4)
- Merge RSS generator updates
- Merge API integration
- Enable for testing: `STORY_POLLING_ENABLED=true`

### Phase 2D: Production (Week 5)
- Full testing complete
- Enable in production
- Monitor for 48 hours

---

## Migration Notes

### Database Migration
The new tables will be created automatically on first run (via `_init_database()`). No manual migration needed.

### Backwards Compatibility
- Stories are additive - existing posts/RSS feed work unchanged
- New functionality is opt-in via config flag
- Config defaults maintain existing behavior

---

## Open Questions

1. **Story media formats**: Instagram stories can have special effects. We're capturing the raw media - is this acceptable or should we investigate preserving effects?

2. **Story grouping**: Should we consider grouping multiple stories from same account/timeframe in RSS, or keep them as individual items? (Currently: individual items)

3. **Performance monitoring**: Should we add metrics to track story fetch performance and mute check overhead?

4. **Manual mute refresh**: Should we add an API endpoint to manually trigger mute status refresh? (Currently: automatic 24h refresh only)

---

## Test Accounts

Known accounts that post stories frequently (for testing):
- `@taniawaikatolawyer` - Posts stories regularly

---

This implementation plan follows the same test-driven development approach as PHASE1, with clear separation of concerns and independent story activity tracking to handle the unique behavioral patterns of Instagram Stories.
