"""Tests for Instagram client story functionality."""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.instagram_client import InstagramClient, InstagramStory, InstagramChallengeError


class TestCheckStoryMuteStatus:
    """Tests for check_story_mute_status."""

    def test_not_muted(self):
        """Test detecting non-muted stories."""
        mock_relationship = Mock()
        mock_relationship.is_muting_reel = False

        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_friendship_v1.return_value = mock_relationship

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            is_muted = client.check_story_mute_status("user123")
            assert is_muted is False

    def test_muted(self):
        """Test detecting muted stories."""
        mock_relationship = Mock()
        mock_relationship.is_muting_reel = True

        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_friendship_v1.return_value = mock_relationship

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            is_muted = client.check_story_mute_status("user123")
            assert is_muted is True

    def test_challenge_raises_error(self):
        """Test that ChallengeRequired raises InstagramChallengeError."""
        from instagrapi.exceptions import ChallengeRequired

        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_friendship_v1.side_effect = ChallengeRequired()

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            with pytest.raises(InstagramChallengeError):
                client.check_story_mute_status("user123")

    def test_error_defaults_to_not_muted(self):
        """Test that generic errors default to not muted."""
        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_friendship_v1.side_effect = Exception("network error")

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            is_muted = client.check_story_mute_status("user123")
            assert is_muted is False


class TestFetchUserStories:
    """Tests for fetch_user_stories."""

    def test_fetch_stories(self):
        """Test fetching stories from user."""
        mock_story = Mock()
        mock_story.pk = "story123"
        mock_story.media_type = 1  # Image
        mock_story.taken_at = datetime.now()
        mock_story.thumbnail_url = "https://example.com/story.jpg"
        mock_story.video_url = None
        mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
        mock_story.story_polls = []
        mock_story.story_stickers = []

        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = [mock_story]

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            stories = client.fetch_user_stories("user123", "testuser")
            assert len(stories) == 1
            assert stories[0].id == "story123"
            assert stories[0].username == "testuser"

    def test_fetch_no_stories(self):
        """Test fetching from user with no stories."""
        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = []

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            stories = client.fetch_user_stories("user123", "testuser")
            assert len(stories) == 0

    def test_challenge_raises_error(self):
        """Test that ChallengeRequired raises InstagramChallengeError."""
        from instagrapi.exceptions import ChallengeRequired

        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.side_effect = ChallengeRequired()

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            with pytest.raises(InstagramChallengeError):
                client.fetch_user_stories("user123", "testuser")


class TestConvertStory:
    """Tests for _convert_story_to_instagram_story."""

    def _make_mock_story(self, **kwargs):
        """Create a mock story with sensible defaults."""
        story = Mock()
        story.pk = kwargs.get("pk", "story456")
        story.media_type = kwargs.get("media_type", 1)
        story.taken_at = kwargs.get("taken_at", datetime.now())
        story.thumbnail_url = kwargs.get("thumbnail_url", "https://example.com/story.jpg")
        story.video_url = kwargs.get("video_url", None)
        story.user = Mock(
            pk=kwargs.get("user_pk", "user123"),
            username=kwargs.get("username", "testuser"),
            full_name=kwargs.get("full_name", "Test User"),
        )
        story.story_polls = kwargs.get("story_polls", [])
        story.story_stickers = kwargs.get("story_stickers", [])
        return story

    def test_image_story(self):
        """Test converting image story."""
        with patch("src.instagram_client.Client"):
            client = InstagramClient("user", "pass")
            story = self._make_mock_story(media_type=1)

            result = client._convert_story_to_instagram_story(story)

            assert result is not None
            assert result.media_type == "image"
            assert "story.jpg" in result.media_url

    def test_video_story(self):
        """Test converting video story."""
        with patch("src.instagram_client.Client"):
            client = InstagramClient("user", "pass")
            story = self._make_mock_story(
                media_type=2,
                video_url="https://example.com/video.mp4",
            )

            result = client._convert_story_to_instagram_story(story)

            assert result is not None
            assert result.media_type == "video"
            assert result.media_url == "https://example.com/video.mp4"

    def test_story_with_poll(self):
        """Test extracting poll question and options."""
        mock_poll = Mock()
        mock_poll.question = "What's your favorite?"
        mock_poll.tallies = [
            Mock(text="Option A", count=10),
            Mock(text="Option B", count=5),
        ]

        with patch("src.instagram_client.Client"):
            client = InstagramClient("user", "pass")
            story = self._make_mock_story(story_polls=[mock_poll])

            result = client._convert_story_to_instagram_story(story)

            assert result is not None
            assert result.poll_question == "What's your favorite?"
            assert result.poll_options == ["Option A", "Option B"]

    def test_story_with_link_sticker(self):
        """Test extracting link text from stickers."""
        mock_sticker = Mock()
        mock_sticker.story_link = Mock()
        mock_sticker.story_link.link_title = "Swipe up!"
        # No extra attribute
        mock_sticker.extra = None

        with patch("src.instagram_client.Client"):
            client = InstagramClient("user", "pass")
            story = self._make_mock_story(story_stickers=[mock_sticker])

            result = client._convert_story_to_instagram_story(story)

            assert result is not None
            assert result.link_text == "Swipe up!"

    def test_story_permalink(self):
        """Test story permalink generation."""
        with patch("src.instagram_client.Client"):
            client = InstagramClient("user", "pass")
            story = self._make_mock_story(pk="12345", username="cooluser")

            result = client._convert_story_to_instagram_story(story)

            assert result is not None
            assert result.permalink == "https://www.instagram.com/stories/cooluser/12345/"

    def test_story_expires_at(self):
        """Test story expiration is 24 hours after taken_at."""
        taken = datetime(2026, 1, 1, 12, 0, 0)
        with patch("src.instagram_client.Client"):
            client = InstagramClient("user", "pass")
            story = self._make_mock_story(taken_at=taken)

            result = client._convert_story_to_instagram_story(story)

            assert result is not None
            assert result.expires_at == datetime(2026, 1, 2, 12, 0, 0)


class TestCheckAccountForNewStories:
    """Tests for check_account_for_new_stories."""

    def test_no_stories(self):
        """Test checking account with no stories."""
        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = []

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            has_new, stories, metadata = client.check_account_for_new_stories(
                "user123", "testuser"
            )

            assert has_new is False
            assert len(stories) == 0
            assert metadata["story_count"] == 0

    def test_with_new_stories(self):
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

        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = [mock_story]

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            has_new, stories, metadata = client.check_account_for_new_stories(
                "user123", "testuser", last_known_story_id="story_old"
            )

            assert has_new is True
            assert len(stories) == 1
            assert metadata["latest_story_id"] == "story_new"
            assert metadata["story_count"] == 1

    def test_no_new_stories_same_id(self):
        """Test checking account when latest story ID matches last known."""
        mock_story = Mock()
        mock_story.pk = "story_same"
        mock_story.media_type = 1
        mock_story.taken_at = datetime.now()
        mock_story.thumbnail_url = "https://example.com/story.jpg"
        mock_story.video_url = None
        mock_story.user = Mock(pk="user123", username="testuser", full_name="Test User")
        mock_story.story_polls = []
        mock_story.story_stickers = []

        with patch("src.instagram_client.Client") as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.user_stories.return_value = [mock_story]

            client = InstagramClient("user", "pass")
            client._is_authenticated = True

            has_new, stories, metadata = client.check_account_for_new_stories(
                "user123", "testuser", last_known_story_id="story_same"
            )

            assert has_new is False
            assert len(stories) == 0
            assert metadata["story_count"] == 1
