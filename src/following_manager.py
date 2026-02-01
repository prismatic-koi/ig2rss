"""Following list manager for caching and refreshing followed accounts.

This module handles the caching and refreshing of the user's following list,
minimizing API calls by maintaining a local cache with configurable TTL.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from .storage import StorageManager
from .instagram_client import InstagramClient


logger = logging.getLogger(__name__)


@dataclass
class FollowedAccount:
    """Represents a followed Instagram account."""
    
    user_id: str
    username: str
    full_name: Optional[str] = None
    is_private: bool = False


class FollowingManager:
    """Manages the list of accounts that the user follows."""
    
    def __init__(
        self, 
        storage: StorageManager, 
        instagram_client: InstagramClient,
        cache_hours: int = 24
    ):
        """Initialize following manager.
        
        Args:
            storage: StorageManager instance
            instagram_client: InstagramClient instance
            cache_hours: Hours before cache is considered stale (default: 24)
        """
        self.storage = storage
        self.instagram_client = instagram_client
        self.cache_hours = cache_hours
        
        logger.info(f"FollowingManager initialized (cache_hours={cache_hours})")
    
    def get_following_list(self, refresh: bool = False) -> List[FollowedAccount]:
        """Get list of followed accounts (cached or from API).
        
        Args:
            refresh: Force refresh from Instagram API
            
        Returns:
            List of FollowedAccount objects
        """
        # Check if we need to refresh
        if refresh or not self._is_cache_fresh():
            logger.info("Following list cache is stale or refresh requested, fetching from API")
            success = self.refresh_following_list()
            
            if not success:
                logger.warning("Failed to refresh following list, using stale cache if available")
        else:
            logger.debug("Using cached following list")
        
        # Get cached data
        accounts_data = self.storage.get_following_accounts()
        
        if not accounts_data:
            logger.warning("No following accounts found in cache")
            return []
        
        # Convert to FollowedAccount objects
        accounts = [
            FollowedAccount(
                user_id=acc['user_id'],
                username=acc['username'],
                full_name=acc.get('full_name'),
                is_private=bool(acc.get('is_private', False))
            )
            for acc in accounts_data
        ]
        
        logger.info(f"Retrieved {len(accounts)} following accounts")
        return accounts
    
    def refresh_following_list(self) -> bool:
        """Force refresh following list from Instagram API.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Fetching following list from Instagram API")
            
            # Ensure client is logged in
            if not self.instagram_client._is_authenticated:
                logger.info("Client not authenticated, logging in")
                self.instagram_client.login()
            
            # Get user's following list
            # Note: This may take a while if following many accounts
            user_id = self.instagram_client.client.user_id
            logger.debug(f"Fetching following list for user_id: {user_id}")
            
            # Get following list from instagrapi
            # Returns list of UserShort objects
            following = self.instagram_client.client.user_following(user_id)
            
            logger.info(f"Retrieved {len(following)} following accounts from API")
            
            # Convert to our format
            accounts = []
            for user in following.values():
                accounts.append({
                    'user_id': str(user.pk),
                    'username': user.username,
                    'full_name': user.full_name,
                    'is_private': user.is_private
                })
            
            # Save to database
            success = self.storage.save_following_accounts(accounts)
            
            if success:
                logger.info(f"Successfully cached {len(accounts)} following accounts")
            else:
                logger.error("Failed to save following accounts to cache")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to refresh following list: {e}", exc_info=True)
            return False
    
    def _is_cache_fresh(self) -> bool:
        """Check if following cache is within TTL.
        
        Returns:
            True if cache is fresh, False if stale or non-existent
        """
        cache_age = self.storage.get_following_cache_age()
        
        if cache_age is None:
            logger.debug("No following cache found")
            return False
        
        is_fresh = cache_age < timedelta(hours=self.cache_hours)
        
        if is_fresh:
            logger.debug(f"Following cache is fresh (age={cache_age})")
        else:
            logger.debug(f"Following cache is stale (age={cache_age}, max={self.cache_hours}h)")
        
        return is_fresh
