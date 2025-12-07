"""Integration test demonstrating Instagram client + Storage layer working together."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from src.instagram_client import InstagramClient, InstagramPost
from src.storage import StorageManager


@pytest.fixture
def temp_storage():
    """Create a temporary storage manager for testing."""
    temp_dir = tempfile.mkdtemp()
    
    db_path = Path(temp_dir) / "test.db"
    media_dir = Path(temp_dir) / "media"
    
    storage = StorageManager(str(db_path), str(media_dir))
    
    yield storage
    
    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_instagram_client():
    """Create a mocked Instagram client."""
    with patch("src.instagram_client.Client"):
        client = InstagramClient("test_user", "test_pass")
        client._is_authenticated = True  # Skip actual login
        yield client


def test_fetch_and_store_posts(mock_instagram_client, temp_storage):
    """Integration test: fetch posts from Instagram and store them."""
    # Mock the timeline feed response
    mock_media = Mock()
    mock_media.id = "1234567890"
    mock_media.media_type = 1  # Photo
    mock_media.taken_at = datetime(2024, 1, 15, 12, 0, 0)
    mock_media.caption_text = "Test post from Instagram"
    mock_media.code = "ABC123"
    mock_media.thumbnail_url = "https://example.com/image.jpg"
    mock_media.user.username = "test_user"
    mock_media.user.full_name = "Test User"
    
    with patch.object(mock_instagram_client, "client") as mock_client:
        mock_client.get_timeline_feed.return_value = [mock_media]
        
        # Fetch posts from Instagram
        posts = mock_instagram_client.get_timeline_feed(count=10)
        
        assert len(posts) == 1
        assert posts[0].id == "1234567890"
        
        # Store the post in database
        result = temp_storage.save_post(posts[0])
        assert result is True
        
        # Verify the post was stored
        assert temp_storage.post_exists(posts[0].id) is True
        
        # Retrieve the post from storage
        stored_post = temp_storage.get_post_by_id(posts[0].id)
        assert stored_post is not None
        assert stored_post['caption'] == "Test post from Instagram"
        assert stored_post['author_username'] == "test_user"
        assert len(stored_post['media']) == 1


def test_fetch_store_and_download_media(mock_instagram_client, temp_storage):
    """Integration test: fetch posts, store them, and download media."""
    # Create a mock post
    post = InstagramPost(
        id="9876543210",
        posted_at=datetime.now(),
        caption="Post with media",
        post_type="photo",
        permalink="https://instagram.com/p/XYZ/",
        author_username="photographer",
        author_full_name="Pro Photographer",
        media_urls=["https://example.com/photo.jpg"],
        media_types=["image"],
    )
    
    # Save post to storage
    temp_storage.save_post(post)
    
    # Get media path
    media_path = temp_storage.get_media_path(post.id, 0, "image")
    assert media_path.parent.exists()
    assert media_path.name == "0.jpg"
    
    # Simulate downloading media
    # In real scenario, we'd use: mock_instagram_client.download_media(url, str(media_path))
    # For this test, just create a fake file
    media_path.write_text("fake image data")
    file_size = media_path.stat().st_size
    
    # Update storage with download info
    result = temp_storage.save_media(
        post.id, 
        0, 
        post.media_urls[0],
        "image",
        str(media_path),
        file_size
    )
    assert result is True
    
    # Verify media info was saved
    stored_post = temp_storage.get_post_by_id(post.id)
    assert stored_post['media'][0]['local_path'] == str(media_path)
    assert stored_post['media'][0]['downloaded_at'] is not None
    assert stored_post['media'][0]['file_size'] == file_size


def test_duplicate_post_handling(mock_instagram_client, temp_storage):
    """Integration test: verify duplicate posts are handled correctly."""
    post = InstagramPost(
        id="duplicate_test",
        posted_at=datetime.now(),
        caption="Original caption",
        post_type="photo",
        permalink="https://instagram.com/p/DUP/",
        author_username="user",
        author_full_name="User",
        media_urls=["https://example.com/1.jpg"],
        media_types=["image"],
    )
    
    # Save post first time
    temp_storage.save_post(post)
    
    # Check it exists
    assert temp_storage.post_exists(post.id) is True
    
    # Modify post and save again
    post.caption = "Updated caption"
    temp_storage.save_post(post)
    
    # Verify only one post exists (not duplicated)
    stats = temp_storage.get_stats()
    assert stats['post_count'] == 1
    
    # Verify caption was updated
    stored_post = temp_storage.get_post_by_id(post.id)
    assert stored_post['caption'] == "Updated caption"


def test_full_workflow_multiple_posts(mock_instagram_client, temp_storage):
    """Integration test: simulate full workflow with multiple posts."""
    # Create multiple posts
    posts = []
    for i in range(3):
        post = InstagramPost(
            id=f"post_{i}",
            posted_at=datetime.now(),
            caption=f"Post {i}",
            post_type="photo",
            permalink=f"https://instagram.com/p/{i}/",
            author_username=f"user_{i}",
            author_full_name=f"User {i}",
            media_urls=[f"https://example.com/image_{i}.jpg"],
            media_types=["image"],
        )
        posts.append(post)
    
    # Store all posts
    for post in posts:
        result = temp_storage.save_post(post)
        assert result is True
    
    # Verify all posts are stored
    recent_posts = temp_storage.get_recent_posts(limit=10)
    assert len(recent_posts) == 3
    
    # Verify stats
    stats = temp_storage.get_stats()
    assert stats['post_count'] == 3
    assert stats['media_count'] == 3
    
    # Verify each post can be retrieved
    for post in posts:
        stored = temp_storage.get_post_by_id(post.id)
        assert stored is not None
        assert stored['author_username'] == post.author_username
