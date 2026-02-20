"""Storage layer for persisting Instagram posts and media to SQLite.

This module provides database management for storing post metadata and organizing
media files on the filesystem.
"""

import logging
import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from contextlib import contextmanager

from .instagram_client import InstagramPost, InstagramStory


logger = logging.getLogger(__name__)


# Configure datetime adapters for SQLite (Python 3.12+ compatibility)
def adapt_datetime(dt: datetime) -> str:
    """Convert datetime to ISO format string for SQLite."""
    return dt.isoformat()


def convert_datetime(val: bytes) -> datetime:
    """Convert ISO format string from SQLite to datetime."""
    return datetime.fromisoformat(val.decode())


def safe_json_dumps(obj: Any) -> Optional[str]:
    """Safely serialize object to JSON string.
    
    Args:
        obj: Object to serialize (typically dict or list)
        
    Returns:
        JSON string if serialization successful, None otherwise
    """
    import json
    
    if obj is None:
        return None
    
    try:
        return json.dumps(obj)
    except (TypeError, ValueError) as e:
        logger.warning(f"Failed to serialize object to JSON: {e}. Object type: {type(obj)}")
        return None


sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("TIMESTAMP", convert_datetime)


class StorageManager:
    """Manages SQLite database and media file storage."""
    
    def __init__(self, db_path: str = "/data/ig2rss.db", media_dir: str = "/data/media"):
        """Initialize storage manager.
        
        Args:
            db_path: Path to SQLite database file
            media_dir: Base directory for media file storage
        """
        self.db_path = db_path
        self.media_dir = Path(media_dir)
        
        # Cache for story_exists() calls to reduce DB queries
        self._story_exists_cache: set = set()
        
        # Ensure directories exist
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"StorageManager initialized (db={db_path}, media={media_dir})")
        
        # Initialize database schema
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections.
        
        Yields:
            sqlite3.Connection object
        """
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row  # Enable column access by name
        conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_database(self):
        """Create database tables and indexes if they don't exist."""
        logger.info("Initializing database schema")
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Posts table - stores Instagram post metadata
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id TEXT PRIMARY KEY,
                    posted_at TIMESTAMP NOT NULL,
                    caption TEXT,
                    post_type TEXT NOT NULL,
                    permalink TEXT NOT NULL,
                    author_username TEXT NOT NULL,
                    author_full_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Media table - stores media file metadata linked to posts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT NOT NULL,
                    media_url TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    local_path TEXT,
                    file_size INTEGER,
                    downloaded_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
                )
            """)
            
            # Following accounts cache (Phase 1: Smart Polling)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS following_accounts (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    full_name TEXT,
                    is_private BOOLEAN DEFAULT 0,
                    last_checked TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Account activity tracking (Phase 1: Smart Polling)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account_activity (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    media_count INTEGER DEFAULT 0,
                    last_post_id TEXT,
                    last_post_date TIMESTAMP,
                    last_checked TIMESTAMP NOT NULL,
                    poll_priority TEXT DEFAULT 'normal',
                    consecutive_no_new_posts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES following_accounts(user_id)
                )
            """)
            
            # Sync metadata (Phase 1: Smart Polling)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Stories table (Phase 2: Stories Support)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    full_name TEXT,
                    taken_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    media_url TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    local_path TEXT,
                    file_size INTEGER,
                    downloaded_at TIMESTAMP,
                    poll_question TEXT,
                    poll_options TEXT,
                    link_text TEXT,
                    sticker_text TEXT,
                    permalink TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Account story activity table (Phase 2: Stories Support)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account_story_activity (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    is_muting_stories BOOLEAN DEFAULT 0,
                    last_story_id TEXT,
                    last_story_date TIMESTAMP,
                    last_checked TIMESTAMP NOT NULL,
                    story_poll_priority TEXT DEFAULT 'normal',
                    consecutive_no_new_stories INTEGER DEFAULT 0,
                    stories_fetched_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES following_accounts(user_id)
                )
            """)
            
            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_posts_posted_at 
                ON posts(posted_at DESC)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_posts_author 
                ON posts(author_username)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_media_post_id 
                ON media(post_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_following_username 
                ON following_accounts(username)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_following_last_checked 
                ON following_accounts(last_checked)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_activity_last_checked 
                ON account_activity(last_checked)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_activity_priority 
                ON account_activity(poll_priority)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_activity_last_post_date 
                ON account_activity(last_post_date DESC)
            """)
            
            # Story table indexes (Phase 2: Stories Support)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_stories_username 
                ON stories(username)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_stories_taken_at 
                ON stories(taken_at DESC)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_stories_expires_at 
                ON stories(expires_at)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_story_activity_muted 
                ON account_story_activity(is_muting_stories)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_story_activity_last_checked 
                ON account_story_activity(last_checked)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_story_activity_priority 
                ON account_story_activity(story_poll_priority)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_story_activity_last_story_date 
                ON account_story_activity(last_story_date DESC)
            """)
            
            logger.info("Database schema initialized successfully")
    
    def post_exists(self, post_id: str) -> bool:
        """Check if a post already exists in the database.
        
        Args:
            post_id: Instagram post ID
            
        Returns:
            True if post exists, False otherwise
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,))
            result = cursor.fetchone()
            return result is not None
    
    def save_post(self, post: InstagramPost) -> bool:
        """Save a post and its media metadata to the database.
        
        This method does not download media files - use save_media() for that.
        If the post already exists, it will be updated.
        
        Args:
            post: InstagramPost object to save
            
        Returns:
            True if save successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Insert or replace post
                cursor.execute("""
                    INSERT OR REPLACE INTO posts 
                    (id, posted_at, caption, post_type, permalink, 
                     author_username, author_full_name, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    post.id,
                    post.posted_at,
                    post.caption,
                    post.post_type,
                    post.permalink,
                    post.author_username,
                    post.author_full_name,
                ))
                
                # Delete existing media entries for this post (if updating)
                cursor.execute("DELETE FROM media WHERE post_id = ?", (post.id,))
                
                # Insert media entries
                for media_url, media_type in zip(post.media_urls, post.media_types):
                    cursor.execute("""
                        INSERT INTO media (post_id, media_url, media_type)
                        VALUES (?, ?, ?)
                    """, (post.id, media_url, media_type))
                
                logger.info(f"Saved post {post.id} with {len(post.media_urls)} media items")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save post {post.id}: {e}")
            return False
    
    def get_media_path(self, post_id: str, media_index: int, media_type: str) -> Path:
        """Generate filesystem path for a media file.
        
        Organizes files as: media/<post_id>/<index>.<ext>
        
        Args:
            post_id: Instagram post ID
            media_index: Index of media item (0 for single posts)
            media_type: 'image' or 'video'
            
        Returns:
            Path object for the media file
        """
        ext = "jpg" if media_type == "image" else "mp4"
        post_dir = self.media_dir / post_id
        post_dir.mkdir(parents=True, exist_ok=True)
        return post_dir / f"{media_index}.{ext}"
    
    def get_story_path(self, story_id: str, media_type: str) -> Path:
        """Generate filesystem path for a story media file.
        
        Organizes files as: media/<story_id>/0.<ext>
        Similar to get_media_path but for stories (always index 0).
        
        Args:
            story_id: Instagram story ID
            media_type: 'image' or 'video'
            
        Returns:
            Path object for the story media file
        """
        ext = "jpg" if media_type == "image" else "mp4"
        story_dir = self.media_dir / story_id
        story_dir.mkdir(parents=True, exist_ok=True)
        return story_dir / f"0.{ext}"
    
    def save_media(self, post_id: str, media_index: int, media_url: str, 
                   media_type: str, local_path: str, file_size: int) -> bool:
        """Update media entry with local file information after download.
        
        Args:
            post_id: Instagram post ID
            media_index: Index of media item in the post
            media_url: Original Instagram URL
            media_type: 'image' or 'video'
            local_path: Local filesystem path where file was saved
            file_size: Size of downloaded file in bytes
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE media 
                    SET local_path = ?, file_size = ?, downloaded_at = CURRENT_TIMESTAMP
                    WHERE post_id = ? AND media_url = ?
                """, (local_path, file_size, post_id, media_url))
                
                if cursor.rowcount == 0:
                    logger.warning(f"No media record found to update for post {post_id}")
                    return False
                
                logger.debug(f"Updated media record for post {post_id}, index {media_index}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save media info for post {post_id}: {e}")
            return False
    
    def get_recent_posts(self, limit: int = 50, days: Optional[int] = None) -> List[Dict[str, Any]]:
        """Query recent posts from the database.
        
        Args:
            limit: Maximum number of posts to return
            days: Only return posts from the last N days (optional)
            
        Returns:
            List of post dictionaries with media information
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Build query with optional date filter
                query = """
                    SELECT * FROM posts 
                    WHERE 1=1
                """
                params = []
                
                if days is not None:
                    cutoff_date = datetime.now() - timedelta(days=days)
                    query += " AND posted_at >= ?"
                    params.append(cutoff_date)
                
                query += " ORDER BY posted_at DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                posts = [dict(row) for row in cursor.fetchall()]
                
                # Fetch media for each post
                for post in posts:
                    cursor.execute("""
                        SELECT media_url, media_type, local_path, file_size, downloaded_at
                        FROM media 
                        WHERE post_id = ?
                        ORDER BY id
                    """, (post['id'],))
                    post['media'] = [dict(row) for row in cursor.fetchall()]
                
                logger.info(f"Retrieved {len(posts)} posts (limit={limit}, days={days})")
                return posts
                
        except Exception as e:
            logger.error(f"Failed to query recent posts: {e}")
            return []
    
    def get_post_by_id(self, post_id: str) -> Optional[Dict[str, Any]]:
        """Get a single post by ID with its media.
        
        Args:
            post_id: Instagram post ID
            
        Returns:
            Post dictionary with media, or None if not found
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                post = dict(row)
                
                # Fetch media
                cursor.execute("""
                    SELECT media_url, media_type, local_path, file_size, downloaded_at
                    FROM media 
                    WHERE post_id = ?
                    ORDER BY id
                """, (post_id,))
                post['media'] = [dict(row) for row in cursor.fetchall()]
                
                return post
                
        except Exception as e:
            logger.error(f"Failed to get post {post_id}: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics.
        
        Returns:
            Dictionary with stats (post count, media count, etc.)
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) as count FROM posts")
                post_count = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM stories")
                story_count = cursor.fetchone()['count']
                
                cursor.execute("SELECT COUNT(*) as count FROM media")
                media_count = cursor.fetchone()['count']
                
                cursor.execute("""
                    SELECT COUNT(*) as count FROM media 
                    WHERE downloaded_at IS NOT NULL
                """)
                downloaded_count = cursor.fetchone()['count']
                
                cursor.execute("""
                    SELECT MIN(posted_at) as oldest, MAX(posted_at) as newest 
                    FROM posts
                """)
                dates = cursor.fetchone()
                
                return {
                    'post_count': post_count,
                    'story_count': story_count,
                    'media_count': media_count,
                    'downloaded_count': downloaded_count,
                    'oldest_post': dates['oldest'],
                    'newest_post': dates['newest'],
                }
                
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}
    
    # ============================================================================
    # Following Accounts Methods (Phase 1: Smart Polling)
    # ============================================================================
    
    def save_following_accounts(self, accounts: List[Dict[str, Any]]) -> bool:
        """Save or update following accounts list.
        
        Replaces the entire following list with the provided accounts.
        Accounts not in the list will be removed.
        
        Args:
            accounts: List of account dicts with keys: user_id, username, full_name, is_private
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Clear existing following accounts first (full replace)
                cursor.execute("DELETE FROM following_accounts")
                
                now = datetime.now()
                for account in accounts:
                    cursor.execute("""
                        INSERT INTO following_accounts 
                        (user_id, username, full_name, is_private, last_checked, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        account['user_id'],
                        account['username'],
                        account.get('full_name'),
                        account.get('is_private', False),
                        now,
                        now
                    ))
                
                logger.info(f"Saved {len(accounts)} following accounts")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save following accounts: {e}")
            return False
    
    def get_following_accounts(self) -> List[Dict[str, Any]]:
        """Get all following accounts from cache.
        
        Returns:
            List of account dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT user_id, username, full_name, is_private, 
                           last_checked, created_at, updated_at
                    FROM following_accounts
                    ORDER BY username
                """)
                accounts = [dict(row) for row in cursor.fetchall()]
                logger.debug(f"Retrieved {len(accounts)} following accounts from cache")
                return accounts
                
        except Exception as e:
            logger.error(f"Failed to get following accounts: {e}")
            return []
    
    def get_following_cache_age(self) -> Optional[timedelta]:
        """Get age of following accounts cache.
        
        Returns:
            timedelta since last cache update, or None if no cache exists
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MAX(last_checked) as last_checked 
                    FROM following_accounts
                """)
                row = cursor.fetchone()
                last_checked = row['last_checked'] if row else None
                
                if last_checked:
                    # Handle both datetime and string types
                    if isinstance(last_checked, str):
                        last_checked = datetime.fromisoformat(last_checked)
                    return datetime.now() - last_checked
                return None
                
        except Exception as e:
            logger.error(f"Failed to get following cache age: {e}")
            return None
    
    # ============================================================================
    # Account Activity Methods (Phase 1: Smart Polling)
    # ============================================================================
    
    def save_account_activity(self, user_id: str, username: str, **kwargs) -> bool:
        """Save or update account activity data.
        
        Args:
            user_id: Instagram user ID
            username: Instagram username
            **kwargs: Optional fields - media_count, last_post_id, last_post_date,
                     last_checked, poll_priority, consecutive_no_new_posts
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                now = datetime.now()
                cursor.execute("""
                    INSERT OR REPLACE INTO account_activity 
                    (user_id, username, media_count, last_post_id, last_post_date,
                     last_checked, poll_priority, consecutive_no_new_posts, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    username,
                    kwargs.get('media_count', 0),
                    kwargs.get('last_post_id'),
                    kwargs.get('last_post_date'),
                    kwargs.get('last_checked', now),
                    kwargs.get('poll_priority', 'normal'),
                    kwargs.get('consecutive_no_new_posts', 0),
                    now
                ))
                
                logger.debug(f"Saved activity for {username} (priority={kwargs.get('poll_priority', 'normal')})")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save activity for {username}: {e}")
            return False
    
    def update_account_activity(self, user_id: str, **kwargs) -> bool:
        """Update specific fields of an account activity record.
        
        Args:
            user_id: Instagram user ID
            **kwargs: Fields to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Build dynamic UPDATE query
                update_fields = []
                values = []
                for key, value in kwargs.items():
                    if key in ['media_count', 'last_post_id', 'last_post_date', 
                              'last_checked', 'poll_priority', 'consecutive_no_new_posts']:
                        update_fields.append(f"{key} = ?")
                        values.append(value)
                
                if not update_fields:
                    logger.warning(f"No valid fields to update for user {user_id}")
                    return False
                
                update_fields.append("updated_at = ?")
                values.append(datetime.now())
                values.append(user_id)
                
                query = f"UPDATE account_activity SET {', '.join(update_fields)} WHERE user_id = ?"
                cursor.execute(query, values)
                
                if cursor.rowcount == 0:
                    logger.warning(f"No activity record found to update for user {user_id}")
                    return False
                
                logger.debug(f"Updated activity for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to update activity for user {user_id}: {e}")
            return False
    
    def get_account_activity(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get account activity data for a specific user.
        
        Args:
            user_id: Instagram user ID
            
        Returns:
            Activity dictionary or None if not found
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM account_activity WHERE user_id = ?
                """, (user_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Failed to get activity for user {user_id}: {e}")
            return None
    
    def get_all_account_activity(self) -> List[Dict[str, Any]]:
        """Get all account activity records.
        
        Returns:
            List of activity dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM account_activity
                    ORDER BY last_checked DESC
                """)
                activities = [dict(row) for row in cursor.fetchall()]
                logger.debug(f"Retrieved {len(activities)} account activity records")
                return activities
                
        except Exception as e:
            logger.error(f"Failed to get all account activity: {e}")
            return []
    
    def get_accounts_by_priority(self, priority: str) -> List[Dict[str, Any]]:
        """Get all accounts with a specific priority level.
        
        Args:
            priority: Priority level ('high', 'normal', 'low', 'dormant')
            
        Returns:
            List of activity dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM account_activity 
                    WHERE poll_priority = ?
                    ORDER BY last_checked ASC
                """, (priority,))
                accounts = [dict(row) for row in cursor.fetchall()]
                logger.debug(f"Retrieved {len(accounts)} accounts with priority={priority}")
                return accounts
                
        except Exception as e:
            logger.error(f"Failed to get accounts by priority {priority}: {e}")
            return []
    
    def get_priority_distribution(self) -> Dict[str, int]:
        """Get count of accounts by priority level.
        
        Returns:
            Dictionary mapping priority -> count
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT poll_priority, COUNT(*) as count
                    FROM account_activity
                    GROUP BY poll_priority
                """)
                distribution = {row['poll_priority']: row['count'] for row in cursor.fetchall()}
                logger.debug(f"Priority distribution: {distribution}")
                return distribution
                
        except Exception as e:
            logger.error(f"Failed to get priority distribution: {e}")
            return {}
    
    # ============================================================================
    # Sync Metadata Methods (Phase 1: Smart Polling)
    # ============================================================================
    
    def save_sync_metadata(self, key: str, value: str) -> bool:
        """Save or update sync metadata.
        
        Args:
            key: Metadata key
            value: Metadata value (stored as string)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO sync_metadata (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, value, datetime.now()))
                logger.debug(f"Saved sync metadata: {key}={value}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save sync metadata {key}: {e}")
            return False
    
    def get_sync_metadata(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get sync metadata value.
        
        Args:
            key: Metadata key
            default: Default value if key not found
            
        Returns:
            Metadata value or default
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT value FROM sync_metadata WHERE key = ?
                """, (key,))
                row = cursor.fetchone()
                value = row['value'] if row else default
                logger.debug(f"Retrieved sync metadata: {key}={value}")
                return value
                
        except Exception as e:
            logger.error(f"Failed to get sync metadata {key}: {e}")
            return default
    
    # ============================================================================
    # Story Methods (Phase 2: Stories Support)
    # ============================================================================
    
    def story_exists(self, story_id: str) -> bool:
        """Check if a story already exists in the database.
        
        Uses in-memory cache to reduce DB queries during bulk operations.
        
        Args:
            story_id: Instagram story ID
            
        Returns:
            True if story exists, False otherwise
        """
        # Check cache first
        if story_id in self._story_exists_cache:
            return True
        
        # Query database
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM stories WHERE id = ?", (story_id,))
            exists = cursor.fetchone() is not None
        
        # Update cache if found
        if exists:
            self._story_exists_cache.add(story_id)
        
        return exists
    
    def save_story(self, story) -> bool:
        """Save a story to the database.
        
        Args:
            story: InstagramStory object to save
            
        Returns:
            True if save successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO stories
                    (id, user_id, username, full_name, taken_at, expires_at,
                     media_url, media_type, permalink, poll_question, poll_options,
                     link_text, sticker_text, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    story.id,
                    story.user_id,
                    story.username,
                    story.full_name,
                    story.taken_at,
                    story.expires_at,
                    story.media_url,
                    story.media_type,
                    story.permalink,
                    story.poll_question,
                    safe_json_dumps(story.poll_options),
                    story.link_text,
                    safe_json_dumps(story.sticker_text)
                ))
                
                # Add to cache
                self._story_exists_cache.add(story.id)
                
                logger.info(f"Saved story {story.id} from @{story.username}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save story {story.id}: {e}")
            return False
    
    def get_story_by_id(self, story_id: str) -> Optional[Dict[str, Any]]:
        """Get a single story by ID.
        
        Args:
            story_id: Instagram story ID
            
        Returns:
            Story dictionary or None if not found
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM stories WHERE id = ?", (story_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get story {story_id}: {e}")
            return None
    
    def get_recent_stories(self, limit: int = 50, days: Optional[int] = None) -> List[Dict[str, Any]]:
        """Query recent stories from the database.
        
        Args:
            limit: Maximum number of stories to return
            days: Only return stories from the last N days (optional)
            
        Returns:
            List of story dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM stories WHERE 1=1"
                params = []
                
                if days is not None:
                    cutoff_date = datetime.now() - timedelta(days=days)
                    query += " AND taken_at >= ?"
                    params.append(cutoff_date)
                
                query += " ORDER BY taken_at DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                stories = [dict(row) for row in cursor.fetchall()]
                
                logger.info(f"Retrieved {len(stories)} stories (limit={limit}, days={days})")
                return stories
                
        except Exception as e:
            logger.error(f"Failed to query recent stories: {e}")
            return []
    
    def update_story_media(self, story_id: str, local_path: str, file_size: int) -> bool:
        """Update story with local file information after download.
        
        Args:
            story_id: Instagram story ID
            local_path: Local filesystem path where file was saved
            file_size: Size of downloaded file in bytes
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE stories
                    SET local_path = ?, file_size = ?, downloaded_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (local_path, file_size, story_id))
                
                if cursor.rowcount == 0:
                    logger.warning(f"No story record found to update for {story_id}")
                    return False
                
                logger.debug(f"Updated story media for {story_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to update story media for {story_id}: {e}")
            return False
    
    # ============================================================================
    # Story Activity Methods (Phase 2: Stories Support)
    # ============================================================================
    
    def save_account_story_activity(self, user_id: str, username: str, **kwargs) -> bool:
        """Save or update account story activity data.
        
        Args:
            user_id: Instagram user ID
            username: Instagram username
            **kwargs: Optional fields - is_muting_stories, last_story_id, 
                     last_story_date, last_checked, story_poll_priority,
                     consecutive_no_new_stories, stories_fetched_count
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                now = datetime.now()
                cursor.execute("""
                    INSERT OR REPLACE INTO account_story_activity
                    (user_id, username, is_muting_stories, last_story_id, 
                     last_story_date, last_checked, story_poll_priority,
                     consecutive_no_new_stories, stories_fetched_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    username,
                    kwargs.get('is_muting_stories', False),
                    kwargs.get('last_story_id'),
                    kwargs.get('last_story_date'),
                    kwargs.get('last_checked', now),
                    kwargs.get('story_poll_priority', 'normal'),
                    kwargs.get('consecutive_no_new_stories', 0),
                    kwargs.get('stories_fetched_count', 0),
                    now
                ))
                
                logger.debug(f"Saved story activity for {username}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save story activity for {username}: {e}")
            return False
    
    def update_account_story_activity(self, user_id: str, **kwargs) -> bool:
        """Update specific fields of an account story activity record.
        
        Args:
            user_id: Instagram user ID
            **kwargs: Fields to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Build dynamic UPDATE query
                update_fields = []
                values = []
                for key, value in kwargs.items():
                    if key in ['is_muting_stories', 'last_story_id', 'last_story_date',
                              'last_checked', 'story_poll_priority', 
                              'consecutive_no_new_stories', 'stories_fetched_count']:
                        update_fields.append(f"{key} = ?")
                        values.append(value)
                
                if not update_fields:
                    logger.warning(f"No valid fields to update for user {user_id}")
                    return False
                
                update_fields.append("updated_at = ?")
                values.append(datetime.now())
                values.append(user_id)
                
                query = f"UPDATE account_story_activity SET {', '.join(update_fields)} WHERE user_id = ?"
                cursor.execute(query, values)
                
                if cursor.rowcount == 0:
                    logger.warning(f"No story activity record found to update for user {user_id}")
                    return False
                
                logger.debug(f"Updated story activity for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to update story activity for user {user_id}: {e}")
            return False
    
    def get_account_story_activity(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get account story activity data for a specific user.
        
        Args:
            user_id: Instagram user ID
            
        Returns:
            Activity dictionary or None if not found
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM account_story_activity WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get story activity for user {user_id}: {e}")
            return None
    
    def get_all_account_story_activity(self) -> List[Dict[str, Any]]:
        """Get all account story activity records.
        
        Returns:
            List of activity dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM account_story_activity ORDER BY last_checked DESC")
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get all story activity: {e}")
            return []
    
    def get_unmuted_accounts_for_stories(self) -> List[Dict[str, Any]]:
        """Get all accounts where is_muting_stories = False.
        
        Returns:
            List of activity dictionaries for unmuted accounts
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM account_story_activity
                    WHERE is_muting_stories = 0
                    ORDER BY last_checked ASC
                """)
                accounts = [dict(row) for row in cursor.fetchall()]
                logger.debug(f"Retrieved {len(accounts)} unmuted accounts for stories")
                return accounts
        except Exception as e:
            logger.error(f"Failed to get unmuted accounts for stories: {e}")
            return []
    
    def get_accounts_by_story_priority(self, priority: str) -> List[Dict[str, Any]]:
        """Get all accounts with a specific story priority level.
        
        Args:
            priority: Priority level ('high', 'normal', 'low', 'dormant')
            
        Returns:
            List of activity dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM account_story_activity
                    WHERE story_poll_priority = ?
                    ORDER BY last_checked ASC
                """, (priority,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get accounts by story priority {priority}: {e}")
            return []
    
    def get_story_priority_distribution(self) -> Dict[str, int]:
        """Get count of accounts by story priority level.
        
        Returns:
            Dictionary mapping priority -> count
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT story_poll_priority, COUNT(*) as count
                    FROM account_story_activity
                    GROUP BY story_poll_priority
                """)
                distribution = {row['story_poll_priority']: row['count'] for row in cursor.fetchall()}
                logger.debug(f"Story priority distribution: {distribution}")
                return distribution
        except Exception as e:
            logger.error(f"Failed to get story priority distribution: {e}")
            return {}

