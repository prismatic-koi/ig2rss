"""Flask HTTP API for serving RSS feeds and media files.

This module provides the web server that exposes RSS feeds and serves
downloaded media files. It also manages background sync tasks.
"""

import os
import logging
import time
from pathlib import Path
from typing import Optional, Type

from flask import Flask, Response, request, jsonify, send_file
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import Config
from src.storage import StorageManager
from src.rss_generator import RSSGenerator
from src.instagram_client import InstagramClient

logger = logging.getLogger(__name__)


def create_app(config: Type[Config]) -> Flask:
    """Create and configure Flask application.
    
    Args:
        config: Configuration object
        
    Returns:
        Configured Flask app
    """
    
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
    
    # Initialize components
    storage = StorageManager(
        db_path=config.DATABASE_PATH,
        media_dir=config.MEDIA_CACHE_PATH
    )
    
    # Determine base URL for RSS feed
    base_url = os.getenv("BASE_URL", f"http://localhost:{config.PORT}")
    
    rss_generator = RSSGenerator(
        base_url=base_url,
        channel_title=f"Instagram - {config.INSTAGRAM_USERNAME}",
        channel_description=f"RSS feed for Instagram user @{config.INSTAGRAM_USERNAME}"
    )
    
    # Store components in app config for access in routes
    app.config['storage'] = storage
    app.config['rss_generator'] = rss_generator
    app.config['app_config'] = config
    
    # Register routes
    register_routes(app)
    
    # Initialize background sync task
    if config.POLL_INTERVAL > 0:
        scheduler = init_scheduler(app, config)
        app.config['scheduler'] = scheduler
    
    logger.info(f"Flask app created (base_url={base_url})")
    
    return app


def register_routes(app: Flask):
    """Register API routes.
    
    Args:
        app: Flask application
    """
    
    @app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint.
        
        Returns JSON with service status and database stats.
        """
        storage: StorageManager = app.config['storage']
        stats = storage.get_stats()
        
        return jsonify({
            'status': 'healthy',
            'service': 'ig2rss',
            'database': {
                'posts': stats.get('post_count', 0),
                'media': stats.get('media_count', 0),
                'downloaded': stats.get('downloaded_count', 0),
            }
        })
    
    @app.route('/feed.rss', methods=['GET'])
    def feed_rss():
        """RSS feed endpoint.
        
        Query parameters:
            limit: Maximum number of posts (default from config)
            days: Only posts from last N days (default from config)
        
        Returns RSS 2.0 XML feed.
        """
        storage: StorageManager = app.config['storage']
        rss_generator: RSSGenerator = app.config['rss_generator']
        config: Config = app.config['app_config']
        
        # Parse query parameters
        try:
            limit = int(request.args.get('limit', config.RSS_FEED_LIMIT))
            days = int(request.args.get('days', config.RSS_FEED_DAYS))
        except ValueError:
            return jsonify({'error': 'Invalid limit or days parameter'}), 400
        
        # Validate parameters
        if limit < 1 or limit > 1000:
            return jsonify({'error': 'limit must be between 1 and 1000'}), 400
        
        if days < 1 or days > 365:
            return jsonify({'error': 'days must be between 1 and 365'}), 400
        
        # Fetch posts from storage
        posts = storage.get_recent_posts(limit=limit, days=days)
        
        # Generate RSS feed
        rss_xml = rss_generator.generate_feed(posts, limit=limit, days=days)
        
        logger.info(f"Served RSS feed: {len(posts)} posts (limit={limit}, days={days})")
        
        return Response(rss_xml, mimetype='application/rss+xml')
    
    @app.route('/media/<path:media_path>', methods=['GET'])
    def serve_media(media_path: str):
        """Serve media files.
        
        Path format: /media/{post_id}/{index}.{ext}
        
        Args:
            media_path: Relative path to media file (post_id/filename)
        
        Returns media file or 404.
        """
        storage: StorageManager = app.config['storage']
        
        # Construct full path
        full_path = storage.media_dir / media_path
        
        # Security check - ensure path is within media directory
        try:
            full_path = full_path.resolve()
            if not str(full_path).startswith(str(storage.media_dir.resolve())):
                logger.warning(f"Attempted path traversal: {media_path}")
                return jsonify({'error': 'Invalid path'}), 403
        except Exception as e:
            logger.error(f"Path resolution error: {e}")
            return jsonify({'error': 'Invalid path'}), 400
        
        # Check if file exists
        if not full_path.is_file():
            logger.warning(f"Media file not found: {media_path}")
            return jsonify({'error': 'File not found'}), 404
        
        # Determine mime type based on extension
        mime_type = 'image/jpeg' if full_path.suffix.lower() in ['.jpg', '.jpeg'] else 'video/mp4'
        
        logger.debug(f"Serving media: {media_path}")
        
        return send_file(full_path, mimetype=mime_type)
    
    @app.route('/', methods=['GET'])
    def index():
        """Index page with basic info."""
        config: Config = app.config['app_config']
        
        return jsonify({
            'service': 'ig2rss',
            'description': 'Instagram to RSS feed converter',
            'endpoints': {
                'feed': '/feed.rss',
                'health': '/health',
                'media': '/media/{post_id}/{filename}'
            },
            'config': {
                'username': config.INSTAGRAM_USERNAME,
                'poll_interval': config.POLL_INTERVAL,
                'fetch_count': config.FETCH_COUNT,
                'feed_limit': config.RSS_FEED_LIMIT,
                'feed_days': config.RSS_FEED_DAYS,
            }
        })


def init_scheduler(app: Flask, config: Type[Config]) -> BackgroundScheduler:
    """Initialize background scheduler for periodic sync.
    
    Args:
        app: Flask application
        config: Configuration object
        
    Returns:
        Configured scheduler
    """
    scheduler = BackgroundScheduler()
    
    # Define sync job
    def sync_instagram():
        """Sync Instagram posts in background."""
        with app.app_context():
            try:
                logger.info("Starting background Instagram sync")
                
                storage: StorageManager = app.config['storage']
                
                # Create Instagram client with session persistence
                client = InstagramClient(
                    username=config.INSTAGRAM_USERNAME,
                    password=config.INSTAGRAM_PASSWORD,
                    session_file=config.SESSION_FILE
                )
                
                # Login
                if not client.login():
                    logger.error("Failed to login to Instagram")
                    return
                
                # Fetch recent posts
                posts = client.get_timeline_feed(count=config.FETCH_COUNT)
                
                logger.info(f"Fetched {len(posts)} posts from Instagram")
                
                # Save posts
                new_count = 0
                for post in posts:
                    if not storage.post_exists(post.id):
                        if storage.save_post(post):
                            new_count += 1
                            
                            # Download media
                            for idx, (media_url, media_type) in enumerate(zip(post.media_urls, post.media_types)):
                                local_path = storage.get_media_path(post.id, idx, media_type)
                                
                                # Download using requests
                                import requests
                                try:
                                    response = requests.get(media_url, timeout=30)
                                    response.raise_for_status()
                                    
                                    with open(local_path, 'wb') as f:
                                        f.write(response.content)
                                    
                                    file_size = len(response.content)
                                    # Save relative path for URL generation (post_id/filename.ext)
                                    relative_path = f"{post.id}/{local_path.name}"
                                    storage.save_media(post.id, idx, media_url, media_type, relative_path, file_size)
                                    
                                    logger.debug(f"Downloaded media: {local_path}")
                                    
                                    # Small delay between media downloads to avoid hammering CDN
                                    time.sleep(0.5)
                                except Exception as e:
                                    logger.error(f"Failed to download media {media_url}: {e}")
                
                logger.info(f"Background sync complete: {new_count} new posts saved")
                
            except Exception as e:
                logger.error(f"Background sync failed: {e}", exc_info=True)
    
    # Schedule job
    scheduler.add_job(
        func=sync_instagram,
        trigger=IntervalTrigger(seconds=config.POLL_INTERVAL),
        id='instagram_sync',
        name='Sync Instagram posts',
        replace_existing=True
    )
    
    # Run immediately on startup
    scheduler.add_job(
        func=sync_instagram,
        trigger='date',
        id='instagram_sync_startup',
        name='Initial Instagram sync'
    )
    
    scheduler.start()
    logger.info(f"Background scheduler started (interval={config.POLL_INTERVAL}s)")
    
    return scheduler


def run_server(config: Type[Config]):
    """Run Flask development server.
    
    Args:
        config: Configuration object
    """
    # Validate config
    errors = config.validate()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        raise ValueError("Invalid configuration")
    
    # Set up logging
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create app
    app = create_app(config)
    
    # Run server
    logger.info(f"Starting Flask server on {config.HOST}:{config.PORT}")
    
    try:
        app.run(host=config.HOST, port=config.PORT, debug=False)
    finally:
        # Shutdown scheduler
        if 'scheduler' in app.config:
            app.config['scheduler'].shutdown()
            logger.info("Background scheduler stopped")
