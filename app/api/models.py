"""
Pydantic models for API request/response validation.

Defines all the data models used by the REST API endpoints
for CalDAV accounts, calendar mappings, and sync operations.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
from enum import Enum


class SyncDirection(str, Enum):
    """Sync direction options."""
    CALDAV_TO_GOOGLE = "caldav_to_google"
    GOOGLE_TO_CALDAV = "google_to_caldav"
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(str, Enum):
    """Sync status options."""
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILURE = "failure"
    RUNNING = "running"


# CalDAV Account Models
class CalDAVAccountCreate(BaseModel):
    """Request model for creating CalDAV account."""
    name: str = Field(..., min_length=1, max_length=100, description="User-friendly account name")
    username: str = Field(..., min_length=1, max_length=100, description="CalDAV username")
    password: str = Field(..., min_length=1, description="CalDAV password")
    base_url: str = Field(..., description="CalDAV server base URL")
    verify_ssl: bool = Field(default=True, description="Whether to verify SSL certificates")

    @validator('base_url')
    def validate_base_url(cls, v):
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('base_url must start with http:// or https://')
        return v


class CalDAVAccountUpdate(BaseModel):
    """Request model for updating CalDAV account."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    username: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=1)
    base_url: Optional[str] = None
    verify_ssl: Optional[bool] = None
    enabled: Optional[bool] = None

    @validator('base_url')
    def validate_base_url(cls, v):
        if v and not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('base_url must start with http:// or https://')
        return v


class CalDAVAccountResponse(BaseModel):
    """Response model for CalDAV account."""
    id: str
    name: str
    username: str
    base_url: str
    verify_ssl: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_tested_at: Optional[datetime]
    last_test_success: Optional[bool]

    class Config:
        from_attributes = True


class CalDAVAccountTest(BaseModel):
    """Request model for testing CalDAV account connection."""
    username: str
    password: str
    base_url: str
    verify_ssl: bool = True


class CalDAVAccountTestResponse(BaseModel):
    """Response model for CalDAV account test."""
    success: bool
    error_message: Optional[str] = None


# Calendar Models
class CalDAVCalendarResponse(BaseModel):
    """Response model for CalDAV calendar."""
    id: str
    name: str
    description: Optional[str]
    color: Optional[str]
    timezone: Optional[str]
    url: Optional[str]


class GoogleCalendarResponse(BaseModel):
    """Response model for Google Calendar."""
    id: str
    summary: str
    description: Optional[str]
    location: Optional[str]
    timezone: Optional[str]
    color_id: Optional[str]
    background_color: Optional[str]
    foreground_color: Optional[str]
    access_role: Optional[str]
    primary: bool


# Calendar Mapping Models
class CalendarMappingCreate(BaseModel):
    """Request model for creating calendar mapping."""
    caldav_account_id: str
    caldav_calendar_id: str
    caldav_calendar_name: str
    google_calendar_id: str
    google_calendar_name: str
    sync_direction: SyncDirection = SyncDirection.CALDAV_TO_GOOGLE
    sync_window_days: int = Field(default=30, ge=1, le=365, description="Days forward to sync")
    sync_interval_minutes: int = Field(default=5, ge=1, le=1440, description="Sync frequency in minutes")
    webhook_url: Optional[str] = Field(None, description="Optional webhook URL for notifications")
    enabled: bool = True

    @validator('webhook_url')
    def validate_webhook_url(cls, v):
        if v and not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('webhook_url must start with http:// or https://')
        return v


class CalendarMappingUpdate(BaseModel):
    """Request model for updating calendar mapping."""
    sync_direction: Optional[SyncDirection] = None
    sync_window_days: Optional[int] = Field(None, ge=1, le=365)
    sync_interval_minutes: Optional[int] = Field(None, ge=1, le=1440)
    webhook_url: Optional[str] = None
    enabled: Optional[bool] = None

    @validator('webhook_url')
    def validate_webhook_url(cls, v):
        if v and not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('webhook_url must start with http:// or https://')
        return v


class CalendarMappingResponse(BaseModel):
    """Response model for calendar mapping."""
    id: str
    caldav_account_id: str
    caldav_account_name: str  # Added for UI display
    caldav_calendar_id: str
    caldav_calendar_name: str
    google_calendar_id: str
    google_calendar_name: str
    sync_direction: SyncDirection
    sync_window_days: int
    sync_interval_minutes: int
    webhook_url: Optional[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_sync_at: Optional[datetime]
    last_sync_status: Optional[SyncStatus]

    class Config:
        from_attributes = True


# Sync Models
class SyncTriggerRequest(BaseModel):
    """Request model for triggering manual sync."""
    mapping_ids: Optional[List[str]] = Field(None, description="Specific mapping IDs to sync (all if not provided)")


class SyncResultResponse(BaseModel):
    """Response model for sync result."""
    mapping_id: str
    caldav_account_name: Optional[str] = None    # Added for UI display
    direction: SyncDirection
    status: SyncStatus
    inserted_count: int
    updated_count: int
    deleted_count: int
    error_count: int
    errors: List[str]
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    
    # Enhanced sync details for richer UI display
    event_summaries: Optional[List[str]] = None  # List of event titles that changed
    change_summary: Optional[str] = None         # Human-readable summary


class SyncStatusResponse(BaseModel):
    """Response model for sync status."""
    mapping_id: str
    scheduled: bool
    next_run: Optional[datetime]
    running: bool
    last_run: Optional[datetime]
    last_sync_status: Optional[SyncStatus]


# OAuth Models
class OAuthAuthorizationResponse(BaseModel):
    """Response model for OAuth authorization URL."""
    authorization_url: str
    state: Optional[str]


class OAuthTokenInfo(BaseModel):
    """Response model for OAuth token information."""
    has_token: bool
    is_expired: bool
    expires_at: Optional[datetime]
    scopes: List[str]
    created_at: datetime
    updated_at: datetime


# Status Models
class HealthCheckResponse(BaseModel):
    """Response model for health check."""
    status: str
    timestamp: datetime
    version: str = "1.0.0"
    database_connected: bool
    google_authenticated: bool
    google_configured: bool
    google_auth_error: Optional[str] = None
    scheduler_running: bool
    active_mappings: int
    last_sync_times: Dict[str, Optional[datetime]]


class SystemStatusResponse(BaseModel):
    """Response model for detailed system status."""
    health: HealthCheckResponse
    scheduler_stats: Dict[str, Any]
    webhook_stats: Dict[str, Any]
    sync_summary: Dict[str, Any]


# Error Models
class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ValidationErrorResponse(BaseModel):
    """Validation error response model."""
    error: str = "Validation failed"
    detail: str
    validation_errors: List[Dict[str, Any]]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Pagination Models
class PaginationParams(BaseModel):
    """Query parameters for pagination."""
    page: int = Field(default=1, ge=1, description="Page number")
    size: int = Field(default=20, ge=1, le=100, description="Items per page")


class PaginatedResponse(BaseModel):
    """Generic paginated response model."""
    items: List[Any]
    total: int
    page: int
    size: int
    pages: int

    @validator('pages', pre=True, always=True)
    def calculate_pages(cls, v, values):
        total = values.get('total', 0)
        size = values.get('size', 20)
        return (total + size - 1) // size if total > 0 else 0


# Discovery Models
class CalendarDiscoveryRequest(BaseModel):
    """Request model for calendar discovery."""
    account_id: str


class CalendarDiscoveryResponse(BaseModel):
    """Response model for calendar discovery."""
    account_id: str
    calendars: List[CalDAVCalendarResponse]
    discovered_at: datetime


# Webhook Models
class WebhookTestRequest(BaseModel):
    """Request model for testing webhook."""
    webhook_url: str
    test_payload: Optional[Dict[str, Any]] = None

    @validator('webhook_url')
    def validate_webhook_url(cls, v):
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('webhook_url must start with http:// or https://')
        return v


class WebhookTestResponse(BaseModel):
    """Response model for webhook test."""
    success: bool
    status_code: Optional[int]
    response_time_ms: Optional[float]
    error_message: Optional[str]
