"""Unit tests for RSS feed generator."""

import pytest
from datetime import datetime
from xml.etree import ElementTree as ET

from src.rss_generator import RSSGenerator


class TestRSSGenerator:
    """Test suite for RSSGenerator class."""
    
    @pytest.fixture
    def generator(self):
        """Create RSSGenerator instance for testing."""
        return RSSGenerator(
            base_url="https://example.com",
            channel_title="Test Instagram Feed",
            channel_description="Test feed description"
        )
    
    @pytest.fixture
    def sample_post(self):
        """Sample post data for testing."""
        return {
            'id': '12345',
            'posted_at': datetime(2025, 12, 8, 10, 30, 0),
            'caption': 'Test caption\nSecond line',
            'post_type': 'image',
            'permalink': 'https://instagram.com/p/test123',
            'author_username': 'testuser',
            'author_full_name': 'Test User',
            'media': [
                {
                    'media_type': 'image',
                    'media_url': 'https://instagram.com/image.jpg',
                    'local_path': '12345/0.jpg'
                }
            ]
        }
    
    def test_init(self, generator):
        """Test RSSGenerator initialization."""
        assert generator.base_url == "https://example.com"
        assert generator.channel_title == "Test Instagram Feed"
        assert generator.channel_description == "Test feed description"
    
    def test_init_strips_trailing_slash(self):
        """Test that base_url trailing slash is removed."""
        gen = RSSGenerator(
            base_url="https://example.com/",
            channel_title="Test",
            channel_description="Test"
        )
        assert gen.base_url == "https://example.com"
    
    def test_generate_feed_basic(self, generator, sample_post):
        """Test basic feed generation."""
        feed_xml = generator.generate_feed([sample_post])
        
        # Parse XML
        root = ET.fromstring(feed_xml)
        
        # Check root element
        assert root.tag == 'rss'
        assert root.attrib['version'] == '2.0'
        
        # Check channel exists
        channel = root.find('channel')
        assert channel is not None
    
    def test_generate_feed_channel_metadata(self, generator, sample_post):
        """Test channel metadata in generated feed."""
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        channel = root.find('channel')
        
        # Check channel metadata
        assert channel.find('title').text == "Test Instagram Feed"
        assert channel.find('link').text == "https://example.com"
        assert channel.find('description').text == "Test feed description"
        assert channel.find('generator').text == "ig2rss"
        
        # Check lastBuildDate exists
        assert channel.find('lastBuildDate') is not None
    
    def test_generate_feed_atom_self_link(self, generator, sample_post):
        """Test atom:link self-reference in feed."""
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        channel = root.find('channel')
        
        # Find atom:link
        atom_link = channel.find('{http://www.w3.org/2005/Atom}link')
        assert atom_link is not None
        assert atom_link.attrib['href'] == "https://example.com/feed.rss"
        assert atom_link.attrib['rel'] == "self"
        assert atom_link.attrib['type'] == "application/rss+xml"
    
    def test_generate_feed_single_post(self, generator, sample_post):
        """Test feed generation with single post."""
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        channel = root.find('channel')
        
        # Check item count
        items = channel.findall('item')
        assert len(items) == 1
        
        # Check item content
        item = items[0]
        assert item.find('title').text == "Test caption"
        assert item.find('link').text == "https://instagram.com/p/test123"
        assert item.find('guid').text == "12345"
        assert item.find('guid').attrib['isPermaLink'] == "false"
    
    def test_generate_feed_multiple_posts(self, generator, sample_post):
        """Test feed generation with multiple posts."""
        posts = [
            {**sample_post, 'id': '1', 'caption': 'Post 1'},
            {**sample_post, 'id': '2', 'caption': 'Post 2'},
            {**sample_post, 'id': '3', 'caption': 'Post 3'},
        ]
        
        feed_xml = generator.generate_feed(posts)
        root = ET.fromstring(feed_xml)
        channel = root.find('channel')
        
        items = channel.findall('item')
        assert len(items) == 3
    
    def test_generate_feed_empty_posts(self, generator):
        """Test feed generation with no posts."""
        feed_xml = generator.generate_feed([])
        root = ET.fromstring(feed_xml)
        channel = root.find('channel')
        
        items = channel.findall('item')
        assert len(items) == 0
    
    def test_extract_title_first_line(self, generator):
        """Test title extraction from caption."""
        title = generator._extract_title("First line\nSecond line")
        assert title == "First line"
    
    def test_extract_title_empty_caption(self, generator):
        """Test title extraction with empty caption."""
        title = generator._extract_title("")
        assert title == "Instagram Post"
        
        title = generator._extract_title(None)
        assert title == "Instagram Post"
    
    def test_extract_title_long_caption(self, generator):
        """Test title extraction with very long caption."""
        long_caption = "A" * 150
        title = generator._extract_title(long_caption)
        assert len(title) <= 100
        assert title.endswith("...")
    
    def test_extract_title_whitespace(self, generator):
        """Test title extraction with whitespace."""
        title = generator._extract_title("   Trimmed   \n\nSecond")
        assert title == "Trimmed"
    
    def test_format_rfc822(self, generator):
        """Test RFC 822 date formatting."""
        dt = datetime(2025, 12, 8, 10, 30, 0)
        rfc822 = generator._format_rfc822(dt)
        assert rfc822 == "Mon, 08 Dec 2025 10:30:00 +0000"
    
    def test_post_item_pubdate(self, generator, sample_post):
        """Test pubDate formatting in post item."""
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        item = root.find('.//item')
        
        pubdate = item.find('pubDate').text
        assert pubdate == "Mon, 08 Dec 2025 10:30:00 +0000"
    
    def test_post_item_author(self, generator, sample_post):
        """Test author formatting in post item."""
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        item = root.find('.//item')
        
        author = item.find('author').text
        assert author == "testuser@instagram.com (Test User)"
    
    def test_post_item_author_no_full_name(self, generator, sample_post):
        """Test author formatting without full name."""
        sample_post['author_full_name'] = None
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        item = root.find('.//item')
        
        author = item.find('author').text
        assert author == "testuser@instagram.com (testuser)"
    
    def test_format_description_image(self, generator, sample_post):
        """Test description formatting with image."""
        description = generator._format_description(sample_post)
        
        # First media item is skipped (it's in the enclosure)
        # So a single-media post should NOT have the image in description
        assert '<img' not in description
        
        # Check caption is still present
        assert 'Test caption<br/>Second line' in description
        
        # Check Instagram link
        assert '<a href="https://instagram.com/p/test123">View on Instagram</a>' in description
    
    def test_format_description_video(self, generator, sample_post):
        """Test description formatting with video."""
        sample_post['media'][0]['media_type'] = 'video'
        sample_post['media'][0]['local_path'] = '12345/0.mp4'
        
        description = generator._format_description(sample_post)
        
        # First media item is skipped (it's in the enclosure)
        # So a single-media post should NOT have the video in description
        assert '<video' not in description
        
        # Check caption is still present
        assert 'Test caption<br/>Second line' in description
    
    def test_format_description_carousel(self, generator, sample_post):
        """Test description formatting with multiple media (carousel)."""
        sample_post['media'] = [
            {
                'media_type': 'image',
                'media_url': 'https://instagram.com/image1.jpg',
                'local_path': '12345/0.jpg'
            },
            {
                'media_type': 'image',
                'media_url': 'https://instagram.com/image2.jpg',
                'local_path': '12345/1.jpg'
            },
            {
                'media_type': 'video',
                'media_url': 'https://instagram.com/video.mp4',
                'local_path': '12345/2.mp4'
            }
        ]
        
        description = generator._format_description(sample_post)
        
        # First media item is skipped (it's in the enclosure)
        # So carousel should have N-1 media items in description
        assert description.count('<img') == 1  # Only second image
        assert description.count('<video') == 1  # Third item (video)
        assert '12345/0.jpg' not in description  # First is skipped
        assert '12345/1.jpg' in description  # Second is included
        assert '12345/2.mp4' in description  # Third is included
    
    def test_format_description_no_local_path(self, generator, sample_post):
        """Test description uses Instagram URL when no local path."""
        # Add a second media item so something appears in description
        sample_post['media'].append({
            'media_type': 'image',
            'media_url': 'https://instagram.com/image2.jpg',
            'local_path': None
        })
        
        description = generator._format_description(sample_post)
        
        # First media is skipped, second should use Instagram URL
        assert 'https://instagram.com/image2.jpg' in description
    
    def test_format_description_html_escape(self, generator, sample_post):
        """Test HTML entities are escaped in description."""
        sample_post['caption'] = 'Test <script>alert("xss")</script> & "quotes"'
        
        description = generator._format_description(sample_post)
        
        # Check HTML is escaped
        assert '&lt;script&gt;' in description
        assert '&amp;' in description
        assert '&quot;' in description
        assert '<script>' not in description
    
    def test_format_description_no_caption(self, generator, sample_post):
        """Test description formatting without caption."""
        sample_post['caption'] = None
        
        description = generator._format_description(sample_post)
        
        # First media is skipped, so single-media post has no image in description
        # Should still have Instagram link
        assert 'View on Instagram' in description
    
    def test_format_description_linebreaks(self, generator, sample_post):
        """Test caption line breaks are converted to <br/>."""
        sample_post['caption'] = "Line 1\nLine 2\nLine 3"
        
        description = generator._format_description(sample_post)
        
        # Check line breaks converted
        assert 'Line 1<br/>Line 2<br/>Line 3' in description
    
    def test_post_item_datetime_string(self, generator, sample_post):
        """Test handling of datetime as ISO string."""
        sample_post['posted_at'] = '2025-12-08T10:30:00'
        
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        item = root.find('.//item')
        
        pubdate = item.find('pubDate').text
        assert pubdate == "Mon, 08 Dec 2025 10:30:00 +0000"
    
    def test_xml_declaration(self, generator, sample_post):
        """Test XML declaration is present."""
        feed_xml = generator.generate_feed([sample_post])
        
        # Check starts with XML declaration
        assert feed_xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    
    def test_namespace_declaration(self, generator, sample_post):
        """Test XML namespace declarations."""
        feed_xml = generator.generate_feed([sample_post])
        root = ET.fromstring(feed_xml)
        
        # Check atom namespace is declared (may use prefix like ns0 or atom)
        xml_str = ET.tostring(root, encoding='unicode')
        assert 'http://www.w3.org/2005/Atom' in xml_str
