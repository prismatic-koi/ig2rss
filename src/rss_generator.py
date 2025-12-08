"""RSS 2.0 feed generator for Instagram posts.

This module generates valid RSS 2.0 XML feeds from stored Instagram posts,
with support for embedded images, videos, and carousel posts.
"""

import logging
import html
from datetime import datetime
from typing import List, Dict, Any, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


class RSSGenerator:
    """Generates RSS 2.0 feeds from Instagram posts."""
    
    def __init__(self, base_url: str, channel_title: str, channel_description: str):
        """Initialize RSS generator.
        
        Args:
            base_url: Base URL for the RSS feed (e.g., https://example.com)
            channel_title: Title of the RSS channel
            channel_description: Description of the RSS channel
        """
        self.base_url = base_url.rstrip('/')
        self.channel_title = channel_title
        self.channel_description = channel_description
        
        logger.info(f"RSSGenerator initialized (base_url={base_url})")
    
    def generate_feed(self, posts: List[Dict[str, Any]], 
                     limit: Optional[int] = None,
                     days: Optional[int] = None) -> str:
        """Generate RSS 2.0 XML feed from posts.
        
        Args:
            posts: List of post dictionaries from StorageManager
            limit: Maximum number of posts (for display in feed info)
            days: Days filter (for display in feed info)
            
        Returns:
            RSS 2.0 XML string
        """
        logger.info(f"Generating RSS feed with {len(posts)} posts")
        
        # Create RSS root element
        rss = ET.Element('rss', version='2.0')
        rss.set('xmlns:atom', 'http://www.w3.org/2005/Atom')
        
        # Create channel element
        channel = ET.SubElement(rss, 'channel')
        
        # Add channel metadata
        ET.SubElement(channel, 'title').text = self.channel_title
        ET.SubElement(channel, 'link').text = self.base_url
        ET.SubElement(channel, 'description').text = self.channel_description
        
        # Add atom:link for self-reference
        atom_link = ET.SubElement(channel, '{http://www.w3.org/2005/Atom}link')
        atom_link.set('href', f"{self.base_url}/feed.rss")
        atom_link.set('rel', 'self')
        atom_link.set('type', 'application/rss+xml')
        
        # Add generator
        ET.SubElement(channel, 'generator').text = 'ig2rss'
        
        # Add lastBuildDate
        ET.SubElement(channel, 'lastBuildDate').text = self._format_rfc822(datetime.now())
        
        # Add items for each post
        for post in posts:
            self._add_post_item(channel, post)
        
        # Convert to string with XML declaration
        xml_str = ET.tostring(rss, encoding='utf-8', method='xml')
        return b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
    
    def _add_post_item(self, channel: ET.Element, post: Dict[str, Any]):
        """Add a single post as an RSS item.
        
        Args:
            channel: XML channel element to add item to
            post: Post dictionary from StorageManager
        """
        item = ET.SubElement(channel, 'item')
        
        # Title - use first line of caption or fallback
        title = self._extract_title(post.get('caption', ''))
        ET.SubElement(item, 'title').text = title
        
        # Link - permalink to Instagram post
        ET.SubElement(item, 'link').text = post['permalink']
        
        # GUID - use post ID as unique identifier
        guid = ET.SubElement(item, 'guid')
        guid.text = post['id']
        guid.set('isPermaLink', 'false')
        
        # PubDate - format as RFC 822
        posted_at = post['posted_at']
        if isinstance(posted_at, str):
            posted_at = datetime.fromisoformat(posted_at)
        ET.SubElement(item, 'pubDate').text = self._format_rfc822(posted_at)
        
        # Author
        author_name = post.get('author_full_name') or post['author_username']
        ET.SubElement(item, 'author').text = f"{post['author_username']}@instagram.com ({author_name})"
        
        # Description - HTML content with media and caption
        description = self._format_description(post)
        ET.SubElement(item, 'description').text = description
        
        # Add enclosure for first video/image (RSS standard is one enclosure per item)
        self._add_enclosure(item, post)
    
    def _add_enclosure(self, item: ET.Element, post: Dict[str, Any]):
        """Add enclosure element for media (RSS standard for attachments).
        
        RSS 2.0 spec says one enclosure per item. We prioritize:
        1. First video with local file
        2. First image with local file
        3. First media (fallback to Instagram URL)
        
        Args:
            item: XML item element to add enclosure to
            post: Post dictionary from StorageManager
        """
        media_items = post.get('media', [])
        if not media_items:
            return
        
        # Try to find first video with local path
        selected_media = None
        for media in media_items:
            if media['media_type'] == 'video' and media.get('local_path'):
                selected_media = media
                break
        
        # Fallback to first image with local path
        if not selected_media:
            for media in media_items:
                if media['media_type'] == 'image' and media.get('local_path'):
                    selected_media = media
                    break
        
        # Fallback to first media item
        if not selected_media:
            selected_media = media_items[0]
        
        # Build enclosure URL
        if selected_media.get('local_path'):
            media_url = f"{self.base_url}/media/{selected_media['local_path']}"
        else:
            media_url = selected_media['media_url']
        
        # Determine MIME type
        if selected_media['media_type'] == 'video':
            mime_type = 'video/mp4'
        else:
            mime_type = 'image/jpeg'
        
        # Get file size (required by RSS spec, use 0 if unknown)
        file_size = selected_media.get('file_size', 0)
        
        # Add enclosure element
        enclosure = ET.SubElement(item, 'enclosure')
        enclosure.set('url', media_url)
        enclosure.set('type', mime_type)
        enclosure.set('length', str(file_size))
        
        logger.debug(f"Added enclosure: {mime_type} {file_size} bytes")
    
    def _extract_title(self, caption: Optional[str]) -> str:
        """Extract title from caption (first line or fallback).
        
        Args:
            caption: Post caption text
            
        Returns:
            Title string
        """
        if not caption:
            return "Instagram Post"
        
        # Get first line, trim whitespace
        first_line = caption.split('\n')[0].strip()
        
        # Limit length
        max_length = 100
        if len(first_line) > max_length:
            first_line = first_line[:max_length-3] + '...'
        
        return first_line if first_line else "Instagram Post"
    
    def _format_description(self, post: Dict[str, Any]) -> str:
        """Format post description with embedded media and caption.
        
        Args:
            post: Post dictionary from StorageManager
            
        Returns:
            HTML string for RSS description
        """
        html_parts = []
        
        # Add media (images/videos)
        media_items = post.get('media', [])
        for media in media_items:
            media_type = media['media_type']
            local_path = media.get('local_path')
            
            if local_path:
                # Use local media URL
                media_url = f"{self.base_url}/media/{local_path}"
            else:
                # Fallback to Instagram URL
                media_url = media['media_url']
            
            if media_type == 'image':
                html_parts.append(f'<p><img src="{html.escape(media_url)}" style="max-width:100%;height:auto;" /></p>')
            elif media_type == 'video':
                html_parts.append(f'<p><video controls style="max-width:100%;height:auto;"><source src="{html.escape(media_url)}" type="video/mp4" />Your browser does not support the video tag.</video></p>')
        
        # Add caption
        caption = post.get('caption', '')
        if caption:
            # Escape HTML and preserve line breaks
            escaped_caption = html.escape(caption)
            formatted_caption = escaped_caption.replace('\n', '<br/>')
            html_parts.append(f'<p>{formatted_caption}</p>')
        
        # Add link to original post
        html_parts.append(f'<p><a href="{html.escape(post["permalink"])}">View on Instagram</a></p>')
        
        return '\n'.join(html_parts)
    
    def _add_enclosure(self, item: ET.Element, post: Dict[str, Any]):
        """Add enclosure element for media (RSS standard for attachments).
        
        RSS 2.0 spec says one enclosure per item. We prioritize:
        1. First video with local file
        2. First image with local file
        3. First media (fallback to Instagram URL)
        
        Args:
            item: XML item element to add enclosure to
            post: Post dictionary from StorageManager
        """
        media_items = post.get('media', [])
        if not media_items:
            return
        
        # Try to find first video with local path
        selected_media = None
        for media in media_items:
            if media['media_type'] == 'video' and media.get('local_path'):
                selected_media = media
                break
        
        # Fallback to first image with local path
        if not selected_media:
            for media in media_items:
                if media['media_type'] == 'image' and media.get('local_path'):
                    selected_media = media
                    break
        
        # Fallback to first media item
        if not selected_media:
            selected_media = media_items[0]
        
        # Build enclosure URL
        if selected_media.get('local_path'):
            media_url = f"{self.base_url}/media/{selected_media['local_path']}"
        else:
            media_url = selected_media['media_url']
        
        # Determine MIME type
        if selected_media['media_type'] == 'video':
            mime_type = 'video/mp4'
        else:
            mime_type = 'image/jpeg'
        
        # Get file size (required by RSS spec, use 0 if unknown)
        file_size = selected_media.get('file_size', 0)
        
        # Add enclosure element
        enclosure = ET.SubElement(item, 'enclosure')
        enclosure.set('url', media_url)
        enclosure.set('type', mime_type)
        enclosure.set('length', str(file_size))
        
        logger.debug(f"Added enclosure: {mime_type} {file_size} bytes")
    
    def _format_rfc822(self, dt: datetime) -> str:
        """Format datetime as RFC 822 date (required for RSS 2.0).
        
        Args:
            dt: Datetime object
            
        Returns:
            RFC 822 formatted string (e.g., "Mon, 08 Dec 2025 10:30:00 +0000")
        """
        # RSS 2.0 requires RFC 822 date format
        # strftime format: "Day, DD Mon YYYY HH:MM:SS +0000"
        return dt.strftime('%a, %d %b %Y %H:%M:%S +0000')
