"""Instagram API client using instagrapi.

This module provides a wrapper around instagrapi to fetch the user's home
feed (timeline), handle authentication with session persistence, and download
media files with proper error handling and retry logic.
"""

import logging
import time
import json
import requests
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    PleaseWaitFewMinutes,
    ChallengeRequired,
    ClientError,
)
from instagrapi.extractors import extract_media_v1


logger = logging.getLogger(__name__)


@dataclass
class InstagramPost:
    """Represents a post from the Instagram feed."""
    
    id: str  # Instagram media ID
    posted_at: datetime
    caption: Optional[str]
    post_type: str  # 'photo', 'video', 'carousel'
    permalink: str
    author_username: str  # Username of the account that posted
    author_full_name: Optional[str]  # Display name
    media_urls: List[str]  # URLs to media files
    media_types: List[str]  # 'image' or 'video' for each media_urls item


class InstagramClient:
    """Client for interacting with Instagram API via instagrapi."""
    
    def __init__(self, username: str, password: str, session_file: Optional[str] = None):
        """Initialize Instagram client with credentials.
        
        Args:
            username: Instagram username
            password: Instagram password
            session_file: Path to session file for persistence (optional)
        """
        self.username = username
        self.password = password
        self.session_file = session_file
        self.client = Client()
        self._is_authenticated = False
        
        # Configure client for better behavior
        # Add random delays between 1-3 seconds (mimics human behavior)
        self.client.delay_range = [1, 3]
        
        # Retry configuration
        self.max_retries = 3
        self.base_backoff = 2  # seconds
        
        logger.info(f"InstagramClient initialized for user: {username}")
    
    def login(self) -> bool:
        """Authenticate with Instagram using session or credentials.
        
        This method attempts to use a saved session first (if session_file is configured),
        then falls back to username/password login. This is more natural behavior
        and less suspicious to Instagram.
        
        Returns:
            True if login successful, False otherwise
            
        Raises:
            LoginRequired: If credentials are invalid
            ChallengeRequired: If Instagram requires additional verification
        """
        if self._is_authenticated:
            logger.debug("Already authenticated")
            return True
        
        # Try to load session if file exists
        if self.session_file and Path(self.session_file).exists():
            try:
                logger.info("Attempting to login using saved session")
                self.client.load_settings(self.session_file)
                self.client.login(self.username, self.password)
                
                # Verify session is valid by checking timeline
                try:
                    self.client.get_timeline_feed()
                    logger.info("Session is valid, logged in successfully")
                    self._is_authenticated = True
                    return True
                except LoginRequired:
                    logger.warning("Session expired, will login with credentials")
                    # Fall through to password login
                    
            except Exception as e:
                logger.warning(f"Failed to login with session: {e}, trying password")
                # Fall through to password login
        
        # Login with username/password
        logger.info(f"Attempting to log in as {self.username}")
        
        try:
            self.client.login(self.username, self.password)
            self._is_authenticated = True
            
            # Save session for future use
            if self.session_file:
                self.client.dump_settings(self.session_file)
                logger.info(f"Session saved to {self.session_file}")
            
            logger.info("Login successful")
            return True
            
        except LoginRequired as e:
            logger.error(f"Login failed - invalid credentials: {e}")
            raise
            
        except ChallengeRequired as e:
            logger.error(f"Login failed - challenge required (2FA/verification): {e}")
            raise
            
        except Exception as e:
            logger.error(f"Login failed with unexpected error: {e}")
            raise
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """Execute a function with exponential backoff retry logic.
        
        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result of func
            
        Raises:
            Last exception if all retries fail
        """
        last_exception: Exception = Exception("No attempts made")
        
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
                
            except PleaseWaitFewMinutes as e:
                # Rate limiting - use longer backoff
                wait_time = self.base_backoff * (2 ** attempt) * 5  # 10s, 20s, 40s
                logger.warning(
                    f"Rate limited by Instagram. Waiting {wait_time}s before retry "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(wait_time)
                last_exception = e
                
            except (ClientError, ConnectionError) as e:
                # Network or API errors
                wait_time = self.base_backoff * (2 ** attempt)
                logger.warning(
                    f"Request failed: {e}. Retrying in {wait_time}s "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(wait_time)
                last_exception = e
                
            except Exception as e:
                # Unexpected errors - don't retry
                logger.error(f"Unexpected error (not retrying): {e}")
                raise
        
        # All retries exhausted
        logger.error(f"All {self.max_retries} retry attempts failed")
        raise last_exception
    
    def get_timeline_feed(self, count: int = 50) -> List[InstagramPost]:
        """Fetch recent posts from user's home feed (timeline).
        
        This fetches posts from all accounts that the authenticated user follows,
        similar to the Instagram home feed.
        
        Args:
            count: Maximum number of posts to fetch (default 50)
            
        Returns:
            List of InstagramPost objects
            
        Raises:
            LoginRequired: If not authenticated
            Exception: On other failures after retries
        """
        if not self._is_authenticated:
            logger.error("Cannot fetch feed - not authenticated")
            raise LoginRequired("Must call login() first")
        
        logger.info(f"Fetching timeline feed (count={count})")
        
        def _fetch():
            # Use instagrapi's get_timeline_feed method
            # This returns a dict with 'feed_items' containing the media
            timeline_response = self.client.get_timeline_feed()
            
            posts = []
            items = timeline_response.get("feed_items", [])
            
            for item in items[:count]:
                try:
                    # Each item may have a 'media_or_ad' field with the actual media
                    media_data = item.get("media_or_ad")
                    if not media_data:
                        continue
                    
                    # Skip ads - check for ad indicators in the media data
                    # Instagram API includes fields like 'is_paid_partnership' or 'dr_ad_type'
                    if media_data.get("dr_ad_type") or media_data.get("is_paid_partnership"):
                        logger.info(f"Skipping ad: {media_data.get('id', 'unknown')}")
                        continue
                    
                    # Fix Pydantic validation issues with clips_metadata
                    # The audio_filter_infos field should be a list but sometimes comes as None
                    if "clips_metadata" in media_data:
                        clips = media_data.get("clips_metadata", {})
                        if isinstance(clips, dict) and "original_sound_info" in clips:
                            sound_info = clips.get("original_sound_info", {})
                            if isinstance(sound_info, dict) and sound_info.get("audio_filter_infos") is None:
                                sound_info["audio_filter_infos"] = []
                    
                    # Use instagrapi's extractor to convert to Media object
                    media = extract_media_v1(media_data)
                    
                    post = self._convert_media_to_post(media)
                    if post:
                        posts.append(post)
                except Exception as e:
                    logger.warning(f"Failed to convert media item: {e}")
                    continue
            
            return posts
        
        posts = self._retry_with_backoff(_fetch)
        logger.info(f"Successfully fetched {len(posts)} posts from timeline")
        return posts
    
    def _convert_media_to_post(self, media) -> Optional[InstagramPost]:
        """Convert instagrapi Media object to InstagramPost.
        
        Args:
            media: instagrapi Media object
            
        Returns:
            InstagramPost or None if conversion fails
        """
        try:
            # Determine post type
            if media.media_type == 1:
                post_type = "photo"
                media_urls = [str(media.thumbnail_url) if media.thumbnail_url else ""]
                media_types = ["image"]
            elif media.media_type == 2:
                post_type = "video"
                media_urls = [str(media.video_url) if media.video_url else ""]
                media_types = ["video"]
            elif media.media_type == 8:
                # Carousel (album)
                post_type = "carousel"
                media_urls = []
                media_types = []
                for resource in media.resources:
                    if resource.media_type == 1:
                        media_urls.append(str(resource.thumbnail_url) if resource.thumbnail_url else "")
                        media_types.append("image")
                    elif resource.media_type == 2:
                        media_urls.append(str(resource.video_url) if resource.video_url else "")
                        media_types.append("video")
            else:
                logger.warning(f"Unknown media type: {media.media_type}")
                return None
            
            # Build permalink
            permalink = f"https://www.instagram.com/p/{media.code}/"
            
            # Extract author info
            author_username = media.user.username if media.user and media.user.username else "unknown"
            author_full_name = media.user.full_name if media.user and media.user.full_name else None
            
            return InstagramPost(
                id=str(media.pk),
                posted_at=media.taken_at,
                caption=media.caption_text if media.caption_text else None,
                post_type=post_type,
                permalink=permalink,
                author_username=author_username,
                author_full_name=author_full_name,
                media_urls=media_urls,
                media_types=media_types,
            )
            
        except Exception as e:
            logger.error(f"Failed to convert media to post: {e}")
            return None
    
    def download_media(self, url: str, local_path: str) -> bool:
        """Download media file from Instagram CDN to local storage.
        
        Args:
            url: Instagram media URL
            local_path: Local filesystem path to save file
            
        Returns:
            True if download successful, False otherwise
        """
        logger.debug(f"Downloading media from {url} to {local_path}")
        
        def _download():
            # Create parent directory if it doesn't exist
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        
        try:
            result = self._retry_with_backoff(_download)
            logger.info(f"Successfully downloaded media to {local_path}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to download media from {url}: {e}")
            return False
    
    def logout(self):
        """Log out and clear session."""
        if self._is_authenticated:
            logger.info("Logging out")
            self._is_authenticated = False
            # Note: instagrapi doesn't have explicit logout, just clear state
