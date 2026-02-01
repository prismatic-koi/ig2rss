"""Account polling manager for smart, priority-based fetching.

This module implements intelligent polling of Instagram accounts based on their
activity patterns. It uses a hybrid approach:
- Cold start: Conservative priority assignment based on last post date
- Refinement: Adaptive priority adjustment after observing activity for 24 hours
"""

import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta

from .storage import StorageManager
from .following_manager import FollowedAccount


logger = logging.getLogger(__name__)


class AccountPollingManager:
    """Manages priority-based polling of Instagram accounts."""
    
    def __init__(
        self,
        storage: StorageManager,
        priority_high_days: int = 7,
        priority_normal_days: int = 30,
        priority_low_days: int = 180,
        poll_high_every_n: int = 1,
        poll_normal_every_n: int = 1,
        poll_low_every_n: int = 3,
        poll_dormant_every_n: int = 12,
        priority_overrides: Optional[List[str]] = None
    ):
        """Initialize account polling manager.
        
        Args:
            storage: StorageManager instance
            priority_high_days: Days threshold for high priority (default: 7)
            priority_normal_days: Days threshold for normal priority (default: 30)
            priority_low_days: Days threshold for low priority (default: 180)
            poll_high_every_n: Poll high priority accounts every N cycles (default: 1)
            poll_normal_every_n: Poll normal priority accounts every N cycles (default: 1)
            poll_low_every_n: Poll low priority accounts every N cycles (default: 3)
            poll_dormant_every_n: Poll dormant accounts every N cycles (default: 12)
            priority_overrides: List of usernames to force to HIGH priority
        """
        self.storage = storage
        self.priority_high_days = priority_high_days
        self.priority_normal_days = priority_normal_days
        self.priority_low_days = priority_low_days
        self.poll_high_every_n = poll_high_every_n
        self.poll_normal_every_n = poll_normal_every_n
        self.poll_low_every_n = poll_low_every_n
        self.poll_dormant_every_n = poll_dormant_every_n
        self.priority_overrides = set(priority_overrides or [])
        
        self.current_cycle = self._load_cycle_number()
        
        logger.info(
            f"AccountPollingManager initialized (cycle={self.current_cycle}, "
            f"overrides={len(self.priority_overrides)})"
        )
    
    def _load_cycle_number(self) -> int:
        """Load current cycle number from database.
        
        Returns:
            Current cycle number (0 if not found)
        """
        cycle_str = self.storage.get_sync_metadata('cycle_number', '0')
        try:
            return int(cycle_str)
        except ValueError:
            logger.warning(f"Invalid cycle number '{cycle_str}', resetting to 0")
            return 0
    
    def increment_cycle(self) -> int:
        """Increment cycle counter and persist to database.
        
        Returns:
            New cycle number
        """
        self.current_cycle += 1
        self.storage.save_sync_metadata('cycle_number', str(self.current_cycle))
        logger.debug(f"Cycle incremented to {self.current_cycle}")
        return self.current_cycle
    
    def is_first_sync(self) -> bool:
        """Check if this is the first sync (initialization needed).
        
        Returns:
            True if first sync, False otherwise
        """
        initialized = self.storage.get_sync_metadata('initialized', 'false')
        return initialized.lower() != 'true'
    
    def mark_initialized(self):
        """Mark that initialization is complete."""
        self.storage.save_sync_metadata('initialized', 'true')
        logger.info("Initialization complete, marked as initialized")
    
    def initialize_activity_profiles(
        self, 
        accounts: List[FollowedAccount],
        posts_by_account: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, int]:
        """Initialize activity profiles for accounts (cold start).
        
        Uses conservative priority assignment based on last post date.
        
        Args:
            accounts: List of FollowedAccount objects
            posts_by_account: Dict mapping username -> list of posts (may be empty)
            
        Returns:
            Dictionary with priority distribution counts
        """
        logger.info(f"Initializing activity profiles for {len(accounts)} accounts")
        
        now = datetime.now()
        distribution = {'high': 0, 'normal': 0, 'low': 0, 'dormant': 0}
        
        for account in accounts:
            # Get latest post for this account
            posts = posts_by_account.get(account.username, [])
            
            if posts:
                # Get most recent post date
                latest_post = max(posts, key=lambda p: p['posted_at'])
                last_post_date = latest_post['posted_at']
                last_post_id = latest_post['id']
                media_count = len(posts)  # Approximate
            else:
                last_post_date = None
                last_post_id = None
                media_count = 0
            
            # Calculate initial priority
            priority = self._calculate_initial_priority(last_post_date)
            
            # Apply override if specified
            if account.username in self.priority_overrides:
                logger.info(f"Applying priority override for @{account.username}: {priority} -> high")
                priority = 'high'
            
            # Save activity profile
            self.storage.save_account_activity(
                user_id=account.user_id,
                username=account.username,
                media_count=media_count,
                last_post_id=last_post_id,
                last_post_date=last_post_date,
                last_checked=now,
                poll_priority=priority,
                consecutive_no_new_posts=0
            )
            
            distribution[priority] += 1
            logger.debug(
                f"Initialized @{account.username}: priority={priority}, "
                f"last_post={last_post_date}"
            )
        
        logger.info(
            f"Activity profiles initialized - "
            f"High: {distribution['high']}, Normal: {distribution['normal']}, "
            f"Low: {distribution['low']}, Dormant: {distribution['dormant']}"
        )
        
        return distribution
    
    def _calculate_initial_priority(self, last_post_date: Optional[datetime]) -> str:
        """Calculate conservative initial priority based on last post date.
        
        Args:
            last_post_date: Date of account's most recent post (or None)
            
        Returns:
            Priority level: 'high', 'normal', 'low', or 'dormant'
        """
        if last_post_date is None:
            return 'dormant'
        
        days_since_post = (datetime.now() - last_post_date).days
        
        if days_since_post <= self.priority_normal_days:
            # Conservative: Recent posters start as normal
            return 'normal'
        elif days_since_post <= self.priority_low_days:
            return 'low'
        else:
            return 'dormant'
    
    def get_accounts_to_poll_this_cycle(
        self, 
        max_accounts: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get accounts that should be polled in this cycle.
        
        Uses priority-based scheduling to determine which accounts to check.
        
        Args:
            max_accounts: Maximum number of accounts to return (None=unlimited)
            
        Returns:
            List of account activity dictionaries
        """
        accounts_to_poll = []
        
        # Get all account activities
        all_activities = self.storage.get_all_account_activity()
        
        if not all_activities:
            logger.warning("No account activity records found")
            return []
        
        # Filter by priority and cycle schedule
        for activity in all_activities:
            priority = activity['poll_priority']
            username = activity['username']
            
            # Priority overrides always get polled
            if username in self.priority_overrides:
                accounts_to_poll.append(activity)
                continue
            
            # Check if this priority should be polled this cycle
            should_poll = False
            
            if priority == 'high' and self.current_cycle % self.poll_high_every_n == 0:
                should_poll = True
            elif priority == 'normal' and self.current_cycle % self.poll_normal_every_n == 0:
                should_poll = True
            elif priority == 'low' and self.current_cycle % self.poll_low_every_n == 0:
                should_poll = True
            elif priority == 'dormant' and self.current_cycle % self.poll_dormant_every_n == 0:
                should_poll = True
            
            if should_poll:
                accounts_to_poll.append(activity)
        
        # Apply max accounts limit if specified
        if max_accounts and max_accounts > 0:
            # Sort by priority (high first) and last_checked (oldest first)
            priority_order = {'high': 0, 'normal': 1, 'low': 2, 'dormant': 3}
            accounts_to_poll.sort(
                key=lambda a: (
                    priority_order.get(a['poll_priority'], 4),
                    a['last_checked']
                )
            )
            accounts_to_poll = accounts_to_poll[:max_accounts]
        
        logger.info(
            f"Cycle {self.current_cycle}: {len(accounts_to_poll)} accounts to poll "
            f"(max={max_accounts or 'unlimited'})"
        )
        
        return accounts_to_poll
    
    def update_account_priority(
        self,
        user_id: str,
        username: str,
        has_new_posts: bool,
        metadata: Dict[str, Any]
    ):
        """Update account priority based on fetching results.
        
        Args:
            user_id: Instagram user ID
            username: Instagram username
            has_new_posts: Whether new posts were found
            metadata: Metadata dict with media_count, latest_post_id, latest_post_date
        """
        # Get current activity record
        activity = self.storage.get_account_activity(user_id)
        
        if not activity:
            logger.warning(f"No activity record found for @{username}, skipping update")
            return
        
        now = datetime.now()
        updates = {
            'last_checked': now,
            'media_count': metadata.get('media_count', activity['media_count'])
        }
        
        # Update post tracking
        if has_new_posts:
            updates['last_post_id'] = metadata.get('latest_post_id')
            updates['last_post_date'] = metadata.get('latest_post_date')
            updates['consecutive_no_new_posts'] = 0
        else:
            updates['consecutive_no_new_posts'] = activity['consecutive_no_new_posts'] + 1
        
        # Refine priority after observation period (24 hours = ~72 cycles @ 20 min)
        created_at = activity['created_at']
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        observation_hours = (now - created_at).total_seconds() / 3600
        
        if observation_hours >= 24:
            new_priority = self._refine_priority(activity, has_new_posts, metadata)
            
            # Apply override if specified
            if username in self.priority_overrides:
                new_priority = 'high'
            
            if new_priority != activity['poll_priority']:
                logger.info(
                    f"@{username}: Priority updated {activity['poll_priority']} -> {new_priority} "
                    f"(observation: {observation_hours:.1f}h)"
                )
                updates['poll_priority'] = new_priority
        
        # Save updates
        self.storage.update_account_activity(user_id, **updates)
    
    def _refine_priority(
        self,
        activity: Dict[str, Any],
        has_new_posts: bool,
        metadata: Dict[str, Any]
    ) -> str:
        """Refine priority based on observed activity.
        
        Args:
            activity: Current activity record
            has_new_posts: Whether new posts were found this check
            metadata: Metadata from this check
            
        Returns:
            Refined priority level
        """
        # If posted recently (new content detected), upgrade to high
        if has_new_posts:
            last_post_date = metadata.get('latest_post_date')
            if last_post_date:
                days_since_post = (datetime.now() - last_post_date).days
                
                if days_since_post <= self.priority_high_days:
                    return 'high'
                elif days_since_post <= self.priority_normal_days:
                    return 'normal'
                elif days_since_post <= self.priority_low_days:
                    return 'low'
        
        # Use last known post date for priority calculation
        last_post_date = activity.get('last_post_date')
        if last_post_date:
            if isinstance(last_post_date, str):
                last_post_date = datetime.fromisoformat(last_post_date)
            
            days_since_post = (datetime.now() - last_post_date).days
            
            if days_since_post <= self.priority_high_days:
                return 'high'
            elif days_since_post <= self.priority_normal_days:
                return 'normal'
            elif days_since_post <= self.priority_low_days:
                return 'low'
        
        # No posts or very old posts = dormant
        return 'dormant'
    
    def get_priority_stats(self) -> Dict[str, Any]:
        """Get statistics about current priority distribution.
        
        Returns:
            Dictionary with stats about accounts and priorities
        """
        distribution = self.storage.get_priority_distribution()
        all_activities = self.storage.get_all_account_activity()
        
        # Calculate additional stats
        total_accounts = len(all_activities)
        
        # Count accounts eligible for this cycle
        eligible_count = len(self.get_accounts_to_poll_this_cycle())
        
        return {
            'total_accounts': total_accounts,
            'cycle': self.current_cycle,
            'distribution': distribution,
            'eligible_this_cycle': eligible_count,
            'priority_overrides': len(self.priority_overrides)
        }
