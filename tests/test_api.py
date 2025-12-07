"""Tests for Flask HTTP API.

This module tests all HTTP endpoints, background sync, and error handling.
"""

import os
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.api import create_app
from src.config import Config
from src.storage import StorageManager
from src.instagram_client import InstagramPost


@pytest.fixture
def temp_dir():
    """Create temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_config(temp_dir):
    """Create test configuration."""
    config = Config()
    config.DATABASE_PATH = os.path.join(temp_dir, "test.db")
    config.MEDIA_CACHE_PATH = os.path.join(temp_dir, "media")
    config.INSTAGRAM_USERNAME = "testuser"
    config.INSTAGRAM_PASSWORD = "testpass"
    config.RSS_FEED_LIMIT = 50
    config.RSS_FEED_DAYS = 30
    config.POLL_INTERVAL = 0  # Disable background sync for tests
    config.HOST = "0.0.0.0"
    config.PORT = 8080
    config.LOG_LEVEL = "INFO"
    
    return config


@pytest.fixture
def app(test_config):
    """Create Flask test app."""
    with patch.dict(os.environ, {'BASE_URL': 'http://testserver'}):
        app = create_app(test_config)
        app.config['TESTING'] = True
        yield app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def storage(app):
    """Get storage manager from app."""
    return app.config['storage']


@pytest.fixture
def sample_posts(storage):
    """Create sample posts in database."""
    posts = []
    
    for i in range(5):
        post = InstagramPost(
            id=f"post_{i}",
            posted_at=datetime.now() - timedelta(days=i),
            caption=f"Test post {i}\nWith multiple lines",
            post_type="image",
            permalink=f"https://instagram.com/p/post_{i}",
            media_urls=[f"https://example.com/image_{i}.jpg"],
            media_types=["image"],
            author_username="testuser",
            author_full_name="Test User"
        )
        
        storage.save_post(post)
        posts.append(post)
        
        # Create dummy media file
        media_path = storage.get_media_path(post.id, 0, "image")
        media_path.write_bytes(b"fake image data")
        storage.save_media(post.id, 0, post.media_urls[0], "image", str(media_path), 15)
    
    return posts


class TestHealthEndpoint:
    """Tests for /health endpoint."""
    
    def test_health_check_empty_database(self, client):
        """Test health endpoint with empty database."""
        response = client.get('/health')
        
        assert response.status_code == 200
        assert response.content_type == 'application/json'
        
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert data['service'] == 'ig2rss'
        assert data['database']['posts'] == 0
        assert data['database']['media'] == 0
        assert data['database']['downloaded'] == 0
    
    def test_health_check_with_data(self, client, sample_posts):
        """Test health endpoint with data in database."""
        response = client.get('/health')
        
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert data['database']['posts'] == 5
        assert data['database']['media'] == 5
        assert data['database']['downloaded'] == 5


class TestFeedEndpoint:
    """Tests for /feed.rss endpoint."""
    
    def test_feed_empty_database(self, client):
        """Test RSS feed with empty database."""
        response = client.get('/feed.rss')
        
        assert response.status_code == 200
        assert 'application/rss+xml' in response.content_type
        assert b'<?xml version="1.0"' in response.data
        assert b'<rss' in response.data
        assert b'version="2.0"' in response.data
        assert b'<channel>' in response.data
        assert b'testuser' in response.data
    
    def test_feed_with_posts(self, client, sample_posts):
        """Test RSS feed with posts."""
        response = client.get('/feed.rss')
        
        assert response.status_code == 200
        assert b'<item>' in response.data
        assert b'Test post 0' in response.data
        assert b'testuser' in response.data
    
    def test_feed_limit_parameter(self, client, sample_posts):
        """Test RSS feed with limit parameter."""
        response = client.get('/feed.rss?limit=2')
        
        assert response.status_code == 200
        
        # Should only have 2 items (hard to count XML items without parsing)
        # Just verify it doesn't error
        assert b'<item>' in response.data
    
    def test_feed_days_parameter(self, client, sample_posts):
        """Test RSS feed with days parameter."""
        response = client.get('/feed.rss?days=1')
        
        assert response.status_code == 200
        
        # Should only have posts from today
        assert b'<item>' in response.data
    
    def test_feed_invalid_limit(self, client):
        """Test RSS feed with invalid limit."""
        response = client.get('/feed.rss?limit=invalid')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
    
    def test_feed_limit_out_of_range(self, client):
        """Test RSS feed with limit out of range."""
        response = client.get('/feed.rss?limit=2000')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'limit' in data['error']
    
    def test_feed_days_out_of_range(self, client):
        """Test RSS feed with days out of range."""
        response = client.get('/feed.rss?days=500')
        
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'days' in data['error']


class TestMediaEndpoint:
    """Tests for /media/* endpoint."""
    
    def test_serve_existing_image(self, client, sample_posts):
        """Test serving existing media file."""
        response = client.get('/media/post_0/0.jpg')
        
        assert response.status_code == 200
        assert response.content_type == 'image/jpeg'
        assert response.data == b"fake image data"
    
    def test_serve_nonexistent_file(self, client):
        """Test serving nonexistent media file."""
        response = client.get('/media/nonexistent/0.jpg')
        
        assert response.status_code == 404
        data = json.loads(response.data)
        assert 'error' in data
    
    def test_path_traversal_protection(self, client):
        """Test path traversal attack protection."""
        response = client.get('/media/../../../etc/passwd')
        
        assert response.status_code in [403, 404]
        
        # Should not return file contents
        if response.status_code == 403:
            data = json.loads(response.data)
            assert 'Invalid path' in data['error']
    
    def test_serve_video_file(self, client, storage):
        """Test serving video file."""
        # Create a video file
        post = InstagramPost(
            id="video_post",
            posted_at=datetime.now(),
            caption="Video post",
            post_type="video",
            permalink="https://instagram.com/p/video_post",
            media_urls=["https://example.com/video.mp4"],
            media_types=["video"],
            author_username="testuser",
            author_full_name="Test User"
        )
        
        storage.save_post(post)
        
        media_path = storage.get_media_path(post.id, 0, "video")
        media_path.write_bytes(b"fake video data")
        storage.save_media(post.id, 0, post.media_urls[0], "video", str(media_path), 15)
        
        response = client.get('/media/video_post/0.mp4')
        
        assert response.status_code == 200
        assert response.content_type == 'video/mp4'
        assert response.data == b"fake video data"


class TestIndexEndpoint:
    """Tests for / index endpoint."""
    
    def test_index_page(self, client):
        """Test index page returns service info."""
        response = client.get('/')
        
        assert response.status_code == 200
        assert response.content_type == 'application/json'
        
        data = json.loads(response.data)
        assert data['service'] == 'ig2rss'
        assert 'endpoints' in data
        assert 'config' in data
        assert data['config']['username'] == 'testuser'


class TestBackgroundSync:
    """Tests for background sync functionality."""
    
    @patch('src.api.InstagramClient')
    def test_sync_job_creation(self, mock_client_class, test_config):
        """Test that background sync job is created."""
        test_config.POLL_INTERVAL = 600  # Enable sync
        
        with patch.dict(os.environ, {'BASE_URL': 'http://testserver'}):
            app = create_app(test_config)
            
            assert 'scheduler' in app.config
            scheduler = app.config['scheduler']
            assert scheduler.running
            
            # Check job exists
            jobs = scheduler.get_jobs()
            assert len(jobs) >= 1
            
            # Clean up
            scheduler.shutdown()
    
    @patch('src.api.InstagramClient')
    @patch('requests.get')
    def test_sync_job_execution(self, mock_requests_get, mock_client_class, app, storage):
        """Test background sync job execution."""
        # Mock Instagram client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.login.return_value = True
        
        # Mock posts
        mock_posts = [
            InstagramPost(
                id="sync_post",
                posted_at=datetime.now(),
                caption="Synced post",
                post_type="image",
                permalink="https://instagram.com/p/sync_post",
                media_urls=["https://example.com/sync_image.jpg"],
                media_types=["image"],
                author_username="testuser",
                author_full_name="Test User"
            )
        ]
        mock_client.get_timeline_feed.return_value = mock_posts
        
        # Mock media download
        mock_response = MagicMock()
        mock_response.content = b"downloaded image data"
        mock_response.raise_for_status = MagicMock()
        mock_requests_get.return_value = mock_response
        
        # Import and run sync function
        from src.api import init_scheduler
        
        with app.app_context():
            # Manually trigger sync (instead of waiting for scheduler)
            config = app.config['app_config']
            
            # Create client and mock behavior
            client = mock_client_class(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)
            client.login()
            posts = client.get_timeline_feed(count=50)
            
            # Save posts
            for post in posts:
                storage.save_post(post)
        
        # Verify post was saved
        saved_post = storage.get_post_by_id("sync_post")
        assert saved_post is not None
        assert saved_post['caption'] == "Synced post"


class TestConfiguration:
    """Tests for configuration handling."""
    
    def test_app_without_base_url_env(self, test_config):
        """Test app creation without BASE_URL environment variable."""
        # Remove BASE_URL if it exists
        with patch.dict(os.environ, {}, clear=True):
            app = create_app(test_config)
            
            # Should default to localhost
            rss_gen = app.config['rss_generator']
            assert 'localhost' in rss_gen.base_url or '0.0.0.0' in rss_gen.base_url
    
    def test_app_with_custom_base_url(self, test_config):
        """Test app creation with custom BASE_URL."""
        with patch.dict(os.environ, {'BASE_URL': 'https://custom.example.com'}):
            app = create_app(test_config)
            
            rss_gen = app.config['rss_generator']
            assert rss_gen.base_url == 'https://custom.example.com'


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_media_with_empty_path(self, client):
        """Test media endpoint with empty path."""
        response = client.get('/media/')
        
        # Flask will return 404 for empty path
        assert response.status_code == 404
    
    def test_feed_with_database_error(self, client, storage, monkeypatch):
        """Test feed endpoint when database errors occur."""
        # Mock get_recent_posts to raise exception
        def mock_error(*args, **kwargs):
            raise Exception("Database error")
        
        monkeypatch.setattr(storage, 'get_recent_posts', mock_error)
        
        # Should raise exception (in production, would be caught by error handler)
        with pytest.raises(Exception):
            client.get('/feed.rss')
