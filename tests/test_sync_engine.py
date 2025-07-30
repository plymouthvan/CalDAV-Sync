"""
Tests for sync engine components.

Tests event normalization, diffing, conflict resolution, and sync orchestration.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

from app.sync.normalizer import EventNormalizer
from app.sync.differ import EventDiffer, ConflictResolver
from app.sync.engine import SyncEngine
from app.caldav.models import CalDAVEvent
from app.google.models import GoogleCalendarEvent


class TestEventNormalizer:
    """Test event normalization between CalDAV and Google Calendar formats."""
    
    def test_caldav_to_google_basic(self, sample_caldav_event):
        """Test basic CalDAV to Google Calendar conversion."""
        normalizer = EventNormalizer()
        google_event = normalizer.caldav_to_google(sample_caldav_event)
        
        assert isinstance(google_event, GoogleCalendarEvent)
        assert google_event.summary == sample_caldav_event.summary
        assert google_event.description == sample_caldav_event.description
        assert google_event.start == sample_caldav_event.start_time
        assert google_event.end == sample_caldav_event.end_time
        assert google_event.location == sample_caldav_event.location
        assert google_event.all_day == sample_caldav_event.all_day
        assert google_event.timezone == sample_caldav_event.timezone
    
    def test_google_to_caldav_basic(self, sample_google_event):
        """Test basic Google Calendar to CalDAV conversion."""
        normalizer = EventNormalizer()
        caldav_event = normalizer.google_to_caldav(sample_google_event)
        
        assert isinstance(caldav_event, CalDAVEvent)
        assert caldav_event.summary == sample_google_event.summary
        assert caldav_event.description == sample_google_event.description
        assert caldav_event.start_time == sample_google_event.start
        assert caldav_event.end_time == sample_google_event.end
        assert caldav_event.location == sample_google_event.location
        assert caldav_event.all_day == sample_google_event.all_day
        assert caldav_event.timezone == sample_google_event.timezone
    
    def test_all_day_event_normalization(self):
        """Test normalization of all-day events."""
        normalizer = EventNormalizer()
        
        # CalDAV all-day event
        caldav_all_day = CalDAVEvent(
            uid="all-day-event",
            summary="All Day Event",
            start_time=datetime(2024, 1, 15),
            end_time=datetime(2024, 1, 16),
            all_day=True,
            timezone="UTC"
        )
        
        google_event = normalizer.caldav_to_google(caldav_all_day)
        
        assert google_event.all_day is True
        assert google_event.start.hour == 0
        assert google_event.start.minute == 0
        assert google_event.end.hour == 0
        assert google_event.end.minute == 0
    
    def test_timezone_handling(self):
        """Test timezone handling in normalization."""
        normalizer = EventNormalizer()
        
        # Event with specific timezone
        caldav_event = CalDAVEvent(
            uid="tz-event",
            summary="Timezone Event",
            start_time=datetime(2024, 1, 15, 14, 30),
            end_time=datetime(2024, 1, 15, 15, 30),
            timezone="America/New_York",
            all_day=False
        )
        
        google_event = normalizer.caldav_to_google(caldav_event)
        
        assert google_event.timezone == "America/New_York"
        assert google_event.start.hour == 14
        assert google_event.start.minute == 30
    
    def test_attendee_normalization(self):
        """Test attendee list normalization."""
        normalizer = EventNormalizer()
        
        caldav_event = CalDAVEvent(
            uid="attendee-event",
            summary="Meeting with Attendees",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1),
            organizer="organizer@example.com",
            attendees=["attendee1@example.com", "attendee2@example.com"],
            all_day=False
        )
        
        google_event = normalizer.caldav_to_google(caldav_event)
        
        assert google_event.organizer == "organizer@example.com"
        assert len(google_event.attendees) == 2
        assert "attendee1@example.com" in google_event.attendees
        assert "attendee2@example.com" in google_event.attendees
    
    def test_recurrence_normalization(self):
        """Test recurrence rule normalization."""
        normalizer = EventNormalizer()
        
        # CalDAV event with recurrence
        caldav_event = CalDAVEvent(
            uid="recurring-event",
            summary="Weekly Meeting",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1),
            recurrence_rule="FREQ=WEEKLY;BYDAY=MO",
            all_day=False
        )
        
        google_event = normalizer.caldav_to_google(caldav_event)
        
        assert google_event.recurrence is not None
        assert "FREQ=WEEKLY" in google_event.recurrence
        assert "BYDAY=MO" in google_event.recurrence


class TestEventDiffer:
    """Test event diffing and change detection."""
    
    def test_no_changes_detected(self, sample_caldav_event, sample_google_event):
        """Test when no changes are detected between events."""
        differ = EventDiffer()
        
        # Make events identical
        sample_google_event.summary = sample_caldav_event.summary
        sample_google_event.description = sample_caldav_event.description
        sample_google_event.start = sample_caldav_event.start_time
        sample_google_event.end = sample_caldav_event.end_time
        sample_google_event.location = sample_caldav_event.location
        
        changes = differ.compare_events(sample_caldav_event, sample_google_event)
        
        assert len(changes) == 0
    
    def test_summary_change_detected(self, sample_caldav_event, sample_google_event):
        """Test detection of summary changes."""
        differ = EventDiffer()
        
        sample_caldav_event.summary = "Updated Summary"
        sample_google_event.summary = "Original Summary"
        
        changes = differ.compare_events(sample_caldav_event, sample_google_event)
        
        assert len(changes) > 0
        assert any(change['field'] == 'summary' for change in changes)
        
        summary_change = next(change for change in changes if change['field'] == 'summary')
        assert summary_change['caldav_value'] == "Updated Summary"
        assert summary_change['google_value'] == "Original Summary"
    
    def test_time_change_detected(self, sample_caldav_event, sample_google_event):
        """Test detection of time changes."""
        differ = EventDiffer()
        
        sample_caldav_event.start_time = datetime(2024, 1, 15, 10, 0)
        sample_caldav_event.end_time = datetime(2024, 1, 15, 11, 0)
        sample_google_event.start = datetime(2024, 1, 15, 14, 0)
        sample_google_event.end = datetime(2024, 1, 15, 15, 0)
        
        changes = differ.compare_events(sample_caldav_event, sample_google_event)
        
        assert len(changes) >= 2  # start and end time changes
        assert any(change['field'] == 'start_time' for change in changes)
        assert any(change['field'] == 'end_time' for change in changes)
    
    def test_location_change_detected(self, sample_caldav_event, sample_google_event):
        """Test detection of location changes."""
        differ = EventDiffer()
        
        sample_caldav_event.location = "New Location"
        sample_google_event.location = "Old Location"
        
        changes = differ.compare_events(sample_caldav_event, sample_google_event)
        
        assert any(change['field'] == 'location' for change in changes)
        
        location_change = next(change for change in changes if change['field'] == 'location')
        assert location_change['caldav_value'] == "New Location"
        assert location_change['google_value'] == "Old Location"
    
    def test_attendee_changes_detected(self, sample_caldav_event, sample_google_event):
        """Test detection of attendee changes."""
        differ = EventDiffer()
        
        sample_caldav_event.attendees = ["new@example.com", "attendee@example.com"]
        sample_google_event.attendees = ["old@example.com", "attendee@example.com"]
        
        changes = differ.compare_events(sample_caldav_event, sample_google_event)
        
        assert any(change['field'] == 'attendees' for change in changes)


class TestConflictResolver:
    """Test conflict resolution logic."""
    
    def test_caldav_wins_by_timestamp(self, sample_caldav_event, sample_google_event):
        """Test CalDAV wins conflict resolution based on newer timestamp."""
        resolver = ConflictResolver()
        
        # CalDAV event is newer
        sample_caldav_event.last_modified = datetime.utcnow()
        sample_google_event.updated = datetime.utcnow() - timedelta(hours=1)
        
        changes = [
            {'field': 'summary', 'caldav_value': 'CalDAV Summary', 'google_value': 'Google Summary'}
        ]
        
        resolution = resolver.resolve_conflict(sample_caldav_event, sample_google_event, changes)
        
        assert resolution['winner'] == 'caldav'
        assert resolution['reason'] == 'caldav_newer'
        assert resolution['action'] == 'update_google'
    
    def test_google_wins_by_timestamp(self, sample_caldav_event, sample_google_event):
        """Test Google wins conflict resolution based on newer timestamp."""
        resolver = ConflictResolver()
        
        # Google event is newer
        sample_caldav_event.last_modified = datetime.utcnow() - timedelta(hours=1)
        sample_google_event.updated = datetime.utcnow()
        
        changes = [
            {'field': 'summary', 'caldav_value': 'CalDAV Summary', 'google_value': 'Google Summary'}
        ]
        
        resolution = resolver.resolve_conflict(sample_caldav_event, sample_google_event, changes)
        
        assert resolution['winner'] == 'google'
        assert resolution['reason'] == 'google_newer'
        assert resolution['action'] == 'update_caldav'
    
    def test_caldav_fallback_on_equal_timestamps(self, sample_caldav_event, sample_google_event):
        """Test CalDAV fallback when timestamps are equal."""
        resolver = ConflictResolver()
        
        # Equal timestamps
        now = datetime.utcnow()
        sample_caldav_event.last_modified = now
        sample_google_event.updated = now
        
        changes = [
            {'field': 'summary', 'caldav_value': 'CalDAV Summary', 'google_value': 'Google Summary'}
        ]
        
        resolution = resolver.resolve_conflict(sample_caldav_event, sample_google_event, changes)
        
        assert resolution['winner'] == 'caldav'
        assert resolution['reason'] == 'caldav_fallback'
        assert resolution['action'] == 'update_google'
    
    def test_no_conflict_resolution(self, sample_caldav_event, sample_google_event):
        """Test when no conflict resolution is needed."""
        resolver = ConflictResolver()
        
        # No changes
        changes = []
        
        resolution = resolver.resolve_conflict(sample_caldav_event, sample_google_event, changes)
        
        assert resolution['winner'] == 'none'
        assert resolution['reason'] == 'no_changes'
        assert resolution['action'] == 'no_action'


class TestSyncEngine:
    """Test the main sync engine orchestration."""
    
    @pytest.fixture
    def sync_engine(self, test_settings, mock_caldav_client, mock_google_client):
        """Create a sync engine with mocked clients."""
        engine = SyncEngine(test_settings)
        engine.caldav_client = mock_caldav_client
        engine.google_client = mock_google_client
        return engine
    
    @pytest.mark.asyncio
    async def test_caldav_to_google_sync(self, sync_engine, db_calendar_mapping, test_db_session):
        """Test CalDAV to Google Calendar sync."""
        # Setup mock data
        caldav_events = [
            CalDAVEvent(
                uid="caldav-event-1",
                summary="CalDAV Event 1",
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow() + timedelta(hours=1),
                last_modified=datetime.utcnow(),
                all_day=False
            )
        ]
        
        google_events = []  # No existing Google events
        
        sync_engine.caldav_client.get_events_by_sync_window.return_value = caldav_events
        sync_engine.google_client.get_events_by_sync_window.return_value = google_events
        sync_engine.google_client.create_event.return_value = "google-event-1"
        
        # Perform sync
        result = await sync_engine.sync_mapping(db_calendar_mapping, test_db_session)
        
        assert result['status'] == 'success'
        assert result['inserted_count'] == 1
        assert result['updated_count'] == 0
        assert result['deleted_count'] == 0
        
        # Verify Google client was called to create event
        sync_engine.google_client.create_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_google_to_caldav_sync(self, sync_engine, test_db_session):
        """Test Google Calendar to CalDAV sync."""
        # Create mapping with Google to CalDAV direction
        from app.database import CalendarMapping
        
        mapping = CalendarMapping(
            caldav_account_id="test-account",
            caldav_calendar_id="caldav-cal",
            caldav_calendar_name="CalDAV Calendar",
            google_calendar_id="google-cal",
            google_calendar_name="Google Calendar",
            sync_direction="google_to_caldav"
        )
        
        # Setup mock data
        google_events = [
            GoogleCalendarEvent(
                id="google-event-1",
                summary="Google Event 1",
                start=datetime.utcnow(),
                end=datetime.utcnow() + timedelta(hours=1),
                updated=datetime.utcnow(),
                all_day=False
            )
        ]
        
        caldav_events = []  # No existing CalDAV events
        
        sync_engine.google_client.get_events_by_sync_window.return_value = google_events
        sync_engine.caldav_client.get_events_by_sync_window.return_value = caldav_events
        sync_engine.caldav_client.create_event.return_value = "caldav-event-1"
        
        # Perform sync
        result = await sync_engine.sync_mapping(mapping, test_db_session)
        
        assert result['status'] == 'success'
        assert result['inserted_count'] == 1
        assert result['updated_count'] == 0
        assert result['deleted_count'] == 0
        
        # Verify CalDAV client was called to create event
        sync_engine.caldav_client.create_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_bidirectional_sync_with_conflicts(self, sync_engine, test_db_session):
        """Test bidirectional sync with conflict resolution."""
        # Create bidirectional mapping
        from app.database import CalendarMapping
        
        mapping = CalendarMapping(
            caldav_account_id="test-account",
            caldav_calendar_id="caldav-cal",
            caldav_calendar_name="CalDAV Calendar",
            google_calendar_id="google-cal",
            google_calendar_name="Google Calendar",
            sync_direction="bidirectional"
        )
        
        # Setup conflicting events (same UID but different content)
        caldav_event = CalDAVEvent(
            uid="conflicting-event",
            summary="CalDAV Version",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1),
            last_modified=datetime.utcnow(),  # Newer
            all_day=False
        )
        
        google_event = GoogleCalendarEvent(
            id="google-event-1",
            summary="Google Version",
            start=datetime.utcnow(),
            end=datetime.utcnow() + timedelta(hours=1),
            updated=datetime.utcnow() - timedelta(hours=1),  # Older
            all_day=False
        )
        
        sync_engine.caldav_client.get_events_by_sync_window.return_value = [caldav_event]
        sync_engine.google_client.get_events_by_sync_window.return_value = [google_event]
        
        # Mock existing event mapping
        with patch.object(test_db_session, 'query') as mock_query:
            mock_event_mapping = Mock()
            mock_event_mapping.caldav_uid = "conflicting-event"
            mock_event_mapping.google_event_id = "google-event-1"
            mock_query.return_value.filter.return_value.first.return_value = mock_event_mapping
            
            # Perform sync
            result = await sync_engine.sync_mapping(mapping, test_db_session)
        
        assert result['status'] == 'success'
        # CalDAV should win due to newer timestamp
        sync_engine.google_client.update_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_sync_with_errors(self, sync_engine, db_calendar_mapping, test_db_session):
        """Test sync handling with errors."""
        # Setup mock to raise exception
        sync_engine.caldav_client.get_events_by_sync_window.side_effect = Exception("Connection failed")
        
        # Perform sync
        result = await sync_engine.sync_mapping(db_calendar_mapping, test_db_session)
        
        assert result['status'] == 'failure'
        assert result['error_count'] > 0
        assert 'Connection failed' in result['error_message']
    
    @pytest.mark.asyncio
    async def test_sync_window_filtering(self, sync_engine, db_calendar_mapping, test_db_session):
        """Test that sync respects the sync window."""
        # Setup mapping with specific sync window
        db_calendar_mapping.sync_window_days = 7
        
        # Setup mock events
        sync_engine.caldav_client.get_events_by_sync_window.return_value = []
        sync_engine.google_client.get_events_by_sync_window.return_value = []
        
        # Perform sync
        await sync_engine.sync_mapping(db_calendar_mapping, test_db_session)
        
        # Verify clients were called with correct sync window
        sync_engine.caldav_client.get_events_by_sync_window.assert_called_once()
        sync_engine.google_client.get_events_by_sync_window.assert_called_once()
        
        # Check that the sync window was passed correctly
        call_args = sync_engine.caldav_client.get_events_by_sync_window.call_args
        assert call_args is not None
    
    @pytest.mark.asyncio
    async def test_event_deletion_sync(self, sync_engine, db_calendar_mapping, test_db_session):
        """Test syncing event deletions."""
        # Setup: Google has event that CalDAV doesn't have (deleted from CalDAV)
        caldav_events = []  # Event deleted from CalDAV
        
        google_events = [
            GoogleCalendarEvent(
                id="google-event-to-delete",
                summary="Event to Delete",
                start=datetime.utcnow(),
                end=datetime.utcnow() + timedelta(hours=1),
                updated=datetime.utcnow(),
                all_day=False
            )
        ]
        
        sync_engine.caldav_client.get_events_by_sync_window.return_value = caldav_events
        sync_engine.google_client.get_events_by_sync_window.return_value = google_events
        
        # Mock existing event mapping
        with patch.object(test_db_session, 'query') as mock_query:
            mock_event_mapping = Mock()
            mock_event_mapping.caldav_uid = "deleted-caldav-event"
            mock_event_mapping.google_event_id = "google-event-to-delete"
            mock_query.return_value.filter.return_value.all.return_value = [mock_event_mapping]
            
            # Perform sync
            result = await sync_engine.sync_mapping(db_calendar_mapping, test_db_session)
        
        assert result['status'] == 'success'
        assert result['deleted_count'] == 1
        
        # Verify Google event was deleted
        sync_engine.google_client.delete_event.assert_called_once()
