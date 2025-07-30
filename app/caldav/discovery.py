"""
CalDAV calendar discovery functionality.

Handles auto-discovery of calendars from CalDAV accounts and provides
utilities for testing connections and validating account configurations.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from app.caldav.client import CalDAVClient, CalDAVClientFactory
from app.caldav.models import CalDAVAccount, CalDAVCalendar
from app.database import CalDAVAccount as DBCalDAVAccount
from app.config import get_settings
from app.utils.logging import CalDAVLogger
from app.utils.exceptions import (
    CalDAVConnectionError,
    CalDAVAuthenticationError,
    handle_caldav_exception
)


class CalDAVDiscovery:
    """Service for discovering CalDAV calendars and testing connections."""
    
    def __init__(self):
        self.settings = get_settings()
    
    def test_account_connection(self, account: CalDAVAccount, password: str) -> Tuple[bool, Optional[str]]:
        """
        Test connection to a CalDAV account.
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        logger = CalDAVLogger(account.name)
        
        try:
            client = CalDAVClientFactory.create_client(account, password)
            success = client.test_connection()
            
            if success:
                logger.log_connection_test(True)
                return True, None
            else:
                error_msg = "Connection test failed - unable to authenticate"
                logger.log_connection_test(False, error_msg)
                return False, error_msg
                
        except CalDAVAuthenticationError as e:
            logger.log_connection_test(False, str(e))
            return False, f"Authentication failed: {e.message}"
            
        except CalDAVConnectionError as e:
            logger.log_connection_test(False, str(e))
            return False, f"Connection failed: {e.message}"
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.log_connection_test(False, error_msg)
            return False, error_msg
    
    def discover_calendars_for_account(self, account: CalDAVAccount, password: str) -> List[CalDAVCalendar]:
        """
        Discover all available calendars for a CalDAV account.
        
        Args:
            account: CalDAV account configuration
            password: Account password
            
        Returns:
            List of discovered calendars
            
        Raises:
            CalDAVConnectionError: If connection fails
            CalDAVAuthenticationError: If authentication fails
        """
        logger = CalDAVLogger(account.name)
        
        try:
            client = CalDAVClientFactory.create_client(account, password)
            
            # Test connection first
            if not client.test_connection():
                raise CalDAVConnectionError(f"Failed to connect to {account.name}")
            
            # Discover calendars
            calendars = client.discover_calendars()
            
            logger.log_calendar_discovery(len(calendars))
            return calendars
            
        except (CalDAVConnectionError, CalDAVAuthenticationError):
            raise
        except Exception as e:
            raise handle_caldav_exception(e)
    
    def discover_calendars_for_db_account(self, db_account: DBCalDAVAccount, encryption_key: str) -> List[CalDAVCalendar]:
        """
        Discover calendars for a database CalDAV account.
        
        Args:
            db_account: Database CalDAV account record
            encryption_key: Key for decrypting the password
            
        Returns:
            List of discovered calendars
        """
        # Convert database account to CalDAV account model
        account = CalDAVAccount(
            name=db_account.name,
            username=db_account.username,
            base_url=db_account.base_url,
            verify_ssl=db_account.verify_ssl
        )
        
        # Decrypt password
        password = db_account.get_password(encryption_key)
        
        return self.discover_calendars_for_account(account, password)
    
    def validate_account_configuration(self, account_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate CalDAV account configuration data.
        
        Args:
            account_data: Dictionary containing account configuration
            
        Returns:
            Tuple of (is_valid: bool, errors: List[str])
        """
        errors = []
        
        # Required fields
        required_fields = ['name', 'username', 'password', 'base_url']
        for field in required_fields:
            if not account_data.get(field):
                errors.append(f"{field} is required")
        
        # Validate base_url format
        base_url = account_data.get('base_url', '')
        if base_url and not (base_url.startswith('http://') or base_url.startswith('https://')):
            errors.append("base_url must start with http:// or https://")
        
        # Validate name length
        name = account_data.get('name', '')
        if len(name) > 100:
            errors.append("name must be 100 characters or less")
        
        # Validate username length
        username = account_data.get('username', '')
        if len(username) > 100:
            errors.append("username must be 100 characters or less")
        
        return len(errors) == 0, errors
    
    def get_calendar_info_summary(self, calendars: List[CalDAVCalendar]) -> Dict[str, Any]:
        """
        Generate a summary of discovered calendars.
        
        Args:
            calendars: List of discovered calendars
            
        Returns:
            Dictionary containing calendar summary information
        """
        return {
            "total_calendars": len(calendars),
            "calendars": [
                {
                    "id": cal.id,
                    "name": cal.name,
                    "description": cal.description,
                    "has_timezone": bool(cal.timezone),
                    "has_color": bool(cal.color),
                }
                for cal in calendars
            ],
            "discovered_at": datetime.utcnow().isoformat()
        }
    
    def filter_calendars_by_criteria(self, calendars: List[CalDAVCalendar], 
                                   name_filter: Optional[str] = None,
                                   exclude_empty: bool = False) -> List[CalDAVCalendar]:
        """
        Filter discovered calendars based on criteria.
        
        Args:
            calendars: List of calendars to filter
            name_filter: Optional name filter (case-insensitive substring match)
            exclude_empty: Whether to exclude calendars that appear to be empty
            
        Returns:
            Filtered list of calendars
        """
        filtered = calendars
        
        # Apply name filter
        if name_filter:
            name_filter_lower = name_filter.lower()
            filtered = [
                cal for cal in filtered 
                if name_filter_lower in cal.name.lower()
            ]
        
        # Note: exclude_empty would require fetching events from each calendar,
        # which could be expensive. For now, we'll skip this filter but leave
        # the parameter for future implementation.
        
        return filtered
    
    def recommend_sync_settings(self, calendars: List[CalDAVCalendar]) -> Dict[str, Any]:
        """
        Recommend sync settings based on discovered calendars.
        
        Args:
            calendars: List of discovered calendars
            
        Returns:
            Dictionary containing recommended settings
        """
        recommendations = {
            "sync_interval_minutes": self.settings.sync.default_interval_minutes,
            "sync_window_days": self.settings.sync.default_sync_window_days,
            "notes": []
        }
        
        # Adjust recommendations based on calendar count
        calendar_count = len(calendars)
        
        if calendar_count > 10:
            recommendations["sync_interval_minutes"] = max(
                recommendations["sync_interval_minutes"], 10
            )
            recommendations["notes"].append(
                "Increased sync interval due to large number of calendars"
            )
        
        if calendar_count > 20:
            recommendations["sync_window_days"] = min(
                recommendations["sync_window_days"], 14
            )
            recommendations["notes"].append(
                "Reduced sync window due to large number of calendars"
            )
        
        return recommendations


# Global discovery service instance
discovery_service = CalDAVDiscovery()


def get_discovery_service() -> CalDAVDiscovery:
    """Get the global CalDAV discovery service instance."""
    return discovery_service
