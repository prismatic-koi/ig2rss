"""Tests for Instagram client story functionality."""

import pytest
from unittest.mock import Mock, MagicMock, patch
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
    
    def test_check_story_mute_status_not_muted(self):
        """Test detecting non-muted stories."""
        # Mock relationship response
        mock_relationship = Mock()
        mock_relationship.is_muting_reel = False
        
        with patch('src.instagram_client.Client') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_friendship_v1.return_value = mock_relationship
            
            client = InstagramClient("user", "pass")
            client._is_authenticated = True
            
            is_muted = client.check_story_mute_status("user123")
            assert is_muted is False
    
    def test_check_story_mute_status_muted(self):
        """Test detecting muted stories."""
        mock_relationship = Mock()
        mock_relationship.is_muting_reel = True
        
        with patch('src.instagram_client.Client') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_friendship_v1.return_value = mock_relationship
            
            client = InstagramClient("user", "pass")
            client._is_authenticated = True
            
            is_muted = client.check_story_mute_status("user123")
            assert is_muted is True
    
    def test_fetch_user_stories(self):
        """Test fetching stories from user."""
        # Mock story response
        mock_story = Mock()
        mock_story.pk = "story123"
        mock_story.media_type = 1  # Image
        mock_story.taken_at = datetime.now()
        mock_story.thumbnail_url = "https://example.com/story.jpg"
        mock_story.video_url = None
        mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
        
        # Mock empty lists for text content
        mock_story.story_polls = []
        mock_story.story_stickers = []
        
        with patch('src.instagram_client.Client') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = [mock_story]
            
            client = InstagramClient("user", "pass")
            client._is_authenticated = True
            
            stories = client.fetch_user_stories("user123", "testuser")
            assert len(stories) == 1
            assert stories[0].id == "story123"
            assert stories[0].username == "testuser"
    
    def test_convert_story_with_poll(self):
        """Test extracting poll question and options."""
        with patch('src.instagram_client.Client'):
            client = InstagramClient("user", "pass")
            
            # Mock story with poll
            mock_story = Mock()
            mock_story.pk = "story456"
            mock_story.media_type = 1
            mock_story.taken_at = datetime.now()
            mock_story.thumbnail_url = "https://example.com/story.jpg"
            mock_story.video_url = None
            mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
            
            # Poll
            mock_poll = Mock()
            mock_poll.question = "What's your favorite?"
            mock_poll.tallies = [
                Mock(text="Option A", count=10),
                Mock(text="Option B", count=5)
            ]
            mock_story.story_polls = [mock_poll]
            mock_story.story_stickers = []
            
            story = client._convert_story_to_instagram_story(mock_story)
            
            assert story is not None
            assert story.poll_question == "What's your favorite?"
            assert story.poll_options == ["Option A", "Option B"]
    
    def test_convert_story_with_link_text(self):
        """Test extracting link text from stickers."""
        with patch('src.instagram_client.Client'):
            client = InstagramClient("user", "pass")
            
            # Mock story with link sticker
            mock_story = Mock()
            mock_story.pk = "story789"
            mock_story.media_type = 1
            mock_story.taken_at = datetime.now()
            mock_story.thumbnail_url = "https://example.com/story.jpg"
            mock_story.video_url = None
            mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
            mock_story.story_polls = []
            
            # Link sticker
            mock_sticker = Mock()
            mock_sticker.story_link = Mock()
            mock_sticker.story_link.link_title = "Swipe up!"
            mock_story.story_stickers = [mock_sticker]
            
            story = client._convert_story_to_instagram_story(mock_story)
            
            assert story is not None
            assert story.link_text == "Swipe up!"
    
    def test_convert_story_video(self):
        """Test converting video story."""
        with patch('src.instagram_client.Client'):
            client = InstagramClient("user", "pass")
            
            mock_story = Mock()
            mock_story.pk = "story_video"
            mock_story.media_type = 2  # Video
            mock_story.taken_at = datetime.now()
            mock_story.thumbnail_url = "https://example.com/thumb.jpg"
            mock_story.video_url = "https://example.com/video.mp4"
            mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
            mock_story.story_polls = []
            mock_story.story_stickers = []
            
            story = client._convert_story_to_instagram_story(mock_story)
            
            assert story is not None
            assert story.media_type == "video"
            assert story.media_url == "https://example.com/video.mp4"
    
    def test_check_account_for_new_stories_no_stories(self):
        """Test checking account with no stories."""
        with patch('src.instagram_client.Client') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = []
            
            client = InstagramClient("user", "pass")
            client._is_authenticated = True
            
            has_new, stories, metadata = client.check_account_for_new_stories("user123", "testuser")
            
            assert has_new is False
            assert len(stories) == 0
            assert metadata['story_count'] == 0
    
    def test_check_account_for_new_stories_with_new_stories(self):
        """Test checking account with new stories."""
        mock_story = Mock()
        mock_story.pk = "story_new"
        mock_story.media_type = 1
        mock_story.taken_at = datetime.now()
        mock_story.thumbnail_url = "https://example.com/story.jpg"
        mock_story.video_url = None
        mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
        mock_story.story_polls = []
        mock_story.story_stickers = []
        
        with patch('src.instagram_client.Client') as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = [mock_story]
            
            client = InstagramClient("user", "pass")
            client._is_authenticated = True
            
            has_new, stories, metadata = client.check_account_for_new_stories(
                "user123", "testuser", last_known_story_id="story_old"
            )
            
            assert has_new is True
            assert len(stories) == 1
            assert metadata['latest_story_id'] == "story_new"
            assert metadata['story_count'] == 1
