"""Unit tests for instagram_client module.

Tests the InstagramClient class with mocked instagrapi responses.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from pathlib import Path
import tempfile

from src.instagram_client import InstagramClient, InstagramPost
from instagrapi.exceptions import (
    LoginRequired,
    PleaseWaitFewMinutes,
    ChallengeRequired,
    ClientError,
)


def create_feed_response(media_list):
    """Helper to create a properly structured feed response.
    
    The Instagram API returns a dict with 'feed_items', where each item
    has a 'media_or_ad' field containing the media data.
    """
    feed_items = []
    for media in media_list:
        feed_items.append({
            "media_or_ad": media
        })
    return {"feed_items": feed_items}


@pytest.fixture
def mock_client():
    """Create a mock instagrapi Client."""
    with patch("src.instagram_client.Client") as mock:
        yield mock


@pytest.fixture
def instagram_client(mock_client):
    """Create an InstagramClient with mocked instagrapi."""
    client = InstagramClient("test_user", "test_pass")
    return client


@pytest.fixture
def mock_media_photo():
    """Create a mock photo media object from Instagram."""
    media = Mock()
    media.pk = "12345678901234567"
    media.media_type = 1  # Photo
    media.taken_at = datetime(2024, 1, 15, 12, 0, 0)
    media.caption_text = "Test photo caption"
    media.code = "ABC123"
    media.thumbnail_url = "https://instagram.com/photo.jpg"
    media.user = Mock()
    media.user.username = "test_author"
    media.user.full_name = "Test Author"
    return media


@pytest.fixture
def mock_media_video():
    """Create a mock video media object from Instagram."""
    media = Mock()
    media.pk = "98765432109876543"
    media.media_type = 2  # Video
    media.taken_at = datetime(2024, 1, 16, 14, 30, 0)
    media.caption_text = "Test video caption"
    media.code = "XYZ789"
    media.video_url = "https://instagram.com/video.mp4"
    media.thumbnail_url = "https://instagram.com/video_thumb.jpg"
    media.user = Mock()
    media.user.username = "video_author"
    media.user.full_name = "Video Author"
    return media


@pytest.fixture
def mock_media_carousel():
    """Create a mock carousel media object from Instagram."""
    media = Mock()
    media.pk = "11111111111111111"
    media.media_type = 8  # Carousel
    media.taken_at = datetime(2024, 1, 17, 10, 0, 0)
    media.caption_text = "Test carousel"
    media.code = "CAR123"
    
    # Create mock resources
    resource1 = Mock()
    resource1.media_type = 1  # Photo
    resource1.thumbnail_url = "https://instagram.com/carousel1.jpg"
    
    resource2 = Mock()
    resource2.media_type = 2  # Video
    resource2.video_url = "https://instagram.com/carousel2.mp4"
    
    media.resources = [resource1, resource2]
    media.user = Mock()
    media.user.username = "carousel_author"
    media.user.full_name = "Carousel Author"
    return media


class TestInstagramClientInit:
    """Tests for InstagramClient initialization."""
    
    def test_init_sets_credentials(self, instagram_client):
        """Test that credentials are stored correctly."""
        assert instagram_client.username == "test_user"
        assert instagram_client.password == "test_pass"
        assert not instagram_client._is_authenticated
    
    def test_init_creates_client(self, instagram_client, mock_client):
        """Test that instagrapi Client is instantiated."""
        mock_client.assert_called_once()


class TestInstagramClientLogin:
    """Tests for login functionality."""
    
    def test_login_success(self, instagram_client):
        """Test successful login."""
        instagram_client.client.login = Mock(return_value=True)
        
        result = instagram_client.login()
        
        assert result is True
        assert instagram_client._is_authenticated is True
        instagram_client.client.login.assert_called_once_with("test_user", "test_pass", verification_code=None)
    
    def test_login_with_2fa(self, mock_client):
        """Test successful login with 2FA."""
        # Create client with TOTP seed
        client = InstagramClient("test_user", "test_pass", totp_seed="TEST_SEED_1234567890")
        
        # Mock totp_generate_code
        client.client.totp_generate_code = Mock(return_value="123456")
        client.client.login = Mock(return_value=True)
        
        result = client.login()
        
        assert result is True
        assert client._is_authenticated is True
        # Verify TOTP code was generated
        client.client.totp_generate_code.assert_called_once_with("TEST_SEED_1234567890")
        # Verify login was called with verification code
        client.client.login.assert_called_once_with("test_user", "test_pass", verification_code="123456")
    
    def test_login_already_authenticated(self, instagram_client):
        """Test login when already authenticated skips re-authentication."""
        instagram_client._is_authenticated = True
        instagram_client.client.login = Mock()
        
        result = instagram_client.login()
        
        assert result is True
        instagram_client.client.login.assert_not_called()
    
    def test_login_invalid_credentials(self, instagram_client):
        """Test login with invalid credentials raises LoginRequired."""
        instagram_client.client.login = Mock(side_effect=LoginRequired("Invalid"))
        
        with pytest.raises(LoginRequired):
            instagram_client.login()
        
        assert instagram_client._is_authenticated is False
    
    def test_login_challenge_required(self, instagram_client):
        """Test login with 2FA/challenge raises ChallengeRequired."""
        instagram_client.client.login = Mock(side_effect=ChallengeRequired("2FA"))
        
        with pytest.raises(ChallengeRequired):
            instagram_client.login()
        
        assert instagram_client._is_authenticated is False
    
    def test_login_unexpected_error(self, instagram_client):
        """Test login with unexpected error is propagated."""
        instagram_client.client.login = Mock(side_effect=RuntimeError("Unexpected"))
        
        with pytest.raises(RuntimeError):
            instagram_client.login()
    
    def test_init_with_totp_seed(self, mock_client):
        """Test initialization with TOTP seed."""
        client = InstagramClient(
            username="test_user",
            password="test_pass",
            session_file="/tmp/session.json",
            totp_seed="TEST_SEED_1234567890"
        )
        
        assert client.username == "test_user"
        assert client.password == "test_pass"
        assert client.session_file == "/tmp/session.json"
        assert client.totp_seed == "TEST_SEED_1234567890"
        assert not client._is_authenticated


class TestInstagramClientGetTimelineFeed:
    """Tests for fetching timeline feed."""
    
    def test_get_timeline_feed_not_authenticated(self, instagram_client):
        """Test fetching feed without authentication raises LoginRequired."""
        with pytest.raises(LoginRequired):
            instagram_client.get_timeline_feed()
    
    def test_get_timeline_feed_success(self, instagram_client, mock_media_photo):
        """Test successful feed fetch."""
        instagram_client._is_authenticated = True
        
        # Mock the feed response structure
        feed_response = create_feed_response([{"pk": "12345678901234567"}])
        instagram_client.client.get_timeline_feed = Mock(return_value=feed_response)
        
        # Mock extract_media_v1 to return our mock_media_photo
        with patch("src.instagram_client.extract_media_v1", return_value=mock_media_photo):
            posts = instagram_client.get_timeline_feed(count=1)
        
        assert len(posts) == 1
        assert posts[0].id == "12345678901234567"
        assert posts[0].author_username == "test_author"
        assert posts[0].post_type == "photo"
    
    def test_get_timeline_feed_multiple_posts(
        self, instagram_client, mock_media_photo, mock_media_video
    ):
        """Test fetching multiple posts."""
        instagram_client._is_authenticated = True
        
        # Mock the feed response structure
        feed_response = create_feed_response([
            {"pk": "12345678901234567"},
            {"pk": "98765432109876543"}
        ])
        instagram_client.client.get_timeline_feed = Mock(return_value=feed_response)
        
        # Mock extract_media_v1 to return the appropriate mock based on pk
        def extract_side_effect(data):
            if data["pk"] == "12345678901234567":
                return mock_media_photo
            return mock_media_video
        
        with patch("src.instagram_client.extract_media_v1", side_effect=extract_side_effect):
            posts = instagram_client.get_timeline_feed(count=2)
        
        assert len(posts) == 2
        assert posts[0].post_type == "photo"
        assert posts[1].post_type == "video"
    
    def test_get_timeline_feed_respects_count_limit(
        self, instagram_client, mock_media_photo
    ):
        """Test that count parameter limits returned posts."""
        instagram_client._is_authenticated = True
        
        # Return 5 posts but request only 3
        feed_response = create_feed_response([{"pk": str(i)} for i in range(5)])
        instagram_client.client.get_timeline_feed = Mock(return_value=feed_response)
        
        # Create unique media objects with different IDs to avoid deduplication
        media_objects = []
        for i in range(5):
            media = Mock()
            media.pk = f"1234567890123456{i}"
            media.media_type = 1
            media.taken_at = datetime(2024, 1, 15, 12, 0, 0)
            media.caption_text = "Test photo caption"
            media.code = "ABC123"
            media.thumbnail_url = "https://instagram.com/photo.jpg"
            media.user = Mock()
            media.user.username = "test_author"
            media.user.full_name = "Test Author"
            media_objects.append(media)
        
        with patch("src.instagram_client.extract_media_v1", side_effect=media_objects):
            posts = instagram_client.get_timeline_feed(count=3)
        
        assert len(posts) == 3
    
    def test_get_timeline_feed_handles_conversion_errors(
        self, instagram_client, mock_media_photo
    ):
        """Test that posts with conversion errors are skipped."""
        instagram_client._is_authenticated = True
        
        # Create feed with good and bad media
        feed_response = create_feed_response([
            {"pk": "12345678901234567"},
            {"pk": "bad"}
        ])
        instagram_client.client.get_timeline_feed = Mock(return_value=feed_response)
        
        # First returns good media, second raises exception
        def extract_side_effect(data):
            if data["pk"] == "12345678901234567":
                return mock_media_photo
            raise Exception("Conversion failed")
        
        with patch("src.instagram_client.extract_media_v1", side_effect=extract_side_effect):
            posts = instagram_client.get_timeline_feed(count=2)
        
        # Should only return the valid post
        assert len(posts) == 1
        assert posts[0].id == "12345678901234567"


class TestInstagramClientRetryLogic:
    """Tests for retry logic with exponential backoff."""
    
    def test_retry_on_rate_limit(self, instagram_client):
        """Test retry logic on rate limiting."""
        instagram_client._is_authenticated = True
        
        # Fail twice with rate limit, then succeed with empty feed
        empty_feed = {"feed_items": []}
        instagram_client.client.get_timeline_feed = Mock(
            side_effect=[
                PleaseWaitFewMinutes("Rate limited"),
                PleaseWaitFewMinutes("Rate limited"),
                empty_feed,
            ]
        )
        
        with patch("time.sleep"):  # Mock sleep to speed up test
            posts = instagram_client.get_timeline_feed()
        
        assert posts == []
        assert instagram_client.client.get_timeline_feed.call_count == 3
    
    def test_retry_on_client_error(self, instagram_client):
        """Test retry logic on ClientError."""
        instagram_client._is_authenticated = True
        
        # Fail once, then succeed with empty feed
        empty_feed = {"feed_items": []}
        instagram_client.client.get_timeline_feed = Mock(
            side_effect=[ClientError("Network error"), empty_feed]
        )
        
        with patch("time.sleep"):
            posts = instagram_client.get_timeline_feed()
        
        assert posts == []
        assert instagram_client.client.get_timeline_feed.call_count == 2
    
    def test_retry_exhausted(self, instagram_client):
        """Test that exception is raised when retries are exhausted."""
        instagram_client._is_authenticated = True
        instagram_client.max_retries = 3
        
        # Always fail
        instagram_client.client.get_timeline_feed = Mock(
            side_effect=ClientError("Network error")
        )
        
        with patch("time.sleep"):
            with pytest.raises(ClientError):
                instagram_client.get_timeline_feed()
        
        assert instagram_client.client.get_timeline_feed.call_count == 3
    
    def test_no_retry_on_unexpected_error(self, instagram_client):
        """Test that unexpected errors are not retried."""
        instagram_client._is_authenticated = True
        
        instagram_client.client.get_timeline_feed = Mock(
            side_effect=ValueError("Unexpected error")
        )
        
        with pytest.raises(ValueError):
            instagram_client.get_timeline_feed()
        
        # Should only be called once (no retry)
        assert instagram_client.client.get_timeline_feed.call_count == 1


class TestInstagramClientMediaConversion:
    """Tests for converting instagrapi Media to InstagramPost."""
    
    def test_convert_photo(self, instagram_client, mock_media_photo):
        """Test converting photo media to InstagramPost."""
        post = instagram_client._convert_media_to_post(mock_media_photo)
        
        assert post is not None
        assert post.id == "12345678901234567"
        assert post.post_type == "photo"
        assert post.author_username == "test_author"
        assert post.author_full_name == "Test Author"
        assert post.caption == "Test photo caption"
        assert post.permalink == "https://www.instagram.com/p/ABC123/"
        assert len(post.media_urls) == 1
        assert post.media_urls[0] == "https://instagram.com/photo.jpg"
        assert post.media_types == ["image"]
    
    def test_convert_video(self, instagram_client, mock_media_video):
        """Test converting video media to InstagramPost."""
        post = instagram_client._convert_media_to_post(mock_media_video)
        
        assert post is not None
        assert post.id == "98765432109876543"
        assert post.post_type == "video"
        assert post.author_username == "video_author"
        assert len(post.media_urls) == 1
        assert post.media_urls[0] == "https://instagram.com/video.mp4"
        assert post.media_types == ["video"]
    
    def test_convert_carousel(self, instagram_client, mock_media_carousel):
        """Test converting carousel media to InstagramPost."""
        post = instagram_client._convert_media_to_post(mock_media_carousel)
        
        assert post is not None
        assert post.id == "11111111111111111"
        assert post.post_type == "carousel"
        assert post.author_username == "carousel_author"
        assert len(post.media_urls) == 2
        assert post.media_urls[0] == "https://instagram.com/carousel1.jpg"
        assert post.media_urls[1] == "https://instagram.com/carousel2.mp4"
        assert post.media_types == ["image", "video"]
    
    def test_convert_unknown_media_type(self, instagram_client):
        """Test that unknown media types return None."""
        media = Mock()
        media.id = "unknown"
        media.media_type = 999  # Unknown
        
        post = instagram_client._convert_media_to_post(media)
        
        assert post is None
    
    def test_convert_media_without_caption(self, instagram_client, mock_media_photo):
        """Test converting media without caption."""
        mock_media_photo.caption_text = None
        
        post = instagram_client._convert_media_to_post(mock_media_photo)
        
        assert post is not None
        assert post.caption is None


class TestInstagramClientDownloadMedia:
    """Tests for downloading media files."""
    
    @patch("requests.get")
    def test_download_media_success(self, mock_get, instagram_client):
        """Test successful media download."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_content = Mock(return_value=[b"image data"])
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "test.jpg"
            result = instagram_client.download_media(
                "https://instagram.com/photo.jpg", str(local_path)
            )
        
        assert result is True
        mock_get.assert_called_once()
    
    @patch("requests.get")
    def test_download_media_creates_parent_dirs(self, mock_get, instagram_client):
        """Test that parent directories are created if they don't exist."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_content = Mock(return_value=[b"data"])
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "subdir" / "nested" / "test.jpg"
            result = instagram_client.download_media(
                "https://instagram.com/photo.jpg", str(local_path)
            )
            
            # Check that parent directories were created
            assert result is True
            assert local_path.parent.exists()
    
    @patch("requests.get")
    def test_download_media_network_error(self, mock_get, instagram_client):
        """Test download failure on network error."""
        mock_get.side_effect = ConnectionError("Network error")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "test.jpg"
            result = instagram_client.download_media(
                "https://instagram.com/photo.jpg", str(local_path)
            )
        
        assert result is False
    
    @patch("requests.get")
    def test_download_media_retry_on_failure(self, mock_get, instagram_client):
        """Test that download retries on failure."""
        # Fail once, then succeed
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_content = Mock(return_value=[b"data"])
        mock_response.raise_for_status = Mock()
        
        mock_get.side_effect = [ConnectionError("Network error"), mock_response]
        
        with patch("time.sleep"):  # Mock sleep
            with tempfile.TemporaryDirectory() as tmpdir:
                local_path = Path(tmpdir) / "test.jpg"
                result = instagram_client.download_media(
                    "https://instagram.com/photo.jpg", str(local_path)
                )
        
        assert result is True
        assert mock_get.call_count == 2


class TestInstagramClientLogout:
    """Tests for logout functionality."""
    
    def test_logout(self, instagram_client):
        """Test logout clears authentication state."""
        instagram_client._is_authenticated = True
        
        instagram_client.logout()
        
        assert instagram_client._is_authenticated is False
    
    def test_logout_when_not_authenticated(self, instagram_client):
        """Test logout when not authenticated doesn't error."""
        instagram_client._is_authenticated = False
        
        instagram_client.logout()  # Should not raise
        
        assert instagram_client._is_authenticated is False
