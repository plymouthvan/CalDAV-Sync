"""
Event normalization for CalDAV Sync Microservice.

Handles conversion between CalDAV and Google Calendar event formats,
timezone normalization, and all-day event handling.
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any, Union
import pytz
from dateutil import tz

from app.caldav.models import CalDAVEvent
from app.google.models import GoogleCalendarEvent
from app.utils.exceptions import EventNormalizationError
from app.utils.logging import get_logger

logger = get_logger("normalizer")


class EventNormalizer:
    """Handles normalization and conversion between different event formats."""
    
    def __init__(self):
        pass
    
    def caldav_to_google(self, caldav_event: CalDAVEvent) -> GoogleCalendarEvent:
        """
        Convert CalDAV event to Google Calendar event format.
        
        Args:
            caldav_event: CalDAV event to convert
            
        Returns:
            Normalized Google Calendar event
        """
        try:
            # Convert recurrence rule from CalDAV to Google format
            recurrence = None
            if caldav_event.rrule:
                recurrence = [f"RRULE:{caldav_event.rrule}"]
            
            # Handle recurring event instances
            recurring_event_id = None
            if caldav_event.recurrence_id:
                # For Google Calendar, we need to handle this differently
                # This would typically be handled by the sync engine
                pass
            
            google_event = GoogleCalendarEvent(
                uid=caldav_event.uid,
                summary=caldav_event.summary,
                description=caldav_event.description,
                start=caldav_event.start,
                end=caldav_event.end,
                all_day=caldav_event.all_day,
                timezone=caldav_event.timezone,
                location=caldav_event.location,
                recurrence=recurrence,
                recurring_event_id=recurring_event_id,
                sequence=caldav_event.sequence,
                status="confirmed"
            )
            
            return google_event
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to convert CalDAV event to Google format: {e}")
    
    def google_to_caldav(self, google_event: GoogleCalendarEvent) -> CalDAVEvent:
        """
        Convert Google Calendar event to CalDAV event format.
        
        Args:
            google_event: Google Calendar event to convert
            
        Returns:
            Normalized CalDAV event
        """
        try:
            # Convert recurrence from Google to CalDAV format
            rrule = None
            if google_event.recurrence:
                for rule in google_event.recurrence:
                    if rule.startswith("RRULE:"):
                        rrule = rule[6:]  # Remove "RRULE:" prefix
                        break
            
            # Handle recurring event instances
            recurrence_id = None
            if google_event.recurring_event_id:
                # This would need to be handled based on the specific instance
                pass
            
            caldav_event = CalDAVEvent(
                uid=google_event.uid or google_event.id,  # Use iCalUID or fall back to Google ID
                summary=google_event.summary,
                description=google_event.description,
                start=google_event.start,
                end=google_event.end,
                all_day=google_event.all_day,
                timezone=google_event.timezone,
                location=google_event.location,
                rrule=rrule,
                recurrence_id=recurrence_id,
                last_modified=google_event.updated,
                created=google_event.created,
                sequence=google_event.sequence
            )
            
            return caldav_event
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to convert Google event to CalDAV format: {e}")
    
    def normalize_timezone(self, event_datetime: datetime, target_timezone: Optional[str] = None) -> datetime:
        """
        Normalize datetime to a specific timezone.
        
        Args:
            event_datetime: Datetime to normalize
            target_timezone: Target timezone (defaults to UTC)
            
        Returns:
            Normalized datetime
        """
        if not event_datetime:
            return event_datetime
        
        target_tz = pytz.UTC
        if target_timezone:
            try:
                target_tz = pytz.timezone(target_timezone)
            except pytz.UnknownTimeZoneError:
                logger.warning(f"Unknown timezone {target_timezone}, using UTC")
                target_tz = pytz.UTC
        
        # If datetime is naive, assume it's in the target timezone
        if event_datetime.tzinfo is None:
            return target_tz.localize(event_datetime)
        
        # Convert to target timezone
        return event_datetime.astimezone(target_tz)
    
    def normalize_all_day_event(self, start: Union[datetime, date], end: Union[datetime, date]) -> tuple[datetime, datetime, bool]:
        """
        Normalize all-day event dates.
        
        Args:
            start: Start date/datetime
            end: End date/datetime
            
        Returns:
            Tuple of (normalized_start, normalized_end, is_all_day)
        """
        # Check if this is an all-day event
        is_all_day = isinstance(start, date) and not isinstance(start, datetime)
        
        if is_all_day:
            # Convert dates to datetime at midnight
            if isinstance(start, date):
                start = datetime.combine(start, datetime.min.time())
            if isinstance(end, date):
                end = datetime.combine(end, datetime.min.time())
            
            # Ensure times are at midnight
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        
        return start, end, is_all_day
    
    def extract_recurrence_exceptions(self, events: List[Union[CalDAVEvent, GoogleCalendarEvent]]) -> Dict[str, List[Union[CalDAVEvent, GoogleCalendarEvent]]]:
        """
        Group events by their master event UID and separate exceptions.
        
        Args:
            events: List of events to process
            
        Returns:
            Dictionary mapping master UID to list of exception events
        """
        exceptions = {}
        
        for event in events:
            if isinstance(event, CalDAVEvent):
                if event.recurrence_id:
                    master_uid = event.uid
                    if master_uid not in exceptions:
                        exceptions[master_uid] = []
                    exceptions[master_uid].append(event)
            
            elif isinstance(event, GoogleCalendarEvent):
                if event.recurring_event_id:
                    master_uid = event.recurring_event_id
                    if master_uid not in exceptions:
                        exceptions[master_uid] = []
                    exceptions[master_uid].append(event)
        
        return exceptions
    
    def merge_event_updates(self, existing_event: Union[CalDAVEvent, GoogleCalendarEvent], 
                          updated_event: Union[CalDAVEvent, GoogleCalendarEvent]) -> Union[CalDAVEvent, GoogleCalendarEvent]:
        """
        Merge updates from one event into another, preserving important metadata.
        
        Args:
            existing_event: Current event
            updated_event: Event with updates
            
        Returns:
            Merged event
        """
        try:
            if type(existing_event) != type(updated_event):
                raise EventNormalizationError("Cannot merge events of different types")
            
            if isinstance(existing_event, CalDAVEvent):
                # Create new event with updated data but preserve metadata
                merged = CalDAVEvent(
                    uid=existing_event.uid,
                    summary=updated_event.summary,
                    description=updated_event.description,
                    start=updated_event.start,
                    end=updated_event.end,
                    all_day=updated_event.all_day,
                    timezone=updated_event.timezone,
                    location=updated_event.location,
                    rrule=updated_event.rrule,
                    recurrence_id=updated_event.recurrence_id,
                    last_modified=updated_event.last_modified or existing_event.last_modified,
                    created=existing_event.created,  # Preserve original creation time
                    sequence=max(existing_event.sequence, updated_event.sequence),
                    raw_data=updated_event.raw_data
                )
                
            elif isinstance(existing_event, GoogleCalendarEvent):
                # Create new event with updated data but preserve metadata
                merged = GoogleCalendarEvent(
                    id=existing_event.id,  # Preserve Google Calendar ID
                    uid=existing_event.uid,  # Preserve iCal UID
                    summary=updated_event.summary,
                    description=updated_event.description,
                    start=updated_event.start,
                    end=updated_event.end,
                    all_day=updated_event.all_day,
                    timezone=updated_event.timezone,
                    location=updated_event.location,
                    recurrence=updated_event.recurrence,
                    recurring_event_id=updated_event.recurring_event_id,
                    updated=updated_event.updated or existing_event.updated,
                    created=existing_event.created,  # Preserve original creation time
                    sequence=max(existing_event.sequence, updated_event.sequence),
                    status=updated_event.status,
                    raw_data=updated_event.raw_data
                )
            
            return merged
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to merge event updates: {e}")
    
    def validate_event_consistency(self, event: Union[CalDAVEvent, GoogleCalendarEvent]) -> List[str]:
        """
        Validate event for consistency and return list of issues.
        
        Args:
            event: Event to validate
            
        Returns:
            List of validation issues (empty if valid)
        """
        issues = []
        
        # Check required fields
        if not event.summary:
            issues.append("Event summary is required")
        
        if not event.uid and not (isinstance(event, GoogleCalendarEvent) and event.id):
            issues.append("Event must have UID or ID")
        
        # Check date/time consistency
        if not event.all_day:
            if not event.start or not event.end:
                issues.append("Timed events must have start and end times")
            elif event.start >= event.end:
                issues.append("Event start time must be before end time")
        
        # Check timezone consistency
        if not event.all_day and event.start and event.end:
            if event.start.tzinfo != event.end.tzinfo:
                issues.append("Start and end times must have consistent timezone info")
        
        # Check recurrence consistency
        if isinstance(event, CalDAVEvent):
            if event.rrule and event.recurrence_id:
                issues.append("Event cannot have both recurrence rule and recurrence ID")
        elif isinstance(event, GoogleCalendarEvent):
            if event.recurrence and event.recurring_event_id:
                issues.append("Event cannot have both recurrence rules and recurring event ID")
        
        return issues


# Global normalizer instance
event_normalizer = EventNormalizer()


def get_event_normalizer() -> EventNormalizer:
    """Get the global event normalizer instance."""
    return event_normalizer
