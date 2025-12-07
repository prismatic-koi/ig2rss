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

from .instagram_client import InstagramPost


logger = logging.getLogger(__name__)


# Configure datetime adapters for SQLite (Python 3.12+ compatibility)
def adapt_datetime(dt: datetime) -> str:
    """Convert datetime to ISO format string for SQLite."""
    return dt.isoformat()


def convert_datetime(val: bytes) -> datetime:
    """Convert ISO format string from SQLite to datetime."""
    return datetime.fromisoformat(val.decode())


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
                    'media_count': media_count,
                    'downloaded_count': downloaded_count,
                    'oldest_post': dates['oldest'],
                    'newest_post': dates['newest'],
                }
                
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}
