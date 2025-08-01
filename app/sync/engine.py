"""
Main sync engine for CalDAV Sync Microservice.

Orchestrates the complete sync process including event fetching, comparison,
conflict resolution, and applying changes with webhook notifications.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import pytz

from app.database import (
    CalendarMapping, EventMapping, SyncLog, CalDAVAccount as DBCalDAVAccount,
    get_db
)
from app.caldav.client import CalDAVClientFactory
from app.caldav.models import CalDAVAccount, CalDAVEvent
from app.google.client import get_google_client
from app.google.models import GoogleCalendarEvent
from app.sync.normalizer import get_event_normalizer
from app.sync.differ import create_event_differ, ChangeAction, ConflictResolution
from app.sync.webhook import get_webhook_client
from app.config import get_settings
from app.utils.logging import SyncLogger
from app.utils.exceptions import (
    SyncError, SyncMappingError, CalDAVError, GoogleCalendarError,
    handle_caldav_exception, handle_google_exception
)


@dataclass
class SyncResult:
    """Result of a sync operation."""
    mapping_id: str
    direction: str
    status: str  # success, partial_failure, failure
    inserted_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    error_count: int = 0
    errors: List[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    
    # Enhanced sync details for richer UI display
    event_summaries: List[str] = None  # List of event titles that changed
    change_summary: Optional[str] = None  # Human-readable summary
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.event_summaries is None:
            self.event_summaries = []


class SyncEngine:
    """Main sync engine that orchestrates calendar synchronization."""
    
    def __init__(self):
        self.settings = get_settings()
        self.google_client = get_google_client()
        self.webhook_client = get_webhook_client()
        self.normalizer = get_event_normalizer()
    
    async def sync_mapping(self, mapping: CalendarMapping) -> SyncResult:
        """
        Execute sync for a single calendar mapping.
        
        Args:
            mapping: Calendar mapping configuration
            
        Returns:
            SyncResult with operation details
        """
        logger = SyncLogger(mapping.id, mapping.sync_direction)
        
        start_time = datetime.utcnow()
        # Ensure timezone awareness
        if start_time.tzinfo is None:
            start_time = pytz.UTC.localize(start_time)
        logger.info(f"SYNC ENGINE DATETIME DEBUG: started_at={start_time} (tzinfo: {start_time.tzinfo})")
        
        result = SyncResult(
            mapping_id=mapping.id,
            direction=mapping.sync_direction,
            status="failure",
            started_at=start_time
        )
        
        # Create sync log record
        sync_log = SyncLog(
            mapping_id=mapping.id,
            direction=mapping.sync_direction,
            status="running",
            started_at=result.started_at
        )
        
        try:
            with next(get_db()) as db:
                db.add(sync_log)
                db.commit()
                db.refresh(sync_log)
            
            logger.log_sync_start(mapping.caldav_calendar_name, mapping.google_calendar_name)
            
            # Execute sync based on direction
            if mapping.sync_direction == "caldav_to_google":
                await self._sync_caldav_to_google(mapping, result, logger)
            elif mapping.sync_direction == "google_to_caldav":
                await self._sync_google_to_caldav(mapping, result, logger)
            elif mapping.sync_direction == "bidirectional":
                await self._sync_bidirectional(mapping, result, logger)
            else:
                raise SyncMappingError(f"Unknown sync direction: {mapping.sync_direction}")
            
            # Determine final status
            if result.error_count == 0:
                result.status = "success"
            elif result.inserted_count + result.updated_count + result.deleted_count > 0:
                result.status = "partial_failure"
            else:
                result.status = "failure"
            
            result.completed_at = datetime.utcnow()
            # Ensure timezone awareness
            if result.completed_at.tzinfo is None:
                result.completed_at = pytz.UTC.localize(result.completed_at)
            logger.info(f"SYNC ENGINE DATETIME DEBUG: completed_at={result.completed_at} (tzinfo: {result.completed_at.tzinfo})")
            result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
            
            # Generate human-readable change summary
            result.change_summary = self._generate_change_summary(result)
            
            logger.log_sync_complete(
                result.inserted_count,
                result.updated_count,
                result.deleted_count,
                result.error_count
            )
            
        except Exception as e:
            result.status = "failure"
            result.errors.append(str(e))
            result.completed_at = datetime.utcnow()
            # Ensure timezone awareness
            if result.completed_at.tzinfo is None:
                result.completed_at = pytz.UTC.localize(result.completed_at)
            result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
            
            logger.error(f"Sync failed: {e}")
        
        finally:
            # Update sync log
            with next(get_db()) as db:
                # Re-fetch the sync log to ensure it's attached to this session
                db_sync_log = db.query(SyncLog).filter(SyncLog.id == sync_log.id).first()
                if db_sync_log:
                    db_sync_log.status = result.status
                    db_sync_log.inserted_count = result.inserted_count
                    db_sync_log.updated_count = result.updated_count
                    db_sync_log.deleted_count = result.deleted_count
                    db_sync_log.error_count = result.error_count
                    db_sync_log.error_message = "; ".join(result.errors) if result.errors else None
                    db_sync_log.completed_at = result.completed_at
                    db_sync_log.duration_seconds = int(result.duration_seconds) if result.duration_seconds else None
                    
                    # Store enhanced sync details
                    if result.event_summaries:
                        import json
                        db_sync_log.event_summaries = json.dumps(result.event_summaries)
                    db_sync_log.change_summary = result.change_summary
                
                # Re-fetch the mapping to ensure it's attached to this session
                db_mapping = db.query(CalendarMapping).filter(CalendarMapping.id == mapping.id).first()
                if db_mapping:
                    db_mapping.last_sync_at = result.completed_at
                    db_mapping.last_sync_status = result.status
                
                db.commit()
            
            # Send webhook notification
            try:
                await self.webhook_client.send_sync_result_webhook(mapping, sync_log)
            except Exception as e:
                logger.warning(f"Webhook delivery failed: {e}")
        
        return result
    
    async def _sync_caldav_to_google(self, mapping: CalendarMapping, result: SyncResult, logger: SyncLogger):
        """Execute CalDAV to Google sync."""
        # Get CalDAV account and create client
        with next(get_db()) as db:
            db_account = db.query(DBCalDAVAccount).filter(
                DBCalDAVAccount.id == mapping.caldav_account_id
            ).first()
            
            if not db_account:
                raise SyncMappingError(f"CalDAV account {mapping.caldav_account_id} not found")
        
        account = CalDAVAccount(
            name=db_account.name,
            username=db_account.username,
            base_url=db_account.base_url,
            verify_ssl=db_account.verify_ssl
        )
        
        password = db_account.get_password(self.settings.security.encryption_key)
        caldav_client = CalDAVClientFactory.create_client(account, password)
        
        # Fetch events from both systems
        caldav_events = caldav_client.get_events_by_sync_window(
            mapping.caldav_calendar_id,
            mapping.sync_window_days
        )
        
        google_events = self.google_client.get_events_by_sync_window(
            mapping.google_calendar_id,
            mapping.sync_window_days
        )
        
        # Get existing mappings
        with next(get_db()) as db:
            existing_mappings = db.query(EventMapping).filter(
                EventMapping.mapping_id == mapping.id
            ).all()
        
        # Analyze changes
        differ = create_event_differ(mapping.id, mapping.sync_direction)
        changes = differ.analyze_unidirectional_changes(
            caldav_events, google_events, existing_mappings, "caldav_to_google"
        )
        
        # Apply changes
        await self._apply_changes_to_google(mapping, changes, result, logger)
    
    async def _sync_google_to_caldav(self, mapping: CalendarMapping, result: SyncResult, logger: SyncLogger):
        """Execute Google to CalDAV sync."""
        # Get CalDAV account and create client
        with next(get_db()) as db:
            db_account = db.query(DBCalDAVAccount).filter(
                DBCalDAVAccount.id == mapping.caldav_account_id
            ).first()
            
            if not db_account:
                raise SyncMappingError(f"CalDAV account {mapping.caldav_account_id} not found")
        
        account = CalDAVAccount(
            name=db_account.name,
            username=db_account.username,
            base_url=db_account.base_url,
            verify_ssl=db_account.verify_ssl
        )
        
        password = db_account.get_password(self.settings.security.encryption_key)
        caldav_client = CalDAVClientFactory.create_client(account, password)
        
        # Fetch events from both systems
        google_events = self.google_client.get_events_by_sync_window(
            mapping.google_calendar_id,
            mapping.sync_window_days
        )
        
        caldav_events = caldav_client.get_events_by_sync_window(
            mapping.caldav_calendar_id,
            mapping.sync_window_days
        )
        
        # Get existing mappings
        with next(get_db()) as db:
            existing_mappings = db.query(EventMapping).filter(
                EventMapping.mapping_id == mapping.id
            ).all()
        
        # Analyze changes
        differ = create_event_differ(mapping.id, mapping.sync_direction)
        changes = differ.analyze_unidirectional_changes(
            google_events, caldav_events, existing_mappings, "google_to_caldav"
        )
        
        # Apply changes
        await self._apply_changes_to_caldav(mapping, changes, caldav_client, result, logger)
    
    async def _sync_bidirectional(self, mapping: CalendarMapping, result: SyncResult, logger: SyncLogger):
        """Execute bidirectional sync with conflict resolution."""
        # Get CalDAV account and create client
        with next(get_db()) as db:
            db_account = db.query(DBCalDAVAccount).filter(
                DBCalDAVAccount.id == mapping.caldav_account_id
            ).first()
            
            if not db_account:
                raise SyncMappingError(f"CalDAV account {mapping.caldav_account_id} not found")
        
        account = CalDAVAccount(
            name=db_account.name,
            username=db_account.username,
            base_url=db_account.base_url,
            verify_ssl=db_account.verify_ssl
        )
        
        password = db_account.get_password(self.settings.security.encryption_key)
        caldav_client = CalDAVClientFactory.create_client(account, password)
        
        # Fetch events from both systems
        caldav_events = caldav_client.get_events_by_sync_window(
            mapping.caldav_calendar_id,
            mapping.sync_window_days
        )
        
        google_events = self.google_client.get_events_by_sync_window(
            mapping.google_calendar_id,
            mapping.sync_window_days
        )
        
        # Get existing mappings
        with next(get_db()) as db:
            existing_mappings = db.query(EventMapping).filter(
                EventMapping.mapping_id == mapping.id
            ).all()
        
        # Analyze changes with conflict resolution
        differ = create_event_differ(mapping.id, mapping.sync_direction)
        sync_changes = differ.analyze_bidirectional_changes(
            caldav_events, google_events, existing_mappings
        )
        
        # Apply changes to Google Calendar
        if sync_changes.caldav_to_google:
            await self._apply_changes_to_google(mapping, sync_changes.caldav_to_google, result, logger)
        
        # Apply changes to CalDAV
        if sync_changes.google_to_caldav:
            await self._apply_changes_to_caldav(mapping, sync_changes.google_to_caldav, caldav_client, result, logger)
        
        # Handle conflicts
        if sync_changes.conflicts:
            await self._handle_conflicts(mapping, sync_changes.conflicts, caldav_client, result, logger)
    
    async def _apply_changes_to_google(self, mapping: CalendarMapping, changes: List, result: SyncResult, logger: SyncLogger):
        """Apply changes to Google Calendar."""
        for change in changes:
            try:
                if change.action == ChangeAction.INSERT:
                    if change.caldav_event:
                        # Convert CalDAV event to Google format
                        google_event = self.normalizer.caldav_to_google(change.caldav_event)
                        
                        # Create event in Google Calendar
                        created_event = self.google_client.create_event(mapping.google_calendar_id, google_event)
                        
                        # Create or update event mapping
                        await self._update_event_mapping(
                            mapping.id, change.caldav_event.uid, created_event.id,
                            change.caldav_event.last_modified, created_event.updated,
                            "caldav_to_google", change.caldav_event.get_content_hash()
                        )
                        
                        result.inserted_count += 1
                        # Capture event title for summary
                        if change.caldav_event.summary:
                            result.event_summaries.append(change.caldav_event.summary)
                        logger.log_event_change("inserted", change.caldav_event.uid, change.caldav_event.summary)
                
                elif change.action == ChangeAction.UPDATE:
                    if change.caldav_event and change.google_event:
                        # Convert CalDAV event to Google format
                        google_event = self.normalizer.caldav_to_google(change.caldav_event)
                        google_event.id = change.google_event.id  # Preserve Google ID
                        
                        # Update event in Google Calendar
                        updated_event = self.google_client.update_event(mapping.google_calendar_id, google_event)
                        
                        # Update event mapping
                        await self._update_event_mapping(
                            mapping.id, change.caldav_event.uid, updated_event.id,
                            change.caldav_event.last_modified, updated_event.updated,
                            "caldav_to_google", change.caldav_event.get_content_hash()
                        )
                        
                        result.updated_count += 1
                        # Capture event title for summary
                        if change.caldav_event.summary:
                            result.event_summaries.append(change.caldav_event.summary)
                        logger.log_event_change("updated", change.caldav_event.uid, change.caldav_event.summary)
                
                elif change.action == ChangeAction.DELETE:
                    if change.existing_mapping and change.existing_mapping.google_event_id:
                        # Add diagnostic logging for delete operations
                        logger.info(f"SYNC DELETE DEBUG: Attempting to delete Google event {change.existing_mapping.google_event_id} for CalDAV UID {change.event_uid}")
                        logger.info(f"SYNC DELETE DEBUG: Event mapping ID {change.existing_mapping.id}, last sync direction: {change.existing_mapping.sync_direction_last}")
                        
                        # Delete event from Google Calendar
                        self.google_client.delete_event(mapping.google_calendar_id, change.existing_mapping.google_event_id)
                        
                        # Remove event mapping
                        await self._delete_event_mapping(change.existing_mapping.id)
                        
                        result.deleted_count += 1
                        # For deletions, we might not have the event title, so use a placeholder
                        result.event_summaries.append("(Deleted event)")
                        logger.log_event_change("deleted", change.event_uid)
            
            except Exception as e:
                result.error_count += 1
                result.errors.append(f"Failed to apply change for {change.event_uid}: {str(e)}")
                logger.error(f"Failed to apply change for {change.event_uid}: {e}")
    
    async def _apply_changes_to_caldav(self, mapping: CalendarMapping, changes: List, caldav_client, result: SyncResult, logger: SyncLogger):
        """Apply changes to CalDAV calendar."""
        for change in changes:
            try:
                if change.action == ChangeAction.INSERT:
                    if change.google_event:
                        # Convert Google event to CalDAV format
                        caldav_event = self.normalizer.google_to_caldav(change.google_event)
                        
                        # Create event in CalDAV calendar
                        caldav_client.create_event(mapping.caldav_calendar_id, caldav_event)
                        
                        # Create or update event mapping
                        await self._update_event_mapping(
                            mapping.id, caldav_event.uid, change.google_event.id,
                            caldav_event.last_modified, change.google_event.updated,
                            "google_to_caldav", change.google_event.get_content_hash()
                        )
                        
                        result.inserted_count += 1
                        # Capture event title for summary
                        if change.google_event.summary:
                            result.event_summaries.append(change.google_event.summary)
                        logger.log_event_change("inserted", caldav_event.uid, caldav_event.summary)
                
                elif change.action == ChangeAction.UPDATE:
                    if change.google_event and change.caldav_event:
                        # Convert Google event to CalDAV format
                        caldav_event = self.normalizer.google_to_caldav(change.google_event)
                        
                        # Update event in CalDAV calendar
                        caldav_client.update_event(mapping.caldav_calendar_id, caldav_event)
                        
                        # Update event mapping
                        await self._update_event_mapping(
                            mapping.id, caldav_event.uid, change.google_event.id,
                            caldav_event.last_modified, change.google_event.updated,
                            "google_to_caldav", change.google_event.get_content_hash()
                        )
                        
                        result.updated_count += 1
                        # Capture event title for summary
                        if change.google_event.summary:
                            result.event_summaries.append(change.google_event.summary)
                        logger.log_event_change("updated", caldav_event.uid, caldav_event.summary)
                
                elif change.action == ChangeAction.DELETE:
                    if change.existing_mapping:
                        # Delete event from CalDAV calendar
                        caldav_client.delete_event(mapping.caldav_calendar_id, change.existing_mapping.caldav_uid)
                        
                        # Remove event mapping
                        await self._delete_event_mapping(change.existing_mapping.id)
                        
                        result.deleted_count += 1
                        # For deletions, we might not have the event title, so use a placeholder
                        result.event_summaries.append("(Deleted event)")
                        logger.log_event_change("deleted", change.event_uid)
            
            except Exception as e:
                result.error_count += 1
                result.errors.append(f"Failed to apply change for {change.event_uid}: {str(e)}")
                logger.error(f"Failed to apply change for {change.event_uid}: {e}")
    
    async def _handle_conflicts(self, mapping: CalendarMapping, conflicts: List, caldav_client, result: SyncResult, logger: SyncLogger):
        """Handle conflict resolution."""
        for conflict in conflicts:
            try:
                if conflict.conflict_resolution == ConflictResolution.CALDAV_WINS:
                    # Apply CalDAV event to Google
                    if conflict.caldav_event and conflict.google_event:
                        google_event = self.normalizer.caldav_to_google(conflict.caldav_event)
                        google_event.id = conflict.google_event.id
                        
                        updated_event = self.google_client.update_event(mapping.google_calendar_id, google_event)
                        
                        await self._update_event_mapping(
                            mapping.id, conflict.caldav_event.uid, updated_event.id,
                            conflict.caldav_event.last_modified, updated_event.updated,
                            "caldav_to_google", conflict.caldav_event.get_content_hash()
                        )
                        
                        result.updated_count += 1
                        # Capture event title for summary
                        if conflict.caldav_event.summary:
                            result.event_summaries.append(conflict.caldav_event.summary)
                        logger.log_event_change("conflict_resolved_caldav_wins", conflict.caldav_event.uid, conflict.caldav_event.summary)
                
                elif conflict.conflict_resolution == ConflictResolution.GOOGLE_WINS:
                    # Apply Google event to CalDAV
                    if conflict.google_event and conflict.caldav_event:
                        caldav_event = self.normalizer.google_to_caldav(conflict.google_event)
                        
                        caldav_client.update_event(mapping.caldav_calendar_id, caldav_event)
                        
                        await self._update_event_mapping(
                            mapping.id, caldav_event.uid, conflict.google_event.id,
                            caldav_event.last_modified, conflict.google_event.updated,
                            "google_to_caldav", conflict.google_event.get_content_hash()
                        )
                        
                        result.updated_count += 1
                        # Capture event title for summary
                        if conflict.google_event.summary:
                            result.event_summaries.append(conflict.google_event.summary)
                        logger.log_event_change("conflict_resolved_google_wins", caldav_event.uid, caldav_event.summary)
            
            except Exception as e:
                result.error_count += 1
                result.errors.append(f"Failed to resolve conflict for {conflict.event_uid}: {str(e)}")
                logger.error(f"Failed to resolve conflict for {conflict.event_uid}: {e}")
    
    def _generate_change_summary(self, result: SyncResult) -> str:
        """Generate a human-readable summary of sync changes."""
        if not result.event_summaries:
            return None
        
        # Limit the number of event titles shown to avoid overly long summaries
        max_titles = 3
        event_titles = result.event_summaries[:max_titles]
        
        # Create the summary text
        if len(result.event_summaries) <= max_titles:
            summary = f"Synced: {', '.join(event_titles)}"
        else:
            remaining = len(result.event_summaries) - max_titles
            summary = f"Synced: {', '.join(event_titles)} and {remaining} more"
        
        return summary
    
    async def _update_event_mapping(self, mapping_id: str, caldav_uid: str, google_event_id: str,
                                  caldav_modified: Optional[datetime], google_updated: Optional[datetime],
                                  sync_direction: str, event_hash: str):
        """Create or update event mapping record."""
        with next(get_db()) as db:
            # Try to find existing mapping
            existing = db.query(EventMapping).filter(
                EventMapping.mapping_id == mapping_id,
                EventMapping.caldav_uid == caldav_uid
            ).first()
            
            if existing:
                # Update existing mapping
                existing.google_event_id = google_event_id
                existing.last_caldav_modified = caldav_modified
                existing.last_google_updated = google_updated
                existing.sync_direction_last = sync_direction
                existing.event_hash = event_hash
                update_time = datetime.utcnow()
                # Ensure timezone awareness
                if update_time.tzinfo is None:
                    update_time = pytz.UTC.localize(update_time)
                # Note: logger is not available in this scope, using print for debugging
                print(f"EVENT MAPPING DATETIME DEBUG: updated_at={update_time} (tzinfo: {update_time.tzinfo})")
                existing.updated_at = update_time
            else:
                # Create new mapping
                new_mapping = EventMapping(
                    mapping_id=mapping_id,
                    caldav_uid=caldav_uid,
                    google_event_id=google_event_id,
                    last_caldav_modified=caldav_modified,
                    last_google_updated=google_updated,
                    sync_direction_last=sync_direction,
                    event_hash=event_hash
                )
                db.add(new_mapping)
            
            db.commit()
    
    async def _delete_event_mapping(self, mapping_id: str):
        """Delete event mapping record."""
        with next(get_db()) as db:
            mapping = db.query(EventMapping).filter(EventMapping.id == mapping_id).first()
            if mapping:
                db.delete(mapping)
                db.commit()


# Global sync engine instance
sync_engine = SyncEngine()


def get_sync_engine() -> SyncEngine:
    """Get the global sync engine instance."""
    return sync_engine
