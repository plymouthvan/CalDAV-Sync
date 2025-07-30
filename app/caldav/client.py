"""
CalDAV client for connecting to and interacting with CalDAV servers.

Handles authentication, calendar discovery, and event fetching with proper
error handling and retry logic.
"""

import caldav
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
import requests
from requests.auth import HTTPBasicAuth

from app.caldav.models import CalDAVEvent, CalDAVCalendar, CalDAVAccount
from app.config import get_settings
from app.utils.logging import CalDAVLogger
from app.utils.exceptions import (
    CalDAVConnectionError,
    CalDAVAuthenticationError,
    CalDAVCalendarNotFoundError,
    CalDAVEventError,
    handle_caldav_exception
)


class CalDAVClient:
    """Client for interacting with CalDAV servers."""
    
    def __init__(self, account: CalDAVAccount, password: str):
        self.account = account
        self.password = password
        self.settings = get_settings()
        self.logger = CalDAVLogger(account.name)
        
        # Configure caldav client
        self.client = None
        self._setup_client()
    
    def _setup_client(self):
        """Initialize the CalDAV client with authentication."""
        try:
            self.client = caldav.DAVClient(
                url=self.account.base_url,
                username=self.account.username,
                password=self.password,
                auth=HTTPBasicAuth(self.account.username, self.password),
                ssl_verify_cert=self.account.verify_ssl
            )
            
            # Set timeouts from configuration
            if hasattr(self.client, 'session'):
                self.client.session.timeout = (
                    self.settings.caldav.connection_timeout,
                    self.settings.caldav.read_timeout
                )
            
        except Exception as e:
            raise handle_caldav_exception(e)
    
    def test_connection(self) -> bool:
        """Test the CalDAV connection and authentication."""
        try:
            # Try to get the principal to test authentication
            principal = self.client.principal()
            if principal:
                self.logger.log_connection_test(True)
                return True
            else:
                self.logger.log_connection_test(False, "No principal found")
                return False
                
        except Exception as e:
            error_msg = str(e)
            self.logger.log_connection_test(False, error_msg)
            
            # Re-raise as appropriate custom exception
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                raise CalDAVAuthenticationError(f"Authentication failed for {self.account.name}: {e}")
            elif "connection" in error_msg.lower() or "timeout" in error_msg.lower():
                raise CalDAVConnectionError(f"Connection failed for {self.account.name}: {e}")
            else:
                raise handle_caldav_exception(e)
    
    def discover_calendars(self) -> List[CalDAVCalendar]:
        """Discover available calendars for this account."""
        try:
            principal = self.client.principal()
            calendars = principal.calendars()
            
            discovered_calendars = []
            
            for cal in calendars:
                try:
                    # Get calendar properties
                    props = cal.get_properties([
                        caldav.dav.DisplayName(),
                        caldav.dav.CalendarDescription(),
                        caldav.dav.CalendarColor(),
                        caldav.dav.CalendarTimeZone(),
                    ])
                    
                    calendar_id = cal.url.path.rstrip('/')
                    name = str(props.get(caldav.dav.DisplayName.tag, calendar_id))
                    description = str(props.get(caldav.dav.CalendarDescription.tag, '')) or None
                    color = str(props.get(caldav.dav.CalendarColor.tag, '')) or None
                    timezone = str(props.get(caldav.dav.CalendarTimeZone.tag, '')) or None
                    
                    caldav_calendar = CalDAVCalendar(
                        id=calendar_id,
                        name=name,
                        description=description,
                        color=color,
                        timezone=timezone,
                        url=str(cal.url)
                    )
                    
                    discovered_calendars.append(caldav_calendar)
                    
                except Exception as e:
                    self.logger.warning(f"Failed to get properties for calendar {cal.url}: {e}")
                    continue
            
            self.logger.log_calendar_discovery(len(discovered_calendars))
            return discovered_calendars
            
        except Exception as e:
            raise handle_caldav_exception(e)
    
    def get_calendar_by_id(self, calendar_id: str) -> Optional[caldav.Calendar]:
        """Get a specific calendar by its ID."""
        try:
            # Construct calendar URL
            calendar_url = urljoin(self.account.base_url, calendar_id)
            if not calendar_url.endswith('/'):
                calendar_url += '/'
            
            calendar = caldav.Calendar(client=self.client, url=calendar_url)
            
            # Test if calendar exists by trying to get its properties
            try:
                calendar.get_properties([caldav.dav.DisplayName()])
                return calendar
            except:
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to get calendar {calendar_id}: {e}")
            return None
    
    def get_events(self, calendar_id: str, start_date: datetime, end_date: datetime) -> List[CalDAVEvent]:
        """Fetch events from a specific calendar within the given date range."""
        try:
            calendar = self.get_calendar_by_id(calendar_id)
            if not calendar:
                raise CalDAVCalendarNotFoundError(f"Calendar {calendar_id} not found")
            
            # Search for events in the date range
            events = calendar.date_search(start=start_date, end=end_date, expand=True)
            
            caldav_events = []
            
            for event in events:
                try:
                    # Get the event data
                    ical_data = event.data
                    
                    # Parse the iCal data
                    parsed_events = CalDAVEvent.from_ical(ical_data)
                    caldav_events.extend(parsed_events)
                    
                except Exception as e:
                    self.logger.warning(f"Failed to parse event {event.url}: {e}")
                    continue
            
            date_range = f"{start_date.date()} to {end_date.date()}"
            self.logger.log_event_fetch(len(caldav_events), date_range)
            
            return caldav_events
            
        except CalDAVCalendarNotFoundError:
            raise
        except Exception as e:
            raise handle_caldav_exception(e)
    
    def get_events_by_sync_window(self, calendar_id: str, sync_window_days: int) -> List[CalDAVEvent]:
        """Fetch events from a calendar using the sync window configuration."""
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=sync_window_days)
        
        return self.get_events(calendar_id, start_date, end_date)
    
    def create_event(self, calendar_id: str, event: CalDAVEvent) -> bool:
        """Create a new event in the specified calendar."""
        try:
            calendar = self.get_calendar_by_id(calendar_id)
            if not calendar:
                raise CalDAVCalendarNotFoundError(f"Calendar {calendar_id} not found")
            
            # Convert CalDAVEvent to iCal format
            ical_data = self._event_to_ical(event)
            
            # Create the event
            calendar.add_event(ical_data)
            
            self.logger.info(f"Created event {event.uid} in calendar {calendar_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to create event {event.uid}: {e}")
            raise CalDAVEventError(f"Failed to create event: {e}")
    
    def update_event(self, calendar_id: str, event: CalDAVEvent) -> bool:
        """Update an existing event in the specified calendar."""
        try:
            calendar = self.get_calendar_by_id(calendar_id)
            if not calendar:
                raise CalDAVCalendarNotFoundError(f"Calendar {calendar_id} not found")
            
            # Find the existing event by UID
            existing_events = calendar.search(uid=event.uid)
            if not existing_events:
                raise CalDAVEventError(f"Event {event.uid} not found for update")
            
            existing_event = existing_events[0]
            
            # Convert CalDAVEvent to iCal format
            ical_data = self._event_to_ical(event)
            
            # Update the event
            existing_event.data = ical_data
            existing_event.save()
            
            self.logger.info(f"Updated event {event.uid} in calendar {calendar_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update event {event.uid}: {e}")
            raise CalDAVEventError(f"Failed to update event: {e}")
    
    def delete_event(self, calendar_id: str, event_uid: str) -> bool:
        """Delete an event from the specified calendar."""
        try:
            calendar = self.get_calendar_by_id(calendar_id)
            if not calendar:
                raise CalDAVCalendarNotFoundError(f"Calendar {calendar_id} not found")
            
            # Find the event by UID
            existing_events = calendar.search(uid=event_uid)
            if not existing_events:
                self.logger.warning(f"Event {event_uid} not found for deletion")
                return True  # Already deleted
            
            existing_event = existing_events[0]
            existing_event.delete()
            
            self.logger.info(f"Deleted event {event_uid} from calendar {calendar_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete event {event_uid}: {e}")
            raise CalDAVEventError(f"Failed to delete event: {e}")
    
    def _event_to_ical(self, event: CalDAVEvent) -> str:
        """Convert a CalDAVEvent to iCal format."""
        try:
            from icalendar import Calendar, Event
            
            cal = Calendar()
            cal.add('prodid', '-//CalDAV Sync Microservice//EN')
            cal.add('version', '2.0')
            
            ical_event = Event()
            ical_event.add('uid', event.uid)
            ical_event.add('summary', event.summary)
            
            if event.description:
                ical_event.add('description', event.description)
            
            if event.location:
                ical_event.add('location', event.location)
            
            if event.start:
                ical_event.add('dtstart', event.start)
            
            if event.end:
                ical_event.add('dtend', event.end)
            
            if event.rrule:
                # Parse and add recurrence rule
                from icalendar.prop import vRecur
                ical_event.add('rrule', vRecur.from_ical(event.rrule))
            
            if event.recurrence_id:
                ical_event.add('recurrence-id', event.recurrence_id)
            
            if event.last_modified:
                ical_event.add('last-modified', event.last_modified)
            
            if event.created:
                ical_event.add('created', event.created)
            
            ical_event.add('sequence', event.sequence)
            
            cal.add_component(ical_event)
            
            return cal.to_ical().decode('utf-8')
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to convert event to iCal: {e}")


class CalDAVClientFactory:
    """Factory for creating CalDAV clients."""
    
    @staticmethod
    def create_client(account: CalDAVAccount, password: str) -> CalDAVClient:
        """Create a CalDAV client for the given account."""
        return CalDAVClient(account, password)
    
    @staticmethod
    def test_connection(account: CalDAVAccount, password: str) -> bool:
        """Test connection to a CalDAV account without creating a persistent client."""
        try:
            client = CalDAVClient(account, password)
            return client.test_connection()
        except Exception:
            return False
