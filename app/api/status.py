"""
System status and health check API endpoints.

Provides health checks, system status, and monitoring information.
"""

from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db, CalendarMapping, SyncLog
from app.sync.scheduler import get_sync_scheduler
from app.sync.webhook import get_webhook_client
from app.auth.google_oauth import get_oauth_manager
from app.api.models import HealthCheckResponse, SystemStatusResponse
from app.auth.security import optional_api_key_auth, check_rate_limit
from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger("api.status")
router = APIRouter(tags=["System Status"])


@router.get("/status", response_model=HealthCheckResponse)
async def health_check(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(optional_api_key_auth),
    __: bool = Depends(check_rate_limit)
):
    """Basic health check endpoint."""
    try:
        # Test database connection
        database_connected = True
        try:
            db.execute(text("SELECT 1"))
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            database_connected = False
        
        # Check Google authentication and configuration
        google_authenticated = False
        google_configured = False
        google_auth_error = None
        try:
            settings = get_settings()
            google_configured = bool(settings.google.client_id and settings.google.client_secret)
            
            if google_configured:
                oauth_manager = get_oauth_manager()
                credentials = oauth_manager.get_valid_credentials()
                google_authenticated = bool(credentials)
            else:
                google_auth_error = "Google OAuth credentials not configured"
        except Exception as e:
            logger.warning(f"Google auth check failed: {e}")
            google_auth_error = str(e)
        
        # Check scheduler status
        scheduler_running = False
        try:
            scheduler = get_sync_scheduler()
            stats = scheduler.get_scheduler_stats()
            scheduler_running = stats.get("running", False)
        except Exception as e:
            logger.warning(f"Scheduler check failed: {e}")
        
        # Get active mappings count
        active_mappings = 0
        try:
            active_mappings = db.query(CalendarMapping).filter(
                CalendarMapping.enabled == True
            ).count()
        except Exception as e:
            logger.warning(f"Active mappings check failed: {e}")
        
        # Get last sync times for each mapping
        last_sync_times = {}
        try:
            mappings = db.query(CalendarMapping).all()
            for mapping in mappings:
                last_sync_times[mapping.id] = mapping.last_sync_at
        except Exception as e:
            logger.warning(f"Last sync times check failed: {e}")
        
        # Determine overall status
        # System is healthy if core components are working
        # Google auth is not required for basic system health
        if database_connected and scheduler_running:
            if google_configured:
                status = "healthy"
            else:
                # System works but needs configuration
                status = "needs_setup"
        elif database_connected:
            # Database works but scheduler has issues - still partially functional
            status = "degraded"
        else:
            # Database connection failed - this is a critical issue
            status = "unhealthy"
        
        return HealthCheckResponse(
            status=status,
            timestamp=datetime.utcnow(),
            database_connected=database_connected,
            google_authenticated=google_authenticated,
            google_configured=google_configured,
            google_auth_error=google_auth_error,
            scheduler_running=scheduler_running,
            active_mappings=active_mappings,
            last_sync_times=last_sync_times
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheckResponse(
            status="unhealthy",
            timestamp=datetime.utcnow(),
            database_connected=False,
            google_authenticated=False,
            scheduler_running=False,
            active_mappings=0,
            last_sync_times={}
        )


@router.get("/status/detailed", response_model=SystemStatusResponse)
async def detailed_system_status(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(optional_api_key_auth),
    __: bool = Depends(check_rate_limit)
):
    """Detailed system status with comprehensive information."""
    try:
        # Get basic health check
        health = await health_check(request, db)
        
        # Get scheduler statistics
        scheduler_stats = {}
        try:
            scheduler = get_sync_scheduler()
            scheduler_stats = scheduler.get_scheduler_stats()
        except Exception as e:
            logger.warning(f"Failed to get scheduler stats: {e}")
            scheduler_stats = {"error": str(e)}
        
        # Get webhook statistics
        webhook_stats = {}
        try:
            webhook_client = get_webhook_client()
            webhook_stats = webhook_client.get_retry_stats()
        except Exception as e:
            logger.warning(f"Failed to get webhook stats: {e}")
            webhook_stats = {"error": str(e)}
        
        # Get sync summary
        sync_summary = {}
        try:
            # Recent sync activity (last 24 hours)
            recent_cutoff = datetime.utcnow() - timedelta(hours=24)
            recent_syncs = db.query(SyncLog).filter(
                SyncLog.started_at >= recent_cutoff
            ).all()
            
            sync_summary = {
                "recent_syncs_24h": len(recent_syncs),
                "successful_syncs_24h": len([s for s in recent_syncs if s.status == "success"]),
                "failed_syncs_24h": len([s for s in recent_syncs if s.status == "failure"]),
                "total_mappings": db.query(CalendarMapping).count(),
                "enabled_mappings": db.query(CalendarMapping).filter(
                    CalendarMapping.enabled == True
                ).count(),
                "last_successful_sync": None
            }
            
            # Get last successful sync
            last_success = db.query(SyncLog).filter(
                SyncLog.status == "success"
            ).order_by(SyncLog.completed_at.desc()).first()
            
            if last_success:
                sync_summary["last_successful_sync"] = last_success.completed_at.isoformat()
                
        except Exception as e:
            logger.warning(f"Failed to get sync summary: {e}")
            sync_summary = {"error": str(e)}
        
        return SystemStatusResponse(
            health=health,
            scheduler_stats=scheduler_stats,
            webhook_stats=webhook_stats,
            sync_summary=sync_summary
        )
        
    except Exception as e:
        logger.error(f"Detailed status check failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve system status")


@router.get("/version")
async def get_version_info(
    request: Request,
    _: bool = Depends(optional_api_key_auth),
    __: bool = Depends(check_rate_limit)
):
    """Get version and build information."""
    try:
        settings = get_settings()
        
        return {
            "version": "1.0.0",
            "build_date": "2025-07-30",
            "python_version": "3.11+",
            "environment": "production" if not settings.server.debug else "development",
            "debug_mode": settings.server.debug,
            "api_docs_enabled": settings.development.enable_api_docs,
            "features": {
                "caldav_sync": True,
                "google_calendar": True,
                "bidirectional_sync": True,
                "webhooks": True,
                "scheduling": True,
                "web_ui": True
            }
        }
        
    except Exception as e:
        logger.error(f"Version info failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve version information")


@router.get("/config")
async def get_configuration_info(
    request: Request,
    _: bool = Depends(optional_api_key_auth),
    __: bool = Depends(check_rate_limit)
):
    """Get non-sensitive configuration information."""
    try:
        settings = get_settings()
        
        return {
            "environment": "production" if not settings.server.debug else "development",
            "database": {
                "type": "SQLite",
                "path": settings.database.url.replace("sqlite:///", "")
            },
            "sync": {
                "default_interval_minutes": settings.sync.default_interval_minutes,
                "default_sync_window_days": settings.sync.default_sync_window_days,
                "max_concurrent_mappings": settings.sync.max_concurrent_mappings
            },
            "api": {
                "rate_limit_per_minute": settings.api.rate_limit_per_minute,
                "enable_cors": settings.api.enable_cors,
                "cors_origins": settings.api.cors_origins
            },
            "webhooks": {
                "timeout_seconds": settings.webhooks.timeout_seconds,
                "max_retries": settings.webhooks.max_retries,
                "include_event_details": settings.webhooks.include_event_details
            },
            "google_calendar": {
                "rate_limit_delay": settings.google_calendar.rate_limit_delay,
                "max_results_per_request": settings.google_calendar.max_results_per_request,
                "batch_size": settings.google_calendar.batch_size
            },
            "caldav": {
                "connection_timeout": settings.caldav.connection_timeout,
                "read_timeout": settings.caldav.read_timeout
            }
        }
        
    except Exception as e:
        logger.error(f"Configuration info failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve configuration information")


@router.get("/metrics")
async def get_system_metrics(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(optional_api_key_auth),
    __: bool = Depends(check_rate_limit)
):
    """Get system metrics for monitoring."""
    try:
        # Database metrics
        db_metrics = {}
        try:
            db_metrics = {
                "total_caldav_accounts": db.query(CalDAVAccount).count(),
                "enabled_caldav_accounts": db.query(CalDAVAccount).filter(
                    CalDAVAccount.enabled == True
                ).count(),
                "total_mappings": db.query(CalendarMapping).count(),
                "enabled_mappings": db.query(CalendarMapping).filter(
                    CalendarMapping.enabled == True
                ).count(),
                "total_sync_logs": db.query(SyncLog).count()
            }
        except Exception as e:
            logger.warning(f"Failed to get database metrics: {e}")
            db_metrics = {"error": str(e)}
        
        # Scheduler metrics
        scheduler_metrics = {}
        try:
            scheduler = get_sync_scheduler()
            scheduler_stats = scheduler.get_scheduler_stats()
            scheduler_metrics = {
                "running": scheduler_stats.get("running", False),
                "total_jobs": scheduler_stats.get("total_jobs", 0),
                "active_syncs": scheduler_stats.get("active_syncs", 0),
                "next_job_run": scheduler_stats.get("next_job_run")
            }
        except Exception as e:
            logger.warning(f"Failed to get scheduler metrics: {e}")
            scheduler_metrics = {"error": str(e)}
        
        # Recent sync metrics (last hour)
        sync_metrics = {}
        try:
            recent_cutoff = datetime.utcnow() - timedelta(hours=1)
            recent_syncs = db.query(SyncLog).filter(
                SyncLog.started_at >= recent_cutoff
            ).all()
            
            sync_metrics = {
                "syncs_last_hour": len(recent_syncs),
                "successful_syncs_last_hour": len([s for s in recent_syncs if s.status == "success"]),
                "failed_syncs_last_hour": len([s for s in recent_syncs if s.status == "failure"]),
                "events_inserted_last_hour": sum(s.inserted_count or 0 for s in recent_syncs),
                "events_updated_last_hour": sum(s.updated_count or 0 for s in recent_syncs),
                "events_deleted_last_hour": sum(s.deleted_count or 0 for s in recent_syncs)
            }
        except Exception as e:
            logger.warning(f"Failed to get sync metrics: {e}")
            sync_metrics = {"error": str(e)}
        
        # Google authentication metrics
        google_metrics = {}
        try:
            oauth_manager = get_oauth_manager()
            token_info = oauth_manager.get_token_info()
            
            google_metrics = {
                "authenticated": bool(token_info and token_info.get('has_token')),
                "token_expired": token_info.get('is_expired', True) if token_info else True,
                "token_expires_at": token_info.get('expires_at') if token_info else None
            }
        except Exception as e:
            logger.warning(f"Failed to get Google metrics: {e}")
            google_metrics = {"error": str(e)}
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "database": db_metrics,
            "scheduler": scheduler_metrics,
            "sync": sync_metrics,
            "google": google_metrics
        }
        
    except Exception as e:
        logger.error(f"System metrics failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve system metrics")


# Add import for CalDAVAccount
from app.database import CalDAVAccount
from datetime import timedelta
