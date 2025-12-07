#!/usr/bin/env python3
"""Manual test script for Instagram client with real credentials.

This script can be used to test the Instagram client with real credentials.
Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD environment variables before running.

Usage:
    export INSTAGRAM_USERNAME="your_username"
    export INSTAGRAM_PASSWORD="your_password"
    python tests/manual_test_instagram.py
"""

import os
import sys
import logging
from datetime import datetime

# Add parent directory to path to import src module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.instagram_client import InstagramClient
from src.config import Config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Run manual test with real Instagram credentials."""
    
    # Load credentials from environment
    username = os.getenv("INSTAGRAM_USERNAME")
    password = os.getenv("INSTAGRAM_PASSWORD")
    
    if not username or not password:
        logger.error("INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD must be set")
        logger.error("Example:")
        logger.error('  export INSTAGRAM_USERNAME="your_username"')
        logger.error('  export INSTAGRAM_PASSWORD="your_password"')
        return 1
    
    logger.info("=" * 70)
    logger.info("Instagram Client Manual Test")
    logger.info("=" * 70)
    logger.info(f"Testing with username: {username}")
    
    try:
        # Initialize client
        logger.info("\n[1/3] Initializing Instagram client...")
        client = InstagramClient(username, password)
        logger.info("✓ Client initialized")
        
        # Test login
        logger.info("\n[2/3] Testing login...")
        success = client.login()
        if success:
            logger.info("✓ Login successful!")
        else:
            logger.error("✗ Login failed")
            return 1
        
        # Test fetching timeline feed
        logger.info("\n[3/3] Testing timeline feed fetch...")
        logger.info("Fetching up to 10 posts from your home feed...")
        posts = client.get_timeline_feed(count=10)
        
        logger.info(f"✓ Successfully fetched {len(posts)} posts\n")
        
        # Display post summaries
        logger.info("=" * 70)
        logger.info("POST SUMMARIES")
        logger.info("=" * 70)
        
        for i, post in enumerate(posts, 1):
            logger.info(f"\nPost {i}:")
            logger.info(f"  ID: {post.id}")
            logger.info(f"  Author: @{post.author_username} ({post.author_full_name})")
            logger.info(f"  Type: {post.post_type}")
            logger.info(f"  Posted: {post.posted_at}")
            logger.info(f"  Media items: {len(post.media_urls)}")
            if post.caption:
                caption_preview = post.caption[:100] + "..." if len(post.caption) > 100 else post.caption
                logger.info(f"  Caption: {caption_preview}")
            logger.info(f"  Permalink: {post.permalink}")
        
        logger.info("\n" + "=" * 70)
        logger.info("TEST SUMMARY")
        logger.info("=" * 70)
        logger.info("✓ All tests passed!")
        logger.info(f"✓ Successfully authenticated as @{username}")
        logger.info(f"✓ Retrieved {len(posts)} posts from timeline")
        logger.info(f"✓ Post types found: {', '.join(set(p.post_type for p in posts))}")
        logger.info("=" * 70)
        
        # Clean up
        client.logout()
        
        return 0
        
    except Exception as e:
        logger.error(f"\n✗ Test failed with error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
