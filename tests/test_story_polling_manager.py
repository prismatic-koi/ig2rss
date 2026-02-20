"""Tests for story polling manager."""

import pytest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, MagicMock

from src.storage import StorageManager
from src.story_polling_manager import StoryPollingManager
from src.following_manager import FollowedAccount
from src.instagram_client import InstagramClient


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def storage(temp_db):
    """Create a StorageManager with temporary database."""
    return StorageManager(db_path=temp_db, media_dir=tempfile.mkdtemp())


@pytest.fixture
def mock_instagram_client():
    """Create a mock Instagram client."""
    client = Mock(spec=InstagramClient)
    client.check_story_mute_status = Mock(return_value=False)
    client.check_account_for_new_stories = Mock(return_value=(False, [], {}))
    return client


@pytest.fixture
def story_manager(storage, mock_instagram_client):
    """Create a StoryPollingManager."""
    return StoryPollingManager(
        storage=storage,
        instagram_client=mock_instagram_client,
        story_active_days=3,
        story_inactive_days=14,
        story_dormant_days=90,
        mute_refresh_hours=24
    )


@pytest.fixture
def sample_accounts():
    """Create sample followed accounts."""
    return [
        FollowedAccount(
            user_id='user1',
            username='active_user',
            full_name='Active User',
            is_private=False
        ),
        FollowedAccount(
            user_id='user2',
            username='inactive_user',
            full_name='Inactive User',
            is_private=False
        ),
        FollowedAccount(
            user_id='user3',
            username='dormant_user',
            full_name='Dormant User',
            is_private=False
        )
    ]


class TestStoryPollingManager:
    """Tests for StoryPollingManager."""
    
    def test_initialization(self, storage, mock_instagram_client):
        """Test manager initialization."""
        manager = StoryPollingManager(
            storage=storage,
            instagram_client=mock_instagram_client,
            story_active_days=3,
            story_inactive_days=14,
            story_dormant_days=90,
            mute_refresh_hours=24
        )
        
        assert manager.storage == storage
        assert manager.instagram_client == mock_instagram_client
        assert manager.story_active_days == 3
        assert manager.story_inactive_days == 14
        assert manager.story_dormant_days == 90
        assert manager.mute_refresh_hours == 24
    
    def test_is_first_sync(self, story_manager):
        """Test first sync detection."""
        assert story_manager.is_first_sync() is True
        
        story_manager.mark_initialized()
        
        assert story_manager.is_first_sync() is False
    
    def test_cycle_increment(self, story_manager):
        """Test cycle counter increments correctly."""
        initial_cycle = story_manager.current_cycle
        
        new_cycle = story_manager.increment_cycle()
        
        assert new_cycle == initial_cycle + 1
        assert story_manager.current_cycle == new_cycle
    
    def test_initialize_activity_profiles(self, story_manager, sample_accounts, mock_instagram_client):
        """Test initializing story activity profiles."""
        # Mock mute status: first user muted, others not
        mock_instagram_client.check_story_mute_status.side_effect = [True, False, False]
        
        distribution = story_manager.initialize_story_activity_profiles(sample_accounts)
        
        # Check distribution
        assert distribution['muted'] == 1
        assert distribution['normal'] == 2  # Conservative initial priority
        assert distribution['high'] == 0
        assert distribution['dormant'] == 0
        
        # Verify mute status checks were called
        assert mock_instagram_client.check_story_mute_status.call_count == 3
    
    def test_priority_refinement_recent_story(self, story_manager, storage):
        """Test priority refinement for account with recent story."""
        # Setup account with story from 2 days ago
        storage.save_following_accounts([{
            'user_id': 'user1',
            'username': 'testuser',
            'full_name': 'Test User',
            'is_private': False
        }])
        
        storage.save_account_story_activity(
            user_id='user1',
            username='testuser',
            last_story_id='story1',
            last_story_date=datetime.now(timezone.utc) - timedelta(days=2),
            last_checked=datetime.now(timezone.utc),
            story_poll_priority='normal',
            consecutive_no_new_stories=0
        )
        
        # Update with new stories found
        new_priority = story_manager.update_account_priority_after_check(
            user_id='user1',
            username='testuser',
            has_new_stories=True,
            story_metadata={
                'latest_story_id': 'story2',
                'latest_story_date': datetime.now(timezone.utc),
                'story_count': 1
            }
        )
        
        # Should be upgraded to high due to new stories
        assert new_priority == 'high'
    
    def test_priority_refinement_no_new_stories(self, story_manager, storage):
        """Test priority downgrade when no new stories found."""
        # Setup account with story from 10 days ago
        storage.save_following_accounts([{
            'user_id': 'user1',
            'username': 'testuser',
            'full_name': 'Test User',
            'is_private': False
        }])
        
        storage.save_account_story_activity(
            user_id='user1',
            username='testuser',
            last_story_id='story1',
            last_story_date=datetime.now(timezone.utc) - timedelta(days=10),
            last_checked=datetime.now(timezone.utc),
            story_poll_priority='normal',
            consecutive_no_new_stories=5
        )
        
        # Update with no new stories
        new_priority = story_manager.update_account_priority_after_check(
            user_id='user1',
            username='testuser',
            has_new_stories=False,
            story_metadata={}
        )
        
        # Should be downgraded due to no new stories and time
        assert new_priority == 'normal'
    
    def test_priority_refinement_dormant_account(self, story_manager, storage):
        """Test priority for dormant account."""
        # Setup account with story from 100 days ago
        storage.save_following_accounts([{
            'user_id': 'user1',
            'username': 'testuser',
            'full_name': 'Test User',
            'is_private': False
        }])
        
        storage.save_account_story_activity(
            user_id='user1',
            username='testuser',
            last_story_id='story1',
            last_story_date=datetime.now(timezone.utc) - timedelta(days=100),
            last_checked=datetime.now(timezone.utc),
            story_poll_priority='low',
            consecutive_no_new_stories=10
        )
        
        # Update with no new stories
        new_priority = story_manager.update_account_priority_after_check(
            user_id='user1',
            username='testuser',
            has_new_stories=False,
            story_metadata={}
        )
        
        # Should be marked as dormant
        assert new_priority == 'dormant'
    
    def test_priority_refinement_no_stories_ever(self, story_manager, storage):
        """Test priority for account that never posted stories."""
        # Setup account with no stories
        storage.save_following_accounts([{
            'user_id': 'user1',
            'username': 'testuser',
            'full_name': 'Test User',
            'is_private': False
        }])
        
        storage.save_account_story_activity(
            user_id='user1',
            username='testuser',
            last_story_id=None,
            last_story_date=None,
            last_checked=datetime.now(timezone.utc),
            story_poll_priority='normal',
            consecutive_no_new_stories=0
        )
        
        # Check multiple times without finding stories
        new_priority = 'normal'  # Initialize
        for i in range(12):
            new_priority = story_manager.update_account_priority_after_check(
                user_id='user1',
                username='testuser',
                has_new_stories=False,
                story_metadata={}
            )
        
        # Should eventually be marked as dormant
        assert new_priority == 'dormant'
    
    def test_get_accounts_to_poll_this_cycle(self, story_manager, storage, sample_accounts):
        """Test getting accounts to poll for current cycle."""
        # Initialize profiles
        storage.save_following_accounts([{
            'user_id': acc.user_id,
            'username': acc.username,
            'full_name': acc.full_name,
            'is_private': acc.is_private
        } for acc in sample_accounts])
        
        for acc in sample_accounts:
            storage.save_account_story_activity(
                user_id=acc.user_id,
                username=acc.username,
                is_muting_stories=False,
                last_checked=datetime.now(timezone.utc),
                story_poll_priority='normal'
            )
        
        # Increment cycle
        story_manager.increment_cycle()
        
        # Get accounts to poll
        accounts = story_manager.get_accounts_to_poll_this_cycle()
        
        # All should be polled (normal priority = every cycle)
        assert len(accounts) == 3
    
    def test_get_accounts_excludes_muted(self, story_manager, storage, sample_accounts):
        """Test that muted accounts are excluded from polling."""
        # Initialize profiles with one muted
        storage.save_following_accounts([{
            'user_id': acc.user_id,
            'username': acc.username,
            'full_name': acc.full_name,
            'is_private': acc.is_private
        } for acc in sample_accounts])
        
        storage.save_account_story_activity(
            user_id='user1',
            username='active_user',
            is_muting_stories=True,  # Muted
            story_poll_priority='normal'
        )
        
        storage.save_account_story_activity(
            user_id='user2',
            username='inactive_user',
            is_muting_stories=False,
            story_poll_priority='normal'
        )
        
        storage.save_account_story_activity(
            user_id='user3',
            username='dormant_user',
            is_muting_stories=False,
            story_poll_priority='normal'
        )
        
        # Get accounts to poll
        story_manager.increment_cycle()
        accounts = story_manager.get_accounts_to_poll_this_cycle()
        
        # Should only get unmuted accounts
        assert len(accounts) == 2
        usernames = [a['username'] for a in accounts]
        assert 'active_user' not in usernames  # Muted account excluded
        assert 'inactive_user' in usernames
        assert 'dormant_user' in usernames
    
    def test_mute_status_refresh_needed(self, story_manager):
        """Test mute status refresh detection."""
        # Initially should need refresh
        assert story_manager.should_refresh_mute_statuses() is True
        
        # After refresh, should not need it
        story_manager.storage.save_sync_metadata('last_mute_refresh', datetime.now().isoformat())
        assert story_manager.should_refresh_mute_statuses() is False
        
        # After 25 hours, should need refresh again
        old_time = datetime.now() - timedelta(hours=25)
        story_manager.storage.save_sync_metadata('last_mute_refresh', old_time.isoformat())
        assert story_manager.should_refresh_mute_statuses() is True
    
    def test_mute_status_refresh(self, storage, sample_accounts, mock_instagram_client):
        """Test refreshing mute statuses."""
        # Setup accounts
        storage.save_following_accounts([{
            'user_id': acc.user_id,
            'username': acc.username,
            'full_name': acc.full_name,
            'is_private': acc.is_private
        } for acc in sample_accounts])
        
        for acc in sample_accounts:
            storage.save_account_story_activity(
                user_id=acc.user_id,
                username=acc.username,
                is_muting_stories=False  # All initially unmuted
            )
        
        # Create story manager with fresh mock
        story_manager = StoryPollingManager(
            storage=storage,
            instagram_client=mock_instagram_client,
            story_active_days=3,
            story_inactive_days=14,
            story_dormant_days=90,
            mute_refresh_hours=24
        )
        
        # Mock mute check: user3 (first returned), user2, user1 (last returned)
        # Make user3 (dormant_user) muted
        mock_instagram_client.check_story_mute_status.side_effect = [True, False, False]
        
        # Refresh mute statuses
        newly_muted, newly_unmuted = story_manager.refresh_mute_statuses()
        
        assert newly_muted == 1
        assert newly_unmuted == 0
        
        # Verify user3 (dormant_user) is now muted
        activity = storage.get_account_story_activity('user3')
        assert activity['is_muting_stories'] == 1
    
    def test_get_priority_stats(self, story_manager, storage, sample_accounts):
        """Test getting priority statistics."""
        # Setup accounts with different priorities
        storage.save_following_accounts([{
            'user_id': acc.user_id,
            'username': acc.username,
            'full_name': acc.full_name,
            'is_private': acc.is_private
        } for acc in sample_accounts])
        
        storage.save_account_story_activity(
            user_id='user1',
            username='active_user',
            is_muting_stories=False,
            story_poll_priority='high'
        )
        
        storage.save_account_story_activity(
            user_id='user2',
            username='inactive_user',
            is_muting_stories=True,  # Muted
            story_poll_priority='normal'
        )
        
        storage.save_account_story_activity(
            user_id='user3',
            username='dormant_user',
            is_muting_stories=False,
            story_poll_priority='dormant'
        )
        
        # Get stats
        stats = story_manager.get_priority_stats()
        
        assert stats['total_accounts'] == 3
        assert stats['unmuted_accounts'] == 2
        assert stats['muted_accounts'] == 1
        assert stats['priority_distribution']['high'] == 1
        assert stats['priority_distribution']['normal'] == 1
        assert stats['priority_distribution']['dormant'] == 1
