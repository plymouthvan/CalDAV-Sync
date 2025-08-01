"""
CalDAV event models and data structures.

Defines the core event structure for CalDAV events with support for
recurrence rules, timezone handling, and normalization to a common format.
"""

import hashlib
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass
from icalendar import Calendar, Event as ICalEvent
from dateutil import tz
import pytz

from app.utils.exceptions import EventNormalizationError, RecurrenceError


@dataclass
class CalDAVEvent:
    """Normalized CalDAV event structure with core fields only."""
    
    # Core required fields
    uid: str
    summary: str
    description: Optional[str] = None
    
    # Date/time fields
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    all_day: bool = False
    timezone: Optional[str] = None
    
    # Location
    location: Optional[str] = None
    
    # Recurrence fields
    rrule: Optional[str] = None  # Recurrence rule as string
    recurrence_id: Optional[str] = None  # For exception instances
    
    # Metadata
    last_modified: Optional[datetime] = None
    created: Optional[datetime] = None
    sequence: int = 0
    
    # Internal fields
    raw_data: Optional[str] = None  # Original iCal data
    
    def __post_init__(self):
        """Validate and normalize event data after initialization."""
        self._validate_required_fields()
        self._normalize_dates()
        self._normalize_timezone()
    
    def _validate_required_fields(self):
        """Validate that required fields are present."""
        if not self.uid:
            raise EventNormalizationError("Event UID is required")
        
        if not self.summary:
            raise EventNormalizationError("Event summary is required")
        
        if not self.all_day and (not self.start or not self.end):
            raise EventNormalizationError("Start and end times are required for non-all-day events")
    
    def _normalize_dates(self):
        """Normalize date/time fields."""
        if self.all_day:
            # For all-day events, ensure we have date objects or datetime at midnight
            if isinstance(self.start, datetime):
                self.start = self.start.replace(hour=0, minute=0, second=0, microsecond=0)
            if isinstance(self.end, datetime):
                self.end = self.end.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            # For timed events, ensure we have datetime objects
            if isinstance(self.start, date) and not isinstance(self.start, datetime):
                self.start = datetime.combine(self.start, datetime.min.time())
            if isinstance(self.end, date) and not isinstance(self.end, datetime):
                self.end = datetime.combine(self.end, datetime.min.time())
    
    def _normalize_timezone(self):
        """Normalize timezone information."""
        if not self.all_day and self.start and self.end:
            # If timezone is specified but datetime objects are naive, apply timezone
            if self.timezone and self.start.tzinfo is None:
                try:
                    tz_obj = pytz.timezone(self.timezone)
                    self.start = tz_obj.localize(self.start)
                    self.end = tz_obj.localize(self.end)
                except pytz.UnknownTimeZoneError:
                    # If timezone is unknown, treat as UTC
                    self.start = pytz.UTC.localize(self.start)
                    self.end = pytz.UTC.localize(self.end)
                    self.timezone = "UTC"
            
            # If datetime objects have timezone but no timezone field, extract it
            elif not self.timezone and self.start.tzinfo:
                self.timezone = str(self.start.tzinfo)
    
    def get_content_hash(self) -> str:
        """Generate a hash of the event content for change detection."""
        content_parts = [
            self.uid or "",  # Ensure consistent handling of None values
            self.summary or "",
            self.description or "",
            self.location or "",
            str(self.start) if self.start else "",
            str(self.end) if self.end else "",
            str(self.all_day),
            self.timezone or "",
            self.rrule or "",  # This maps to Google's normalized recurrence
            self.recurrence_id or "",  # This maps to Google's recurring_event_id
        ]
        
        content_string = "|".join(content_parts)
        return hashlib.sha256(content_string.encode()).hexdigest()
    
    def is_recurring(self) -> bool:
        """Check if this event has recurrence rules."""
        return bool(self.rrule)
    
    def is_exception(self) -> bool:
        """Check if this event is an exception to a recurring series."""
        return bool(self.recurrence_id)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary representation."""
        return {
            "uid": self.uid,
            "summary": self.summary,
            "description": self.description,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "all_day": self.all_day,
            "timezone": self.timezone,
            "location": self.location,
            "rrule": self.rrule,
            "recurrence_id": self.recurrence_id,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "created": self.created.isoformat() if self.created else None,
            "sequence": self.sequence,
        }
    
    @classmethod
    def from_ical(cls, ical_data: str) -> List['CalDAVEvent']:
        """Parse iCal data and return list of CalDAV events."""
        try:
            calendar = Calendar.from_ical(ical_data)
            events = []
            
            for component in calendar.walk():
                if component.name == "VEVENT":
                    event = cls._parse_ical_event(component, ical_data)
                    if event:
                        events.append(event)
            
            return events
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to parse iCal data: {e}")
    
    @classmethod
    def _parse_ical_event(cls, ical_event: ICalEvent, raw_data: str) -> Optional['CalDAVEvent']:
        """Parse a single iCal event component."""
        try:
            # Extract basic fields
            uid = str(ical_event.get('UID', ''))
            summary = str(ical_event.get('SUMMARY', ''))
            description = str(ical_event.get('DESCRIPTION', '')) if ical_event.get('DESCRIPTION') else None
            location = str(ical_event.get('LOCATION', '')) if ical_event.get('LOCATION') else None
            
            # Extract date/time fields
            dtstart = ical_event.get('DTSTART')
            dtend = ical_event.get('DTEND')
            
            if not dtstart:
                return None
            
            start_dt = dtstart.dt if dtstart else None
            end_dt = dtend.dt if dtend else None
            
            # Determine if all-day event
            all_day = isinstance(start_dt, date) and not isinstance(start_dt, datetime)
            
            # Ensure timezone awareness for timed events
            if not all_day:
                if start_dt and isinstance(start_dt, datetime) and start_dt.tzinfo is None:
                    start_dt = pytz.UTC.localize(start_dt)
                    print(f"CALDAV MODEL DEBUG: normalized start_dt to UTC: {start_dt}")
                if end_dt and isinstance(end_dt, datetime) and end_dt.tzinfo is None:
                    end_dt = pytz.UTC.localize(end_dt)
                    print(f"CALDAV MODEL DEBUG: normalized end_dt to UTC: {end_dt}")
            
            # Extract timezone
            timezone = None
            if not all_day and isinstance(start_dt, datetime) and start_dt.tzinfo:
                timezone = str(start_dt.tzinfo)
            
            # Extract recurrence rule
            rrule = None
            if ical_event.get('RRULE'):
                rrule = str(ical_event.get('RRULE'))
            
            # Extract recurrence ID for exceptions
            recurrence_id = None
            if ical_event.get('RECURRENCE-ID'):
                recurrence_id = str(ical_event.get('RECURRENCE-ID'))
            
            # Extract metadata
            last_modified = None
            if ical_event.get('LAST-MODIFIED'):
                last_modified = ical_event.get('LAST-MODIFIED').dt
                # Add diagnostic logging for datetime parsing
                print(f"CALDAV MODEL DEBUG: last_modified={last_modified} (type: {type(last_modified)}, tzinfo: {getattr(last_modified, 'tzinfo', None)})")
                # Ensure timezone awareness - if naive, assume UTC
                if last_modified and last_modified.tzinfo is None:
                    last_modified = pytz.UTC.localize(last_modified)
                    print(f"CALDAV MODEL DEBUG: normalized last_modified to UTC: {last_modified}")
            
            created = None
            if ical_event.get('CREATED'):
                created = ical_event.get('CREATED').dt
                print(f"CALDAV MODEL DEBUG: created={created} (type: {type(created)}, tzinfo: {getattr(created, 'tzinfo', None)})")
                # Ensure timezone awareness - if naive, assume UTC
                if created and created.tzinfo is None:
                    created = pytz.UTC.localize(created)
                    print(f"CALDAV MODEL DEBUG: normalized created to UTC: {created}")
            
            sequence = int(ical_event.get('SEQUENCE', 0))
            
            return cls(
                uid=uid,
                summary=summary,
                description=description,
                start=start_dt,
                end=end_dt,
                all_day=all_day,
                timezone=timezone,
                location=location,
                rrule=rrule,
                recurrence_id=recurrence_id,
                last_modified=last_modified,
                created=created,
                sequence=sequence,
                raw_data=raw_data
            )
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to parse iCal event: {e}")


@dataclass
class CalDAVCalendar:
    """CalDAV calendar information."""
    
    id: str  # Calendar identifier/path
    name: str  # Display name
    description: Optional[str] = None
    color: Optional[str] = None
    timezone: Optional[str] = None
    url: Optional[str] = None  # Full calendar URL
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert calendar to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "timezone": self.timezone,
            "url": self.url,
        }


@dataclass
class CalDAVAccount:
    """CalDAV account information."""
    
    name: str  # User-friendly name
    username: str
    base_url: str
    verify_ssl: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert account to dictionary representation."""
        return {
            "name": self.name,
            "username": self.username,
            "base_url": self.base_url,
            "verify_ssl": self.verify_ssl,
        }
