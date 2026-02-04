"""Instagram API client using instagrapi.

This module provides a wrapper around instagrapi to fetch the user's home
feed (timeline), handle authentication with session persistence, and download
media files with proper error handling and retry logic.
"""

import logging
import time
import json
import re
import base64
import requests
from typing import List, Optional, Dict, Any, Tuple
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
    
    def __init__(
        self, 
        username: str, 
        password: str, 
        session_file: Optional[str] = None,
        totp_seed: Optional[str] = None
    ):
        """Initialize Instagram client with credentials.
        
        Args:
            username: Instagram username
            password: Instagram password
            session_file: Path to session file for persistence (optional)
            totp_seed: TOTP seed for 2FA authentication (optional)
        """
        self.username = username
        self.password = password
        self.session_file = session_file
        self.totp_seed = totp_seed
        self.client = Client()
        self._is_authenticated = False
        
        # Configure client for better behavior
        # Add random delays between 1-3 seconds (mimics human behavior)
        self.client.delay_range = [1, 3]
        
        # Retry configuration
        self.max_retries = 3
        self.base_backoff = 2  # seconds
        
        # Re-authentication metrics
        self._reauth_attempts = 0
        self._reauth_successes = 0
        self._reauth_failures = 0
        
        logger.info(f"InstagramClient initialized for user: {username}")
        if totp_seed:
            logger.info("2FA TOTP seed provided for authentication")
    
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
                
                # Verify session is valid by checking account info
                try:
                    self.client.account_info()
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
            # Generate 2FA code if TOTP seed is provided
            verification_code = None
            if self.totp_seed:
                try:
                    # Clean and validate the TOTP seed
                    # Remove ALL whitespace characters (spaces, tabs, newlines, etc.)
                    seed = re.sub(r'\s+', '', self.totp_seed.strip())
                    
                    # Remove common separators
                    seed = seed.replace("-", "").replace("_", "")
                    
                    # Log the cleaned seed info for debugging (first/last few chars only)
                    logger.debug(
                        f"TOTP seed after cleaning: length={len(seed)}, "
                        f"preview={seed[:4]}...{seed[-4:] if len(seed) > 8 else ''}"
                    )
                    
                    # Try to detect if it's a hex-encoded secret (some apps use this)
                    # If it contains lowercase or numbers > 7, it might be hex
                    if any(c in seed.lower() for c in '89abcdef'):
                        logger.info("TOTP seed appears to be hex-encoded, converting to base32")
                        try:
                            hex_bytes = bytes.fromhex(seed)
                            seed = base64.b32encode(hex_bytes).decode('ascii').rstrip('=')
                            logger.debug(f"Converted to base32: length={len(seed)}")
                        except ValueError:
                            logger.debug("Failed to parse as hex, treating as base32")
                    
                    # Ensure uppercase for base32
                    seed = seed.upper()
                    
                    verification_code = self.client.totp_generate_code(seed)
                    logger.info("Generated 2FA verification code from TOTP seed")
                except Exception as e:
                    whitespace_chars = ' \t\n\r'
                    has_whitespace = any(c in self.totp_seed for c in whitespace_chars)
                    logger.error(
                        f"Failed to generate 2FA code from TOTP seed: {e}. "
                        f"Original seed length: {len(self.totp_seed)}, "
                        f"contains spaces/tabs: {has_whitespace}"
                    )
                    raise ValueError(
                        f"Invalid TOTP seed format: {e}. "
                        "The seed should be base32 (A-Z, 2-7) or hex-encoded. "
                        "Make sure to remove any quotes around the seed in your .env file."
                    ) from e
            
            # Login with optional 2FA code
            if verification_code:
                self.client.login(self.username, self.password, verification_code=verification_code)
            else:
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
    
    def validate_session(self) -> bool:
        """Check if current session is still valid.
        
        Performs a lightweight API call to verify the session is working.
        If the session has expired, marks the client as not authenticated
        so the next operation will trigger re-authentication.
        
        Returns:
            True if session is valid and working
            False if session expired or invalid
        """
        if not self._is_authenticated:
            logger.debug("validate_session: Not authenticated")
            return False
        
        try:
            # Quick lightweight check - fetch account info (minimal data transfer)
            self.client.account_info()
            logger.debug("Session validation successful")
            return True
        except (LoginRequired, PleaseWaitFewMinutes) as e:
            if self._is_authentication_error(e):
                logger.warning(
                    "Session validation failed - session has expired. "
                    "Will re-authenticate on next operation."
                )
                self._is_authenticated = False
                return False
            # Real rate limit, session is still fine
            logger.debug("Session validation: rate limited but session is valid")
            return True
        except Exception as e:
            logger.warning(f"Session validation check failed: {e}")
            return False
    
    def _is_authentication_error(self, exception: Exception) -> bool:
        """Detect if exception indicates session expiry or authentication failure.
        
        Instagram returns 401 with 'Please wait a few minutes' when session expires,
        which instagrapi wraps as PleaseWaitFewMinutes. We need to check the 
        underlying HTTP status code to distinguish it from actual rate limiting.
        
        Args:
            exception: Exception to check
            
        Returns:
            True if this is an authentication error, False otherwise
        """
        # Check if it's PleaseWaitFewMinutes with 401 status (session expired)
        if isinstance(exception, PleaseWaitFewMinutes):
            response = getattr(exception, 'response', None)
            if response and response.status_code == 401:
                logger.debug(
                    f"Detected authentication error: {type(exception).__name__} "
                    f"with status 401"
                )
                return True
        
        # Direct LoginRequired exception
        if isinstance(exception, LoginRequired):
            logger.debug(f"Detected LoginRequired exception")
            return True
        
        return False
    
    def get_reauth_metrics(self) -> dict:
        """Get re-authentication metrics for monitoring.
        
        Returns:
            Dict with reauth_attempts, reauth_successes, reauth_failures
        """
        return {
            'reauth_attempts': self._reauth_attempts,
            'reauth_successes': self._reauth_successes,
            'reauth_failures': self._reauth_failures
        }
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """Execute a function with exponential backoff retry logic.
        
        Now includes automatic re-authentication on session expiry detection.
        When a 401 error is detected (wrapped as PleaseWaitFewMinutes),
        attempts to re-authenticate once before retrying.
        
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
        auth_retry_attempted = False  # Track if we already tried re-auth
        
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
                
            except PleaseWaitFewMinutes as e:
                # Check if this is actually an authentication error (401)
                if self._is_authentication_error(e) and not auth_retry_attempted:
                    logger.warning(
                        "Detected authentication failure (401 Unauthorized). "
                        "Session has expired. Attempting to re-authenticate..."
                    )
                    
                    # Mark as not authenticated and try to re-login
                    self._is_authenticated = False
                    auth_retry_attempted = True
                    self._reauth_attempts += 1
                    
                    try:
                        if self.login():
                            logger.info(
                                "Re-authentication successful. Session restored. "
                                "Retrying operation..."
                            )
                            self._reauth_successes += 1
                            continue  # Retry the operation with new session
                        else:
                            logger.error("Re-authentication failed")
                            self._reauth_failures += 1
                            raise LoginRequired(
                                "Failed to re-authenticate after session expiry"
                            )
                    except LoginRequired:
                        # Already handled above, just re-raise
                        raise
                    except Exception as login_err:
                        logger.error(f"Re-authentication error: {login_err}")
                        self._reauth_failures += 1
                        raise
                
                # Real rate limiting (429 or other non-auth errors) - use longer backoff
                wait_time = self.base_backoff * (2 ** attempt) * 5  # 10s, 20s, 40s
                logger.warning(
                    f"Rate limited by Instagram. Waiting {wait_time}s before retry "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(wait_time)
                last_exception = e
                
            except LoginRequired as e:
                # Direct login required exception
                if not auth_retry_attempted:
                    logger.warning(
                        "Session expired (LoginRequired). Attempting to re-authenticate..."
                    )
                    self._is_authenticated = False
                    auth_retry_attempted = True
                    self._reauth_attempts += 1
                    
                    try:
                        if self.login():
                            logger.info("Re-authentication successful. Retrying operation...")
                            self._reauth_successes += 1
                            continue
                        else:
                            logger.error("Re-authentication failed")
                            self._reauth_failures += 1
                            raise
                    except LoginRequired:
                        # Already handled above, just re-raise
                        raise
                    except Exception as login_err:
                        logger.error(f"Re-authentication error: {login_err}")
                        self._reauth_failures += 1
                        raise
                else:
                    # Already tried re-auth, don't retry again
                    logger.error("Re-authentication already attempted and failed")
                    raise
                
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
        similar to the Instagram home feed. Automatically handles pagination to
        fetch the requested number of posts.
        
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
            posts = []
            seen_ids = set()  # Track post IDs to avoid duplicates
            max_id = None
            page_count = 0
            max_pages = 5  # Limit scrolling - most valuable posts are in first 2 pages
            
            # Keep fetching pages until we have enough posts or no more pages
            while len(posts) < count and page_count < max_pages:
                page_count += 1
                
                # Fetch next page of timeline
                logger.debug(f"Fetching timeline page {page_count} (max_id={max_id})")
                timeline_response = self.client.get_timeline_feed(max_id=max_id)
                
                items = timeline_response.get("feed_items", [])
                if not items:
                    logger.debug("No more feed items available")
                    break
                
                # Process items from this page
                page_posts_added = 0
                page_items_total = len(items)
                page_ads_skipped = 0
                
                for item in items:
                    if len(posts) >= count:
                        break
                    
                    try:
                        # Each item may have a 'media_or_ad' field with the actual media
                        media_data = item.get("media_or_ad")
                        if not media_data:
                            logger.debug("Item has no media_or_ad field, skipping")
                            continue
                        
                        # Debug: Log all available fields for troubleshooting
                        item_keys = list(item.keys())
                        media_keys = list(media_data.keys())
                        logger.debug(f"Item keys: {item_keys}")
                        logger.debug(f"Media data keys: {media_keys}")
                        
                        # Skip ads - check for ad indicators in the media data
                        # Instagram has many different ad indicators we need to check
                        is_ad = (
                            media_data.get("dr_ad_type") or
                            media_data.get("is_paid_partnership") or
                            media_data.get("injected") or
                            media_data.get("ad_action") or
                            media_data.get("ad_id") or
                            media_data.get("ad_header_style") or
                            media_data.get("is_sponsored") or
                            # Check if item itself has injected flag
                            item.get("injected")
                        )
                        
                        if is_ad:
                            page_ads_skipped += 1
                            ad_username = media_data.get("user", {}).get("username", "unknown")
                            ad_type = (
                                media_data.get("dr_ad_type") or
                                "injected" if (media_data.get("injected") or item.get("injected")) else
                                "sponsored" if media_data.get("is_sponsored") else
                                "partnership" if media_data.get("is_paid_partnership") else
                                "ad_action" if media_data.get("ad_action") else
                                "unknown"
                            )
                            logger.info(f"🚫 SKIPPED AD (type: {ad_type}) from @{ad_username} (id: {media_data.get('id', 'unknown')})")
                            continue
                        
                        # Fix Pydantic validation issues with clips_metadata
                        # The audio_filter_infos field should be a list but sometimes comes as None
                        if "clips_metadata" in media_data:
                            clips = media_data.get("clips_metadata", {})
                            if isinstance(clips, dict) and "original_sound_info" in clips:
                                sound_info = clips.get("original_sound_info", {})
                                if isinstance(sound_info, dict) and sound_info.get("audio_filter_infos") is None:
                                    sound_info["audio_filter_infos"] = []
                        
                        # Fix Pydantic validation issues with image_versions2
                        # The scans_profile field should be a string but sometimes comes as None
                        if "image_versions2" in media_data:
                            image_versions = media_data.get("image_versions2", {})
                            if isinstance(image_versions, dict) and "candidates" in image_versions:
                                candidates = image_versions.get("candidates", [])
                                if isinstance(candidates, list):
                                    for candidate in candidates:
                                        if isinstance(candidate, dict) and candidate.get("scans_profile") is None:
                                            candidate["scans_profile"] = ""
                        
                        # Use instagrapi's extractor to convert to Media object
                        media = extract_media_v1(media_data)
                        
                        post = self._convert_media_to_post(media)
                        if post:
                            # Skip if we've already seen this post ID in this fetch
                            if post.id in seen_ids:
                                logger.debug(f"Skipping duplicate post within fetch: {post.id}")
                                continue
                            
                            seen_ids.add(post.id)
                            posts.append(post)
                            page_posts_added += 1
                            logger.info(f"✅ FETCHED POST from @{post.author_username} (id: {post.id})")
                    except Exception as e:
                        logger.warning(f"Failed to convert media item: {e}")
                        continue
                
                logger.info(
                    f"Page {page_count}: {page_posts_added} posts fetched, {page_ads_skipped} ads skipped "
                    f"(processed {page_items_total} items total)"
                )
                
                # Get next page cursor
                next_max_id = timeline_response.get("next_max_id")
                if not next_max_id or next_max_id == max_id:
                    logger.debug("No more pages available (no next_max_id)")
                    break
                
                max_id = next_max_id
                
                # Add small delay between pages to avoid rate limiting
                time.sleep(1)
            
            logger.debug(f"Fetched {len(posts)} posts across {page_count} pages")
            return posts
        
        posts = self._retry_with_backoff(_fetch)
        logger.info(f"📊 FETCH COMPLETE: {len(posts)} total posts fetched from timeline")
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
    
    def _fetch_user_medias_with_fix(
        self, 
        user_id: str, 
        amount: int = 20
    ) -> List:
        """Fetch user medias with Pydantic validation fixes applied.
        
        This method uses the low-level private API to get raw JSON,
        applies fixes for common Pydantic validation issues, then
        converts to Media objects.
        
        Args:
            user_id: Instagram user ID (pk)
            amount: Number of media items to fetch
            
        Returns:
            List of instagrapi Media objects
        """
        from instagrapi.extractors import extract_media_v1
        
        try:
            # Use low-level API to get raw JSON
            items = self.client.private_request(
                f"feed/user/{user_id}/",
                params={
                    "count": amount,
                    "rank_token": self.client.rank_token,
                    "ranked_content": "true",
                },
            )["items"]
            
            medias = []
            for media_data in items:
                try:
                    # Apply Pydantic fixes before extraction
                    
                    # Fix 1: clips_metadata.original_sound_info.audio_filter_infos
                    if "clips_metadata" in media_data:
                        clips = media_data.get("clips_metadata", {})
                        if isinstance(clips, dict) and "original_sound_info" in clips:
                            sound_info = clips.get("original_sound_info", {})
                            if isinstance(sound_info, dict) and sound_info.get("audio_filter_infos") is None:
                                sound_info["audio_filter_infos"] = []
                    
                    # Fix 2: image_versions2.candidates.scans_profile
                    if "image_versions2" in media_data:
                        image_versions = media_data.get("image_versions2", {})
                        if isinstance(image_versions, dict) and "candidates" in image_versions:
                            candidates = image_versions.get("candidates", [])
                            if isinstance(candidates, list):
                                for candidate in candidates:
                                    if isinstance(candidate, dict) and candidate.get("scans_profile") is None:
                                        candidate["scans_profile"] = ""
                    
                    # Convert to Media object
                    media = extract_media_v1(media_data)
                    medias.append(media)
                    
                except Exception as e:
                    logger.warning(f"Failed to parse media item: {e}")
                    continue
            
            return medias
            
        except Exception as e:
            logger.error(f"Failed to fetch user medias: {e}")
            raise

    def check_account_for_new_posts(
        self, 
        user_id: str, 
        username: str,
        last_known_post_id: Optional[str] = None
    ) -> Tuple[bool, List[InstagramPost], Dict[str, Any]]:
        """Efficiently check if account has new posts.
        
        Uses a 3-step process to minimize API calls:
        1. Get user_info (media_count) - 1 API call
        2. If media_count > 0, fetch latest post only - 1 API call
        3. Compare latest_post.pk with last_known_post_id
        4. If new, fetch recent posts (amount=20) - 1 API call
        
        Args:
            user_id: Instagram user ID (pk)
            username: Instagram username (for logging)
            last_known_post_id: ID of last post we fetched (optional)
            
        Returns:
            Tuple of (has_new_posts, new_posts_list, account_metadata)
            - has_new_posts: True if new posts detected
            - new_posts_list: List of InstagramPost objects (empty if no new posts)
            - account_metadata: Dict with media_count, latest_post_id, latest_post_date
        """
        if not self._is_authenticated:
            logger.error("Cannot check account - not authenticated")
            raise LoginRequired("Must call login() first")
        
        logger.debug(f"Checking @{username} for new posts (last_known={last_known_post_id})")
        
        def _check():
            metadata = {
                'media_count': 0,
                'latest_post_id': None,
                'latest_post_date': None
            }
            
            # Step 1: Get user info (media count)
            try:
                user_info = self.client.user_info(user_id)
                metadata['media_count'] = user_info.media_count
                
                logger.debug(f"@{username} has {metadata['media_count']} total posts")
                
                # If account has no posts, skip
                if metadata['media_count'] == 0:
                    logger.debug(f"@{username} has no posts, skipping")
                    return False, [], metadata
                
            except Exception as e:
                logger.error(f"Failed to get user info for @{username}: {e}")
                # Return empty but don't fail completely
                return False, [], metadata
            
            # Step 2: Fetch latest post only (amount=1) with Pydantic fixes
            try:
                latest_medias = self._fetch_user_medias_with_fix(user_id, amount=1)
                
                if not latest_medias:
                    logger.debug(f"@{username} returned no posts, skipping")
                    return False, [], metadata
                
                latest_media = latest_medias[0]
                latest_post_id = str(latest_media.pk)
                metadata['latest_post_id'] = latest_post_id
                metadata['latest_post_date'] = latest_media.taken_at
                
                logger.debug(f"@{username} latest post: {latest_post_id} (date: {metadata['latest_post_date']})")
                
            except Exception as e:
                logger.error(f"Failed to fetch latest post for @{username}: {e}", exc_info=True)
                return False, [], metadata
            
            # Step 3: Compare with last known post
            if last_known_post_id and latest_post_id == last_known_post_id:
                logger.debug(f"@{username} has no new posts (latest={latest_post_id})")
                return False, [], metadata
            
            # Step 4: New post detected! Fetch recent posts (amount=20)
            logger.info(f"@{username} has new posts! Fetching recent content...")
            
            try:
                recent_medias = self._fetch_user_medias_with_fix(user_id, amount=20)
                
                posts = []
                for media in recent_medias:
                    post = self._convert_media_to_post(media)
                    if post:
                        posts.append(post)
                
                logger.info(f"@{username}: Fetched {len(posts)} recent posts")
                return True, posts, metadata
                
            except Exception as e:
                logger.error(f"Failed to fetch recent posts for @{username}: {e}", exc_info=True)
                # Return the latest post data we have
                return True, [], metadata
        
        return self._retry_with_backoff(_check)
    
    def logout(self):
        """Log out and clear session."""
        if self._is_authenticated:
            logger.info("Logging out")
            self._is_authenticated = False
            # Note: instagrapi doesn't have explicit logout, just clear state
