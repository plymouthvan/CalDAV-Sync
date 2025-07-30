"""
Pytest configuration and shared fixtures for CalDAV Sync Microservice tests.

Provides common test fixtures, database setup, and testing utilities.
"""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database import Base, get_db, get_database_manager
from app.main import create_app
from app.caldav.models import CalDAVAccount, CalDAVEvent
from app.google.models import GoogleCalendarEvent
from app.database import CalDAVAccount as DBCalDAVAccount, CalendarMapping, SyncLog


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    yield f"sqlite:///{db_path}"
    
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def test_settings(temp_db):
    """Create test settings with temporary database."""
    return Settings(
        environment="test",
        database={"url": temp_db},
        security={"encryption_key": "test-key-32-characters-long-12345"},
        development={"debug": True, "log_all_requests": False},
        sync={"default_interval_minutes": 5, "default_sync_window_days": 30},
        api={"rate_limit_per_minute": 1000},
        google_calendar={"rate_limit_delay": 0.1},
        caldav={"connection_timeout": 5, "read_timeout": 10},
        webhooks={"timeout_seconds": 5, "max_retries": 2}
    )


@pytest.fixture
def test_db_engine(test_settings):
    """Create test database engine."""
    engine = create_engine(test_settings.database.url, echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def test_db_session(test_db_engine):
    """Create test database session."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def override_get_db(test_db_session):
    """Override the get_db dependency for testing."""
    def _get_test_db():
        yield test_db_session
    return _get_test_db


@pytest.fixture
def override_get_settings(test_settings):
    """Override the get_settings dependency for testing."""
    def _get_test_settings():
        return test_settings
    return _get_test_settings


@pytest.fixture
def test_app(test_settings, override_get_db, override_get_settings):
    """Create test FastAPI application."""
    app = create_app()
    
    # Override dependencies
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    
    yield app
    
    # Clear overrides
    app.dependency_overrides.clear()


@pytest.fixture
def test_client(test_app):
    """Create test client for FastAPI application."""
    return TestClient(test_app)


@pytest.fixture
def sample_caldav_account():
    """Create a sample CalDAV account for testing."""
    return CalDAVAccount(
        name="Test CalDAV",
        username="testuser",
        base_url="https://caldav.example.com",
        verify_ssl=True
    )


@pytest.fixture
def sample_caldav_event():
    """Create a sample CalDAV event for testing."""
    return CalDAVEvent(
        uid="test-event-123",
        summary="Test Event",
        description="Test event description",
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow() + timedelta(hours=1),
        location="Test Location",
        organizer="test@example.com",
        attendees=["attendee1@example.com", "attendee2@example.com"],
        all_day=False,
        timezone="UTC",
        recurrence_rule=None,
        last_modified=datetime.utcnow(),
        created=datetime.utcnow(),
        status="CONFIRMED"
    )


@pytest.fixture
def sample_google_event():
    """Create a sample Google Calendar event for testing."""
    return GoogleCalendarEvent(
        id="google-event-123",
        summary="Test Google Event",
        description="Test Google event description",
        start=datetime.utcnow(),
        end=datetime.utcnow() + timedelta(hours=1),
        location="Test Location",
        organizer="test@example.com",
        attendees=["attendee1@example.com", "attendee2@example.com"],
        all_day=False,
        timezone="UTC",
        recurrence=None,
        updated=datetime.utcnow(),
        created=datetime.utcnow(),
        status="confirmed",
        color_id="1",
        visibility="default"
    )


@pytest.fixture
def db_caldav_account(test_db_session, test_settings):
    """Create a CalDAV account in the test database."""
    account = DBCalDAVAccount(
        name="Test CalDAV Account",
        username="testuser",
        base_url="https://caldav.example.com",
        verify_ssl=True,
        enabled=True
    )
    account.set_password("testpassword", test_settings.security.encryption_key)
    
    test_db_session.add(account)
    test_db_session.commit()
    test_db_session.refresh(account)
    
    yield account
    
    test_db_session.delete(account)
    test_db_session.commit()


@pytest.fixture
def db_calendar_mapping(test_db_session, db_caldav_account):
    """Create a calendar mapping in the test database."""
    mapping = CalendarMapping(
        caldav_account_id=db_caldav_account.id,
        caldav_calendar_id="test-caldav-calendar",
        caldav_calendar_name="Test CalDAV Calendar",
        google_calendar_id="test-google-calendar",
        google_calendar_name="Test Google Calendar",
        sync_direction="caldav_to_google",
        sync_window_days=30,
        sync_interval_minutes=5,
        enabled=True
    )
    
    test_db_session.add(mapping)
    test_db_session.commit()
    test_db_session.refresh(mapping)
    
    yield mapping
    
    test_db_session.delete(mapping)
    test_db_session.commit()


@pytest.fixture
def mock_caldav_client():
    """Create a mock CalDAV client for testing."""
    client = Mock()
    client.test_connection = Mock(return_value=(True, None))
    client.discover_calendars = Mock(return_value=[])
    client.get_events_by_sync_window = Mock(return_value=[])
    client.create_event = Mock()
    client.update_event = Mock()
    client.delete_event = Mock()
    return client


@pytest.fixture
def mock_google_client():
    """Create a mock Google Calendar client for testing."""
    client = Mock()
    client.list_calendars = Mock(return_value=[])
    client.get_calendar_by_id = Mock(return_value=None)
    client.get_events_by_sync_window = Mock(return_value=[])
    client.create_event = Mock()
    client.update_event = Mock()
    client.delete_event = Mock()
    return client


@pytest.fixture
def mock_oauth_manager():
    """Create a mock OAuth manager for testing."""
    manager = Mock()
    manager.get_valid_credentials = Mock(return_value=Mock())
    manager.get_authorization_url = Mock(return_value="https://oauth.example.com")
    manager.exchange_code_for_tokens = Mock()
    manager.test_credentials = Mock(return_value=(True, None))
    manager.get_token_info = Mock(return_value={
        "has_token": True,
        "is_expired": False,
        "expires_at": datetime.utcnow() + timedelta(hours=1),
        "scopes": ["https://www.googleapis.com/auth/calendar"],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    })
    return manager


@pytest.fixture
def mock_sync_scheduler():
    """Create a mock sync scheduler for testing."""
    scheduler = AsyncMock()
    scheduler.start = AsyncMock()
    scheduler.stop = AsyncMock()
    scheduler.schedule_mapping = AsyncMock()
    scheduler.unschedule_mapping = AsyncMock()
    scheduler.trigger_manual_sync = AsyncMock(return_value=True)
    scheduler.get_job_status = Mock(return_value={
        "scheduled": True,
        "next_run": datetime.utcnow() + timedelta(minutes=5),
        "running": False,
        "last_run": None
    })
    scheduler.get_scheduler_stats = Mock(return_value={
        "running": True,
        "total_jobs": 1,
        "active_syncs": 0,
        "next_job_run": datetime.utcnow() + timedelta(minutes=5)
    })
    return scheduler


@pytest.fixture
def mock_webhook_client():
    """Create a mock webhook client for testing."""
    client = AsyncMock()
    client.send_sync_result_webhook = AsyncMock()
    client.test_webhook = AsyncMock(return_value=(True, 200, 0.1, None))
    client.get_retry_stats = Mock(return_value={
        "pending_webhooks": 0,
        "failed_webhooks": 0,
        "total_sent": 10,
        "success_rate": 100.0
    })
    return client


# Test data generators
def create_test_sync_log(mapping_id: str, status: str = "success") -> SyncLog:
    """Create a test sync log entry."""
    return SyncLog(
        mapping_id=mapping_id,
        direction="caldav_to_google",
        status=status,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow() + timedelta(seconds=30),
        duration_seconds=30,
        inserted_count=5,
        updated_count=2,
        deleted_count=1,
        error_count=0
    )


def create_test_events(count: int = 5) -> list:
    """Create a list of test CalDAV events."""
    events = []
    for i in range(count):
        event = CalDAVEvent(
            uid=f"test-event-{i}",
            summary=f"Test Event {i}",
            description=f"Description for test event {i}",
            start_time=datetime.utcnow() + timedelta(days=i),
            end_time=datetime.utcnow() + timedelta(days=i, hours=1),
            location=f"Location {i}",
            organizer="test@example.com",
            attendees=[f"attendee{i}@example.com"],
            all_day=False,
            timezone="UTC",
            last_modified=datetime.utcnow(),
            created=datetime.utcnow(),
            status="CONFIRMED"
        )
        events.append(event)
    return events


# Test utilities
class TestUtils:
    """Utility functions for testing."""
    
    @staticmethod
    def assert_caldav_event_equal(event1: CalDAVEvent, event2: CalDAVEvent):
        """Assert that two CalDAV events are equal."""
        assert event1.uid == event2.uid
        assert event1.summary == event2.summary
        assert event1.description == event2.description
        assert event1.start_time == event2.start_time
        assert event1.end_time == event2.end_time
        assert event1.location == event2.location
        assert event1.all_day == event2.all_day
    
    @staticmethod
    def assert_google_event_equal(event1: GoogleCalendarEvent, event2: GoogleCalendarEvent):
        """Assert that two Google Calendar events are equal."""
        assert event1.id == event2.id
        assert event1.summary == event2.summary
        assert event1.description == event2.description
        assert event1.start == event2.start
        assert event1.end == event2.end
        assert event1.location == event2.location
        assert event1.all_day == event2.all_day


@pytest.fixture
def test_utils():
    """Provide test utilities."""
    return TestUtils
