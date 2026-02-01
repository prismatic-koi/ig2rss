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
