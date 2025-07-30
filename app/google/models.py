"""
Google Calendar event models and data structures.

Defines the core event structure for Google Calendar events with support for
conversion to/from CalDAV events and Google Calendar API format.
"""

import hashlib
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass
import pytz
from dateutil import parser as date_parser

from app.utils.exceptions import EventNormalizationError


@dataclass
class GoogleCalendarEvent:
    """Normalized Google Calendar event structure with core fields only."""
    
    # Core required fields
    id: Optional[str] = None  # Google Calendar event ID
    uid: Optional[str] = None  # iCalendar UID (for sync mapping)
    summary: str = ""
    description: Optional[str] = None
    
    # Date/time fields
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    all_day: bool = False
    timezone: Optional[str] = None
    
    # Location
    location: Optional[str] = None
    
    # Recurrence fields
    recurrence: Optional[List[str]] = None  # Google's recurrence format
    recurring_event_id: Optional[str] = None  # For recurring event instances
    
    # Metadata
    updated: Optional[datetime] = None
    created: Optional[datetime] = None
    sequence: int = 0
    status: str = "confirmed"  # confirmed, tentative, cancelled
    
    # Internal fields
    raw_data: Optional[Dict[str, Any]] = None  # Original Google API data
    
    def __post_init__(self):
        """Validate and normalize event data after initialization."""
        self._validate_required_fields()
        self._normalize_dates()
        self._normalize_timezone()
    
    def _validate_required_fields(self):
        """Validate that required fields are present."""
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
            self.uid or "",
            self.summary or "",
            self.description or "",
            self.location or "",
            str(self.start) if self.start else "",
            str(self.end) if self.end else "",
            str(self.all_day),
            self.timezone or "",
            "|".join(self.recurrence or []),
            self.recurring_event_id or "",
        ]
        
        content_string = "|".join(content_parts)
        return hashlib.sha256(content_string.encode()).hexdigest()
    
    def is_recurring(self) -> bool:
        """Check if this event has recurrence rules."""
        return bool(self.recurrence)
    
    def is_recurring_instance(self) -> bool:
        """Check if this event is an instance of a recurring series."""
        return bool(self.recurring_event_id)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary representation."""
        return {
            "id": self.id,
            "uid": self.uid,
            "summary": self.summary,
            "description": self.description,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "all_day": self.all_day,
            "timezone": self.timezone,
            "location": self.location,
            "recurrence": self.recurrence,
            "recurring_event_id": self.recurring_event_id,
            "updated": self.updated.isoformat() if self.updated else None,
            "created": self.created.isoformat() if self.created else None,
            "sequence": self.sequence,
            "status": self.status,
        }
    
    def to_google_api_format(self) -> Dict[str, Any]:
        """Convert event to Google Calendar API format."""
        event_data = {
            "summary": self.summary,
            "status": self.status,
        }
        
        # Add optional fields
        if self.description:
            event_data["description"] = self.description
        
        if self.location:
            event_data["location"] = self.location
        
        if self.uid:
            event_data["iCalUID"] = self.uid
        
        if self.sequence:
            event_data["sequence"] = self.sequence
        
        # Add date/time information
        if self.all_day:
            # All-day events use date format
            if self.start:
                event_data["start"] = {"date": self.start.date().isoformat()}
            if self.end:
                event_data["end"] = {"date": self.end.date().isoformat()}
        else:
            # Timed events use dateTime format
            if self.start:
                start_data = {"dateTime": self.start.isoformat()}
                if self.timezone:
                    start_data["timeZone"] = self.timezone
                event_data["start"] = start_data
            
            if self.end:
                end_data = {"dateTime": self.end.isoformat()}
                if self.timezone:
                    end_data["timeZone"] = self.timezone
                event_data["end"] = end_data
        
        # Add recurrence rules
        if self.recurrence:
            event_data["recurrence"] = self.recurrence
        
        return event_data
    
    @classmethod
    def from_google_api(cls, api_data: Dict[str, Any]) -> 'GoogleCalendarEvent':
        """Create GoogleCalendarEvent from Google Calendar API response."""
        try:
            # Extract basic fields
            event_id = api_data.get("id")
            uid = api_data.get("iCalUID")
            summary = api_data.get("summary", "")
            description = api_data.get("description")
            location = api_data.get("location")
            status = api_data.get("status", "confirmed")
            sequence = api_data.get("sequence", 0)
            
            # Extract date/time fields
            start_data = api_data.get("start", {})
            end_data = api_data.get("end", {})
            
            # Determine if all-day event
            all_day = "date" in start_data
            
            start_dt = None
            end_dt = None
            timezone = None
            
            if all_day:
                # All-day event
                if start_data.get("date"):
                    start_dt = date_parser.parse(start_data["date"]).date()
                if end_data.get("date"):
                    end_dt = date_parser.parse(end_data["date"]).date()
            else:
                # Timed event
                if start_data.get("dateTime"):
                    start_dt = date_parser.parse(start_data["dateTime"])
                    timezone = start_data.get("timeZone") or (str(start_dt.tzinfo) if start_dt.tzinfo else None)
                if end_data.get("dateTime"):
                    end_dt = date_parser.parse(end_data["dateTime"])
            
            # Extract recurrence
            recurrence = api_data.get("recurrence")
            recurring_event_id = api_data.get("recurringEventId")
            
            # Extract metadata
            updated = None
            if api_data.get("updated"):
                updated = date_parser.parse(api_data["updated"])
            
            created = None
            if api_data.get("created"):
                created = date_parser.parse(api_data["created"])
            
            return cls(
                id=event_id,
                uid=uid,
                summary=summary,
                description=description,
                start=start_dt,
                end=end_dt,
                all_day=all_day,
                timezone=timezone,
                location=location,
                recurrence=recurrence,
                recurring_event_id=recurring_event_id,
                updated=updated,
                created=created,
                sequence=sequence,
                status=status,
                raw_data=api_data
            )
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to parse Google Calendar event: {e}")
    
    @classmethod
    def from_caldav_event(cls, caldav_event) -> 'GoogleCalendarEvent':
        """Create GoogleCalendarEvent from CalDAVEvent."""
        try:
            # Convert recurrence rule from CalDAV to Google format
            recurrence = None
            if caldav_event.rrule:
                recurrence = [f"RRULE:{caldav_event.rrule}"]
            
            return cls(
                uid=caldav_event.uid,
                summary=caldav_event.summary,
                description=caldav_event.description,
                start=caldav_event.start,
                end=caldav_event.end,
                all_day=caldav_event.all_day,
                timezone=caldav_event.timezone,
                location=caldav_event.location,
                recurrence=recurrence,
                sequence=caldav_event.sequence,
            )
            
        except Exception as e:
            raise EventNormalizationError(f"Failed to convert CalDAV event to Google format: {e}")


@dataclass
class GoogleCalendar:
    """Google Calendar information."""
    
    id: str  # Calendar ID
    summary: str  # Calendar name/title
    description: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    color_id: Optional[str] = None
    background_color: Optional[str] = None
    foreground_color: Optional[str] = None
    access_role: Optional[str] = None  # owner, reader, writer, etc.
    primary: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert calendar to dictionary representation."""
        return {
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "timezone": self.timezone,
            "color_id": self.color_id,
            "background_color": self.background_color,
            "foreground_color": self.foreground_color,
            "access_role": self.access_role,
            "primary": self.primary,
        }
    
    @classmethod
    def from_google_api(cls, api_data: Dict[str, Any]) -> 'GoogleCalendar':
        """Create GoogleCalendar from Google Calendar API response."""
        return cls(
            id=api_data.get("id", ""),
            summary=api_data.get("summary", ""),
            description=api_data.get("description"),
            location=api_data.get("location"),
            timezone=api_data.get("timeZone"),
            color_id=api_data.get("colorId"),
            background_color=api_data.get("backgroundColor"),
            foreground_color=api_data.get("foregroundColor"),
            access_role=api_data.get("accessRole"),
            primary=api_data.get("primary", False),
        )
