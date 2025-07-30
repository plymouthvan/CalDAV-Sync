"""
Sync operation API endpoints.

Handles manual sync triggers, sync status monitoring,
and sync history management.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db, CalendarMapping, SyncLog
from app.sync.scheduler import get_sync_scheduler
from app.sync.engine import get_sync_engine
from app.api.models import (
    SyncTriggerRequest, SyncResultResponse, SyncStatusResponse,
    SyncDirection, SyncStatus, ErrorResponse
)
from app.auth.security import require_api_key_unless_localhost, check_rate_limit
from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger("api.sync")
router = APIRouter(prefix="/sync", tags=["Sync Operations"])


@router.post("/trigger")
async def trigger_manual_sync(
    request: Request,
    sync_request: SyncTriggerRequest = SyncTriggerRequest(),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Trigger manual sync for specified mappings or all enabled mappings."""
    try:
        scheduler = get_sync_scheduler()
        
        if sync_request.mapping_ids:
            # Trigger sync for specific mappings
            triggered_count = 0
            failed_mappings = []
            
            for mapping_id in sync_request.mapping_ids:
                # Verify mapping exists and is enabled
                mapping = db.query(CalendarMapping).filter(
                    CalendarMapping.id == mapping_id
                ).first()
                
                if not mapping:
                    failed_mappings.append({
                        "mapping_id": mapping_id,
                        "error": "Mapping not found"
                    })
                    continue
                
                if not mapping.enabled:
                    failed_mappings.append({
                        "mapping_id": mapping_id,
                        "error": "Mapping is disabled"
                    })
                    continue
                
                success = await scheduler.trigger_manual_sync(mapping_id)
                if success:
                    triggered_count += 1
                else:
                    failed_mappings.append({
                        "mapping_id": mapping_id,
                        "error": "Sync already running"
                    })
            
            return {
                "message": f"Triggered sync for {triggered_count} mappings",
                "triggered_count": triggered_count,
                "failed_mappings": failed_mappings,
                "triggered_at": datetime.utcnow().isoformat()
            }
        
        else:
            # Trigger sync for all enabled mappings
            triggered_count = await scheduler.trigger_manual_sync_all()
            
            return {
                "message": f"Triggered sync for {triggered_count} enabled mappings",
                "triggered_count": triggered_count,
                "triggered_at": datetime.utcnow().isoformat()
            }
        
    except Exception as e:
        logger.error(f"Failed to trigger manual sync: {e}")
        raise HTTPException(status_code=500, detail="Failed to trigger sync")


@router.get("/status")
async def get_sync_status(
    request: Request,
    mapping_id: Optional[str] = Query(None, description="Get status for specific mapping"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get sync status for all mappings or a specific mapping."""
    try:
        scheduler = get_sync_scheduler()
        
        if mapping_id:
            # Get status for specific mapping
            mapping = db.query(CalendarMapping).filter(
                CalendarMapping.id == mapping_id
            ).first()
            
            if not mapping:
                raise HTTPException(status_code=404, detail="Calendar mapping not found")
            
            job_status = scheduler.get_job_status(mapping_id)
            
            return SyncStatusResponse(
                mapping_id=mapping_id,
                scheduled=job_status["scheduled"],
                next_run=datetime.fromisoformat(job_status["next_run"]) if job_status["next_run"] else None,
                running=job_status["running"],
                last_run=datetime.fromisoformat(job_status["last_run"]) if job_status["last_run"] else None,
                last_sync_status=SyncStatus(mapping.last_sync_status) if mapping.last_sync_status else None
            )
        
        else:
            # Get status for all mappings
            all_job_status = scheduler.get_all_job_status()
            mappings = db.query(CalendarMapping).all()
            
            status_list = []
            for mapping in mappings:
                job_status = all_job_status.get(mapping.id, {
                    "scheduled": False,
                    "next_run": None,
                    "running": False,
                    "last_run": None
                })
                
                status_list.append(SyncStatusResponse(
                    mapping_id=mapping.id,
                    scheduled=job_status["scheduled"],
                    next_run=datetime.fromisoformat(job_status["next_run"]) if job_status["next_run"] else None,
                    running=job_status["running"],
                    last_run=datetime.fromisoformat(job_status["last_run"]) if job_status["last_run"] else None,
                    last_sync_status=SyncStatus(mapping.last_sync_status) if mapping.last_sync_status else None
                ))
            
            return status_list
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get sync status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sync status")


@router.get("/history")
async def get_sync_history(
    request: Request,
    mapping_id: Optional[str] = Query(None, description="Filter by mapping ID"),
    status: Optional[SyncStatus] = Query(None, description="Filter by sync status"),
    direction: Optional[SyncDirection] = Query(None, description="Filter by sync direction"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get sync history with optional filtering."""
    try:
        query = db.query(SyncLog)
        
        if mapping_id:
            query = query.filter(SyncLog.mapping_id == mapping_id)
        
        if status:
            query = query.filter(SyncLog.status == status.value)
        
        if direction:
            query = query.filter(SyncLog.direction == direction.value)
        
        # Get total count for pagination
        total_count = query.count()
        
        # Apply pagination and ordering
        sync_logs = query.order_by(SyncLog.started_at.desc()).offset(offset).limit(limit).all()
        
        results = []
        for log in sync_logs:
            results.append(SyncResultResponse(
                mapping_id=log.mapping_id,
                direction=SyncDirection(log.direction),
                status=SyncStatus(log.status),
                inserted_count=log.inserted_count or 0,
                updated_count=log.updated_count or 0,
                deleted_count=log.deleted_count or 0,
                error_count=log.error_count or 0,
                errors=log.error_message.split("; ") if log.error_message else [],
                started_at=log.started_at,
                completed_at=log.completed_at,
                duration_seconds=float(log.duration_seconds) if log.duration_seconds else None
            ))
        
        return {
            "results": results,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(results) < total_count
        }
        
    except Exception as e:
        logger.error(f"Failed to get sync history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sync history")


@router.get("/history/{sync_id}")
async def get_sync_details(
    sync_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get detailed information about a specific sync operation."""
    try:
        sync_log = db.query(SyncLog).filter(SyncLog.id == sync_id).first()
        
        if not sync_log:
            raise HTTPException(status_code=404, detail="Sync log not found")
        
        # Get mapping information
        mapping = db.query(CalendarMapping).filter(
            CalendarMapping.id == sync_log.mapping_id
        ).first()
        
        return {
            "sync_log": SyncResultResponse(
                mapping_id=sync_log.mapping_id,
                direction=SyncDirection(sync_log.direction),
                status=SyncStatus(sync_log.status),
                inserted_count=sync_log.inserted_count or 0,
                updated_count=sync_log.updated_count or 0,
                deleted_count=sync_log.deleted_count or 0,
                error_count=sync_log.error_count or 0,
                errors=sync_log.error_message.split("; ") if sync_log.error_message else [],
                started_at=sync_log.started_at,
                completed_at=sync_log.completed_at,
                duration_seconds=float(sync_log.duration_seconds) if sync_log.duration_seconds else None
            ),
            "mapping": {
                "id": mapping.id,
                "caldav_calendar_name": mapping.caldav_calendar_name,
                "google_calendar_name": mapping.google_calendar_name,
                "sync_direction": mapping.sync_direction,
                "enabled": mapping.enabled
            } if mapping else None,
            "webhook_sent": sync_log.webhook_sent,
            "webhook_status": sync_log.webhook_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get sync details {sync_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sync details")


@router.get("/stats")
async def get_sync_stats(
    request: Request,
    days: int = Query(7, ge=1, le=90, description="Number of days to include in stats"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get sync statistics for the specified time period."""
    try:
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get sync logs in the date range
        sync_logs = db.query(SyncLog).filter(
            SyncLog.started_at >= start_date,
            SyncLog.started_at <= end_date
        ).all()
        
        # Calculate statistics
        total_syncs = len(sync_logs)
        successful_syncs = len([log for log in sync_logs if log.status == "success"])
        failed_syncs = len([log for log in sync_logs if log.status == "failure"])
        partial_failures = len([log for log in sync_logs if log.status == "partial_failure"])
        
        total_events_inserted = sum(log.inserted_count or 0 for log in sync_logs)
        total_events_updated = sum(log.updated_count or 0 for log in sync_logs)
        total_events_deleted = sum(log.deleted_count or 0 for log in sync_logs)
        total_errors = sum(log.error_count or 0 for log in sync_logs)
        
        # Calculate average duration
        completed_syncs = [log for log in sync_logs if log.duration_seconds is not None]
        avg_duration = sum(log.duration_seconds for log in completed_syncs) / len(completed_syncs) if completed_syncs else 0
        
        # Get stats by direction
        direction_stats = {}
        for direction in ["caldav_to_google", "google_to_caldav", "bidirectional"]:
            direction_logs = [log for log in sync_logs if log.direction == direction]
            direction_stats[direction] = {
                "total_syncs": len(direction_logs),
                "successful_syncs": len([log for log in direction_logs if log.status == "success"]),
                "events_inserted": sum(log.inserted_count or 0 for log in direction_logs),
                "events_updated": sum(log.updated_count or 0 for log in direction_logs),
                "events_deleted": sum(log.deleted_count or 0 for log in direction_logs)
            }
        
        # Get active mappings count
        active_mappings = db.query(CalendarMapping).filter(
            CalendarMapping.enabled == True
        ).count()
        
        return {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days
            },
            "overview": {
                "total_syncs": total_syncs,
                "successful_syncs": successful_syncs,
                "failed_syncs": failed_syncs,
                "partial_failures": partial_failures,
                "success_rate": (successful_syncs / total_syncs * 100) if total_syncs > 0 else 0,
                "average_duration_seconds": round(avg_duration, 2)
            },
            "events": {
                "total_inserted": total_events_inserted,
                "total_updated": total_events_updated,
                "total_deleted": total_events_deleted,
                "total_errors": total_errors
            },
            "by_direction": direction_stats,
            "active_mappings": active_mappings,
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get sync stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sync statistics")


@router.delete("/history")
async def cleanup_sync_history(
    request: Request,
    days_old: int = Query(30, ge=1, le=365, description="Delete sync logs older than this many days"),
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Clean up old sync history records."""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Count records to be deleted
        old_logs = db.query(SyncLog).filter(SyncLog.started_at < cutoff_date)
        count_to_delete = old_logs.count()
        
        # Delete old records
        old_logs.delete()
        db.commit()
        
        logger.info(f"Cleaned up {count_to_delete} sync history records older than {days_old} days")
        
        return {
            "message": f"Deleted {count_to_delete} sync history records",
            "deleted_count": count_to_delete,
            "cutoff_date": cutoff_date.isoformat(),
            "cleaned_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to cleanup sync history: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to cleanup sync history")


@router.get("/scheduler")
async def get_scheduler_status(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get scheduler status and statistics."""
    try:
        scheduler = get_sync_scheduler()
        stats = scheduler.get_scheduler_stats()
        
        return {
            "scheduler": stats,
            "checked_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve scheduler status")


@router.post("/scheduler/cleanup")
async def cleanup_orphaned_jobs(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Clean up orphaned scheduler jobs."""
    try:
        scheduler = get_sync_scheduler()
        await scheduler.cleanup_orphaned_jobs()
        
        return {
            "message": "Orphaned jobs cleanup completed",
            "cleaned_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned jobs: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup orphaned jobs")
