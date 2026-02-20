"""Story polling manager for smart, priority-based story fetching.

This module implements intelligent polling of Instagram Stories based on
story activity patterns, separate from post activity tracking.
"""

import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timedelta, timezone

from .storage import StorageManager
from .following_manager import FollowedAccount
from .instagram_client import InstagramClient


logger = logging.getLogger(__name__)


class StoryPollingManager:
    """Manages priority-based polling of Instagram Stories."""
    
    def __init__(
        self,
        storage: StorageManager,
        instagram_client: InstagramClient,
        story_active_days: int = 3,
        story_inactive_days: int = 14,
        story_dormant_days: int = 90,
        poll_high_every_n: int = 1,
        poll_normal_every_n: int = 1,
        poll_low_every_n: int = 3,
        poll_dormant_every_n: int = 12,
        mute_refresh_hours: int = 24
    ):
        """Initialize story polling manager.
        
        Args:
            storage: StorageManager instance
            instagram_client: InstagramClient instance for mute checks
            story_active_days: Days threshold for high priority (default: 3)
            story_inactive_days: Days threshold for normal priority (default: 14)
            story_dormant_days: Days threshold for low priority (default: 90)
            poll_high_every_n: Poll high priority accounts every N cycles (default: 1)
            poll_normal_every_n: Poll normal priority accounts every N cycles (default: 1)
            poll_low_every_n: Poll low priority accounts every N cycles (default: 3)
            poll_dormant_every_n: Poll dormant accounts every N cycles (default: 12)
            mute_refresh_hours: Hours between mute status refreshes (default: 24)
        """
        self.storage = storage
        self.instagram_client = instagram_client
        self.story_active_days = story_active_days
        self.story_inactive_days = story_inactive_days
        self.story_dormant_days = story_dormant_days
        self.poll_high_every_n = poll_high_every_n
        self.poll_normal_every_n = poll_normal_every_n
        self.poll_low_every_n = poll_low_every_n
        self.poll_dormant_every_n = poll_dormant_every_n
        self.mute_refresh_hours = mute_refresh_hours
        
        self.current_cycle = self._load_cycle_number()
        
        logger.info(
            f"StoryPollingManager initialized (cycle={self.current_cycle}, "
            f"mute_refresh={mute_refresh_hours}h)"
        )
    
    def _load_cycle_number(self) -> int:
        """Load current story cycle number from database.
        
        Returns:
            Current cycle number (0 if not found)
        """
        cycle_str = self.storage.get_sync_metadata('story_cycle_number', '0')
        try:
            return int(cycle_str)
        except ValueError:
            logger.warning(f"Invalid story cycle number '{cycle_str}', resetting to 0")
            return 0
    
    def increment_cycle(self) -> int:
        """Increment cycle counter and persist to database.
        
        Returns:
            New cycle number
        """
        self.current_cycle += 1
        self.storage.save_sync_metadata('story_cycle_number', str(self.current_cycle))
        logger.debug(f"Story cycle incremented to {self.current_cycle}")
        return self.current_cycle
    
    def is_first_sync(self) -> bool:
        """Check if this is the first story sync (initialization needed).
        
        Returns:
            True if first sync, False otherwise
        """
        initialized = self.storage.get_sync_metadata('story_initialized', 'false')
        return initialized.lower() != 'true'
    
    def mark_initialized(self):
        """Mark that story initialization is complete."""
        self.storage.save_sync_metadata('story_initialized', 'true')
        logger.info("Story initialization complete, marked as initialized")
    
    def initialize_story_activity_profiles(
        self,
        accounts: List[FollowedAccount]
    ) -> Dict[str, int]:
        """Initialize story activity profiles for accounts.
        
        Checks mute status for each account and sets conservative initial priority.
        
        Args:
            accounts: List of FollowedAccount objects
            
        Returns:
            Dictionary with priority distribution counts
        """
        logger.info(f"Initializing story activity profiles for {len(accounts)} accounts")
        
        now = datetime.now()
        distribution = {'high': 0, 'normal': 0, 'low': 0, 'dormant': 0, 'muted': 0}
        
        for account in accounts:
            # Check if stories are muted for this account
            is_muted = self.instagram_client.check_story_mute_status(account.user_id)
            
            if is_muted:
                logger.info(f"@{account.username}: Stories are muted, will skip")
                distribution['muted'] += 1
            
            # Start with conservative 'normal' priority for all non-muted accounts
            priority = 'normal'
            
            # Save story activity profile
            self.storage.save_account_story_activity(
                user_id=account.user_id,
                username=account.username,
                is_muting_stories=is_muted,
                last_story_id=None,
                last_story_date=None,
                last_checked=now,
                story_poll_priority=priority,
                consecutive_no_new_stories=0,
                stories_fetched_count=0
            )
            
            if not is_muted:
                distribution[priority] += 1
            
            logger.debug(
                f"Initialized @{account.username}: muted={is_muted}, priority={priority}"
            )
        
        logger.info(
            f"Story activity profiles initialized - "
            f"High: {distribution['high']}, Normal: {distribution['normal']}, "
            f"Low: {distribution['low']}, Dormant: {distribution['dormant']}, "
            f"Muted: {distribution['muted']}"
        )
        
        return distribution
    
    def get_accounts_to_poll_this_cycle(
        self,
        max_accounts: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get list of accounts to poll for stories in current cycle.
        
        Only returns unmuted accounts that are due for polling based on their priority.
        
        Args:
            max_accounts: Maximum number of accounts to return (optional)
            
        Returns:
            List of account activity dictionaries
        """
        cycle = self.current_cycle
        accounts_to_poll = []
        
        # Get all unmuted accounts
        unmuted_accounts = self.storage.get_unmuted_accounts_for_stories()
        
        for activity in unmuted_accounts:
            priority = activity['story_poll_priority']
            
            # Determine polling frequency based on priority
            if priority == 'high':
                poll_every_n = self.poll_high_every_n
            elif priority == 'normal':
                poll_every_n = self.poll_normal_every_n
            elif priority == 'low':
                poll_every_n = self.poll_low_every_n
            elif priority == 'dormant':
                poll_every_n = self.poll_dormant_every_n
            else:
                logger.warning(f"Unknown priority '{priority}' for {activity['username']}")
                continue
            
            # Check if account should be polled this cycle
            if cycle % poll_every_n == 0:
                accounts_to_poll.append(activity)
        
        # Sort by last_checked (oldest first)
        accounts_to_poll.sort(key=lambda x: x['last_checked'] or datetime.min)
        
        # Apply max limit if specified
        if max_accounts and len(accounts_to_poll) > max_accounts:
            accounts_to_poll = accounts_to_poll[:max_accounts]
        
        logger.info(
            f"Cycle {cycle}: Polling {len(accounts_to_poll)} accounts for stories "
            f"(total unmuted: {len(unmuted_accounts)})"
        )
        
        return accounts_to_poll
    
    def update_account_priority_after_check(
        self,
        user_id: str,
        username: str,
        has_new_stories: bool,
        story_metadata: Dict[str, Any]
    ) -> str:
        """Update account priority after checking for stories.
        
        Args:
            user_id: Instagram user ID
            username: Instagram username
            has_new_stories: Whether new stories were found
            story_metadata: Metadata from story check (latest_story_id, etc.)
            
        Returns:
            New priority level
        """
        activity = self.storage.get_account_story_activity(user_id)
        
        if not activity:
            logger.warning(f"No story activity record for @{username}")
            return 'normal'
        
        # Update based on story activity
        if has_new_stories:
            # Reset consecutive no-new-stories counter
            new_consecutive = 0
            
            # Update story metadata
            update_kwargs = {
                'last_story_id': story_metadata.get('latest_story_id'),
                'last_story_date': story_metadata.get('latest_story_date'),
                'last_checked': datetime.now(),
                'consecutive_no_new_stories': new_consecutive,
                'stories_fetched_count': activity['stories_fetched_count'] + story_metadata.get('story_count', 0)
            }
        else:
            # Increment consecutive no-new-stories counter
            new_consecutive = activity['consecutive_no_new_stories'] + 1
            
            update_kwargs = {
                'last_checked': datetime.now(),
                'consecutive_no_new_stories': new_consecutive
            }
        
        # Calculate new priority
        new_priority = self._refine_priority(activity, new_consecutive, has_new_stories)
        update_kwargs['story_poll_priority'] = new_priority
        
        # Update in database
        self.storage.update_account_story_activity(user_id, **update_kwargs)
        
        logger.debug(
            f"@{username}: priority={activity['story_poll_priority']}->{new_priority}, "
            f"consecutive_no_new={new_consecutive}, has_new={has_new_stories}"
        )
        
        return new_priority
    
    def _refine_priority(
        self,
        activity: Dict[str, Any],
        consecutive_no_new: int,
        has_new_stories: bool
    ) -> str:
        """Refine priority based on observed story activity.
        
        Args:
            activity: Current activity record
            consecutive_no_new: Number of consecutive checks with no new stories
            has_new_stories: Whether new stories were found in latest check
            
        Returns:
            New priority level
        """
        last_story_date = activity['last_story_date']
        
        # If we have new stories, boost priority
        if has_new_stories:
            return 'high'
        
        # If no last story date, start at normal and degrade over time
        if last_story_date is None:
            if consecutive_no_new >= 10:
                return 'dormant'
            elif consecutive_no_new >= 5:
                return 'low'
            else:
                return 'normal'
        
        # Calculate days since last story
        if isinstance(last_story_date, str):
            last_story_date = datetime.fromisoformat(last_story_date)
        
        # Ensure both datetimes are timezone-aware for correct comparison
        now = datetime.now(timezone.utc)
        if last_story_date.tzinfo is None:
            # Assume UTC if no timezone info
            last_story_date = last_story_date.replace(tzinfo=timezone.utc)
        
        days_since_story = (now - last_story_date).days
        
        # Priority based on recency and consecutive no-new checks
        if days_since_story <= self.story_active_days:
            # Recent stories - keep high priority unless many consecutive misses
            if consecutive_no_new >= 5:
                return 'normal'
            else:
                return 'high'
        elif days_since_story <= self.story_inactive_days:
            # Medium recency
            if consecutive_no_new >= 7:
                return 'low'
            else:
                return 'normal'
        elif days_since_story <= self.story_dormant_days:
            # Old stories
            return 'low'
        else:
            # Very old or no stories
            return 'dormant'
    
    def should_refresh_mute_statuses(self) -> bool:
        """Check if mute statuses should be refreshed.
        
        Returns:
            True if mute refresh is needed
        """
        last_refresh_str = self.storage.get_sync_metadata('last_mute_refresh')
        
        if not last_refresh_str:
            return True
        
        try:
            last_refresh = datetime.fromisoformat(last_refresh_str)
            hours_since_refresh = (datetime.now() - last_refresh).total_seconds() / 3600
            return hours_since_refresh >= self.mute_refresh_hours
        except (ValueError, TypeError):
            logger.warning(f"Invalid last_mute_refresh value: {last_refresh_str}")
            return True
    
    def refresh_mute_statuses(self) -> Tuple[int, int]:
        """Refresh mute status for all accounts.
        
        Returns:
            Tuple of (newly_muted_count, newly_unmuted_count)
        """
        logger.info("Refreshing mute statuses for all accounts")
        
        all_activities = self.storage.get_all_account_story_activity()
        newly_muted = 0
        newly_unmuted = 0
        
        for activity in all_activities:
            old_muted = bool(activity['is_muting_stories'])
            new_muted = self.instagram_client.check_story_mute_status(activity['user_id'])
            
            if old_muted != new_muted:
                if new_muted:
                    newly_muted += 1
                    logger.info(f"@{activity['username']}: Stories newly muted")
                else:
                    newly_unmuted += 1
                    logger.info(f"@{activity['username']}: Stories newly unmuted")
                
                self.storage.update_account_story_activity(
                    activity['user_id'],
                    is_muting_stories=new_muted
                )
        
        # Update last refresh timestamp
        self.storage.save_sync_metadata('last_mute_refresh', datetime.now().isoformat())
        
        logger.info(
            f"Mute status refresh complete: {newly_muted} newly muted, "
            f"{newly_unmuted} newly unmuted"
        )
        
        return newly_muted, newly_unmuted
    
    def get_priority_stats(self) -> Dict[str, Any]:
        """Get statistics about story priority distribution.
        
        Returns:
            Dictionary with priority stats and metadata
        """
        distribution = self.storage.get_story_priority_distribution()
        total_accounts = sum(distribution.values())
        
        # Count muted accounts
        all_activities = self.storage.get_all_account_story_activity()
        muted_count = sum(1 for a in all_activities if a['is_muting_stories'])
        unmuted_count = total_accounts - muted_count
        
        return {
            'cycle': self.current_cycle,
            'total_accounts': total_accounts,
            'unmuted_accounts': unmuted_count,
            'muted_accounts': muted_count,
            'priority_distribution': distribution,
            'is_first_sync': self.is_first_sync()
        }
