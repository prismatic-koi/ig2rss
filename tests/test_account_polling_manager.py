"""Tests for AccountPollingManager."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock
from pathlib import Path
import tempfile

from src.account_polling_manager import AccountPollingManager
from src.storage import StorageManager
from src.following_manager import FollowedAccount


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def storage(temp_db):
    """Create a StorageManager with temporary database and FK constraints disabled."""
    import sqlite3
    from contextlib import contextmanager
    
    storage = StorageManager(db_path=temp_db, media_dir=tempfile.mkdtemp())
    
    # Patch _get_connection to disable FK constraints
    original_get_connection = storage._get_connection
    
    @contextmanager
    def patched_get_connection():
        conn = sqlite3.connect(
            storage.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        # Do NOT enable FK constraints for testing
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    storage._get_connection = patched_get_connection
    return storage


@pytest.fixture
def polling_manager(storage):
    """Create an AccountPollingManager for testing."""
    return AccountPollingManager(
        storage=storage,
        priority_high_days=7,
        priority_normal_days=30,
        priority_low_days=180,
        poll_high_every_n=1,
        poll_normal_every_n=1,
        poll_low_every_n=3,
        poll_dormant_every_n=12
    )


class TestAccountPollingManager:
    """Tests for AccountPollingManager."""
    
    def test_initialization(self, polling_manager):
        """Test AccountPollingManager initialization."""
        assert polling_manager.priority_high_days == 7
        assert polling_manager.priority_normal_days == 30
        assert polling_manager.priority_low_days == 180
        assert polling_manager.poll_high_every_n == 1
        assert polling_manager.poll_normal_every_n == 1
        assert polling_manager.poll_low_every_n == 3
        assert polling_manager.poll_dormant_every_n == 12
        assert polling_manager.current_cycle == 0
    
    def test_is_first_sync_true(self, polling_manager):
        """Test first sync detection when not initialized."""
        assert polling_manager.is_first_sync() is True
    
    def test_is_first_sync_false(self, polling_manager, storage):
        """Test first sync detection when already initialized."""
        storage.save_sync_metadata('initialized', 'true')
        assert polling_manager.is_first_sync() is False
    
    def test_mark_initialized(self, polling_manager, storage):
        """Test marking as initialized."""
        polling_manager.mark_initialized()
        
        value = storage.get_sync_metadata('initialized')
        assert value == 'true'
    
    def test_increment_cycle(self, polling_manager, storage):
        """Test cycle increment and persistence."""
        assert polling_manager.current_cycle == 0
        
        polling_manager.increment_cycle()
        assert polling_manager.current_cycle == 1
        
        # Check persisted
        stored_cycle = storage.get_sync_metadata('cycle_number', '0')
        assert stored_cycle == '1'
        
        polling_manager.increment_cycle()
        assert polling_manager.current_cycle == 2
    
    def test_calculate_initial_priority_no_posts(self, polling_manager):
        """Test initial priority calculation for account with no posts."""
        priority = polling_manager._calculate_initial_priority(None)
        assert priority == 'dormant'
    
    def test_calculate_initial_priority_recent(self, polling_manager):
        """Test initial priority for recently active account."""
        recent_date = datetime.now() - timedelta(days=5)
        priority = polling_manager._calculate_initial_priority(recent_date)
        assert priority == 'normal'  # Conservative initial
    
    def test_calculate_initial_priority_medium(self, polling_manager):
        """Test initial priority for moderately active account."""
        medium_date = datetime.now() - timedelta(days=60)
        priority = polling_manager._calculate_initial_priority(medium_date)
        assert priority == 'low'
    
    def test_calculate_initial_priority_old(self, polling_manager):
        """Test initial priority for dormant account."""
        old_date = datetime.now() - timedelta(days=200)
        priority = polling_manager._calculate_initial_priority(old_date)
        assert priority == 'dormant'
    
    def test_initialize_activity_profiles(self, polling_manager, storage):
        """Test initialization of activity profiles."""
        accounts = [
            FollowedAccount(user_id='1', username='active', full_name='Active'),
            FollowedAccount(user_id='2', username='dormant', full_name='Dormant'),
        ]
        
        posts_by_account = {
            'active': [
                {'id': '123', 'posted_at': datetime.now() - timedelta(days=2), 'author_username': 'active'}
            ],
            'dormant': []
        }
        
        distribution = polling_manager.initialize_activity_profiles(accounts, posts_by_account)
        
        # Check distribution
        assert distribution['normal'] == 1  # active (recent, starts as normal)
        assert distribution['dormant'] == 1  # dormant (no posts)
        
        # Check saved activities
        activities = storage.get_all_account_activity()
        assert len(activities) == 2
        
        active_activity = storage.get_account_activity('1')
        assert active_activity['poll_priority'] == 'normal'
        
        dormant_activity = storage.get_account_activity('2')
        assert dormant_activity['poll_priority'] == 'dormant'
    
    def test_initialize_with_priority_overrides(self, storage):
        """Test initialization with priority overrides."""
        manager = AccountPollingManager(
            storage=storage,
            priority_overrides=['forced_high']
        )
        
        accounts = [
            FollowedAccount(user_id='1', username='forced_high'),
            FollowedAccount(user_id='2', username='normal_user'),
        ]
        
        posts_by_account = {
            'forced_high': [],
            'normal_user': []
        }
        
        distribution = manager.initialize_activity_profiles(accounts, posts_by_account)
        
        # forced_high should be high despite no posts
        forced_activity = storage.get_account_activity('1')
        assert forced_activity['poll_priority'] == 'high'
        
        # normal_user should be dormant (no posts)
        normal_activity = storage.get_account_activity('2')
        assert normal_activity['poll_priority'] == 'dormant'
    
    def test_get_accounts_to_poll_high_priority(self, polling_manager, storage):
        """Test getting accounts to poll for high priority."""
        # Create high priority account
        storage.save_account_activity(
            user_id='1',
            username='high_user',
            poll_priority='high',
            last_checked=datetime.now()
        )
        
        # Cycle 1 - high should be polled (every cycle)
        polling_manager.increment_cycle()
        accounts = polling_manager.get_accounts_to_poll_this_cycle()
        
        assert len(accounts) == 1
        assert accounts[0]['username'] == 'high_user'
    
    def test_get_accounts_to_poll_low_priority(self, polling_manager, storage):
        """Test low priority polling frequency."""
        storage.save_account_activity(
            user_id='1',
            username='low_user',
            poll_priority='low',
            last_checked=datetime.now()
        )
        
        # Cycle 1 - low not polled
        polling_manager.increment_cycle()
        accounts = polling_manager.get_accounts_to_poll_this_cycle()
        assert len(accounts) == 0
        
        # Cycle 2 - low not polled
        polling_manager.increment_cycle()
        accounts = polling_manager.get_accounts_to_poll_this_cycle()
        assert len(accounts) == 0
        
        # Cycle 3 - low polled (every 3rd cycle)
        polling_manager.increment_cycle()
        accounts = polling_manager.get_accounts_to_poll_this_cycle()
        assert len(accounts) == 1
        assert accounts[0]['username'] == 'low_user'
    
    def test_get_accounts_to_poll_dormant_priority(self, polling_manager, storage):
        """Test dormant priority polling frequency."""
        storage.save_account_activity(
            user_id='1',
            username='dormant_user',
            poll_priority='dormant',
            last_checked=datetime.now()
        )
        
        # Cycles 1-11: dormant not polled
        for i in range(11):
            polling_manager.increment_cycle()
            accounts = polling_manager.get_accounts_to_poll_this_cycle()
            assert len(accounts) == 0
        
        # Cycle 12: dormant polled
        polling_manager.increment_cycle()
        accounts = polling_manager.get_accounts_to_poll_this_cycle()
        assert len(accounts) == 1
        assert accounts[0]['username'] == 'dormant_user'
    
    def test_get_accounts_with_max_limit(self, polling_manager, storage):
        """Test max accounts limit."""
        # Create 5 high priority accounts
        for i in range(5):
            storage.save_account_activity(
                user_id=str(i),
                username=f'user{i}',
                poll_priority='high',
                last_checked=datetime.now()
            )
        
        polling_manager.increment_cycle()
        
        # Get with limit
        accounts = polling_manager.get_accounts_to_poll_this_cycle(max_accounts=3)
        assert len(accounts) == 3
    
    def test_update_account_priority_new_posts(self, polling_manager, storage):
        """Test priority update when new posts found."""
        # Create account with old data
        old_date = datetime.now() - timedelta(hours=48)
        storage.save_account_activity(
            user_id='1',
            username='test_user',
            poll_priority='normal',
            last_checked=old_date,
            consecutive_no_new_posts=5
        )
        
        # Update with new posts
        metadata = {
            'media_count': 10,
            'latest_post_id': 'new_post_123',
            'latest_post_date': datetime.now() - timedelta(days=2)
        }
        
        polling_manager.update_account_priority(
            user_id='1',
            username='test_user',
            has_new_posts=True,
            metadata=metadata
        )
        
        # Check updated activity
        activity = storage.get_account_activity('1')
        assert activity['last_post_id'] == 'new_post_123'
        assert activity['consecutive_no_new_posts'] == 0
        assert activity['media_count'] == 10
    
    def test_update_account_priority_no_new_posts(self, polling_manager, storage):
        """Test priority update when no new posts found."""
        storage.save_account_activity(
            user_id='1',
            username='test_user',
            poll_priority='normal',
            last_checked=datetime.now(),
            consecutive_no_new_posts=2
        )
        
        polling_manager.update_account_priority(
            user_id='1',
            username='test_user',
            has_new_posts=False,
            metadata={'media_count': 5}
        )
        
        activity = storage.get_account_activity('1')
        assert activity['consecutive_no_new_posts'] == 3
    
    def test_refine_priority_active_account(self, polling_manager, storage):
        """Test priority refinement for active account after 24h."""
        # Create account 25 hours ago with normal priority
        old_date = datetime.now() - timedelta(hours=25)
        storage.save_account_activity(
            user_id='1',
            username='active_user',
            poll_priority='normal',
            last_checked=old_date,
            last_post_date=datetime.now() - timedelta(days=3)
        )
        
        # Manually set created_at in past to simulate 25h observation period
        with storage._get_connection() as conn:
            conn.execute(
                "UPDATE account_activity SET created_at = ? WHERE user_id = ?",
                (old_date, '1')
            )
        
        # Update with new post (3 days old = within 7 day high threshold)
        metadata = {
            'media_count': 10,
            'latest_post_id': 'new_123',
            'latest_post_date': datetime.now() - timedelta(days=3)
        }
        
        polling_manager.update_account_priority(
            user_id='1',
            username='active_user',
            has_new_posts=True,
            metadata=metadata
        )
        
        # After 24h observation, priority should be refined to high (post is 3 days old)
        activity = storage.get_account_activity('1')
        assert activity['poll_priority'] == 'high'
    
    def test_get_priority_stats(self, polling_manager, storage):
        """Test getting priority statistics."""
        # Create accounts with different priorities
        storage.save_account_activity('1', 'user1', poll_priority='high', last_checked=datetime.now())
        storage.save_account_activity('2', 'user2', poll_priority='high', last_checked=datetime.now())
        storage.save_account_activity('3', 'user3', poll_priority='normal', last_checked=datetime.now())
        storage.save_account_activity('4', 'user4', poll_priority='low', last_checked=datetime.now())
        storage.save_account_activity('5', 'user5', poll_priority='dormant', last_checked=datetime.now())
        
        stats = polling_manager.get_priority_stats()
        
        assert stats['total_accounts'] == 5
        assert stats['distribution']['high'] == 2
        assert stats['distribution']['normal'] == 1
        assert stats['distribution']['low'] == 1
        assert stats['distribution']['dormant'] == 1
        assert stats['priority_overrides'] == 0
    
    def test_priority_overrides_always_polled(self, storage):
        """Test that priority overrides are always polled."""
        manager = AccountPollingManager(
            storage=storage,
            poll_high_every_n=1,
            poll_dormant_every_n=12,
            priority_overrides=['override_user']
        )
        
        # Create override account with dormant priority
        storage.save_account_activity(
            user_id='1',
            username='override_user',
            poll_priority='dormant',  # Would normally skip many cycles
            last_checked=datetime.now()
        )
        
        # Cycle 1 - should be polled despite dormant
        manager.increment_cycle()
        accounts = manager.get_accounts_to_poll_this_cycle()
        
        assert len(accounts) == 1
        assert accounts[0]['username'] == 'override_user'
