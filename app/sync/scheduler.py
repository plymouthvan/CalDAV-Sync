"""
Sync scheduler for CalDAV Sync Microservice.

Handles background sync jobs using APScheduler with per-mapping job isolation
and overlap prevention to ensure only one sync per mapping runs at a time.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from app.database import CalendarMapping, get_db, get_database_manager
from app.sync.engine import get_sync_engine
from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.exceptions import SyncError

logger = get_logger("scheduler")


class SyncScheduler:
    """Manages scheduled sync jobs for calendar mappings."""
    
    def __init__(self):
        self.settings = get_settings()
        self.sync_engine = get_sync_engine()
        self.scheduler = None
        self.active_jobs = {}  # Track running jobs per mapping to prevent overlaps
        self._setup_scheduler()
    
    def _setup_scheduler(self):
        """Initialize APScheduler with SQLAlchemy job store."""
        # Configure job store to use the same database
        db_manager = get_database_manager()
        jobstore = SQLAlchemyJobStore(engine=db_manager.engine, tablename='apscheduler_jobs')
        
        # Configure executor
        executor = AsyncIOExecutor()
        
        # Job defaults
        job_defaults = {
            'coalesce': True,  # Combine multiple pending executions into one
            'max_instances': 1,  # Only one instance of each job at a time
            'misfire_grace_time': 300  # 5 minutes grace time for missed jobs
        }
        
        # Create scheduler
        self.scheduler = AsyncIOScheduler(
            jobstores={'default': jobstore},
            executors={'default': executor},
            job_defaults=job_defaults,
            timezone='UTC'
        )
        
        # Add event listeners
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)
        self.scheduler.add_listener(self._job_missed, EVENT_JOB_MISSED)
    
    async def start(self):
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Sync scheduler started")
            
            # Schedule all enabled mappings
            await self.schedule_all_mappings()
    
    async def stop(self):
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Sync scheduler stopped")
    
    async def schedule_all_mappings(self):
        """Schedule sync jobs for all enabled calendar mappings."""
        with next(get_db()) as db:
            mappings = db.query(CalendarMapping).filter(
                CalendarMapping.enabled == True
            ).all()
            
            for mapping in mappings:
                await self.schedule_mapping(mapping)
        
        logger.info(f"Scheduled {len(mappings)} calendar mappings")
    
    async def schedule_mapping(self, mapping: CalendarMapping):
        """
        Schedule sync job for a single mapping.
        
        Args:
            mapping: Calendar mapping to schedule
        """
        job_id = f"sync_mapping_{mapping.id}"
        
        # Remove existing job if present
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        
        # Add new job
        self.scheduler.add_job(
            self._sync_mapping_with_lock,
            'interval',
            minutes=mapping.sync_interval_minutes,
            id=job_id,
            args=[mapping.id],
            max_instances=1,  # Prevent overlapping runs
            replace_existing=True,
            next_run_time=datetime.utcnow() + timedelta(seconds=30)  # Start in 30 seconds
        )
        
        logger.info(f"Scheduled mapping {mapping.id} with {mapping.sync_interval_minutes}min interval")
    
    async def unschedule_mapping(self, mapping_id: str):
        """
        Remove scheduled job for a mapping.
        
        Args:
            mapping_id: ID of mapping to unschedule
        """
        job_id = f"sync_mapping_{mapping_id}"
        
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"Unscheduled mapping {mapping_id}")
    
    async def trigger_manual_sync(self, mapping_id: str) -> bool:
        """
        Trigger manual sync for a mapping.
        
        Args:
            mapping_id: ID of mapping to sync
            
        Returns:
            True if sync was triggered, False if already running
        """
        if mapping_id in self.active_jobs:
            logger.warning(f"Sync already running for mapping {mapping_id}")
            return False
        
        # Get mapping from database
        with next(get_db()) as db:
            mapping = db.query(CalendarMapping).filter(
                CalendarMapping.id == mapping_id
            ).first()
            
            if not mapping:
                logger.error(f"Mapping {mapping_id} not found")
                return False
            
            if not mapping.enabled:
                logger.warning(f"Mapping {mapping_id} is disabled")
                return False
        
        # Execute sync in background
        asyncio.create_task(self._sync_mapping_with_lock(mapping_id))
        return True
    
    async def trigger_manual_sync_all(self) -> int:
        """
        Trigger manual sync for all enabled mappings.
        
        Returns:
            Number of syncs triggered
        """
        triggered_count = 0
        
        with next(get_db()) as db:
            mappings = db.query(CalendarMapping).filter(
                CalendarMapping.enabled == True
            ).all()
            
            for mapping in mappings:
                if await self.trigger_manual_sync(mapping.id):
                    triggered_count += 1
        
        logger.info(f"Triggered manual sync for {triggered_count} mappings")
        return triggered_count
    
    async def _sync_mapping_with_lock(self, mapping_id: str):
        """
        Execute sync with concurrency protection.
        
        Args:
            mapping_id: ID of mapping to sync
        """
        # Check if sync is already running
        if mapping_id in self.active_jobs:
            logger.warning(f"Sync already running for mapping {mapping_id}, skipping")
            return
        
        # Mark as active
        self.active_jobs[mapping_id] = datetime.utcnow()
        
        try:
            # Get mapping from database
            with next(get_db()) as db:
                mapping = db.query(CalendarMapping).filter(
                    CalendarMapping.id == mapping_id
                ).first()
                
                if not mapping:
                    logger.error(f"Mapping {mapping_id} not found")
                    return
                
                if not mapping.enabled:
                    logger.info(f"Mapping {mapping_id} is disabled, skipping sync")
                    return
            
            # Execute sync
            result = await self.sync_engine.sync_mapping(mapping)
            
            logger.info(
                f"Sync completed for mapping {mapping_id}: "
                f"{result.status} ({result.inserted_count}I/{result.updated_count}U/{result.deleted_count}D)"
            )
            
        except Exception as e:
            logger.error(f"Sync failed for mapping {mapping_id}: {e}")
            
        finally:
            # Remove from active jobs
            self.active_jobs.pop(mapping_id, None)
    
    def _job_executed(self, event):
        """Handle job execution event."""
        logger.debug(f"Job {event.job_id} executed successfully")
    
    def _job_error(self, event):
        """Handle job error event."""
        logger.error(f"Job {event.job_id} failed: {event.exception}")
    
    def _job_missed(self, event):
        """Handle missed job event."""
        logger.warning(f"Job {event.job_id} missed execution")
    
    def get_job_status(self, mapping_id: str) -> Dict[str, any]:
        """
        Get status information for a mapping's sync job.
        
        Args:
            mapping_id: ID of mapping to check
            
        Returns:
            Dictionary with job status information
        """
        job_id = f"sync_mapping_{mapping_id}"
        job = self.scheduler.get_job(job_id)
        
        if not job:
            return {
                "scheduled": False,
                "next_run": None,
                "running": False
            }
        
        return {
            "scheduled": True,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "running": mapping_id in self.active_jobs,
            "last_run": self.active_jobs.get(mapping_id).isoformat() if mapping_id in self.active_jobs else None
        }
    
    def get_all_job_status(self) -> Dict[str, Dict[str, any]]:
        """
        Get status information for all scheduled jobs.
        
        Returns:
            Dictionary mapping mapping IDs to job status
        """
        status = {}
        
        # Get all sync jobs
        for job in self.scheduler.get_jobs():
            if job.id.startswith("sync_mapping_"):
                mapping_id = job.id.replace("sync_mapping_", "")
                status[mapping_id] = self.get_job_status(mapping_id)
        
        return status
    
    def get_scheduler_stats(self) -> Dict[str, any]:
        """
        Get scheduler statistics.
        
        Returns:
            Dictionary with scheduler statistics
        """
        jobs = self.scheduler.get_jobs()
        
        return {
            "running": self.scheduler.running,
            "total_jobs": len(jobs),
            "active_syncs": len(self.active_jobs),
            "next_job_run": min([job.next_run_time for job in jobs if job.next_run_time], default=None),
            "active_sync_mappings": list(self.active_jobs.keys())
        }
    
    async def reschedule_mapping(self, mapping: CalendarMapping):
        """
        Reschedule a mapping with updated configuration.
        
        Args:
            mapping: Updated calendar mapping
        """
        await self.unschedule_mapping(mapping.id)
        
        if mapping.enabled:
            await self.schedule_mapping(mapping)
        
        logger.info(f"Rescheduled mapping {mapping.id}")
    
    async def pause_mapping(self, mapping_id: str):
        """
        Pause sync for a mapping without removing the job.
        
        Args:
            mapping_id: ID of mapping to pause
        """
        job_id = f"sync_mapping_{mapping_id}"
        job = self.scheduler.get_job(job_id)
        
        if job:
            self.scheduler.pause_job(job_id)
            logger.info(f"Paused sync for mapping {mapping_id}")
    
    async def resume_mapping(self, mapping_id: str):
        """
        Resume sync for a paused mapping.
        
        Args:
            mapping_id: ID of mapping to resume
        """
        job_id = f"sync_mapping_{mapping_id}"
        job = self.scheduler.get_job(job_id)
        
        if job:
            self.scheduler.resume_job(job_id)
            logger.info(f"Resumed sync for mapping {mapping_id}")
    
    async def cleanup_orphaned_jobs(self):
        """Remove jobs for mappings that no longer exist."""
        with next(get_db()) as db:
            existing_mapping_ids = set(
                mapping.id for mapping in db.query(CalendarMapping).all()
            )
        
        removed_count = 0
        
        for job in self.scheduler.get_jobs():
            if job.id.startswith("sync_mapping_"):
                mapping_id = job.id.replace("sync_mapping_", "")
                
                if mapping_id not in existing_mapping_ids:
                    self.scheduler.remove_job(job.id)
                    removed_count += 1
                    logger.info(f"Removed orphaned job for mapping {mapping_id}")
        
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} orphaned sync jobs")


# Global scheduler instance
sync_scheduler = SyncScheduler()


def get_sync_scheduler() -> SyncScheduler:
    """Get the global sync scheduler instance."""
    return sync_scheduler
