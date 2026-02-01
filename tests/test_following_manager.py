"""Tests for FollowingManager."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import tempfile
import sqlite3

from src.following_manager import FollowingManager, FollowedAccount
from src.storage import StorageManager
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
    client._is_authenticated = True
    client.client = Mock()
    client.client.user_id = 12345
    return client


@pytest.fixture
def following_manager(storage, mock_instagram_client):
    """Create a FollowingManager for testing."""
    return FollowingManager(
        storage=storage,
        instagram_client=mock_instagram_client,
        cache_hours=24
    )


class TestFollowedAccount:
    """Tests for FollowedAccount dataclass."""
    
    def test_create_followed_account(self):
        """Test creating a FollowedAccount."""
        account = FollowedAccount(
            user_id="123",
            username="testuser",
            full_name="Test User",
            is_private=False
        )
        
        assert account.user_id == "123"
        assert account.username == "testuser"
        assert account.full_name == "Test User"
        assert account.is_private is False
    
    def test_followed_account_defaults(self):
        """Test FollowedAccount with default values."""
        account = FollowedAccount(
            user_id="123",
            username="testuser"
        )
        
        assert account.full_name is None
        assert account.is_private is False


class TestFollowingManager:
    """Tests for FollowingManager."""
    
    def test_initialization(self, following_manager):
        """Test FollowingManager initialization."""
        assert following_manager.cache_hours == 24
        assert following_manager.storage is not None
        assert following_manager.instagram_client is not None
    
    def test_is_cache_fresh_no_cache(self, following_manager):
        """Test cache freshness check when no cache exists."""
        assert following_manager._is_cache_fresh() is False
    
    def test_is_cache_fresh_with_fresh_cache(self, following_manager, storage):
        """Test cache freshness check with fresh cache."""
        # Save some accounts
        accounts = [
            {'user_id': '1', 'username': 'user1', 'full_name': 'User 1', 'is_private': False}
        ]
        storage.save_following_accounts(accounts)
        
        # Cache should be fresh
        assert following_manager._is_cache_fresh() is True
    
    def test_is_cache_fresh_with_stale_cache(self, following_manager, storage, temp_db):
        """Test cache freshness check with stale cache."""
        # Manually insert an old cache entry
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        old_time = datetime.now() - timedelta(hours=25)
        cursor.execute("""
            INSERT INTO following_accounts (user_id, username, full_name, is_private, last_checked)
            VALUES (?, ?, ?, ?, ?)
        """, ('1', 'user1', 'User 1', False, old_time))
        conn.commit()
        conn.close()
        
        # Cache should be stale
        assert following_manager._is_cache_fresh() is False
    
    def test_refresh_following_list_success(self, following_manager, mock_instagram_client, storage):
        """Test successful refresh of following list from API."""
        # Mock the API response
        mock_user1 = Mock()
        mock_user1.pk = 111
        mock_user1.username = "alice"
        mock_user1.full_name = "Alice Smith"
        mock_user1.is_private = False
        
        mock_user2 = Mock()
        mock_user2.pk = 222
        mock_user2.username = "bob"
        mock_user2.full_name = "Bob Jones"
        mock_user2.is_private = True
        
        mock_instagram_client.client.user_following.return_value = {
            111: mock_user1,
            222: mock_user2
        }
        
        # Refresh
        result = following_manager.refresh_following_list()
        
        assert result is True
        
        # Check saved accounts
        accounts = storage.get_following_accounts()
        assert len(accounts) == 2
        
        usernames = {acc['username'] for acc in accounts}
        assert 'alice' in usernames
        assert 'bob' in usernames
    
    def test_refresh_following_list_api_error(self, following_manager, mock_instagram_client):
        """Test refresh handling when API fails."""
        mock_instagram_client.client.user_following.side_effect = Exception("API Error")
        
        result = following_manager.refresh_following_list()
        
        assert result is False
    
    def test_get_following_list_with_fresh_cache(self, following_manager, storage):
        """Test getting following list when cache is fresh."""
        # Pre-populate cache
        accounts = [
            {'user_id': '1', 'username': 'user1', 'full_name': 'User 1', 'is_private': False},
            {'user_id': '2', 'username': 'user2', 'full_name': 'User 2', 'is_private': True}
        ]
        storage.save_following_accounts(accounts)
        
        # Get list (should use cache)
        result = following_manager.get_following_list(refresh=False)
        
        assert len(result) == 2
        assert isinstance(result[0], FollowedAccount)
        assert result[0].username in ['user1', 'user2']
        
        # Should not call API
        following_manager.instagram_client.client.user_following.assert_not_called()
    
    def test_get_following_list_force_refresh(self, following_manager, mock_instagram_client, storage):
        """Test getting following list with forced refresh."""
        # Pre-populate cache
        storage.save_following_accounts([
            {'user_id': '1', 'username': 'old_user', 'full_name': 'Old', 'is_private': False}
        ])
        
        # Mock new API response
        mock_user = Mock()
        mock_user.pk = 999
        mock_user.username = "new_user"
        mock_user.full_name = "New User"
        mock_user.is_private = False
        
        mock_instagram_client.client.user_following.return_value = {999: mock_user}
        
        # Force refresh
        result = following_manager.get_following_list(refresh=True)
        
        assert len(result) == 1
        assert result[0].username == "new_user"
        
        # Should have called API
        mock_instagram_client.client.user_following.assert_called_once()
    
    def test_get_following_list_empty(self, following_manager, mock_instagram_client):
        """Test getting following list when none exist."""
        mock_instagram_client.client.user_following.return_value = {}
        
        result = following_manager.get_following_list(refresh=True)
        
        assert len(result) == 0
    
    def test_get_following_list_refresh_failure_uses_stale_cache(
        self, following_manager, storage, mock_instagram_client
    ):
        """Test that stale cache is used when refresh fails."""
        # Pre-populate cache
        storage.save_following_accounts([
            {'user_id': '1', 'username': 'cached_user', 'full_name': 'Cached', 'is_private': False}
        ])
        
        # Make cache stale (mock the check)
        with patch.object(following_manager, '_is_cache_fresh', return_value=False):
            # Mock API failure
            mock_instagram_client.client.user_following.side_effect = Exception("API Error")
            
            # Should fall back to cache
            result = following_manager.get_following_list()
            
            assert len(result) == 1
            assert result[0].username == "cached_user"
    
    def test_custom_cache_hours(self, storage, mock_instagram_client):
        """Test FollowingManager with custom cache TTL."""
        manager = FollowingManager(
            storage=storage,
            instagram_client=mock_instagram_client,
            cache_hours=12
        )
        
        assert manager.cache_hours == 12
    
    def test_get_following_list_not_authenticated(self, following_manager, mock_instagram_client):
        """Test that manager handles unauthenticated client."""
        mock_instagram_client._is_authenticated = False
        
        # Mock login
        mock_instagram_client.login.return_value = True
        mock_instagram_client.client.user_following.return_value = {}
        
        result = following_manager.refresh_following_list()
        
        # Should have attempted login
        mock_instagram_client.login.assert_called_once()
        assert result is True
