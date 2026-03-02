"""Tests for story storage functionality."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.instagram_client import InstagramStory
from src.storage import StorageManager, safe_json_dumps


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def storage(temp_db):
    """Create a StorageManager with temporary database."""
    return StorageManager(db_path=temp_db, media_dir=tempfile.mkdtemp())


class TestStoriesTable:
    """Tests for stories table schema and basic operations."""

    def test_stories_table_created(self, storage):
        """Test stories table exists with correct schema."""
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='stories'"
            )
            assert cursor.fetchone() is not None

    def test_account_story_activity_table_created(self, storage):
        """Test account_story_activity table exists with correct schema."""
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='account_story_activity'"
            )
            assert cursor.fetchone() is not None

    def test_story_exists_false(self, storage):
        """Test checking for non-existent story."""
        assert storage.story_exists("nonexistent_id") is False


class TestSaveAndRetrieveStories:
    """Tests for saving and retrieving stories."""

    def _ensure_following(self, storage, user_id="user456", username="testuser"):
        """Create a following_accounts parent record for FK constraint."""
        storage.save_following_accounts([{
            "user_id": user_id,
            "username": username,
            "full_name": f"Test {username}",
            "is_private": False,
        }])

    def test_save_story(self, storage):
        """Test saving a story to database."""
        self._ensure_following(storage)
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
            sticker_text={"type": "gif", "data": "test"},
        )

        result = storage.save_story(story)
        assert result is True
        assert storage.story_exists("story123") is True

    def test_get_story_by_id(self, storage):
        """Test fetching single story by ID."""
        self._ensure_following(storage)
        story = InstagramStory(
            id="story789",
            user_id="user456",
            username="testuser",
            full_name="Test User",
            taken_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=24),
            media_url="https://example.com/story.jpg",
            media_type="image",
            permalink="https://instagram.com/stories/testuser/story789/",
        )

        storage.save_story(story)

        retrieved = storage.get_story_by_id("story789")
        assert retrieved is not None
        assert retrieved["id"] == "story789"
        assert retrieved["username"] == "testuser"

    def test_get_recent_stories(self, storage):
        """Test querying recent stories."""
        self._ensure_following(storage)
        for i in range(5):
            story = InstagramStory(
                id=f"story{i}",
                user_id="user456",
                username="testuser",
                full_name="Test User",
                taken_at=datetime.now() - timedelta(hours=i),
                expires_at=datetime.now() + timedelta(hours=24 - i),
                media_url=f"https://example.com/story{i}.jpg",
                media_type="image",
                permalink=f"https://instagram.com/stories/testuser/story{i}/",
            )
            storage.save_story(story)

        stories = storage.get_recent_stories(limit=3)
        assert len(stories) == 3
        # Most recent first
        assert stories[0]["id"] == "story0"

    def test_save_story_with_json_fields(self, storage):
        """Test that JSON fields are serialized correctly."""
        self._ensure_following(storage, user_id="user123")
        story = InstagramStory(
            id="story_json",
            user_id="user123",
            username="testuser",
            full_name="Test User",
            taken_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=24),
            media_url="https://example.com/story.jpg",
            media_type="image",
            permalink="https://instagram.com/stories/testuser/story_json/",
            poll_options=["Option 1", "Option 2"],
            sticker_text={"text": "valid"},
        )

        assert storage.save_story(story) is True

        saved = storage.get_story_by_id("story_json")
        assert saved is not None
        assert saved["poll_options"] == json.dumps(["Option 1", "Option 2"])
        assert saved["sticker_text"] == json.dumps({"text": "valid"})


class TestStoryMediaPaths:
    """Tests for story media path generation."""

    def test_get_story_path_image(self, storage):
        """Test get_story_path generates correct path for images."""
        path = storage.get_story_path("story123", "image")
        assert path.name == "0.jpg"
        assert "story123" in str(path)
        assert path.parent.exists()

    def test_get_story_path_video(self, storage):
        """Test get_story_path generates correct path for videos."""
        path = storage.get_story_path("story456", "video")
        assert path.name == "0.mp4"
        assert "story456" in str(path)
        assert path.parent.exists()


class TestStoryExistsCache:
    """Tests for story_exists caching."""

    def test_caching_on_save(self, storage):
        """Test that story_exists uses caching correctly."""
        # Create FK parent first
        storage.save_following_accounts([{
            "user_id": "user123",
            "username": "testuser",
            "full_name": "Test User",
            "is_private": False,
        }])

        story = InstagramStory(
            id="cached_story",
            user_id="user123",
            username="testuser",
            full_name="Test User",
            taken_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=24),
            media_url="https://example.com/story.jpg",
            media_type="image",
            permalink="https://instagram.com/stories/testuser/cached_story/",
        )

        # Initially not in cache or DB
        assert storage.story_exists("cached_story") is False
        assert "cached_story" not in storage._story_exists_cache

        # Save story
        storage.save_story(story)

        # Should now be in cache
        assert "cached_story" in storage._story_exists_cache
        assert storage.story_exists("cached_story") is True


class TestAccountStoryActivity:
    """Tests for account_story_activity CRUD operations."""

    def _create_following_account(self, storage, user_id="user123", username="testuser"):
        """Helper to create a following_accounts entry for FK constraint."""
        storage.save_following_accounts([{
            "user_id": user_id,
            "username": username,
            "full_name": f"Test {username}",
            "is_private": False,
        }])

    def test_save_activity_with_mute_status(self, storage):
        """Test saving story activity with is_muting_stories flag."""
        self._create_following_account(storage)

        result = storage.save_account_story_activity(
            user_id="user123",
            username="testuser",
            is_muting_stories=True,
        )

        assert result is True

        activity = storage.get_account_story_activity("user123")
        assert activity is not None
        assert activity["is_muting_stories"] == 1  # SQLite stores as int

    def test_get_unmuted_accounts(self, storage):
        """Test querying only accounts that haven't muted stories."""
        # Must save all following accounts in one call to avoid CASCADE deletes
        storage.save_following_accounts([
            {"user_id": "user1", "username": "user1",
             "full_name": "Test user1", "is_private": False},
            {"user_id": "user2", "username": "user2",
             "full_name": "Test user2", "is_private": False},
            {"user_id": "user3", "username": "user3",
             "full_name": "Test user3", "is_private": False},
        ])
        for uid, uname, muted in [
            ("user1", "user1", False),
            ("user2", "user2", True),
            ("user3", "user3", False),
        ]:
            storage.save_account_story_activity(uid, uname, is_muting_stories=muted)

        unmuted = storage.get_unmuted_accounts_for_stories()

        assert len(unmuted) == 2
        usernames = [a["username"] for a in unmuted]
        assert "user1" in usernames
        assert "user3" in usernames
        assert "user2" not in usernames

    def test_update_activity(self, storage):
        """Test updating story activity fields."""
        self._create_following_account(storage)
        storage.save_account_story_activity("user123", "testuser")

        result = storage.update_account_story_activity(
            user_id="user123",
            last_story_id="story999",
            consecutive_no_new_stories=5,
        )

        assert result is True

        activity = storage.get_account_story_activity("user123")
        assert activity["last_story_id"] == "story999"
        assert activity["consecutive_no_new_stories"] == 5


class TestSafeJsonDumps:
    """Tests for safe_json_dumps module-level function."""

    def test_valid_list(self):
        """Test serializing a list."""
        assert safe_json_dumps(["a", "b", "c"]) == '["a", "b", "c"]'

    def test_valid_dict(self):
        """Test serializing a dict."""
        assert safe_json_dumps({"key": "value"}) == '{"key": "value"}'

    def test_none_returns_none(self):
        """Test that None input returns None."""
        assert safe_json_dumps(None) is None

    def test_non_serializable_returns_none(self):
        """Test that non-serializable object returns None (not str())."""

        class NonSerializable:
            pass

        result = safe_json_dumps(NonSerializable())
        assert result is None

    def test_nested_structure(self):
        """Test nested structure with valid data."""
        nested = {"list": [1, 2, 3], "dict": {"nested": "value"}}
        result = safe_json_dumps(nested)
        assert result is not None
        assert json.loads(result) == nested
