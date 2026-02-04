"""Flask HTTP API for serving RSS feeds and media files.

This module provides the web server that exposes RSS feeds and serves
downloaded media files. It also manages background sync tasks.
"""

import os
import logging
import time
from pathlib import Path
from typing import Optional, Type, List
from datetime import datetime

from flask import Flask, Response, request, jsonify, send_file
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import Config
from src.storage import StorageManager
from src.rss_generator import RSSGenerator
from src.instagram_client import InstagramClient, InstagramPost
from src.following_manager import FollowingManager, FollowedAccount
from src.account_polling_manager import AccountPollingManager

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
        ext = full_path.suffix.lower()
        if ext in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif ext == '.webp':
            mime_type = 'image/webp'
        else:
            mime_type = 'video/mp4'
        
        logger.debug(f"Serving media: {media_path}")
        
        return send_file(full_path, mimetype=mime_type)
    
    @app.route('/icon.webp', methods=['GET'])
    def serve_icon():
        """Serve feed icon.
        
        Returns the icon.webp file from assets folder.
        """
        # Icon is in assets folder
        icon_path = Path(__file__).parent.parent / 'assets' / 'icon.webp'
        
        if not icon_path.is_file():
            logger.warning("Feed icon not found")
            return jsonify({'error': 'Icon not found'}), 404
        
        return send_file(icon_path, mimetype='image/webp')
    
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
        """Sync Instagram posts using smart polling or legacy timeline mode."""
        with app.app_context():
            try:
                if config.SMART_POLLING_ENABLED and config.FETCH_STRATEGY == 'profile':
                    _smart_polling_sync(app, config)
                else:
                    _legacy_timeline_sync(app, config)
                    
            except Exception as e:
                logger.error(f"Background sync failed: {e}", exc_info=True)
    
    def _smart_polling_sync(app: Flask, config: Type[Config]):
        """Smart polling sync using profile-based fetching."""
        logger.info("Starting smart polling sync")
        
        storage: StorageManager = app.config['storage']
        
        # Create Instagram client
        client = InstagramClient(
            username=config.INSTAGRAM_USERNAME,
            password=config.INSTAGRAM_PASSWORD,
            session_file=config.SESSION_FILE,
            totp_seed=config.INSTAGRAM_2FA_SEED,
            storage=storage
        )
        
        # Login
        if not client.login():
            logger.error("Failed to login to Instagram")
            return
        
        # Create managers
        following_manager = FollowingManager(
            storage=storage,
            instagram_client=client,
            cache_hours=config.FOLLOWING_CACHE_HOURS
        )
        
        polling_manager = AccountPollingManager(
            storage=storage,
            priority_high_days=config.PRIORITY_HIGH_DAYS,
            priority_normal_days=config.PRIORITY_NORMAL_DAYS,
            priority_low_days=config.PRIORITY_LOW_DAYS,
            poll_high_every_n=config.POLL_HIGH_EVERY_N_CYCLES,
            poll_normal_every_n=config.POLL_NORMAL_EVERY_N_CYCLES,
            poll_low_every_n=config.POLL_LOW_EVERY_N_CYCLES,
            poll_dormant_every_n=config.POLL_DORMANT_EVERY_N_CYCLES,
            priority_overrides=config.PRIORITY_OVERRIDE_ACCOUNTS
        )
        
        # Check if this is first sync (initialization needed)
        if polling_manager.is_first_sync():
            logger.info("=" * 70)
            logger.info("🚀 FIRST SYNC DETECTED - Initializing activity profiles...")
            logger.info("=" * 70)
            
            # Prominent warning if account limiting is active
            if config.MAX_ACCOUNTS_TO_FETCH > 0:
                logger.warning("=" * 70)
                logger.warning(f"⚠️  TESTING MODE: Limited to {config.MAX_ACCOUNTS_TO_FETCH} accounts")
                logger.warning("⚠️  Set MAX_ACCOUNTS_TO_FETCH=0 for unlimited (production mode)")
                logger.warning("=" * 70)
            
            # Get following list
            following_accounts = following_manager.get_following_list()
            logger.info(f"📋 Following {len(following_accounts)} accounts")
            
            # Apply max accounts limit for testing
            if config.MAX_ACCOUNTS_TO_FETCH > 0:
                following_accounts = following_accounts[:config.MAX_ACCOUNTS_TO_FETCH]
                logger.info(f"⚠️  Testing mode: Limiting to {len(following_accounts)} accounts")
            
            # CRITICAL: Save following accounts to DB BEFORE initializing activity profiles
            # This ensures FK constraint is satisfied (account_activity references following_accounts)
            storage.save_following_accounts([{
                'user_id': acc.user_id,
                'username': acc.username,
                'full_name': acc.full_name,
                'is_private': acc.is_private
            } for acc in following_accounts])
            
            logger.info(f"🔍 Fetching 1 post from each account to determine activity levels...")
            
            # Fetch 1 post from each account to determine priority
            posts_by_account = {}
            for idx, account in enumerate(following_accounts, 1):
                try:
                    logger.info(f"[{idx}/{len(following_accounts)}] Checking @{account.username}...")
                    
                    has_new, posts, metadata = client.check_account_for_new_posts(
                        user_id=account.user_id,
                        username=account.username,
                        last_known_post_id=None  # First sync, no known posts
                    )
                    
                    if posts:
                        posts_by_account[account.username] = [
                            {
                                'id': p.id,
                                'posted_at': p.posted_at,
                                'author_username': p.author_username
                            } for p in posts
                        ]
                        
                        # Save posts to database
                        for post in posts:
                            if not storage.post_exists(post.id):
                                storage.save_post(post)
                                _download_post_media(post, storage, client)
                    
                    # Small delay between accounts
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(
                        f"Failed to check @{account.username}: {e}",
                        exc_info=True  # Include full traceback for debugging
                    )
                    posts_by_account[account.username] = []
            
            # Initialize activity profiles
            distribution = polling_manager.initialize_activity_profiles(
                accounts=following_accounts,
                posts_by_account=posts_by_account
            )
            
            # Check initialization success rate
            successful_accounts = sum(1 for posts in posts_by_account.values() if posts)
            total_accounts = len(following_accounts)
            success_rate = successful_accounts / total_accounts if total_accounts > 0 else 0
            
            logger.info(
                f"Initialization results: {successful_accounts}/{total_accounts} accounts "
                f"succeeded ({success_rate:.1%})"
            )
            
            # Only mark as initialized if we got reasonable success
            if success_rate < 0.5:
                logger.error("=" * 70)
                logger.error(
                    f"❌ Initialization failed: only {success_rate:.1%} of accounts "
                    f"initialized successfully."
                )
                logger.error("Will retry initialization on next sync.")
                logger.error("=" * 70)
                return
            
            # Mark as initialized
            polling_manager.mark_initialized()
            
            logger.info("=" * 70)
            logger.info("✅ Activity profiles initialized:")
            logger.info(f"   📈 High priority: {distribution['high']} accounts")
            logger.info(f"   📊 Normal priority: {distribution['normal']} accounts")
            logger.info(f"   📉 Low priority: {distribution['low']} accounts")
            logger.info(f"   💤 Dormant: {distribution['dormant']} accounts")
            logger.info("=" * 70)
            
            return
        
        # Regular sync (not first time)
        polling_manager.increment_cycle()
        
        # Warn on every sync if limiting is active
        if config.MAX_ACCOUNTS_TO_FETCH > 0:
            logger.warning(
                f"Account limit active: MAX_ACCOUNTS_TO_FETCH={config.MAX_ACCOUNTS_TO_FETCH} "
                f"(set to 0 for unlimited)"
            )
        
        # Validate session before starting sync
        if not client.validate_session():
            logger.warning("Session validation failed. Attempting to re-authenticate...")
            if not client.login():
                logger.error("Failed to re-authenticate. Aborting sync.")
                return
            logger.info("Re-authentication successful. Proceeding with sync.")
        
        # Refresh following list (respects cache TTL)
        following_accounts = following_manager.get_following_list()
        logger.debug(f"Following {len(following_accounts)} accounts (from cache)")
        
        # Sync account_activity with following list (add new follows, keep orphaned for now)
        _sync_following_with_activity(storage, following_accounts, polling_manager)
        
        # Get accounts to poll this cycle
        accounts_to_poll = polling_manager.get_accounts_to_poll_this_cycle(
            max_accounts=config.MAX_ACCOUNTS_TO_FETCH if config.MAX_ACCOUNTS_TO_FETCH > 0 else None
        )
        
        if not accounts_to_poll:
            logger.info("No accounts to poll this cycle")
            return
        
        logger.info(f"Cycle {polling_manager.current_cycle}: Polling {len(accounts_to_poll)} accounts")
        
        # Poll each account
        total_new_posts = 0
        accounts_with_new_posts = 0
        
        for idx, activity in enumerate(accounts_to_poll, 1):
            try:
                username = activity['username']
                user_id = activity['user_id']
                last_post_id = activity.get('last_post_id')
                
                logger.info(
                    f"[{idx}/{len(accounts_to_poll)}] Checking @{username} "
                    f"(priority: {activity['poll_priority']})"
                )
                
                has_new, posts, metadata = client.check_account_for_new_posts(
                    user_id=user_id,
                    username=username,
                    last_known_post_id=last_post_id
                )
                
                if has_new and posts:
                    accounts_with_new_posts += 1
                    
                    # Save new posts
                    for post in posts:
                        if not storage.post_exists(post.id):
                            storage.save_post(post)
                            _download_post_media(post, storage, client)
                            total_new_posts += 1
                    
                    logger.info(f"✅ @{username}: {len(posts)} posts fetched")
                else:
                    logger.info(f"⏭️  @{username}: No new posts")
                
                # Update account priority
                polling_manager.update_account_priority(
                    user_id=user_id,
                    username=username,
                    has_new_posts=has_new,
                    metadata=metadata
                )
                
                # Delay between accounts
                time.sleep(1)
                
            except Exception as e:
                logger.error(
                    f"Failed to check @{activity['username']}: {e}",
                    exc_info=True  # Include full traceback for debugging
                )
        
        # Log summary
        stats = polling_manager.get_priority_stats()
        reauth_metrics = client.get_reauth_metrics()
        
        logger.info("=" * 70)
        logger.info(f"Sync complete:")
        logger.info(f"   Cycle: {stats['cycle']}")
        logger.info(f"   Accounts polled: {len(accounts_to_poll)}")
        logger.info(f"   Accounts with new posts: {accounts_with_new_posts}")
        logger.info(f"   New posts saved: {total_new_posts}")
        
        # Log re-authentication metrics if any re-auth occurred
        if reauth_metrics['reauth_attempts'] > 0:
            logger.info(f"   Re-auth attempts: {reauth_metrics['reauth_attempts']}")
            logger.info(f"   Re-auth successes: {reauth_metrics['reauth_successes']}")
            logger.info(f"   Re-auth failures: {reauth_metrics['reauth_failures']}")
        
        logger.info(f"   Priority distribution:")
        for priority, count in stats['distribution'].items():
            logger.info(f"      {priority}: {count} accounts")
        logger.info("=" * 70)
    
    def _sync_following_with_activity(
        storage: StorageManager,
        following_accounts: List[FollowedAccount],
        polling_manager: AccountPollingManager
    ):
        """Sync following list with account_activity table.
        
        Adds newly followed accounts to account_activity.
        Keeps unfollowed accounts for historical data (can be cleaned up separately).
        """
        existing_activities = {a['user_id']: a for a in storage.get_all_account_activity()}
        following_user_ids = {acc.user_id for acc in following_accounts}
        
        # Add new follows
        new_follows = [acc for acc in following_accounts if acc.user_id not in existing_activities]
        
        if new_follows:
            logger.info(f"Found {len(new_follows)} newly followed accounts, adding to tracking...")
            for account in new_follows:
                # Initialize with conservative priority
                storage.save_account_activity(
                    user_id=account.user_id,
                    username=account.username,
                    media_count=0,
                    last_post_id=None,
                    last_post_date=None,
                    last_checked=datetime.now(),
                    poll_priority='normal',  # Start as normal, will refine
                    consecutive_no_new_posts=0
                )
                logger.info(f"Added newly followed account: @{account.username}")
        
        # Optional: Log unfollowed accounts (but keep them for historical data)
        unfollowed = [uid for uid in existing_activities if uid not in following_user_ids]
        if unfollowed:
            logger.debug(f"{len(unfollowed)} accounts in activity table are no longer followed (keeping for history)")
    
    def _download_post_media(post: InstagramPost, storage: StorageManager, client: InstagramClient):
        """Download media for a post using client's retry logic.
        
        Args:
            post: Instagram post with media to download
            storage: Storage manager for saving media metadata
            client: Instagram client with download_media method and retry logic
        """
        for idx, (media_url, media_type) in enumerate(zip(post.media_urls, post.media_types)):
            try:
                local_path = storage.get_media_path(post.id, idx, media_type)
                
                # Use client's download_media method which includes retry logic
                if client.download_media(media_url, str(local_path)):
                    file_size = local_path.stat().st_size
                    relative_path = f"{post.id}/{local_path.name}"
                    storage.save_media(post.id, idx, media_url, media_type, relative_path, file_size)
                    logger.debug(f"Downloaded media: {local_path}")
                else:
                    logger.error(f"Failed to download media {media_url}")
                
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Failed to download media for post {post.id}: {e}")
    
    def _legacy_timeline_sync(app: Flask, config: Type[Config]):
        """Legacy timeline-based sync (original behavior)."""
        logger.info("Starting legacy timeline sync")
        
        storage: StorageManager = app.config['storage']
        
        # Create Instagram client with session persistence
        client = InstagramClient(
            username=config.INSTAGRAM_USERNAME,
            password=config.INSTAGRAM_PASSWORD,
            session_file=config.SESSION_FILE,
            totp_seed=config.INSTAGRAM_2FA_SEED,
            storage=storage
        )
        
        # Login
        if not client.login():
            logger.error("Failed to login to Instagram")
            return
        
        # Fetch recent posts
        posts = client.get_timeline_feed(count=config.FETCH_COUNT)
        
        logger.info(f"📥 Fetched {len(posts)} posts from Instagram (after ad filtering)")
        
        # Save posts
        new_count = 0
        duplicate_count = 0
        for post in posts:
            if not storage.post_exists(post.id):
                if storage.save_post(post):
                    new_count += 1
                    logger.info(f"💾 SAVED NEW POST from @{post.author_username} (id: {post.id})")
                    _download_post_media(post, storage, client)
            else:
                duplicate_count += 1
                logger.info(f"⏭️  DUPLICATE (already in DB) from @{post.author_username} (id: {post.id})")
        
        logger.info(f"Background sync complete: {new_count} new posts saved, {duplicate_count} duplicates skipped")
    
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
