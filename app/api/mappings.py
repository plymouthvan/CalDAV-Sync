"""
Calendar mapping management API endpoints.

Handles CRUD operations for calendar mappings and sync configuration.
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session

from app.database import get_db, CalendarMapping, CalDAVAccount
from app.sync.scheduler import get_sync_scheduler
from app.api.models import (
    CalendarMappingCreate, CalendarMappingUpdate, CalendarMappingResponse,
    SyncDirection, SyncStatus, ErrorResponse
)
from app.auth.security import require_api_key_unless_localhost, check_rate_limit
from app.auth.google_oauth import get_oauth_manager
from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger("api.mappings")
router = APIRouter(prefix="/mappings", tags=["Calendar Mappings"])


@router.get("", response_model=List[CalendarMappingResponse])
async def list_calendar_mappings(
    request: Request,
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    sync_direction: Optional[SyncDirection] = Query(None, description="Filter by sync direction"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """List all calendar mappings with optional filtering."""
    try:
        # Join with CalDAV accounts to get account names
        query = db.query(CalendarMapping, CalDAVAccount.name.label('caldav_account_name')).join(
            CalDAVAccount, CalendarMapping.caldav_account_id == CalDAVAccount.id
        )
        
        if enabled is not None:
            query = query.filter(CalendarMapping.enabled == enabled)
        
        if sync_direction is not None:
            query = query.filter(CalendarMapping.sync_direction == sync_direction.value)
        
        results = query.all()
        
        # Build response with account names
        mappings_with_names = []
        for mapping, account_name in results:
            mapping_dict = {
                "id": mapping.id,
                "caldav_account_id": mapping.caldav_account_id,
                "caldav_account_name": account_name,
                "caldav_calendar_id": mapping.caldav_calendar_id,
                "caldav_calendar_name": mapping.caldav_calendar_name,
                "google_calendar_id": mapping.google_calendar_id,
                "google_calendar_name": mapping.google_calendar_name,
                "sync_direction": mapping.sync_direction,
                "sync_window_days": mapping.sync_window_days,
                "sync_interval_minutes": mapping.sync_interval_minutes,
                "webhook_url": mapping.webhook_url,
                "enabled": mapping.enabled,
                "created_at": mapping.created_at,
                "updated_at": mapping.updated_at,
                "last_sync_at": mapping.last_sync_at,
                "last_sync_status": mapping.last_sync_status
            }
            mappings_with_names.append(CalendarMappingResponse(**mapping_dict))
        
        return mappings_with_names
        
    except Exception as e:
        logger.error(f"Failed to list calendar mappings: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve calendar mappings")


@router.post("", response_model=CalendarMappingResponse, status_code=201)
async def create_calendar_mapping(
    mapping_data: CalendarMappingCreate,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Create a new calendar mapping."""
    try:
        # Verify CalDAV account exists
        caldav_account = db.query(CalDAVAccount).filter(
            CalDAVAccount.id == mapping_data.caldav_account_id
        ).first()
        
        if not caldav_account:
            raise HTTPException(
                status_code=400,
                detail=f"CalDAV account {mapping_data.caldav_account_id} not found"
            )
        
        if not caldav_account.enabled:
            raise HTTPException(
                status_code=400,
                detail="CalDAV account is disabled"
            )
        
        # Verify Google authentication
        oauth_manager = get_oauth_manager()
        credentials = oauth_manager.get_valid_credentials()
        if not credentials:
            raise HTTPException(
                status_code=401,
                detail="Google Calendar authentication required"
            )
        
        # Check for duplicate mappings
        existing = db.query(CalendarMapping).filter(
            CalendarMapping.caldav_account_id == mapping_data.caldav_account_id,
            CalendarMapping.caldav_calendar_id == mapping_data.caldav_calendar_id,
            CalendarMapping.google_calendar_id == mapping_data.google_calendar_id
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Calendar mapping already exists for this CalDAV and Google calendar combination"
            )
        
        # Create mapping
        db_mapping = CalendarMapping(
            caldav_account_id=mapping_data.caldav_account_id,
            caldav_calendar_id=mapping_data.caldav_calendar_id,
            caldav_calendar_name=mapping_data.caldav_calendar_name,
            google_calendar_id=mapping_data.google_calendar_id,
            google_calendar_name=mapping_data.google_calendar_name,
            sync_direction=mapping_data.sync_direction.value,
            sync_window_days=mapping_data.sync_window_days,
            sync_interval_minutes=mapping_data.sync_interval_minutes,
            webhook_url=mapping_data.webhook_url,
            enabled=mapping_data.enabled
        )
        
        db.add(db_mapping)
        db.commit()
        db.refresh(db_mapping)
        
        logger.info("=== MAPPING CREATION DEBUG ===")
        logger.info(f"Created mapping ID: {db_mapping.id}")
        logger.info(f"Mapping enabled: {db_mapping.enabled}")
        logger.info(f"Mapping type: {type(db_mapping)}")
        
        # Schedule sync job if enabled
        if db_mapping.enabled:
            try:
                logger.info("Attempting to schedule mapping...")
                scheduler = get_sync_scheduler()
                logger.info(f"Got scheduler: {type(scheduler)}")
                
                # Detach the object from the session to avoid serialization issues
                db.expunge(db_mapping)
                logger.info("Detached mapping from database session")
                
                await scheduler.schedule_mapping(db_mapping)
                logger.info("Successfully scheduled mapping")
                
            except Exception as e:
                logger.error(f"Failed to schedule mapping: {type(e).__name__}: {e}")
                logger.error(f"Error details: {str(e)}")
                # Don't fail the entire operation if scheduling fails
                # The mapping is created, just not scheduled
                logger.warning("Mapping created but not scheduled - manual scheduling may be required")
        
        logger.info(f"Created calendar mapping: {db_mapping.id}")
        return CalendarMappingResponse.from_orm(db_mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create calendar mapping: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create calendar mapping")


@router.get("/{mapping_id}", response_model=CalendarMappingResponse)
async def get_calendar_mapping(
    mapping_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get a specific calendar mapping."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        return CalendarMappingResponse.from_orm(mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get calendar mapping {mapping_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve calendar mapping")


@router.put("/{mapping_id}", response_model=CalendarMappingResponse)
async def update_calendar_mapping(
    mapping_id: str,
    mapping_data: CalendarMappingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Update a calendar mapping."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        # Update fields
        update_data = mapping_data.dict(exclude_unset=True)
        
        for field, value in update_data.items():
            if field == 'sync_direction' and value:
                setattr(mapping, field, value.value)
            else:
                setattr(mapping, field, value)
        
        mapping.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(mapping)
        
        # Reschedule sync job
        scheduler = get_sync_scheduler()
        await scheduler.reschedule_mapping(mapping)
        
        logger.info(f"Updated calendar mapping: {mapping_id}")
        return CalendarMappingResponse.from_orm(mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update calendar mapping {mapping_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update calendar mapping")


@router.delete("/{mapping_id}", status_code=204)
async def delete_calendar_mapping(
    mapping_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Delete a calendar mapping."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        # Unschedule sync job
        scheduler = get_sync_scheduler()
        await scheduler.unschedule_mapping(mapping_id)
        
        # Delete related event mappings
        from app.database import EventMapping
        db.query(EventMapping).filter(
            EventMapping.mapping_id == mapping_id
        ).delete()
        
        # Delete mapping
        db.delete(mapping)
        db.commit()
        
        logger.info(f"Deleted calendar mapping: {mapping_id}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete calendar mapping {mapping_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete calendar mapping")


@router.post("/{mapping_id}/enable", response_model=CalendarMappingResponse)
async def enable_calendar_mapping(
    mapping_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Enable a calendar mapping."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        if mapping.enabled:
            return CalendarMappingResponse.from_orm(mapping)
        
        # Verify CalDAV account is enabled
        caldav_account = db.query(CalDAVAccount).filter(
            CalDAVAccount.id == mapping.caldav_account_id
        ).first()
        
        if not caldav_account or not caldav_account.enabled:
            raise HTTPException(
                status_code=400,
                detail="CalDAV account is disabled"
            )
        
        # Verify Google authentication
        oauth_manager = get_oauth_manager()
        credentials = oauth_manager.get_valid_credentials()
        if not credentials:
            raise HTTPException(
                status_code=401,
                detail="Google Calendar authentication required"
            )
        
        mapping.enabled = True
        mapping.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(mapping)
        
        # Schedule sync job
        scheduler = get_sync_scheduler()
        await scheduler.schedule_mapping(mapping)
        
        logger.info(f"Enabled calendar mapping: {mapping_id}")
        return CalendarMappingResponse.from_orm(mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to enable calendar mapping {mapping_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to enable calendar mapping")


@router.post("/{mapping_id}/disable", response_model=CalendarMappingResponse)
async def disable_calendar_mapping(
    mapping_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Disable a calendar mapping."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        if not mapping.enabled:
            return CalendarMappingResponse.from_orm(mapping)
        
        mapping.enabled = False
        mapping.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(mapping)
        
        # Unschedule sync job
        scheduler = get_sync_scheduler()
        await scheduler.unschedule_mapping(mapping_id)
        
        logger.info(f"Disabled calendar mapping: {mapping_id}")
        return CalendarMappingResponse.from_orm(mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disable calendar mapping {mapping_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to disable calendar mapping")


@router.post("/{mapping_id}/pause", response_model=CalendarMappingResponse)
async def pause_calendar_mapping(
    mapping_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Pause sync for a calendar mapping without disabling it."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        if not mapping.enabled:
            raise HTTPException(status_code=400, detail="Calendar mapping is disabled")
        
        # Pause sync job
        scheduler = get_sync_scheduler()
        await scheduler.pause_mapping(mapping_id)
        
        logger.info(f"Paused calendar mapping: {mapping_id}")
        return CalendarMappingResponse.from_orm(mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause calendar mapping {mapping_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to pause calendar mapping")


@router.post("/{mapping_id}/resume", response_model=CalendarMappingResponse)
async def resume_calendar_mapping(
    mapping_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Resume sync for a paused calendar mapping."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        if not mapping.enabled:
            raise HTTPException(status_code=400, detail="Calendar mapping is disabled")
        
        # Resume sync job
        scheduler = get_sync_scheduler()
        await scheduler.resume_mapping(mapping_id)
        
        logger.info(f"Resumed calendar mapping: {mapping_id}")
        return CalendarMappingResponse.from_orm(mapping)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume calendar mapping {mapping_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to resume calendar mapping")


@router.get("/{mapping_id}/status")
async def get_mapping_status(
    mapping_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get detailed status for a calendar mapping."""
    try:
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == mapping_id
        ).first()
        
        if not mapping:
            raise HTTPException(status_code=404, detail="Calendar mapping not found")
        
        # Get scheduler status
        scheduler = get_sync_scheduler()
        job_status = scheduler.get_job_status(mapping_id)
        
        # Get recent sync logs
        from app.database import SyncLog
        recent_syncs = db.query(SyncLog).filter(
            SyncLog.mapping_id == mapping_id
        ).order_by(SyncLog.started_at.desc()).limit(5).all()
        
        return {
            "mapping_id": mapping_id,
            "enabled": mapping.enabled,
            "sync_direction": mapping.sync_direction,
            "sync_interval_minutes": mapping.sync_interval_minutes,
            "last_sync_at": mapping.last_sync_at.isoformat() if mapping.last_sync_at else None,
            "last_sync_status": mapping.last_sync_status,
            "scheduler": job_status,
            "recent_syncs": [
                {
                    "id": sync.id,
                    "status": sync.status,
                    "started_at": sync.started_at.isoformat(),
                    "completed_at": sync.completed_at.isoformat() if sync.completed_at else None,
                    "inserted_count": sync.inserted_count,
                    "updated_count": sync.updated_count,
                    "deleted_count": sync.deleted_count,
                    "error_count": sync.error_count
                }
                for sync in recent_syncs
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get mapping status {mapping_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve mapping status")
