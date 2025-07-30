"""
Logging configuration and utilities for CalDAV Sync Microservice.

Provides structured logging with JSON or text format support,
and specialized loggers for different components.
"""

import logging
import sys
from typing import Any, Dict, Optional
from datetime import datetime
import structlog
from structlog.stdlib import LoggerFactory

from app.config import get_settings


def configure_logging():
    """Configure structured logging for the application."""
    settings = get_settings()
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if settings.logging.format == "json" 
            else structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.logging.level.upper()),
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger for the given name."""
    return structlog.get_logger(name)


class SyncLogger:
    """Specialized logger for sync operations."""
    
    def __init__(self, mapping_id: str, direction: str):
        self.logger = get_logger("sync")
        self.mapping_id = mapping_id
        self.direction = direction
        self.start_time = datetime.utcnow()
    
    def info(self, message: str, **kwargs):
        """Log info message with sync context."""
        self.logger.info(
            message,
            mapping_id=self.mapping_id,
            direction=self.direction,
            **kwargs
        )
    
    def warning(self, message: str, **kwargs):
        """Log warning message with sync context."""
        self.logger.warning(
            message,
            mapping_id=self.mapping_id,
            direction=self.direction,
            **kwargs
        )
    
    def error(self, message: str, **kwargs):
        """Log error message with sync context."""
        self.logger.error(
            message,
            mapping_id=self.mapping_id,
            direction=self.direction,
            **kwargs
        )
    
    def log_sync_start(self, caldav_calendar: str, google_calendar: str):
        """Log sync operation start."""
        self.info(
            "Sync started",
            caldav_calendar=caldav_calendar,
            google_calendar=google_calendar,
            started_at=self.start_time.isoformat()
        )
    
    def log_sync_complete(self, inserted: int, updated: int, deleted: int, errors: int):
        """Log sync operation completion."""
        duration = (datetime.utcnow() - self.start_time).total_seconds()
        
        self.info(
            "Sync completed",
            inserted_count=inserted,
            updated_count=updated,
            deleted_count=deleted,
            error_count=errors,
            duration_seconds=duration,
            completed_at=datetime.utcnow().isoformat()
        )
    
    def log_conflict_resolution(self, event_uid: str, resolution: str, reason: str):
        """Log conflict resolution decision."""
        settings = get_settings()
        if settings.logging.log_conflict_resolutions:
            self.info(
                "Conflict resolved",
                event_uid=event_uid,
                resolution=resolution,
                reason=reason
            )
    
    def log_event_change(self, action: str, event_uid: str, summary: str = None, **kwargs):
        """Log individual event changes."""
        self.info(
            f"Event {action}",
            action=action,
            event_uid=event_uid,
            summary=summary,
            **kwargs
        )


class WebhookLogger:
    """Specialized logger for webhook operations."""
    
    def __init__(self, mapping_id: str, webhook_url: str):
        self.logger = get_logger("webhook")
        self.mapping_id = mapping_id
        self.webhook_url = webhook_url
    
    def info(self, message: str, **kwargs):
        """Log info message with webhook context."""
        self.logger.info(
            message,
            mapping_id=self.mapping_id,
            webhook_url=self.webhook_url,
            **kwargs
        )
    
    def warning(self, message: str, **kwargs):
        """Log warning message with webhook context."""
        self.logger.warning(
            message,
            mapping_id=self.mapping_id,
            webhook_url=self.webhook_url,
            **kwargs
        )
    
    def error(self, message: str, **kwargs):
        """Log error message with webhook context."""
        self.logger.error(
            message,
            mapping_id=self.mapping_id,
            webhook_url=self.webhook_url,
            **kwargs
        )
    
    def log_webhook_sent(self, status_code: int, response_time: float):
        """Log successful webhook delivery."""
        self.info(
            "Webhook sent successfully",
            status_code=status_code,
            response_time_ms=response_time * 1000
        )
    
    def log_webhook_failed(self, error: str, status_code: Optional[int] = None, attempt: int = 1):
        """Log webhook delivery failure."""
        settings = get_settings()
        if settings.logging.log_webhook_failures:
            self.error(
                "Webhook delivery failed",
                error=error,
                status_code=status_code,
                attempt=attempt
            )
    
    def log_webhook_retry(self, attempt: int, next_retry_at: datetime):
        """Log webhook retry scheduling."""
        self.warning(
            "Webhook retry scheduled",
            attempt=attempt,
            next_retry_at=next_retry_at.isoformat()
        )


class CalDAVLogger:
    """Specialized logger for CalDAV operations."""
    
    def __init__(self, account_name: str, calendar_name: str = None):
        self.logger = get_logger("caldav")
        self.account_name = account_name
        self.calendar_name = calendar_name
    
    def info(self, message: str, **kwargs):
        """Log info message with CalDAV context."""
        self.logger.info(
            message,
            account_name=self.account_name,
            calendar_name=self.calendar_name,
            **kwargs
        )
    
    def warning(self, message: str, **kwargs):
        """Log warning message with CalDAV context."""
        self.logger.warning(
            message,
            account_name=self.account_name,
            calendar_name=self.calendar_name,
            **kwargs
        )
    
    def error(self, message: str, **kwargs):
        """Log error message with CalDAV context."""
        self.logger.error(
            message,
            account_name=self.account_name,
            calendar_name=self.calendar_name,
            **kwargs
        )
    
    def log_connection_test(self, success: bool, error: str = None):
        """Log CalDAV connection test result."""
        if success:
            self.info("CalDAV connection test successful")
        else:
            self.error("CalDAV connection test failed", error=error)
    
    def log_calendar_discovery(self, calendar_count: int):
        """Log calendar discovery result."""
        self.info(
            "Calendar discovery completed",
            calendar_count=calendar_count
        )
    
    def log_event_fetch(self, event_count: int, date_range: str):
        """Log event fetch operation."""
        self.info(
            "Events fetched from CalDAV",
            event_count=event_count,
            date_range=date_range
        )


class GoogleLogger:
    """Specialized logger for Google Calendar operations."""
    
    def __init__(self, calendar_name: str = None):
        self.logger = get_logger("google")
        self.calendar_name = calendar_name
    
    def info(self, message: str, **kwargs):
        """Log info message with Google context."""
        self.logger.info(
            message,
            calendar_name=self.calendar_name,
            **kwargs
        )
    
    def warning(self, message: str, **kwargs):
        """Log warning message with Google context."""
        self.logger.warning(
            message,
            calendar_name=self.calendar_name,
            **kwargs
        )
    
    def error(self, message: str, **kwargs):
        """Log error message with Google context."""
        self.logger.error(
            message,
            calendar_name=self.calendar_name,
            **kwargs
        )
    
    def log_oauth_refresh(self, success: bool):
        """Log OAuth token refresh attempt."""
        if success:
            self.info("OAuth token refreshed successfully")
        else:
            self.error("OAuth token refresh failed")
    
    def log_calendar_list(self, calendar_count: int):
        """Log calendar list retrieval."""
        self.info(
            "Google calendars retrieved",
            calendar_count=calendar_count
        )
    
    def log_event_operation(self, operation: str, event_count: int):
        """Log bulk event operations."""
        self.info(
            f"Google Calendar events {operation}",
            operation=operation,
            event_count=event_count
        )
    
    def log_rate_limit(self, delay: float):
        """Log rate limiting delay."""
        self.warning(
            "Rate limit applied",
            delay_seconds=delay
        )


# Initialize logging on module import
configure_logging()
