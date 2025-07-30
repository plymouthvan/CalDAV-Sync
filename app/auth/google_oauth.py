"""
Google OAuth2 authentication for Google Calendar API access.

Handles OAuth flow, token management, and automatic token refresh
with secure storage in the database.
"""

import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode
import httpx

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.database import GoogleOAuthToken, get_db
from app.utils.logging import GoogleLogger
from app.utils.exceptions import GoogleOAuthError, handle_google_exception


class GoogleOAuthManager:
    """Manages Google OAuth2 authentication and token lifecycle."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = GoogleLogger()
        
        # Validate required configuration
        if not self.settings.google.client_id or not self.settings.google.client_secret:
            raise GoogleOAuthError("Google OAuth credentials not configured")
    
    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """
        Generate Google OAuth authorization URL.
        
        Args:
            state: Optional state parameter for CSRF protection
            
        Returns:
            Authorization URL for redirecting users
        """
        try:
            flow = Flow.from_client_config(
                client_config={
                    "web": {
                        "client_id": self.settings.google.client_id,
                        "client_secret": self.settings.google.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [f"{self.settings.server.base_url}{self.settings.google.redirect_uri}"]
                    }
                },
                scopes=self.settings.google.scopes
            )
            
            flow.redirect_uri = f"{self.settings.server.base_url}{self.settings.google.redirect_uri}"
            
            authorization_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                state=state
            )
            
            return authorization_url
            
        except Exception as e:
            raise GoogleOAuthError(f"Failed to generate authorization URL: {e}")
    
    def exchange_code_for_tokens(self, authorization_code: str, state: Optional[str] = None) -> GoogleOAuthToken:
        """
        Exchange authorization code for access and refresh tokens.
        
        Args:
            authorization_code: Authorization code from OAuth callback
            state: State parameter for validation
            
        Returns:
            GoogleOAuthToken database record
        """
        try:
            flow = Flow.from_client_config(
                client_config={
                    "web": {
                        "client_id": self.settings.google.client_id,
                        "client_secret": self.settings.google.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [f"{self.settings.server.base_url}{self.settings.google.redirect_uri}"]
                    }
                },
                scopes=self.settings.google.scopes,
                state=state
            )
            
            flow.redirect_uri = f"{self.settings.server.base_url}{self.settings.google.redirect_uri}"
            
            # Exchange code for tokens
            flow.fetch_token(code=authorization_code)
            
            credentials = flow.credentials
            
            # Calculate expiration time
            expires_at = None
            if credentials.expiry:
                expires_at = credentials.expiry
            elif credentials.expires_in:
                expires_at = datetime.utcnow() + timedelta(seconds=credentials.expires_in)
            
            # Create database record
            db_token = GoogleOAuthToken(
                token_type=credentials.token or "Bearer",
                expires_at=expires_at,
                scopes=json.dumps(list(credentials.scopes)) if credentials.scopes else None
            )
            
            # Encrypt and store tokens
            encryption_key = self.settings.security.encryption_key
            db_token.set_access_token(credentials.token, encryption_key)
            
            if credentials.refresh_token:
                db_token.set_refresh_token(credentials.refresh_token, encryption_key)
            
            # Save to database
            with next(get_db()) as db:
                # Remove any existing tokens (single user system)
                db.query(GoogleOAuthToken).delete()
                
                db.add(db_token)
                db.commit()
                db.refresh(db_token)
            
            self.logger.info("OAuth tokens stored successfully")
            return db_token
            
        except Exception as e:
            raise GoogleOAuthError(f"Failed to exchange authorization code: {e}")
    
    def get_valid_credentials(self) -> Optional[Credentials]:
        """
        Get valid Google credentials, refreshing if necessary.
        
        Returns:
            Valid Credentials object or None if not authenticated
        """
        try:
            with next(get_db()) as db:
                db_token = db.query(GoogleOAuthToken).first()
                
                if not db_token:
                    return None
                
                encryption_key = self.settings.security.encryption_key
                
                # Decrypt tokens
                access_token = db_token.get_access_token(encryption_key)
                refresh_token = db_token.get_refresh_token(encryption_key)
                
                # Create credentials object
                credentials = Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.settings.google.client_id,
                    client_secret=self.settings.google.client_secret,
                    scopes=json.loads(db_token.scopes) if db_token.scopes else self.settings.google.scopes
                )
                
                # Check if token needs refresh
                if credentials.expired and credentials.refresh_token:
                    try:
                        credentials.refresh(Request())
                        
                        # Update database with new tokens
                        db_token.set_access_token(credentials.token, encryption_key)
                        
                        # Update expiry
                        if credentials.expiry:
                            db_token.expires_at = credentials.expiry
                        
                        db_token.updated_at = datetime.utcnow()
                        db.commit()
                        
                        self.logger.log_oauth_refresh(True)
                        
                    except Exception as e:
                        self.logger.log_oauth_refresh(False)
                        self.logger.error(f"Token refresh failed: {e}")
                        return None
                
                return credentials
                
        except Exception as e:
            self.logger.error(f"Failed to get valid credentials: {e}")
            return None
    
    def revoke_tokens(self) -> bool:
        """
        Revoke stored OAuth tokens and remove from database.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            credentials = self.get_valid_credentials()
            
            if credentials and credentials.token:
                # Revoke token with Google
                try:
                    revoke_url = f"https://oauth2.googleapis.com/revoke?token={credentials.token}"
                    with httpx.Client() as client:
                        response = client.post(revoke_url)
                        response.raise_for_status()
                except Exception as e:
                    self.logger.warning(f"Failed to revoke token with Google: {e}")
            
            # Remove from database
            with next(get_db()) as db:
                db.query(GoogleOAuthToken).delete()
                db.commit()
            
            self.logger.info("OAuth tokens revoked and removed")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to revoke tokens: {e}")
            return False
    
    def get_token_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the current OAuth token.
        
        Returns:
            Dictionary with token information or None if not authenticated
        """
        try:
            with next(get_db()) as db:
                db_token = db.query(GoogleOAuthToken).first()
                
                if not db_token:
                    return None
                
                credentials = self.get_valid_credentials()
                
                return {
                    "has_token": bool(credentials),
                    "is_expired": credentials.expired if credentials else True,
                    "expires_at": db_token.expires_at.isoformat() if db_token.expires_at else None,
                    "scopes": json.loads(db_token.scopes) if db_token.scopes else [],
                    "created_at": db_token.created_at.isoformat(),
                    "updated_at": db_token.updated_at.isoformat(),
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get token info: {e}")
            return None
    
    def test_credentials(self) -> Tuple[bool, Optional[str]]:
        """
        Test if current credentials are valid by making a simple API call.
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            credentials = self.get_valid_credentials()
            
            if not credentials:
                return False, "No valid credentials available"
            
            # Test credentials by listing calendars
            service = build('calendar', 'v3', credentials=credentials)
            calendar_list = service.calendarList().list(maxResults=1).execute()
            
            return True, None
            
        except HttpError as e:
            error_msg = f"Google API error: {e.resp.status} - {e.resp.reason}"
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Credential test failed: {str(e)}"
            return False, error_msg


# Global OAuth manager instance
oauth_manager = GoogleOAuthManager()


def get_oauth_manager() -> GoogleOAuthManager:
    """Get the global Google OAuth manager instance."""
    return oauth_manager


def require_google_auth(func):
    """Decorator to require valid Google authentication."""
    def wrapper(*args, **kwargs):
        credentials = oauth_manager.get_valid_credentials()
        if not credentials:
            raise GoogleOAuthError("Google authentication required")
        return func(*args, **kwargs)
    return wrapper
