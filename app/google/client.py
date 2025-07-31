"""
Google Calendar API client for interacting with Google Calendar.

Handles calendar listing, event CRUD operations, and rate limiting
with proper error handling and retry logic.
"""

import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import asyncio
import pytz

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from app.google.models import GoogleCalendarEvent, GoogleCalendar
from app.auth.google_oauth import get_oauth_manager
from app.config import get_settings
from app.utils.logging import GoogleLogger
from app.utils.exceptions import (
    GoogleCalendarError,
    GoogleCalendarNotFoundError,
    GoogleCalendarEventError,
    GoogleRateLimitError,
    handle_google_exception
)


class GoogleCalendarClient:
    """Client for interacting with Google Calendar API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.oauth_manager = get_oauth_manager()
        self.logger = GoogleLogger()
        self._service = None
    
    def _get_service(self):
        """Get authenticated Google Calendar service."""
        if not self._service:
            credentials = self.oauth_manager.get_valid_credentials()
            if not credentials:
                raise GoogleCalendarError("No valid Google credentials available")
            
            self._service = build('calendar', 'v3', credentials=credentials)
        
        return self._service
    
    def _handle_rate_limit(self, delay: float = None):
        """Handle rate limiting with configurable delay."""
        if delay is None:
            delay = self.settings.google_calendar.rate_limit_delay
        
        if delay > 0:
            self.logger.log_rate_limit(delay)
            time.sleep(delay)
    
    def _execute_with_retry(self, request, max_retries: int = 3):
        """Execute API request with retry logic for rate limits."""
        for attempt in range(max_retries):
            try:
                return request.execute()
            
            except HttpError as e:
                if e.resp.status == 429:  # Rate limit exceeded
                    retry_after = int(e.resp.headers.get('Retry-After', 1))
                    if attempt < max_retries - 1:
                        self.logger.warning(f"Rate limit hit, retrying in {retry_after}s (attempt {attempt + 1})")
                        time.sleep(retry_after)
                        continue
                    else:
                        raise GoogleRateLimitError(f"Rate limit exceeded after {max_retries} attempts", retry_after)
                else:
                    raise handle_google_exception(e)
            
            except Exception as e:
                error_str = str(e).lower()
                # Check if this is an invalid_grant error (refresh token revoked)
                if 'invalid_grant' in error_str or 'token has been expired or revoked' in error_str:
                    self.logger.error(f"Refresh token invalid or revoked: {e}")
                    # Clear the service to force re-authentication
                    self._service = None
                    raise handle_google_exception(e)
                
                if attempt < max_retries - 1:
                    self.logger.warning(f"Request failed, retrying (attempt {attempt + 1}): {e}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    raise handle_google_exception(e)
        
        raise GoogleCalendarError("Max retries exceeded")
    
    def list_calendars(self) -> List[GoogleCalendar]:
        """List all accessible Google Calendars."""
        try:
            service = self._get_service()
            
            calendars = []
            page_token = None
            
            while True:
                request = service.calendarList().list(
                    maxResults=self.settings.google_calendar.max_results_per_request,
                    pageToken=page_token
                )
                
                result = self._execute_with_retry(request)
                
                for item in result.get('items', []):
                    calendar = GoogleCalendar.from_google_api(item)
                    calendars.append(calendar)
                
                page_token = result.get('nextPageToken')
                if not page_token:
                    break
                
                self._handle_rate_limit()
            
            self.logger.log_calendar_list(len(calendars))
            return calendars
            
        except Exception as e:
            if not isinstance(e, (GoogleCalendarError, GoogleRateLimitError)):
                e = handle_google_exception(e)
            raise e
    
    def get_calendar_by_id(self, calendar_id: str) -> Optional[GoogleCalendar]:
        """Get a specific calendar by ID."""
        try:
            service = self._get_service()
            
            request = service.calendarList().get(calendarId=calendar_id)
            result = self._execute_with_retry(request)
            
            return GoogleCalendar.from_google_api(result)
            
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise handle_google_exception(e)
        except Exception as e:
            raise handle_google_exception(e)
    
    def get_events(self, calendar_id: str, start_date: datetime, end_date: datetime, 
                   single_events: bool = True) -> List[GoogleCalendarEvent]:
        """
        Fetch events from a specific calendar within the given date range.
        
        Args:
            calendar_id: Google Calendar ID
            start_date: Start of date range
            end_date: End of date range
            single_events: Whether to expand recurring events into individual instances
        """
        try:
            service = self._get_service()
            
            events = []
            page_token = None
            
            while True:
                request = service.events().list(
                    calendarId=calendar_id,
                    timeMin=start_date.isoformat() + 'Z',
                    timeMax=end_date.isoformat() + 'Z',
                    singleEvents=single_events,
                    orderBy='startTime',
                    maxResults=self.settings.google_calendar.max_results_per_request,
                    pageToken=page_token
                )
                
                result = self._execute_with_retry(request)
                
                for item in result.get('items', []):
                    try:
                        event = GoogleCalendarEvent.from_google_api(item)
                        events.append(event)
                    except Exception as e:
                        self.logger.warning(f"Failed to parse event {item.get('id', 'unknown')}: {e}")
                        continue
                
                page_token = result.get('nextPageToken')
                if not page_token:
                    break
                
                self._handle_rate_limit()
            
            date_range = f"{start_date.date()} to {end_date.date()}"
            self.logger.info(f"Fetched {len(events)} events from {calendar_id} ({date_range})")
            
            return events
            
        except Exception as e:
            if not isinstance(e, (GoogleCalendarError, GoogleRateLimitError)):
                e = handle_google_exception(e)
            raise e
    
    def get_events_by_sync_window(self, calendar_id: str, sync_window_days: int) -> List[GoogleCalendarEvent]:
        """Fetch events from a calendar using the sync window configuration."""
        start_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=sync_window_days)
        
        # Ensure timezone awareness
        if start_date.tzinfo is None:
            start_date = pytz.UTC.localize(start_date)
        if end_date.tzinfo is None:
            end_date = pytz.UTC.localize(end_date)
        
        self.logger.info(f"GOOGLE DATETIME DEBUG: start_date={start_date} (tzinfo: {start_date.tzinfo}), end_date={end_date} (tzinfo: {end_date.tzinfo})")
        
        events = self.get_events(calendar_id, start_date, end_date)
        
        # Log datetime info for fetched events
        for event in events:
            self.logger.info(f"GOOGLE EVENT DATETIME DEBUG for UID {event.uid} (ID: {event.id}):")
            self.logger.info(f"  start: {event.start} (type: {type(event.start)}, tzinfo: {getattr(event.start, 'tzinfo', None)})")
            self.logger.info(f"  end: {event.end} (type: {type(event.end)}, tzinfo: {getattr(event.end, 'tzinfo', None)})")
            self.logger.info(f"  updated: {event.updated} (type: {type(event.updated)}, tzinfo: {getattr(event.updated, 'tzinfo', None)})")
            self.logger.info(f"  created: {event.created} (type: {type(event.created)}, tzinfo: {getattr(event.created, 'tzinfo', None)})")
        
        return events
    
    def create_event(self, calendar_id: str, event: GoogleCalendarEvent) -> GoogleCalendarEvent:
        """Create a new event in the specified calendar."""
        try:
            service = self._get_service()
            
            event_data = event.to_google_api_format()
            
            request = service.events().insert(
                calendarId=calendar_id,
                body=event_data
            )
            
            result = self._execute_with_retry(request)
            
            created_event = GoogleCalendarEvent.from_google_api(result)
            
            self.logger.info(f"Created event {created_event.id} in calendar {calendar_id}")
            return created_event
            
        except Exception as e:
            self.logger.error(f"Failed to create event: {e}")
            if not isinstance(e, (GoogleCalendarError, GoogleRateLimitError)):
                e = handle_google_exception(e)
            raise GoogleCalendarEventError(f"Failed to create event: {e}")
    
    def update_event(self, calendar_id: str, event: GoogleCalendarEvent) -> GoogleCalendarEvent:
        """Update an existing event in the specified calendar."""
        try:
            if not event.id:
                raise GoogleCalendarEventError("Event ID is required for update")
            
            service = self._get_service()
            
            event_data = event.to_google_api_format()
            
            request = service.events().update(
                calendarId=calendar_id,
                eventId=event.id,
                body=event_data
            )
            
            result = self._execute_with_retry(request)
            
            updated_event = GoogleCalendarEvent.from_google_api(result)
            
            self.logger.info(f"Updated event {updated_event.id} in calendar {calendar_id}")
            return updated_event
            
        except HttpError as e:
            if e.resp.status == 404:
                raise GoogleCalendarEventError(f"Event {event.id} not found for update")
            raise handle_google_exception(e)
        except Exception as e:
            self.logger.error(f"Failed to update event {event.id}: {e}")
            if not isinstance(e, (GoogleCalendarError, GoogleRateLimitError)):
                e = handle_google_exception(e)
            raise GoogleCalendarEventError(f"Failed to update event: {e}")
    
    def delete_event(self, calendar_id: str, event_id: str) -> bool:
        """Delete an event from the specified calendar."""
        try:
            service = self._get_service()
            
            request = service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            )
            
            self._execute_with_retry(request)
            
            self.logger.info(f"Deleted event {event_id} from calendar {calendar_id}")
            return True
            
        except HttpError as e:
            if e.resp.status == 404:
                self.logger.warning(f"Event {event_id} not found for deletion")
                return True  # Already deleted
            raise handle_google_exception(e)
        except Exception as e:
            self.logger.error(f"Failed to delete event {event_id}: {e}")
            if not isinstance(e, (GoogleCalendarError, GoogleRateLimitError)):
                e = handle_google_exception(e)
            raise GoogleCalendarEventError(f"Failed to delete event: {e}")
    
    def get_event_by_id(self, calendar_id: str, event_id: str) -> Optional[GoogleCalendarEvent]:
        """Get a specific event by ID."""
        try:
            service = self._get_service()
            
            request = service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            )
            
            result = self._execute_with_retry(request)
            
            return GoogleCalendarEvent.from_google_api(result)
            
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise handle_google_exception(e)
        except Exception as e:
            raise handle_google_exception(e)
    
    def find_events_by_uid(self, calendar_id: str, uid: str) -> List[GoogleCalendarEvent]:
        """Find events by iCalendar UID."""
        try:
            service = self._get_service()
            
            # Search for events with the specific iCalUID
            request = service.events().list(
                calendarId=calendar_id,
                iCalUID=uid,
                maxResults=self.settings.google_calendar.max_results_per_request
            )
            
            result = self._execute_with_retry(request)
            
            events = []
            for item in result.get('items', []):
                try:
                    event = GoogleCalendarEvent.from_google_api(item)
                    events.append(event)
                except Exception as e:
                    self.logger.warning(f"Failed to parse event {item.get('id', 'unknown')}: {e}")
                    continue
            
            return events
            
        except Exception as e:
            if not isinstance(e, (GoogleCalendarError, GoogleRateLimitError)):
                e = handle_google_exception(e)
            raise e
    
    def batch_create_events(self, calendar_id: str, events: List[GoogleCalendarEvent]) -> List[GoogleCalendarEvent]:
        """Create multiple events in batch."""
        created_events = []
        
        # Process in batches to respect rate limits
        batch_size = self.settings.google_calendar.batch_size
        
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            
            for event in batch:
                try:
                    created_event = self.create_event(calendar_id, event)
                    created_events.append(created_event)
                    self._handle_rate_limit()
                except Exception as e:
                    self.logger.error(f"Failed to create event in batch: {e}")
                    continue
        
        self.logger.log_event_operation("created", len(created_events))
        return created_events
    
    def batch_update_events(self, calendar_id: str, events: List[GoogleCalendarEvent]) -> List[GoogleCalendarEvent]:
        """Update multiple events in batch."""
        updated_events = []
        
        # Process in batches to respect rate limits
        batch_size = self.settings.google_calendar.batch_size
        
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            
            for event in batch:
                try:
                    updated_event = self.update_event(calendar_id, event)
                    updated_events.append(updated_event)
                    self._handle_rate_limit()
                except Exception as e:
                    self.logger.error(f"Failed to update event in batch: {e}")
                    continue
        
        self.logger.log_event_operation("updated", len(updated_events))
        return updated_events
    
    def batch_delete_events(self, calendar_id: str, event_ids: List[str]) -> int:
        """Delete multiple events in batch."""
        deleted_count = 0
        
        # Process in batches to respect rate limits
        batch_size = self.settings.google_calendar.batch_size
        
        for i in range(0, len(event_ids), batch_size):
            batch = event_ids[i:i + batch_size]
            
            for event_id in batch:
                try:
                    if self.delete_event(calendar_id, event_id):
                        deleted_count += 1
                    self._handle_rate_limit()
                except Exception as e:
                    self.logger.error(f"Failed to delete event in batch: {e}")
                    continue
        
        self.logger.log_event_operation("deleted", deleted_count)
        return deleted_count


# Global client instance
google_client = GoogleCalendarClient()


def get_google_client() -> GoogleCalendarClient:
    """Get the global Google Calendar client instance."""
    return google_client
