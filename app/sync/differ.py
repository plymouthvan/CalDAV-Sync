"""
Event diffing and conflict resolution for CalDAV Sync Microservice.

Handles bidirectional event comparison, change detection, and conflict resolution
based on last-modified timestamps with fallback to CalDAV source priority.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import pytz

from app.caldav.models import CalDAVEvent
from app.google.models import GoogleCalendarEvent
from app.database import EventMapping
from app.utils.logging import SyncLogger
from app.utils.exceptions import SyncConflictError


class ChangeAction(Enum):
    """Types of sync actions that can be performed."""
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    NO_CHANGE = "no_change"


class ConflictResolution(Enum):
    """Conflict resolution strategies."""
    CALDAV_WINS = "caldav_wins"
    GOOGLE_WINS = "google_wins"
    SKIP = "skip"


@dataclass
class EventChange:
    """Represents a change to be applied during sync."""
    action: ChangeAction
    event_uid: str
    caldav_event: Optional[CalDAVEvent] = None
    google_event: Optional[GoogleCalendarEvent] = None
    existing_mapping: Optional[EventMapping] = None
    conflict_resolution: Optional[ConflictResolution] = None
    reason: str = ""


@dataclass
class SyncChanges:
    """Collection of changes for a sync operation."""
    caldav_to_google: List[EventChange]
    google_to_caldav: List[EventChange]
    conflicts: List[EventChange]
    
    def get_all_changes(self) -> List[EventChange]:
        """Get all changes combined."""
        return self.caldav_to_google + self.google_to_caldav + self.conflicts


class EventDiffer:
    """Handles event comparison and change detection for bidirectional sync."""
    
    def __init__(self, mapping_id: str, sync_direction: str):
        self.mapping_id = mapping_id
        self.sync_direction = sync_direction
        self.logger = SyncLogger(mapping_id, sync_direction)
    
    def analyze_bidirectional_changes(self, 
                                    caldav_events: List[CalDAVEvent],
                                    google_events: List[GoogleCalendarEvent],
                                    existing_mappings: List[EventMapping]) -> SyncChanges:
        """
        Analyze changes for bidirectional sync.
        
        Args:
            caldav_events: Current CalDAV events
            google_events: Current Google Calendar events
            existing_mappings: Existing event mappings
            
        Returns:
            SyncChanges object with all detected changes
        """
        # Create lookup dictionaries
        caldav_by_uid = {event.uid: event for event in caldav_events}
        google_by_uid = {event.uid: event for event in google_events if event.uid}
        google_by_id = {event.id: event for event in google_events if event.id}
        mappings_by_caldav_uid = {mapping.caldav_uid: mapping for mapping in existing_mappings}
        mappings_by_google_id = {mapping.google_event_id: mapping for mapping in existing_mappings if mapping.google_event_id}
        
        changes = SyncChanges(
            caldav_to_google=[],
            google_to_caldav=[],
            conflicts=[]
        )
        
        processed_uids = set()
        
        # Process CalDAV events
        for caldav_event in caldav_events:
            if caldav_event.uid in processed_uids:
                continue
            
            processed_uids.add(caldav_event.uid)
            
            # Find corresponding Google event and mapping
            google_event = google_by_uid.get(caldav_event.uid)
            mapping = mappings_by_caldav_uid.get(caldav_event.uid)
            
            if mapping and mapping.google_event_id:
                # Also check by Google event ID
                google_event = google_event or google_by_id.get(mapping.google_event_id)
            
            change = self._analyze_event_pair(caldav_event, google_event, mapping)
            if change:
                if change.conflict_resolution:
                    changes.conflicts.append(change)
                elif change.action != ChangeAction.NO_CHANGE:
                    if self._should_sync_to_google(change):
                        changes.caldav_to_google.append(change)
                    elif self._should_sync_to_caldav(change):
                        changes.google_to_caldav.append(change)
        
        # Process Google events that don't have CalDAV counterparts
        for google_event in google_events:
            if not google_event.uid or google_event.uid in processed_uids:
                continue
            
            processed_uids.add(google_event.uid)
            
            # Find mapping by Google event ID
            mapping = mappings_by_google_id.get(google_event.id) if google_event.id else None
            
            change = self._analyze_event_pair(None, google_event, mapping)
            if change and change.action != ChangeAction.NO_CHANGE:
                if self._should_sync_to_caldav(change):
                    changes.google_to_caldav.append(change)
        
        # Process orphaned mappings (events that no longer exist in either system)
        for mapping in existing_mappings:
            if mapping.caldav_uid not in processed_uids:
                # This mapping points to events that no longer exist
                change = EventChange(
                    action=ChangeAction.DELETE,
                    event_uid=mapping.caldav_uid,
                    existing_mapping=mapping,
                    reason="Event no longer exists in either system"
                )
                changes.caldav_to_google.append(change)
        
        return changes
    
    def analyze_unidirectional_changes(self,
                                     source_events: List[Union[CalDAVEvent, GoogleCalendarEvent]],
                                     target_events: List[Union[CalDAVEvent, GoogleCalendarEvent]],
                                     existing_mappings: List[EventMapping],
                                     direction: str) -> List[EventChange]:
        """
        Analyze changes for unidirectional sync.
        
        Args:
            source_events: Events from source system
            target_events: Events from target system
            existing_mappings: Existing event mappings
            direction: Sync direction ('caldav_to_google' or 'google_to_caldav')
            
        Returns:
            List of changes to apply
        """
        changes = []
        
        # Create lookup dictionaries
        source_by_uid = {}
        target_by_uid = {}
        
        for event in source_events:
            uid = event.uid if hasattr(event, 'uid') else event.id
            if uid:
                source_by_uid[uid] = event
        
        for event in target_events:
            uid = event.uid if hasattr(event, 'uid') else event.id
            if uid:
                target_by_uid[uid] = event
        
        mappings_by_uid = {mapping.caldav_uid: mapping for mapping in existing_mappings}
        
        # Process source events
        for source_event in source_events:
            source_uid = source_event.uid if hasattr(source_event, 'uid') else source_event.id
            if not source_uid:
                continue
            
            target_event = target_by_uid.get(source_uid)
            mapping = mappings_by_uid.get(source_uid)
            
            if direction == 'caldav_to_google':
                change = self._analyze_caldav_to_google_change(source_event, target_event, mapping)
            else:
                change = self._analyze_google_to_caldav_change(source_event, target_event, mapping)
            
            if change and change.action != ChangeAction.NO_CHANGE:
                changes.append(change)
        
        # Process target events that don't exist in source (deletions)
        for target_event in target_events:
            target_uid = target_event.uid if hasattr(target_event, 'uid') else target_event.id
            if not target_uid:
                continue
            
            if target_uid not in source_by_uid:
                mapping = mappings_by_uid.get(target_uid)
                if mapping:  # Only delete if we have a mapping (we created this event)
                    change = EventChange(
                        action=ChangeAction.DELETE,
                        event_uid=target_uid,
                        existing_mapping=mapping,
                        reason="Event deleted from source"
                    )
                    changes.append(change)
        
        return changes
    
    def _analyze_event_pair(self, 
                           caldav_event: Optional[CalDAVEvent],
                           google_event: Optional[GoogleCalendarEvent],
                           mapping: Optional[EventMapping]) -> Optional[EventChange]:
        """Analyze a pair of events and determine what action is needed."""
        
        if not caldav_event and not google_event:
            return None
        
        event_uid = (caldav_event.uid if caldav_event else 
                    google_event.uid if google_event else 
                    mapping.caldav_uid if mapping else "unknown")
        
        # Case 1: Only CalDAV event exists
        if caldav_event and not google_event:
            return EventChange(
                action=ChangeAction.INSERT,
                event_uid=event_uid,
                caldav_event=caldav_event,
                existing_mapping=mapping,
                reason="New CalDAV event"
            )
        
        # Case 2: Only Google event exists
        if google_event and not caldav_event:
            return EventChange(
                action=ChangeAction.INSERT,
                event_uid=event_uid,
                google_event=google_event,
                existing_mapping=mapping,
                reason="New Google event"
            )
        
        # Case 3: Both events exist - check for changes and conflicts
        if caldav_event and google_event:
            return self._analyze_conflict_or_update(caldav_event, google_event, mapping)
        
        return None
    
    def _analyze_conflict_or_update(self,
                                  caldav_event: CalDAVEvent,
                                  google_event: GoogleCalendarEvent,
                                  mapping: Optional[EventMapping]) -> Optional[EventChange]:
        """Analyze two existing events for conflicts or updates."""
        
        # Check if events have been modified since last sync
        caldav_modified = caldav_event.last_modified
        google_modified = google_event.updated
        
        last_caldav_sync = mapping.last_caldav_modified if mapping else None
        last_google_sync = mapping.last_google_updated if mapping else None
        
        # Normalize datetime objects to ensure timezone awareness before comparison
        def normalize_datetime(dt):
            """Ensure datetime is timezone-aware (assume UTC if naive)."""
            if dt and isinstance(dt, datetime) and dt.tzinfo is None:
                return pytz.UTC.localize(dt)
            return dt
        
        # Normalize all datetime objects including those from database
        caldav_modified = normalize_datetime(caldav_modified)
        google_modified = normalize_datetime(google_modified)
        last_caldav_sync = normalize_datetime(last_caldav_sync)
        last_google_sync = normalize_datetime(last_google_sync)
        
        # Add diagnostic logging for datetime comparison issue
        self.logger.info(f"DATETIME DEBUG for UID {caldav_event.uid}:")
        self.logger.info(f"  caldav_modified: {caldav_modified} (type: {type(caldav_modified)}, tzinfo: {getattr(caldav_modified, 'tzinfo', None)})")
        self.logger.info(f"  google_modified: {google_modified} (type: {type(google_modified)}, tzinfo: {getattr(google_modified, 'tzinfo', None)})")
        self.logger.info(f"  last_caldav_sync: {last_caldav_sync} (type: {type(last_caldav_sync)}, tzinfo: {getattr(last_caldav_sync, 'tzinfo', None)})")
        self.logger.info(f"  last_google_sync: {last_google_sync} (type: {type(last_google_sync)}, tzinfo: {getattr(last_google_sync, 'tzinfo', None)})")
        
        # Add change detection debugging
        self.logger.info(f"CHANGE DETECTION DEBUG for UID {caldav_event.uid}:")
        
        try:
            caldav_has_changes = (not last_caldav_sync or
                                 (caldav_modified and caldav_modified > last_caldav_sync))
            self.logger.info(f"  caldav_has_changes: {caldav_has_changes} (no last_sync: {not last_caldav_sync}, modified_newer: {caldav_modified and caldav_modified > last_caldav_sync if last_caldav_sync else 'N/A'})")
        except TypeError as e:
            self.logger.error(f"DATETIME COMPARISON ERROR (CalDAV): {e}")
            self.logger.error(f"  Comparing: {caldav_modified} > {last_caldav_sync}")
            raise
            
        try:
            google_has_changes = (not last_google_sync or
                                 (google_modified and google_modified > last_google_sync))
            self.logger.info(f"  google_has_changes: {google_has_changes} (no last_sync: {not last_google_sync}, modified_newer: {google_modified and google_modified > last_google_sync if last_google_sync else 'N/A'})")
        except TypeError as e:
            self.logger.error(f"DATETIME COMPARISON ERROR (Google): {e}")
            self.logger.error(f"  Comparing: {google_modified} > {last_google_sync}")
            raise
        
        # Check content changes as fallback
        if not caldav_has_changes and not google_has_changes:
            caldav_hash = caldav_event.get_content_hash()
            google_hash = google_event.get_content_hash()
            mapping_hash = mapping.event_hash if mapping else None
            
            if mapping_hash:
                caldav_has_changes = caldav_hash != mapping_hash
                google_has_changes = google_hash != mapping_hash
            else:
                caldav_has_changes = caldav_hash != google_hash
        
        # No changes detected
        if not caldav_has_changes and not google_has_changes:
            self.logger.info(f"  DECISION: NO_CHANGE - No changes detected")
            return EventChange(
                action=ChangeAction.NO_CHANGE,
                event_uid=caldav_event.uid,
                caldav_event=caldav_event,
                google_event=google_event,
                existing_mapping=mapping,
                reason="No changes detected"
            )
        
        # Only one side has changes
        if caldav_has_changes and not google_has_changes:
            self.logger.info(f"  DECISION: UPDATE - CalDAV event updated")
            return EventChange(
                action=ChangeAction.UPDATE,
                event_uid=caldav_event.uid,
                caldav_event=caldav_event,
                google_event=google_event,
                existing_mapping=mapping,
                reason="CalDAV event updated"
            )
        
        if google_has_changes and not caldav_has_changes:
            self.logger.info(f"  DECISION: UPDATE - Google event updated")
            return EventChange(
                action=ChangeAction.UPDATE,
                event_uid=caldav_event.uid,
                caldav_event=caldav_event,
                google_event=google_event,
                existing_mapping=mapping,
                reason="Google event updated"
            )
        
        # Both sides have changes - conflict resolution needed
        self.logger.info(f"  DECISION: CONFLICT - Both events modified")
        resolution = self._resolve_conflict(caldav_event, google_event, mapping)
        
        return EventChange(
            action=ChangeAction.UPDATE,
            event_uid=caldav_event.uid,
            caldav_event=caldav_event,
            google_event=google_event,
            existing_mapping=mapping,
            conflict_resolution=resolution,
            reason="Conflict detected - both events modified"
        )
    
    def _resolve_conflict(self,
                         caldav_event: CalDAVEvent,
                         google_event: GoogleCalendarEvent,
                         mapping: Optional[EventMapping]) -> ConflictResolution:
        """
        Resolve conflicts between CalDAV and Google events.
        
        Uses lastModified vs updated timestamps, with CalDAV winning ties.
        """
        caldav_modified = caldav_event.last_modified
        google_modified = google_event.updated
        
        # Normalize datetime objects to ensure timezone awareness before comparison
        def normalize_datetime(dt):
            """Ensure datetime is timezone-aware (assume UTC if naive)."""
            if dt and isinstance(dt, datetime) and dt.tzinfo is None:
                return pytz.UTC.localize(dt)
            return dt
        
        caldav_modified = normalize_datetime(caldav_modified)
        google_modified = normalize_datetime(google_modified)
        
        # Add diagnostic logging for datetime comparison issue
        self.logger.info(f"CONFLICT RESOLUTION DEBUG for UID {caldav_event.uid}:")
        self.logger.info(f"  caldav_modified: {caldav_modified} (type: {type(caldav_modified)}, tzinfo: {getattr(caldav_modified, 'tzinfo', None)})")
        self.logger.info(f"  google_modified: {google_modified} (type: {type(google_modified)}, tzinfo: {getattr(google_modified, 'tzinfo', None)})")
        
        # Log conflict for debugging
        reason = ""
        
        if caldav_modified and google_modified:
            try:
                if caldav_modified > google_modified:
                    reason = f"CalDAV more recent ({caldav_modified} > {google_modified})"
                    resolution = ConflictResolution.CALDAV_WINS
                elif google_modified > caldav_modified:
                    reason = f"Google more recent ({google_modified} > {caldav_modified})"
                    resolution = ConflictResolution.GOOGLE_WINS
                else:
                    reason = f"Equal timestamps ({caldav_modified} = {google_modified}), CalDAV wins"
                    resolution = ConflictResolution.CALDAV_WINS
            except TypeError as e:
                self.logger.error(f"DATETIME COMPARISON ERROR in conflict resolution: {e}")
                self.logger.error(f"  caldav_modified: {caldav_modified} (tzinfo: {getattr(caldav_modified, 'tzinfo', None)})")
                self.logger.error(f"  google_modified: {google_modified} (tzinfo: {getattr(google_modified, 'tzinfo', None)})")
                raise
        elif caldav_modified:
            reason = f"Only CalDAV has timestamp ({caldav_modified})"
            resolution = ConflictResolution.CALDAV_WINS
        elif google_modified:
            reason = f"Only Google has timestamp ({google_modified})"
            resolution = ConflictResolution.GOOGLE_WINS
        else:
            reason = "No timestamps available, CalDAV wins by default"
            resolution = ConflictResolution.CALDAV_WINS
            # Log warning for missing timestamps as requested
            self.logger.warning(
                f"Conflict resolution fallback: both events missing timestamps "
                f"for UID {caldav_event.uid}, defaulting to CalDAV source"
            )
        
        self.logger.log_conflict_resolution(caldav_event.uid, resolution.value, reason)
        
        return resolution
    
    def _analyze_caldav_to_google_change(self,
                                       caldav_event: CalDAVEvent,
                                       google_event: Optional[GoogleCalendarEvent],
                                       mapping: Optional[EventMapping]) -> Optional[EventChange]:
        """Analyze change for CalDAV to Google sync."""
        
        if not google_event:
            return EventChange(
                action=ChangeAction.INSERT,
                event_uid=caldav_event.uid,
                caldav_event=caldav_event,
                existing_mapping=mapping,
                reason="New CalDAV event to sync to Google"
            )
        
        # Check if CalDAV event has been modified
        if mapping and mapping.last_caldav_modified and caldav_event.last_modified:
            # Normalize database datetime
            last_caldav_modified = mapping.last_caldav_modified
            if last_caldav_modified.tzinfo is None:
                last_caldav_modified = pytz.UTC.localize(last_caldav_modified)
            if caldav_event.last_modified <= last_caldav_modified:
                return EventChange(
                    action=ChangeAction.NO_CHANGE,
                    event_uid=caldav_event.uid,
                    caldav_event=caldav_event,
                    google_event=google_event,
                    existing_mapping=mapping,
                    reason="No changes in CalDAV event"
                )
        
        # Check content hash as fallback
        caldav_hash = caldav_event.get_content_hash()
        if mapping and mapping.event_hash == caldav_hash:
            return EventChange(
                action=ChangeAction.NO_CHANGE,
                event_uid=caldav_event.uid,
                caldav_event=caldav_event,
                google_event=google_event,
                existing_mapping=mapping,
                reason="No content changes detected"
            )
        
        return EventChange(
            action=ChangeAction.UPDATE,
            event_uid=caldav_event.uid,
            caldav_event=caldav_event,
            google_event=google_event,
            existing_mapping=mapping,
            reason="CalDAV event updated"
        )
    
    def _analyze_google_to_caldav_change(self,
                                       google_event: GoogleCalendarEvent,
                                       caldav_event: Optional[CalDAVEvent],
                                       mapping: Optional[EventMapping]) -> Optional[EventChange]:
        """Analyze change for Google to CalDAV sync."""
        
        if not caldav_event:
            return EventChange(
                action=ChangeAction.INSERT,
                event_uid=google_event.uid or google_event.id,
                google_event=google_event,
                existing_mapping=mapping,
                reason="New Google event to sync to CalDAV"
            )
        
        # Check if Google event has been modified
        if mapping and mapping.last_google_updated and google_event.updated:
            # Normalize database datetime
            last_google_updated = mapping.last_google_updated
            if last_google_updated.tzinfo is None:
                last_google_updated = pytz.UTC.localize(last_google_updated)
            if google_event.updated <= last_google_updated:
                return EventChange(
                    action=ChangeAction.NO_CHANGE,
                    event_uid=google_event.uid or google_event.id,
                    caldav_event=caldav_event,
                    google_event=google_event,
                    existing_mapping=mapping,
                    reason="No changes in Google event"
                )
        
        # Check content hash as fallback
        google_hash = google_event.get_content_hash()
        if mapping and mapping.event_hash == google_hash:
            return EventChange(
                action=ChangeAction.NO_CHANGE,
                event_uid=google_event.uid or google_event.id,
                caldav_event=caldav_event,
                google_event=google_event,
                existing_mapping=mapping,
                reason="No content changes detected"
            )
        
        return EventChange(
            action=ChangeAction.UPDATE,
            event_uid=google_event.uid or google_event.id,
            caldav_event=caldav_event,
            google_event=google_event,
            existing_mapping=mapping,
            reason="Google event updated"
        )
    
    def _should_sync_to_google(self, change: EventChange) -> bool:
        """Determine if change should be synced to Google."""
        if self.sync_direction == "google_to_caldav":
            return False
        
        if change.conflict_resolution == ConflictResolution.CALDAV_WINS:
            return True
        
        if change.conflict_resolution == ConflictResolution.GOOGLE_WINS:
            return False
        
        # For non-conflict changes, sync based on direction
        return self.sync_direction in ["caldav_to_google", "bidirectional"]
    
    def _should_sync_to_caldav(self, change: EventChange) -> bool:
        """Determine if change should be synced to CalDAV."""
        if self.sync_direction == "caldav_to_google":
            return False
        
        if change.conflict_resolution == ConflictResolution.GOOGLE_WINS:
            return True
        
        if change.conflict_resolution == ConflictResolution.CALDAV_WINS:
            return False
        
        # For non-conflict changes, sync based on direction
        return self.sync_direction in ["google_to_caldav", "bidirectional"]


class ConflictResolver:
    """Handles conflict resolution between CalDAV and Google Calendar events."""
    
    def __init__(self):
        self.logger = SyncLogger("conflict_resolver", "bidirectional")
    
    def resolve_conflict(self, caldav_event: CalDAVEvent, google_event: GoogleCalendarEvent, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Resolve conflict between CalDAV and Google Calendar events.
        
        Args:
            caldav_event: CalDAV event
            google_event: Google Calendar event
            changes: List of detected changes
            
        Returns:
            Dictionary with resolution details
        """
        if not changes:
            return {
                'winner': 'none',
                'reason': 'no_changes',
                'action': 'no_action'
            }
        
        caldav_modified = caldav_event.last_modified
        google_modified = google_event.updated
        
        if caldav_modified and google_modified:
            if caldav_modified > google_modified:
                return {
                    'winner': 'caldav',
                    'reason': 'caldav_newer',
                    'action': 'update_google'
                }
            elif google_modified > caldav_modified:
                return {
                    'winner': 'google',
                    'reason': 'google_newer',
                    'action': 'update_caldav'
                }
            else:
                return {
                    'winner': 'caldav',
                    'reason': 'caldav_fallback',
                    'action': 'update_google'
                }
        elif caldav_modified:
            return {
                'winner': 'caldav',
                'reason': 'only_caldav_timestamp',
                'action': 'update_google'
            }
        elif google_modified:
            return {
                'winner': 'google',
                'reason': 'only_google_timestamp',
                'action': 'update_caldav'
            }
        else:
            return {
                'winner': 'caldav',
                'reason': 'caldav_fallback',
                'action': 'update_google'
            }


def create_event_differ(mapping_id: str, sync_direction: str) -> EventDiffer:
    """Create an EventDiffer instance for the given mapping and direction."""
    return EventDiffer(mapping_id, sync_direction)
