"""
Tests for database models and functionality.

Tests SQLAlchemy models, relationships, encryption, and database operations.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError

from app.database import (
    CalDAVAccount, CalendarMapping, EventMapping, SyncLog, GoogleOAuthToken,
    get_database_manager, DatabaseManager
)


class TestCalDAVAccount:
    """Test CalDAV account model."""
    
    def test_create_caldav_account(self, test_db_session, test_settings):
        """Test creating a CalDAV account."""
        account = CalDAVAccount(
            name="Test Account",
            username="testuser",
            base_url="https://caldav.example.com",
            verify_ssl=True,
            enabled=True
        )
        
        test_db_session.add(account)
        test_db_session.commit()
        test_db_session.refresh(account)
        
        assert account.id is not None
        assert account.name == "Test Account"
        assert account.username == "testuser"
        assert account.base_url == "https://caldav.example.com"
        assert account.verify_ssl is True
        assert account.enabled is True
        assert account.created_at is not None
        assert account.updated_at is not None
    
    def test_password_encryption(self, test_db_session, test_settings):
        """Test password encryption and decryption."""
        account = CalDAVAccount(
            name="Test Account",
            username="testuser",
            base_url="https://caldav.example.com"
        )
        
        # Set password
        password = "test-password-123"
        account.set_password(password, test_settings.security.encryption_key)
        
        test_db_session.add(account)
        test_db_session.commit()
        test_db_session.refresh(account)
        
        # Verify password is encrypted
        assert account.encrypted_password is not None
        assert account.encrypted_password != password
        
        # Verify password can be decrypted
        decrypted = account.get_password(test_settings.security.encryption_key)
        assert decrypted == password
    
    def test_unique_name_constraint(self, test_db_session):
        """Test that account names must be unique."""
        account1 = CalDAVAccount(
            name="Duplicate Name",
            username="user1",
            base_url="https://caldav1.example.com"
        )
        
        account2 = CalDAVAccount(
            name="Duplicate Name",
            username="user2",
            base_url="https://caldav2.example.com"
        )
        
        test_db_session.add(account1)
        test_db_session.commit()
        
        test_db_session.add(account2)
        
        with pytest.raises(IntegrityError):
            test_db_session.commit()
    
    def test_account_relationships(self, test_db_session, db_caldav_account):
        """Test CalDAV account relationships."""
        # Create a calendar mapping
        mapping = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="test-calendar",
            caldav_calendar_name="Test Calendar",
            google_calendar_id="google-calendar",
            google_calendar_name="Google Calendar",
            sync_direction="caldav_to_google"
        )
        
        test_db_session.add(mapping)
        test_db_session.commit()
        
        # Test relationship
        assert len(db_caldav_account.mappings) == 1
        assert db_caldav_account.mappings[0].caldav_calendar_name == "Test Calendar"


class TestCalendarMapping:
    """Test calendar mapping model."""
    
    def test_create_calendar_mapping(self, test_db_session, db_caldav_account):
        """Test creating a calendar mapping."""
        mapping = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="caldav-cal-123",
            caldav_calendar_name="My CalDAV Calendar",
            google_calendar_id="google-cal-456",
            google_calendar_name="My Google Calendar",
            sync_direction="bidirectional",
            sync_window_days=45,
            sync_interval_minutes=10,
            webhook_url="https://webhook.example.com/sync",
            enabled=True
        )
        
        test_db_session.add(mapping)
        test_db_session.commit()
        test_db_session.refresh(mapping)
        
        assert mapping.id is not None
        assert mapping.caldav_account_id == db_caldav_account.id
        assert mapping.caldav_calendar_id == "caldav-cal-123"
        assert mapping.caldav_calendar_name == "My CalDAV Calendar"
        assert mapping.google_calendar_id == "google-cal-456"
        assert mapping.google_calendar_name == "My Google Calendar"
        assert mapping.sync_direction == "bidirectional"
        assert mapping.sync_window_days == 45
        assert mapping.sync_interval_minutes == 10
        assert mapping.webhook_url == "https://webhook.example.com/sync"
        assert mapping.enabled is True
        assert mapping.created_at is not None
        assert mapping.updated_at is not None
    
    def test_mapping_defaults(self, test_db_session, db_caldav_account):
        """Test default values for calendar mapping."""
        mapping = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="caldav-cal-123",
            caldav_calendar_name="My CalDAV Calendar",
            google_calendar_id="google-cal-456",
            google_calendar_name="My Google Calendar"
        )
        
        test_db_session.add(mapping)
        test_db_session.commit()
        test_db_session.refresh(mapping)
        
        assert mapping.sync_direction == "caldav_to_google"  # Default
        assert mapping.sync_window_days == 30  # Default
        assert mapping.sync_interval_minutes == 5  # Default
        assert mapping.enabled is True  # Default
        assert mapping.webhook_url is None  # Default
    
    def test_unique_mapping_constraint(self, test_db_session, db_caldav_account):
        """Test that calendar mappings must be unique per account/calendar combination."""
        mapping1 = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="same-calendar",
            caldav_calendar_name="Calendar 1",
            google_calendar_id="google-cal-1",
            google_calendar_name="Google Calendar 1"
        )
        
        mapping2 = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="same-calendar",  # Same calendar
            caldav_calendar_name="Calendar 2",
            google_calendar_id="google-cal-2",
            google_calendar_name="Google Calendar 2"
        )
        
        test_db_session.add(mapping1)
        test_db_session.commit()
        
        test_db_session.add(mapping2)
        
        with pytest.raises(IntegrityError):
            test_db_session.commit()


class TestEventMapping:
    """Test event mapping model."""
    
    def test_create_event_mapping(self, test_db_session, db_calendar_mapping):
        """Test creating an event mapping."""
        event_mapping = EventMapping(
            mapping_id=db_calendar_mapping.id,
            caldav_uid="caldav-event-123",
            google_event_id="google-event-456",
            last_caldav_modified=datetime.utcnow(),
            last_google_updated=datetime.utcnow(),
            sync_direction_last="caldav_to_google",
            event_hash="abc123def456"
        )
        
        test_db_session.add(event_mapping)
        test_db_session.commit()
        test_db_session.refresh(event_mapping)
        
        assert event_mapping.id is not None
        assert event_mapping.mapping_id == db_calendar_mapping.id
        assert event_mapping.caldav_uid == "caldav-event-123"
        assert event_mapping.google_event_id == "google-event-456"
        assert event_mapping.sync_direction_last == "caldav_to_google"
        assert event_mapping.event_hash == "abc123def456"
        assert event_mapping.created_at is not None
        assert event_mapping.updated_at is not None
    
    def test_event_mapping_relationships(self, test_db_session, db_calendar_mapping):
        """Test event mapping relationships."""
        event_mapping = EventMapping(
            mapping_id=db_calendar_mapping.id,
            caldav_uid="caldav-event-123",
            google_event_id="google-event-456"
        )
        
        test_db_session.add(event_mapping)
        test_db_session.commit()
        
        # Test relationship
        assert event_mapping.calendar_mapping == db_calendar_mapping
        assert len(db_calendar_mapping.event_mappings) == 1
        assert db_calendar_mapping.event_mappings[0].caldav_uid == "caldav-event-123"


class TestSyncLog:
    """Test sync log model."""
    
    def test_create_sync_log(self, test_db_session, db_calendar_mapping):
        """Test creating a sync log entry."""
        sync_log = SyncLog(
            mapping_id=db_calendar_mapping.id,
            direction="bidirectional",
            status="success",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow() + timedelta(seconds=45),
            duration_seconds=45,
            inserted_count=10,
            updated_count=5,
            deleted_count=2,
            error_count=0,
            error_message=None,
            webhook_sent=True,
            webhook_status=200
        )
        
        test_db_session.add(sync_log)
        test_db_session.commit()
        test_db_session.refresh(sync_log)
        
        assert sync_log.id is not None
        assert sync_log.mapping_id == db_calendar_mapping.id
        assert sync_log.direction == "bidirectional"
        assert sync_log.status == "success"
        assert sync_log.duration_seconds == 45
        assert sync_log.inserted_count == 10
        assert sync_log.updated_count == 5
        assert sync_log.deleted_count == 2
        assert sync_log.error_count == 0
        assert sync_log.webhook_sent is True
        assert sync_log.webhook_status == 200
    
    def test_sync_log_with_errors(self, test_db_session, db_calendar_mapping):
        """Test sync log with error information."""
        sync_log = SyncLog(
            mapping_id=db_calendar_mapping.id,
            direction="caldav_to_google",
            status="partial_failure",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow() + timedelta(seconds=30),
            duration_seconds=30,
            inserted_count=5,
            updated_count=3,
            deleted_count=1,
            error_count=2,
            error_message="Connection timeout; Invalid event format",
            webhook_sent=False,
            webhook_status=None
        )
        
        test_db_session.add(sync_log)
        test_db_session.commit()
        test_db_session.refresh(sync_log)
        
        assert sync_log.status == "partial_failure"
        assert sync_log.error_count == 2
        assert sync_log.error_message == "Connection timeout; Invalid event format"
        assert sync_log.webhook_sent is False
        assert sync_log.webhook_status is None


class TestGoogleOAuthToken:
    """Test Google OAuth token model."""
    
    def test_create_oauth_token(self, test_db_session, test_settings):
        """Test creating an OAuth token."""
        token = GoogleOAuthToken(
            access_token="access-token-123",
            refresh_token="refresh-token-456",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            scopes="https://www.googleapis.com/auth/calendar"
        )
        
        test_db_session.add(token)
        test_db_session.commit()
        test_db_session.refresh(token)
        
        assert token.id is not None
        assert token.access_token == "access-token-123"
        assert token.refresh_token == "refresh-token-456"
        assert token.scopes == "https://www.googleapis.com/auth/calendar"
        assert token.created_at is not None
        assert token.updated_at is not None
    
    def test_token_encryption(self, test_db_session, test_settings):
        """Test OAuth token encryption."""
        token = GoogleOAuthToken()
        
        # Set tokens
        access_token = "access-token-secret"
        refresh_token = "refresh-token-secret"
        
        token.set_access_token(access_token, test_settings.security.encryption_key)
        token.set_refresh_token(refresh_token, test_settings.security.encryption_key)
        
        test_db_session.add(token)
        test_db_session.commit()
        test_db_session.refresh(token)
        
        # Verify tokens are encrypted
        assert token.encrypted_access_token is not None
        assert token.encrypted_access_token != access_token
        assert token.encrypted_refresh_token is not None
        assert token.encrypted_refresh_token != refresh_token
        
        # Verify tokens can be decrypted
        decrypted_access = token.get_access_token(test_settings.security.encryption_key)
        decrypted_refresh = token.get_refresh_token(test_settings.security.encryption_key)
        
        assert decrypted_access == access_token
        assert decrypted_refresh == refresh_token
    
    def test_token_expiry_check(self, test_db_session):
        """Test token expiry checking."""
        # Expired token
        expired_token = GoogleOAuthToken(
            access_token="expired-token",
            expires_at=datetime.utcnow() - timedelta(hours=1)
        )
        
        # Valid token
        valid_token = GoogleOAuthToken(
            access_token="valid-token",
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        
        assert expired_token.is_expired() is True
        assert valid_token.is_expired() is False


class TestDatabaseManager:
    """Test database manager functionality."""
    
    def test_database_manager_creation(self, test_settings):
        """Test database manager creation."""
        manager = DatabaseManager(test_settings)
        
        assert manager.settings == test_settings
        assert manager.engine is not None
        assert manager.SessionLocal is not None
    
    def test_create_tables(self, test_settings):
        """Test table creation."""
        manager = DatabaseManager(test_settings)
        
        # Should not raise exception
        manager.create_tables()
        
        # Verify tables exist by checking engine
        from sqlalchemy import inspect
        inspector = inspect(manager.engine)
        table_names = inspector.get_table_names()
        
        expected_tables = [
            'caldav_accounts',
            'calendar_mappings',
            'event_mappings',
            'sync_logs',
            'google_oauth_tokens'
        ]
        
        for table in expected_tables:
            assert table in table_names
    
    def test_get_database_manager_singleton(self, test_settings):
        """Test that get_database_manager returns singleton."""
        manager1 = get_database_manager()
        manager2 = get_database_manager()
        
        assert manager1 is manager2


class TestDatabaseIndexes:
    """Test database indexes and performance optimizations."""
    
    def test_caldav_account_indexes(self, test_db_engine):
        """Test CalDAV account indexes."""
        from sqlalchemy import inspect
        inspector = inspect(test_db_engine)
        indexes = inspector.get_indexes('caldav_accounts')
        
        # Should have index on name (unique constraint)
        index_columns = [idx['column_names'] for idx in indexes]
        assert ['name'] in index_columns
    
    def test_calendar_mapping_indexes(self, test_db_engine):
        """Test calendar mapping indexes."""
        from sqlalchemy import inspect
        inspector = inspect(test_db_engine)
        indexes = inspector.get_indexes('calendar_mappings')
        
        # Should have indexes for foreign keys and unique constraints
        index_columns = [idx['column_names'] for idx in indexes]
        
        # Check for caldav_account_id index
        caldav_account_indexes = [idx for idx in indexes if 'caldav_account_id' in idx['column_names']]
        assert len(caldav_account_indexes) > 0
    
    def test_event_mapping_indexes(self, test_db_engine):
        """Test event mapping indexes."""
        from sqlalchemy import inspect
        inspector = inspect(test_db_engine)
        indexes = inspector.get_indexes('event_mappings')
        
        # Should have indexes for lookups
        index_columns = [idx['column_names'] for idx in indexes]
        
        # Check for mapping_id index
        mapping_indexes = [idx for idx in indexes if 'mapping_id' in idx['column_names']]
        assert len(mapping_indexes) > 0
    
    def test_sync_log_indexes(self, test_db_engine):
        """Test sync log indexes."""
        from sqlalchemy import inspect
        inspector = inspect(test_db_engine)
        indexes = inspector.get_indexes('sync_logs')
        
        # Should have indexes for queries
        index_columns = [idx['column_names'] for idx in indexes]
        
        # Check for mapping_id index
        mapping_indexes = [idx for idx in indexes if 'mapping_id' in idx['column_names']]
        assert len(mapping_indexes) > 0


class TestDatabaseConstraints:
    """Test database constraints and data integrity."""
    
    def test_foreign_key_constraints(self, test_db_session, db_caldav_account):
        """Test foreign key constraints."""
        # Create mapping with valid foreign key
        mapping = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="test-calendar",
            caldav_calendar_name="Test Calendar",
            google_calendar_id="google-calendar",
            google_calendar_name="Google Calendar"
        )
        
        test_db_session.add(mapping)
        test_db_session.commit()  # Should succeed
        
        # Try to create mapping with invalid foreign key
        invalid_mapping = CalendarMapping(
            caldav_account_id="invalid-account-id",
            caldav_calendar_id="test-calendar-2",
            caldav_calendar_name="Test Calendar 2",
            google_calendar_id="google-calendar-2",
            google_calendar_name="Google Calendar 2"
        )
        
        test_db_session.add(invalid_mapping)
        
        with pytest.raises(IntegrityError):
            test_db_session.commit()
    
    def test_cascade_deletes(self, test_db_session, db_caldav_account):
        """Test cascade delete behavior."""
        # Create mapping and event mapping
        mapping = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="test-calendar",
            caldav_calendar_name="Test Calendar",
            google_calendar_id="google-calendar",
            google_calendar_name="Google Calendar"
        )
        
        test_db_session.add(mapping)
        test_db_session.commit()
        test_db_session.refresh(mapping)
        
        event_mapping = EventMapping(
            mapping_id=mapping.id,
            caldav_uid="test-event",
            google_event_id="google-event"
        )
        
        test_db_session.add(event_mapping)
        test_db_session.commit()
        
        # Delete the calendar mapping
        test_db_session.delete(mapping)
        test_db_session.commit()
        
        # Event mapping should be deleted too (cascade)
        remaining_event_mappings = test_db_session.query(EventMapping).filter(
            EventMapping.mapping_id == mapping.id
        ).all()
        
        assert len(remaining_event_mappings) == 0
