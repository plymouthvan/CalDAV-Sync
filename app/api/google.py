"""
Google OAuth and Calendar API endpoints.

Handles Google OAuth authentication flow, token management,
and Google Calendar operations.
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.google_oauth import get_oauth_manager
from app.google.client import get_google_client
from app.api.models import (
    OAuthAuthorizationResponse, OAuthTokenInfo,
    GoogleCalendarResponse, ErrorResponse
)
from app.auth.security import require_api_key_unless_localhost, check_rate_limit
from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.exceptions import GoogleOAuthError, GoogleCalendarError

logger = get_logger("api.google")
router = APIRouter(prefix="/google", tags=["Google OAuth & Calendar"])


@router.get("/oauth/authorize", response_model=OAuthAuthorizationResponse)
async def get_oauth_authorization_url(
    request: Request,
    state: Optional[str] = Query(None, description="Optional state parameter for CSRF protection"),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get Google OAuth authorization URL."""
    try:
        oauth_manager = get_oauth_manager()
        authorization_url = oauth_manager.get_authorization_url(state)
        
        return OAuthAuthorizationResponse(
            authorization_url=authorization_url,
            state=state
        )
        
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate OAuth authorization URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate authorization URL")


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(..., description="Authorization code from Google"),
    state: Optional[str] = Query(None, description="State parameter"),
    error: Optional[str] = Query(None, description="Error from OAuth provider")
):
    """Handle Google OAuth callback."""
    try:
        if error:
            logger.warning(f"OAuth callback received error: {error}")
            # Redirect to Google auth page with error
            return RedirectResponse(url=f"/google?error={error}")
        
        oauth_manager = get_oauth_manager()
        oauth_manager.exchange_code_for_tokens(code, state)
        
        # Test the credentials
        success, error_message = oauth_manager.test_credentials()
        if not success:
            logger.error(f"OAuth credentials test failed: {error_message}")
            return RedirectResponse(url=f"/google?error=test_failed")
        
        logger.info("Google OAuth authentication completed successfully")
        
        # Redirect to Google auth page with success
        return RedirectResponse(url="/google?success=true")
        
    except HTTPException:
        raise
    except GoogleOAuthError as e:
        logger.error(f"OAuth error: {e}")
        return RedirectResponse(url=f"/google?error=oauth_failed")
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        return RedirectResponse(url=f"/google?error=callback_failed")


@router.get("/oauth/token", response_model=OAuthTokenInfo)
async def get_oauth_token_info(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get information about the current OAuth token."""
    try:
        oauth_manager = get_oauth_manager()
        token_info = oauth_manager.get_token_info()
        
        if not token_info:
            raise HTTPException(status_code=404, detail="No OAuth token found")
        
        return OAuthTokenInfo(**token_info)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get OAuth token info: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve token information")


@router.post("/oauth/revoke", status_code=204)
async def revoke_oauth_token(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Revoke the current OAuth token."""
    logger.info("=== REVOKE TOKEN REQUEST RECEIVED ===")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    try:
        oauth_manager = get_oauth_manager()
        logger.info("OAuth manager obtained, attempting to revoke tokens...")
        
        success = oauth_manager.revoke_tokens()
        logger.info(f"Revoke tokens result: {success}")
        
        if not success:
            logger.error("OAuth manager returned False for revoke_tokens()")
            raise HTTPException(status_code=500, detail="Failed to revoke OAuth token")
        
        logger.info("Google OAuth token revoked successfully")
        
    except HTTPException:
        logger.error("HTTPException during token revocation")
        raise
    except Exception as e:
        logger.error(f"Failed to revoke OAuth token: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to revoke OAuth token")


@router.post("/oauth/test")
async def test_oauth_credentials(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Test the current OAuth credentials."""
    logger.info("=== TEST CREDENTIALS REQUEST RECEIVED ===")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    try:
        oauth_manager = get_oauth_manager()
        logger.info("OAuth manager obtained, testing credentials...")
        
        success, error_message = oauth_manager.test_credentials()
        logger.info(f"Test credentials result: success={success}, error={error_message}")
        
        result = {
            "success": success,
            "error_message": error_message,
            "tested_at": datetime.utcnow().isoformat()
        }
        logger.info(f"Returning test result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"OAuth credentials test failed: {e}", exc_info=True)
        result = {
            "success": False,
            "error_message": str(e),
            "tested_at": datetime.utcnow().isoformat()
        }
        logger.info(f"Returning error result: {result}")
        return result


@router.get("/calendars", response_model=List[GoogleCalendarResponse])
async def list_google_calendars(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """List all accessible Google Calendars."""
    try:
        # Check OAuth authentication
        oauth_manager = get_oauth_manager()
        credentials = oauth_manager.get_valid_credentials()
        if not credentials:
            raise HTTPException(
                status_code=401,
                detail="Google Calendar authentication required. Please complete OAuth flow."
            )
        
        google_client = get_google_client()
        calendars = google_client.list_calendars()
        
        calendar_responses = [
            GoogleCalendarResponse(
                id=cal.id,
                summary=cal.summary,
                description=cal.description,
                location=cal.location,
                timezone=cal.timezone,
                color_id=cal.color_id,
                background_color=cal.background_color,
                foreground_color=cal.foreground_color,
                access_role=cal.access_role,
                primary=cal.primary
            )
            for cal in calendars
        ]
        
        return calendar_responses
        
    except HTTPException:
        raise
    except GoogleCalendarError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list Google calendars: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Google calendars")


@router.get("/calendars/{calendar_id}", response_model=GoogleCalendarResponse)
async def get_google_calendar(
    calendar_id: str,
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get a specific Google Calendar."""
    try:
        # Check OAuth authentication
        oauth_manager = get_oauth_manager()
        credentials = oauth_manager.get_valid_credentials()
        if not credentials:
            raise HTTPException(
                status_code=401,
                detail="Google Calendar authentication required. Please complete OAuth flow."
            )
        
        google_client = get_google_client()
        calendar = google_client.get_calendar_by_id(calendar_id)
        
        if not calendar:
            raise HTTPException(status_code=404, detail="Google Calendar not found")
        
        return GoogleCalendarResponse(
            id=calendar.id,
            summary=calendar.summary,
            description=calendar.description,
            location=calendar.location,
            timezone=calendar.timezone,
            color_id=calendar.color_id,
            background_color=calendar.background_color,
            foreground_color=calendar.foreground_color,
            access_role=calendar.access_role,
            primary=calendar.primary
        )
        
    except HTTPException:
        raise
    except GoogleCalendarError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get Google calendar {calendar_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Google calendar")


@router.get("/auth/status")
async def get_google_auth_status(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get Google authentication status."""
    try:
        oauth_manager = get_oauth_manager()
        
        # Check if credentials are configured
        settings = get_settings()
        has_credentials = bool(settings.google.client_id and settings.google.client_secret)
        
        # Get token info
        token_info = oauth_manager.get_token_info()
        
        # Test credentials if available
        credentials_valid = False
        credentials_error = None
        
        if token_info and token_info.get('has_token'):
            success, error_message = oauth_manager.test_credentials()
            credentials_valid = success
            credentials_error = error_message
        
        # Get calendar count if authenticated
        calendar_count = 0
        if credentials_valid:
            try:
                google_client = get_google_client()
                calendars = google_client.list_calendars()
                calendar_count = len(calendars)
            except Exception as e:
                logger.warning(f"Failed to count calendars: {e}")
        
        return {
            "has_credentials": has_credentials,
            "authenticated": bool(token_info and token_info.get('has_token')),
            "credentials_valid": credentials_valid,
            "credentials_error": credentials_error,
            "token_valid": credentials_valid and not token_info.get('is_expired', True) if token_info else False,
            "token_expired": token_info.get('is_expired', True) if token_info else True,
            "token_expires_at": token_info.get('expires_at') if token_info else None,
            "scopes": token_info.get('scopes', []) if token_info else [],
            "calendar_count": calendar_count,
            "checked_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get Google auth status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Google auth status")

@router.get("/auth/url")
async def get_oauth_url(
    request: Request,
    state: Optional[str] = Query(None, description="Optional state parameter for CSRF protection"),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get Google OAuth authorization URL (alias for authorize endpoint)."""
    try:
        oauth_manager = get_oauth_manager()
        authorization_url = oauth_manager.get_authorization_url(state)
        
        return {
            "auth_url": authorization_url,
            "state": state
        }
        
    except GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate OAuth authorization URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate authorization URL")

@router.post("/auth/refresh")
async def refresh_oauth_token_alias(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Alias for refresh-token endpoint."""
    return await refresh_oauth_token(request, _, __)

@router.post("/auth/revoke")
async def revoke_oauth_token_alias(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Alias for revoke endpoint."""
    logger.info("=== REVOKE AUTH ALIAS REQUEST RECEIVED ===")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request URL: {request.url}")
    
    await revoke_oauth_token(request, _, __)
    logger.info("Revoke completed successfully, returning success message")
    return {"message": "Authentication revoked successfully"}

@router.post("/test")
async def test_oauth_credentials_alias(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Alias for oauth/test endpoint."""
    logger.info("=== TEST ALIAS REQUEST RECEIVED ===")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request URL: {request.url}")
    
    result = await test_oauth_credentials(request, _, __)
    logger.info(f"Test alias returning result: {result}")
    return result


@router.post("/refresh-token")
async def refresh_oauth_token(
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Manually refresh the OAuth token."""
    try:
        oauth_manager = get_oauth_manager()
        credentials = oauth_manager.get_valid_credentials()
        
        if not credentials:
            raise HTTPException(
                status_code=404,
                detail="No OAuth token found to refresh"
            )
        
        if not credentials.refresh_token:
            raise HTTPException(
                status_code=400,
                detail="No refresh token available. Please re-authenticate."
            )
        
        # The get_valid_credentials method automatically refreshes if needed
        # Test the refreshed credentials
        success, error_message = oauth_manager.test_credentials()
        
        return {
            "success": success,
            "error_message": error_message,
            "refreshed_at": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to refresh OAuth token: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh OAuth token")
