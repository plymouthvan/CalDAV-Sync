"""
CalDAV account management API endpoints.

Handles CRUD operations for CalDAV accounts, connection testing,
and calendar discovery.
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db, CalDAVAccount as DBCalDAVAccount
from app.caldav.discovery import get_discovery_service
from app.caldav.models import CalDAVAccount
from app.api.models import (
    CalDAVAccountCreate, CalDAVAccountUpdate, CalDAVAccountResponse,
    CalDAVAccountTest, CalDAVAccountTestResponse,
    CalendarDiscoveryRequest, CalendarDiscoveryResponse,
    CalDAVCalendarResponse, ErrorResponse
)
from app.auth.security import require_api_key_unless_localhost, check_rate_limit
from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.exceptions import CalDAVConnectionError, CalDAVAuthenticationError

logger = get_logger("api.caldav")
router = APIRouter(prefix="/caldav", tags=["CalDAV Accounts"])


@router.get("/accounts", response_model=List[CalDAVAccountResponse])
async def list_caldav_accounts(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """List all CalDAV accounts."""
    try:
        accounts = db.query(DBCalDAVAccount).all()
        return [CalDAVAccountResponse.from_orm(account) for account in accounts]
    except Exception as e:
        logger.error(f"Failed to list CalDAV accounts: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve CalDAV accounts")


@router.post("/accounts", response_model=CalDAVAccountResponse, status_code=201)
async def create_caldav_account(
    account_data: CalDAVAccountCreate,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Create a new CalDAV account."""
    try:
        settings = get_settings()
        
        # Check if account with same name already exists
        existing = db.query(DBCalDAVAccount).filter(
            DBCalDAVAccount.name == account_data.name
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"CalDAV account with name '{account_data.name}' already exists"
            )
        
        # Test connection before creating
        test_account = CalDAVAccount(
            name=account_data.name,
            username=account_data.username,
            base_url=account_data.base_url,
            verify_ssl=account_data.verify_ssl
        )
        
        discovery_service = get_discovery_service()
        success, error_message = discovery_service.test_account_connection(
            test_account, account_data.password
        )
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"CalDAV connection test failed: {error_message}"
            )
        
        # Create account
        db_account = DBCalDAVAccount(
            name=account_data.name,
            username=account_data.username,
            base_url=account_data.base_url,
            verify_ssl=account_data.verify_ssl,
            enabled=True,
            last_tested_at=datetime.utcnow(),
            last_test_success=True
        )
        
        # Encrypt and store password
        db_account.set_password(account_data.password, settings.security.encryption_key)
        
        db.add(db_account)
        db.commit()
        db.refresh(db_account)
        
        logger.info(f"Created CalDAV account: {account_data.name}")
        return CalDAVAccountResponse.from_orm(db_account)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create CalDAV account: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create CalDAV account")


@router.get("/accounts/{account_id}", response_model=CalDAVAccountResponse)
async def get_caldav_account(
    account_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Get a specific CalDAV account."""
    try:
        account = db.query(DBCalDAVAccount).filter(
            DBCalDAVAccount.id == account_id
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="CalDAV account not found")
        
        return CalDAVAccountResponse.from_orm(account)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get CalDAV account {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve CalDAV account")


@router.put("/accounts/{account_id}", response_model=CalDAVAccountResponse)
async def update_caldav_account(
    account_id: str,
    account_data: CalDAVAccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Update a CalDAV account."""
    try:
        settings = get_settings()
        
        account = db.query(DBCalDAVAccount).filter(
            DBCalDAVAccount.id == account_id
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="CalDAV account not found")
        
        # Check for name conflicts if name is being changed
        if account_data.name and account_data.name != account.name:
            existing = db.query(DBCalDAVAccount).filter(
                DBCalDAVAccount.name == account_data.name,
                DBCalDAVAccount.id != account_id
            ).first()
            
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"CalDAV account with name '{account_data.name}' already exists"
                )
        
        # Update fields
        update_data = account_data.dict(exclude_unset=True)
        
        # Test connection if credentials are being changed
        test_needed = any(field in update_data for field in ['username', 'password', 'base_url', 'verify_ssl'])
        
        if test_needed:
            test_account = CalDAVAccount(
                name=update_data.get('name', account.name),
                username=update_data.get('username', account.username),
                base_url=update_data.get('base_url', account.base_url),
                verify_ssl=update_data.get('verify_ssl', account.verify_ssl)
            )
            
            # Use new password if provided, otherwise decrypt existing
            if 'password' in update_data:
                test_password = update_data['password']
            else:
                test_password = account.get_password(settings.security.encryption_key)
            
            discovery_service = get_discovery_service()
            success, error_message = discovery_service.test_account_connection(
                test_account, test_password
            )
            
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail=f"CalDAV connection test failed: {error_message}"
                )
            
            # Update test results
            account.last_tested_at = datetime.utcnow()
            account.last_test_success = True
        
        # Apply updates
        for field, value in update_data.items():
            if field == 'password':
                account.set_password(value, settings.security.encryption_key)
            else:
                setattr(account, field, value)
        
        account.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(account)
        
        logger.info(f"Updated CalDAV account: {account.name}")
        return CalDAVAccountResponse.from_orm(account)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update CalDAV account {account_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update CalDAV account")


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_caldav_account(
    account_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Delete a CalDAV account."""
    try:
        account = db.query(DBCalDAVAccount).filter(
            DBCalDAVAccount.id == account_id
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="CalDAV account not found")
        
        # Check if account is used in any mappings
        from app.database import CalendarMapping
        mappings = db.query(CalendarMapping).filter(
            CalendarMapping.caldav_account_id == account_id
        ).count()
        
        if mappings > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete CalDAV account: {mappings} calendar mappings depend on it"
            )
        
        db.delete(account)
        db.commit()
        
        logger.info(f"Deleted CalDAV account: {account.name}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete CalDAV account {account_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete CalDAV account")


@router.post("/test", response_model=CalDAVAccountTestResponse)
async def test_caldav_connection(
    test_data: CalDAVAccountTest,
    request: Request,
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Test CalDAV connection without creating an account."""
    try:
        test_account = CalDAVAccount(
            name="test",
            username=test_data.username,
            base_url=test_data.base_url,
            verify_ssl=test_data.verify_ssl
        )
        
        discovery_service = get_discovery_service()
        success, error_message = discovery_service.test_account_connection(
            test_account, test_data.password
        )
        
        return CalDAVAccountTestResponse(
            success=success,
            error_message=error_message
        )
        
    except Exception as e:
        logger.error(f"CalDAV connection test failed: {e}")
        return CalDAVAccountTestResponse(
            success=False,
            error_message=str(e)
        )


@router.post("/accounts/{account_id}/test", response_model=CalDAVAccountTestResponse)
async def test_existing_caldav_account(
    account_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Test connection for an existing CalDAV account."""
    try:
        settings = get_settings()
        
        account = db.query(DBCalDAVAccount).filter(
            DBCalDAVAccount.id == account_id
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="CalDAV account not found")
        
        test_account = CalDAVAccount(
            name=account.name,
            username=account.username,
            base_url=account.base_url,
            verify_ssl=account.verify_ssl
        )
        
        password = account.get_password(settings.security.encryption_key)
        
        discovery_service = get_discovery_service()
        success, error_message = discovery_service.test_account_connection(
            test_account, password
        )
        
        # Update test results
        account.last_tested_at = datetime.utcnow()
        account.last_test_success = success
        db.commit()
        
        return CalDAVAccountTestResponse(
            success=success,
            error_message=error_message
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test CalDAV account {account_id}: {e}")
        return CalDAVAccountTestResponse(
            success=False,
            error_message=str(e)
        )


@router.get("/accounts/{account_id}/calendars", response_model=CalendarDiscoveryResponse)
async def discover_calendars(
    account_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(require_api_key_unless_localhost),
    __: bool = Depends(check_rate_limit)
):
    """Discover calendars for a CalDAV account."""
    try:
        settings = get_settings()
        
        account = db.query(DBCalDAVAccount).filter(
            DBCalDAVAccount.id == account_id
        ).first()
        
        if not account:
            raise HTTPException(status_code=404, detail="CalDAV account not found")
        
        if not account.enabled:
            raise HTTPException(status_code=400, detail="CalDAV account is disabled")
        
        discovery_service = get_discovery_service()
        calendars = discovery_service.discover_calendars_for_db_account(
            account, settings.security.encryption_key
        )
        
        calendar_responses = [
            CalDAVCalendarResponse(
                id=cal.id,
                name=cal.name,
                description=cal.description,
                color=cal.color,
                timezone=cal.timezone,
                url=cal.url
            )
            for cal in calendars
        ]
        
        return CalendarDiscoveryResponse(
            account_id=account_id,
            calendars=calendar_responses,
            discovered_at=datetime.utcnow()
        )
        
    except HTTPException:
        raise
    except (CalDAVConnectionError, CalDAVAuthenticationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to discover calendars for account {account_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to discover calendars")
