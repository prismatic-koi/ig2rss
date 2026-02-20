"""Tests for RSS generator story functionality."""

import pytest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from src.rss_generator import RSSGenerator


@pytest.fixture
def generator():
    """Create RSSGenerator instance."""
    return RSSGenerator(
        base_url="http://localhost:5000",
        channel_title="Test Feed",
        channel_description="Test Description"
    )


@pytest.fixture
def sample_posts():
    """Create sample posts for testing."""
    return [
        {
            'id': 'post1',
            'author_username': 'testuser',
            'full_name': 'Test User',
            'posted_at': datetime.now() - timedelta(hours=2),
            'caption': 'Test post 1',
            'permalink': 'https://instagram.com/p/post1',
            'media_urls': ['https://example.com/img1.jpg'],
            'media_types': ['image'],
            'local_paths': ['post1/0.jpg']
        },
        {
            'id': 'post2',
            'author_username': 'testuser',
            'full_name': 'Test User',
            'posted_at': datetime.now() - timedelta(hours=5),
            'caption': 'Test post 2',
            'permalink': 'https://instagram.com/p/post2',
            'media_urls': ['https://example.com/img2.jpg'],
            'media_types': ['image'],
            'local_paths': ['post2/0.jpg']
        }
    ]


@pytest.fixture
def sample_stories():
    """Create sample stories for testing."""
    return [
        {
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now() - timedelta(hours=1),
            'expires_at': datetime.now() + timedelta(hours=23),
            'media_url': 'https://example.com/story1.jpg',
            'media_type': 'image',
            'local_path': 'story1/0.jpg',
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': 'What do you think?',
            'poll_options': '["Option A", "Option B"]',
            'link_text': None,
            'sticker_text': None
        },
        {
            'id': 'story2',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now() - timedelta(hours=3),
            'expires_at': datetime.now() + timedelta(hours=21),
            'media_url': 'https://example.com/story2.mp4',
            'media_type': 'video',
            'local_path': 'story2/0.mp4',
            'permalink': 'https://instagram.com/stories/testuser/story2/',
            'poll_question': None,
            'poll_options': None,
            'link_text': 'Swipe up!',
            'sticker_text': None
        }
    ]


class TestRSSGeneratorStories:
    """Tests for RSS generator with stories."""
    
    def test_unified_feed_sorting(self, generator, sample_posts, sample_stories):
        """Test that posts and stories are properly sorted by date in unified feed."""
        # Generate feed with both posts and stories
        xml = generator.generate_feed(sample_posts, stories=sample_stories, limit=50, days=7)
        
        # Parse XML
        root = ET.fromstring(xml)
        channel = root.find('channel')
        items = channel.findall('item')
        
        # Should have 4 items total (2 posts + 2 stories)
        assert len(items) == 4
        
        # Extract dates and titles
        pub_dates = []
        titles = []
        for item in items:
            pub_date = item.find('pubDate').text
            title = item.find('title').text
            pub_dates.append(pub_date)
            titles.append(title)
        
        # Verify chronological order (newest first)
        # story1 (1h ago), post1 (2h ago), story2 (3h ago), post2 (5h ago)
        assert '[STORY]' in titles[0]  # Newest should be story
        assert '[STORY]' not in titles[1]  # Second should be post
        assert '[STORY]' in titles[2]  # Third should be story
        assert '[STORY]' not in titles[3]  # Oldest should be post
    
    def test_story_prefix_in_title(self, generator, sample_stories):
        """Test that story titles have [STORY] prefix."""
        xml = generator.generate_feed([], stories=sample_stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        channel = root.find('channel')
        items = channel.findall('item')
        
        # All items should have [STORY] prefix
        for item in items:
            title = item.find('title').text
            assert title.startswith('[STORY]')
    
    def test_story_poll_text_in_title(self, generator):
        """Test that poll questions appear in story titles."""
        stories = [{
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24),
            'media_url': 'https://example.com/story1.jpg',
            'media_type': 'image',
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': 'What is your favorite color?',
            'poll_options': '["Red", "Blue", "Green"]',
            'link_text': None,
            'sticker_text': None
        }]
        
        xml = generator.generate_feed([], stories=stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        item = root.find('.//item')
        title = item.find('title').text
        
        # Title should include poll question
        assert 'What is your favorite color?' in title
    
    def test_story_link_text_in_title(self, generator):
        """Test that link text appears in story titles when no poll."""
        stories = [{
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24),
            'media_url': 'https://example.com/story1.jpg',
            'media_type': 'image',
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': None,
            'poll_options': None,
            'link_text': 'Check out this link!',
            'sticker_text': None
        }]
        
        xml = generator.generate_feed([], stories=stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        item = root.find('.//item')
        title = item.find('title').text
        
        # Title should include link text
        assert 'Check out this link!' in title
    
    def test_story_poll_options_in_description(self, generator):
        """Test that poll options appear in RSS description."""
        stories = [{
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24),
            'media_url': 'https://example.com/story1.jpg',
            'media_type': 'image',
            'local_path': 'story1/0.jpg',
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': 'Pick one:',
            'poll_options': '["Choice A", "Choice B", "Choice C"]',
            'link_text': None,
            'sticker_text': None
        }]
        
        xml = generator.generate_feed([], stories=stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        item = root.find('.//item')
        description = item.find('description').text
        
        # Description should include poll question and options
        assert 'Pick one:' in description
        assert 'Choice A' in description
        assert 'Choice B' in description
        assert 'Choice C' in description
    
    def test_story_empty_poll_options(self, generator):
        """Test handling of empty poll options."""
        stories = [{
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24),
            'media_url': 'https://example.com/story1.jpg',
            'media_type': 'image',
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': 'What do you think?',
            'poll_options': None,  # Empty/missing options
            'link_text': None,
            'sticker_text': None
        }]
        
        # Should not raise exception
        xml = generator.generate_feed([], stories=stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        item = root.find('.//item')
        description = item.find('description').text
        
        # Should still show poll question
        assert 'What do you think?' in description
    
    def test_story_missing_sticker_data(self, generator):
        """Test handling of missing sticker data."""
        stories = [{
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24),
            'media_url': 'https://example.com/story1.jpg',
            'media_type': 'image',
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': None,
            'poll_options': None,
            'link_text': None,
            'sticker_text': None  # Missing sticker data
        }]
        
        # Should not raise exception
        xml = generator.generate_feed([], stories=stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        item = root.find('.//item')
        title = item.find('title').text
        
        # Should have basic story title
        assert '[STORY]' in title
        assert 'testuser' in title or 'Test User' in title
    
    def test_story_video_enclosure(self, generator):
        """Test that video stories have correct enclosure type."""
        stories = [{
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24),
            'media_url': 'https://example.com/story1.mp4',
            'media_type': 'video',
            'local_path': 'story1/0.mp4',
            'file_size': 1024000,
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': None,
            'poll_options': None,
            'link_text': None,
            'sticker_text': None
        }]
        
        xml = generator.generate_feed([], stories=stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        item = root.find('.//item')
        enclosure = item.find('enclosure')
        
        assert enclosure is not None
        assert enclosure.get('type') == 'video/mp4'
        assert 'story1/0.mp4' in enclosure.get('url')
    
    def test_story_image_in_description(self, generator):
        """Test that story images are embedded in description."""
        stories = [{
            'id': 'story1',
            'username': 'testuser',
            'full_name': 'Test User',
            'taken_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=24),
            'media_url': 'https://example.com/story1.jpg',
            'media_type': 'image',
            'local_path': 'story1/0.jpg',
            'permalink': 'https://instagram.com/stories/testuser/story1/',
            'poll_question': None,
            'poll_options': None,
            'link_text': None,
            'sticker_text': None
        }]
        
        xml = generator.generate_feed([], stories=stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        item = root.find('.//item')
        description = item.find('description').text
        
        # Description should contain img tag
        assert '<img' in description
        assert 'story1/0.jpg' in description
    
    def test_unified_feed_empty_stories(self, generator, sample_posts):
        """Test that feed works with posts but no stories."""
        xml = generator.generate_feed(sample_posts, stories=[], limit=50, days=7)
        
        root = ET.fromstring(xml)
        channel = root.find('channel')
        items = channel.findall('item')
        
        # Should have only posts
        assert len(items) == len(sample_posts)
        
        # None should have [STORY] prefix
        for item in items:
            title = item.find('title').text
            assert '[STORY]' not in title
    
    def test_unified_feed_only_stories(self, generator, sample_stories):
        """Test that feed works with only stories, no posts."""
        xml = generator.generate_feed([], stories=sample_stories, limit=50, days=7)
        
        root = ET.fromstring(xml)
        channel = root.find('channel')
        items = channel.findall('item')
        
        # Should have only stories
        assert len(items) == len(sample_stories)
        
        # All should have [STORY] prefix
        for item in items:
            title = item.find('title').text
            assert '[STORY]' in title
