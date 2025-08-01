"""
Custom exceptions for CalDAV Sync Microservice.

Defines specific exception types for different error conditions
to enable proper error handling and logging throughout the application.
"""

from typing import Optional, Dict, Any


class CalDAVSyncException(Exception):
    """Base exception for all CalDAV Sync Microservice errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ConfigurationError(CalDAVSyncException):
    """Raised when there are configuration issues."""
    pass


class DatabaseError(CalDAVSyncException):
    """Raised when database operations fail."""
    pass


class CalDAVError(CalDAVSyncException):
    """Base exception for CalDAV-related errors."""
    pass


class CalDAVConnectionError(CalDAVError):
    """Raised when CalDAV server connection fails."""
    pass


class CalDAVAuthenticationError(CalDAVError):
    """Raised when CalDAV authentication fails."""
    pass


class CalDAVCalendarNotFoundError(CalDAVError):
    """Raised when a CalDAV calendar cannot be found."""
    pass


class CalDAVEventError(CalDAVError):
    """Raised when CalDAV event operations fail."""
    pass


class GoogleCalendarError(CalDAVSyncException):
    """Base exception for Google Calendar-related errors."""
    pass


class GoogleOAuthError(GoogleCalendarError):
    """Raised when Google OAuth operations fail."""
    pass


class GoogleCalendarNotFoundError(GoogleCalendarError):
    """Raised when a Google Calendar cannot be found."""
    pass


class GoogleCalendarEventError(GoogleCalendarError):
    """Raised when Google Calendar event operations fail."""
    pass


class GoogleRateLimitError(GoogleCalendarError):
    """Raised when Google API rate limits are exceeded."""
    
    def __init__(self, message: str, retry_after: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        self.retry_after = retry_after
        super().__init__(message, details)


class SyncError(CalDAVSyncException):
    """Base exception for sync operation errors."""
    pass


class SyncConflictError(SyncError):
    """Raised when sync conflicts cannot be resolved automatically."""
    pass


class SyncMappingError(SyncError):
    """Raised when calendar mapping issues occur."""
    pass


class SyncEventError(SyncError):
    """Raised when individual event sync fails."""
    pass


class WebhookError(CalDAVSyncException):
    """Base exception for webhook-related errors."""
    pass


class WebhookDeliveryError(WebhookError):
    """Raised when webhook delivery fails."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message, details)


class WebhookTimeoutError(WebhookError):
    """Raised when webhook delivery times out."""
    pass


class AuthenticationError(CalDAVSyncException):
    """Raised when API authentication fails."""
    pass


class AuthorizationError(CalDAVSyncException):
    """Raised when API authorization fails."""
    pass


class ValidationError(CalDAVSyncException):
    """Raised when input validation fails."""
    pass


class EventNormalizationError(CalDAVSyncException):
    """Raised when event normalization fails."""
    pass


class RecurrenceError(CalDAVSyncException):
    """Raised when recurrence rule processing fails."""
    pass


def handle_caldav_exception(e: Exception) -> CalDAVError:
    """Convert generic CalDAV library exceptions to our custom exceptions."""
    error_message = str(e).lower()
    
    if "authentication" in error_message or "unauthorized" in error_message:
        return CalDAVAuthenticationError(f"CalDAV authentication failed: {e}")
    elif "connection" in error_message or "timeout" in error_message:
        return CalDAVConnectionError(f"CalDAV connection failed: {e}")
    elif "not found" in error_message or "404" in error_message:
        return CalDAVCalendarNotFoundError(f"CalDAV calendar not found: {e}")
    else:
        return CalDAVError(f"CalDAV operation failed: {e}")


def handle_google_exception(e: Exception) -> GoogleCalendarError:
    """Convert generic Google API exceptions to our custom exceptions."""
    error_message = str(e).lower()
    
    # Check for HTTP status codes if available
    status_code = None
    if hasattr(e, 'resp') and hasattr(e.resp, 'status'):
        status_code = e.resp.status
    
    if "oauth" in error_message or "unauthorized" in error_message:
        return GoogleOAuthError(f"Google OAuth failed: {e}")
    elif "not found" in error_message or "404" in error_message or status_code == 404:
        return GoogleCalendarNotFoundError(f"Google Calendar not found: {e}")
    elif status_code == 410 or "resource has been deleted" in error_message:
        # 410 Gone - resource has been deleted, treat similar to 404
        return GoogleCalendarNotFoundError(f"Google Calendar resource deleted: {e}")
    elif "rate limit" in error_message or "quota" in error_message:
        # Try to extract retry-after from the exception if available
        retry_after = None
        if hasattr(e, 'resp') and hasattr(e.resp, 'headers'):
            retry_after = e.resp.headers.get('Retry-After')
            if retry_after:
                try:
                    retry_after = int(retry_after)
                except ValueError:
                    retry_after = None
        return GoogleRateLimitError(f"Google API rate limit exceeded: {e}", retry_after=retry_after)
    else:
        return GoogleCalendarError(f"Google Calendar operation failed: {e}")
