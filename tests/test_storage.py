"""Unit tests for the storage layer."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from src.storage import StorageManager
from src.instagram_client import InstagramPost


@pytest.fixture
def temp_storage():
    """Create a temporary storage manager for testing."""
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    
    db_path = Path(temp_dir) / "test.db"
    media_dir = Path(temp_dir) / "media"
    
    storage = StorageManager(str(db_path), str(media_dir))
    
    yield storage
    
    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_post():
    """Create a sample InstagramPost for testing."""
    return InstagramPost(
        id="1234567890",
        posted_at=datetime(2024, 1, 15, 12, 30, 0),
        caption="Test post caption with #hashtag",
        post_type="photo",
        permalink="https://www.instagram.com/p/ABC123/",
        author_username="testuser",
        author_full_name="Test User",
        media_urls=["https://example.com/image.jpg"],
        media_types=["image"],
    )


@pytest.fixture
def sample_carousel_post():
    """Create a sample carousel post for testing."""
    return InstagramPost(
        id="9876543210",
        posted_at=datetime(2024, 1, 20, 18, 45, 0),
        caption="Carousel post with multiple images",
        post_type="carousel",
        permalink="https://www.instagram.com/p/XYZ789/",
        author_username="carousel_user",
        author_full_name="Carousel User",
        media_urls=[
            "https://example.com/image1.jpg",
            "https://example.com/image2.jpg",
            "https://example.com/video1.mp4",
        ],
        media_types=["image", "image", "video"],
    )


def test_database_initialization(temp_storage):
    """Test that database tables are created correctly."""
    with temp_storage._get_connection() as conn:
        cursor = conn.cursor()
        
        # Check posts table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='posts'
        """)
        assert cursor.fetchone() is not None
        
        # Check media table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='media'
        """)
        assert cursor.fetchone() is not None
        
        # Check indexes exist
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name='idx_posts_posted_at'
        """)
        assert cursor.fetchone() is not None


def test_post_exists_false(temp_storage):
    """Test post_exists returns False for non-existent post."""
    assert temp_storage.post_exists("nonexistent") is False


def test_save_and_check_post_exists(temp_storage, sample_post):
    """Test saving a post and checking if it exists."""
    # Post should not exist initially
    assert temp_storage.post_exists(sample_post.id) is False
    
    # Save post
    result = temp_storage.save_post(sample_post)
    assert result is True
    
    # Post should now exist
    assert temp_storage.post_exists(sample_post.id) is True


def test_save_post_single_media(temp_storage, sample_post):
    """Test saving a post with single media item."""
    result = temp_storage.save_post(sample_post)
    assert result is True
    
    # Verify post in database
    with temp_storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM posts WHERE id = ?", (sample_post.id,))
        row = cursor.fetchone()
        
        assert row is not None
        assert row['id'] == sample_post.id
        assert row['caption'] == sample_post.caption
        assert row['post_type'] == sample_post.post_type
        assert row['permalink'] == sample_post.permalink
        assert row['author_username'] == sample_post.author_username
        
        # Verify media in database
        cursor.execute("SELECT * FROM media WHERE post_id = ?", (sample_post.id,))
        media_rows = cursor.fetchall()
        
        assert len(media_rows) == 1
        assert media_rows[0]['media_url'] == sample_post.media_urls[0]
        assert media_rows[0]['media_type'] == sample_post.media_types[0]
        assert media_rows[0]['local_path'] is None  # Not downloaded yet


def test_save_post_multiple_media(temp_storage, sample_carousel_post):
    """Test saving a carousel post with multiple media items."""
    result = temp_storage.save_post(sample_carousel_post)
    assert result is True
    
    # Verify media count
    with temp_storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media WHERE post_id = ?", (sample_carousel_post.id,))
        media_rows = cursor.fetchall()
        
        assert len(media_rows) == 3
        assert media_rows[0]['media_type'] == "image"
        assert media_rows[1]['media_type'] == "image"
        assert media_rows[2]['media_type'] == "video"


def test_update_existing_post(temp_storage, sample_post):
    """Test updating an existing post."""
    # Save initial post
    temp_storage.save_post(sample_post)
    
    # Modify post
    sample_post.caption = "Updated caption"
    sample_post.media_urls.append("https://example.com/image2.jpg")
    sample_post.media_types.append("image")
    
    # Save again (should update)
    result = temp_storage.save_post(sample_post)
    assert result is True
    
    # Verify update
    with temp_storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT caption FROM posts WHERE id = ?", (sample_post.id,))
        row = cursor.fetchone()
        assert row['caption'] == "Updated caption"
        
        # Verify media count updated
        cursor.execute("SELECT COUNT(*) as count FROM media WHERE post_id = ?", (sample_post.id,))
        count = cursor.fetchone()['count']
        assert count == 2


def test_get_media_path(temp_storage):
    """Test media file path generation."""
    path = temp_storage.get_media_path("test_post_123", 0, "image")
    
    assert path.parent.name == "test_post_123"
    assert path.name == "0.jpg"
    assert path.parent.exists()  # Directory should be created
    
    # Test video
    video_path = temp_storage.get_media_path("test_post_456", 2, "video")
    assert video_path.name == "2.mp4"


def test_save_media_info(temp_storage, sample_post):
    """Test updating media with local file information."""
    # Save post first
    temp_storage.save_post(sample_post)
    
    # Update media info
    local_path = "/data/media/1234567890/0.jpg"
    result = temp_storage.save_media(
        sample_post.id, 
        0, 
        sample_post.media_urls[0],
        "image",
        local_path,
        1024000
    )
    assert result is True
    
    # Verify media info updated
    with temp_storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT local_path, file_size, downloaded_at 
            FROM media 
            WHERE post_id = ? AND media_url = ?
        """, (sample_post.id, sample_post.media_urls[0]))
        row = cursor.fetchone()
        
        assert row['local_path'] == local_path
        assert row['file_size'] == 1024000
        assert row['downloaded_at'] is not None


def test_get_post_by_id(temp_storage, sample_post):
    """Test retrieving a single post by ID."""
    # Save post
    temp_storage.save_post(sample_post)
    
    # Retrieve post
    post = temp_storage.get_post_by_id(sample_post.id)
    
    assert post is not None
    assert post['id'] == sample_post.id
    assert post['caption'] == sample_post.caption
    assert post['author_username'] == sample_post.author_username
    assert 'media' in post
    assert len(post['media']) == 1


def test_get_post_by_id_not_found(temp_storage):
    """Test retrieving non-existent post returns None."""
    post = temp_storage.get_post_by_id("nonexistent")
    assert post is None


def test_get_recent_posts(temp_storage):
    """Test retrieving recent posts."""
    # Create multiple posts with different dates
    posts = []
    for i in range(5):
        post = InstagramPost(
            id=f"post_{i}",
            posted_at=datetime.now() - timedelta(days=i),
            caption=f"Post {i}",
            post_type="photo",
            permalink=f"https://instagram.com/p/{i}/",
            author_username="testuser",
            author_full_name="Test User",
            media_urls=[f"https://example.com/image{i}.jpg"],
            media_types=["image"],
        )
        posts.append(post)
        temp_storage.save_post(post)
    
    # Get recent posts
    recent = temp_storage.get_recent_posts(limit=3)
    
    assert len(recent) == 3
    # Should be in reverse chronological order
    assert recent[0]['id'] == "post_0"
    assert recent[1]['id'] == "post_1"
    assert recent[2]['id'] == "post_2"


def test_get_recent_posts_with_days_filter(temp_storage):
    """Test retrieving posts with days filter."""
    # Create posts: one today, one 5 days ago, one 10 days ago
    posts = [
        InstagramPost(
            id="post_today",
            posted_at=datetime.now(),
            caption="Today",
            post_type="photo",
            permalink="https://instagram.com/p/1/",
            author_username="user1",
            author_full_name="User 1",
            media_urls=["https://example.com/1.jpg"],
            media_types=["image"],
        ),
        InstagramPost(
            id="post_5days",
            posted_at=datetime.now() - timedelta(days=5),
            caption="5 days ago",
            post_type="photo",
            permalink="https://instagram.com/p/2/",
            author_username="user2",
            author_full_name="User 2",
            media_urls=["https://example.com/2.jpg"],
            media_types=["image"],
        ),
        InstagramPost(
            id="post_10days",
            posted_at=datetime.now() - timedelta(days=10),
            caption="10 days ago",
            post_type="photo",
            permalink="https://instagram.com/p/3/",
            author_username="user3",
            author_full_name="User 3",
            media_urls=["https://example.com/3.jpg"],
            media_types=["image"],
        ),
    ]
    
    for post in posts:
        temp_storage.save_post(post)
    
    # Get posts from last 7 days
    recent = temp_storage.get_recent_posts(limit=10, days=7)
    
    assert len(recent) == 2
    assert recent[0]['id'] == "post_today"
    assert recent[1]['id'] == "post_5days"


def test_get_stats(temp_storage, sample_post, sample_carousel_post):
    """Test getting database statistics."""
    # Empty database
    stats = temp_storage.get_stats()
    assert stats['post_count'] == 0
    assert stats['media_count'] == 0
    
    # Add posts
    temp_storage.save_post(sample_post)
    temp_storage.save_post(sample_carousel_post)
    
    stats = temp_storage.get_stats()
    assert stats['post_count'] == 2
    assert stats['media_count'] == 4  # 1 from sample_post + 3 from carousel
    assert stats['downloaded_count'] == 0  # Nothing downloaded yet
    assert stats['oldest_post'] is not None
    assert stats['newest_post'] is not None


def test_foreign_key_cascade(temp_storage, sample_post):
    """Test that deleting a post cascades to media."""
    # Save post
    temp_storage.save_post(sample_post)
    
    # Verify media exists
    with temp_storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM media WHERE post_id = ?", (sample_post.id,))
        assert cursor.fetchone()['count'] == 1
        
        # Delete post
        cursor.execute("DELETE FROM posts WHERE id = ?", (sample_post.id,))
        conn.commit()
        
        # Verify media is also deleted (cascade)
        cursor.execute("SELECT COUNT(*) as count FROM media WHERE post_id = ?", (sample_post.id,))
        assert cursor.fetchone()['count'] == 0


def test_concurrent_access(temp_storage, sample_post):
    """Test that multiple connections can access the database."""
    # This tests the context manager works correctly
    temp_storage.save_post(sample_post)
    
    # Multiple reads should work
    post1 = temp_storage.get_post_by_id(sample_post.id)
    post2 = temp_storage.get_post_by_id(sample_post.id)
    
    assert post1 is not None
    assert post2 is not None
    assert post1['id'] == post2['id']


def test_media_directory_creation(temp_storage):
    """Test that media directories are created as needed."""
    path = temp_storage.get_media_path("new_post", 0, "image")
    assert path.parent.exists()
    assert path.parent.name == "new_post"


def test_save_post_with_null_caption(temp_storage):
    """Test saving post with no caption."""
    post = InstagramPost(
        id="no_caption",
        posted_at=datetime.now(),
        caption=None,
        post_type="photo",
        permalink="https://instagram.com/p/xyz/",
        author_username="user",
        author_full_name="User",
        media_urls=["https://example.com/1.jpg"],
        media_types=["image"],
    )
    
    result = temp_storage.save_post(post)
    assert result is True
    
    retrieved = temp_storage.get_post_by_id("no_caption")
    assert retrieved['caption'] is None


def test_save_post_with_special_characters(temp_storage):
    """Test saving post with special characters in caption."""
    post = InstagramPost(
        id="special_chars",
        posted_at=datetime.now(),
        caption="Test with emoji 🎉 and quotes \"hello\" and apostrophe's",
        post_type="photo",
        permalink="https://instagram.com/p/xyz/",
        author_username="user",
        author_full_name="User",
        media_urls=["https://example.com/1.jpg"],
        media_types=["image"],
    )
    
    result = temp_storage.save_post(post)
    assert result is True
    
    retrieved = temp_storage.get_post_by_id("special_chars")
    assert retrieved['caption'] == post.caption
