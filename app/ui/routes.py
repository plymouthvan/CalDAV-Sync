"""
Web UI routes for CalDAV Sync Microservice.

Serves HTML templates for the configuration interface.
"""

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.security import optional_api_key_auth
from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger("ui.routes")

# Initialize templates
templates = Jinja2Templates(directory="app/templates")

# Create router
router = APIRouter(tags=["Web UI"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(optional_api_key_auth)
):
    """Main dashboard page."""
    try:
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "title": "Dashboard"
        })
    except Exception as e:
        logger.error(f"Error rendering dashboard: {e}")
        raise HTTPException(status_code=500, detail="Error loading dashboard")


@router.get("/accounts", response_class=HTMLResponse)
async def caldav_accounts(
    request: Request,
    _: bool = Depends(optional_api_key_auth)
):
    """CalDAV accounts management page."""
    try:
        return templates.TemplateResponse("caldav_accounts.html", {
            "request": request,
            "title": "CalDAV Accounts"
        })
    except Exception as e:
        logger.error(f"Error rendering CalDAV accounts page: {e}")
        raise HTTPException(status_code=500, detail="Error loading CalDAV accounts page")


@router.get("/mappings", response_class=HTMLResponse)
async def calendar_mappings(
    request: Request,
    _: bool = Depends(optional_api_key_auth)
):
    """Calendar mappings management page."""
    try:
        return templates.TemplateResponse("calendar_mappings.html", {
            "request": request,
            "title": "Calendar Mappings"
        })
    except Exception as e:
        logger.error(f"Error rendering calendar mappings page: {e}")
        raise HTTPException(status_code=500, detail="Error loading calendar mappings page")


@router.get("/sync", response_class=HTMLResponse)
async def sync_status(
    request: Request,
    _: bool = Depends(optional_api_key_auth)
):
    """Sync status and operations page."""
    try:
        return templates.TemplateResponse("sync_status.html", {
            "request": request,
            "title": "Sync Status"
        })
    except Exception as e:
        logger.error(f"Error rendering sync status page: {e}")
        raise HTTPException(status_code=500, detail="Error loading sync status page")


@router.get("/sync/history", response_class=HTMLResponse)
async def sync_history(
    request: Request,
    _: bool = Depends(optional_api_key_auth)
):
    """Sync history page."""
    try:
        return templates.TemplateResponse("sync_history.html", {
            "request": request,
            "title": "Sync History"
        })
    except Exception as e:
        logger.error(f"Error rendering sync history page: {e}")
        raise HTTPException(status_code=500, detail="Error loading sync history page")


@router.get("/google", response_class=HTMLResponse)
async def google_auth(
    request: Request,
    _: bool = Depends(optional_api_key_auth)
):
    """Google authentication management page."""
    try:
        return templates.TemplateResponse("google_auth.html", {
            "request": request,
            "title": "Google Authentication"
        })
    except Exception as e:
        logger.error(f"Error rendering Google auth page: {e}")
        raise HTTPException(status_code=500, detail="Error loading Google auth page")


@router.get("/status", response_class=HTMLResponse)
async def system_status(
    request: Request,
    _: bool = Depends(optional_api_key_auth)
):
    """System status page."""
    try:
        return templates.TemplateResponse("system_status.html", {
            "request": request,
            "title": "System Status"
        })
    except Exception as e:
        logger.error(f"Error rendering system status page: {e}")
        raise HTTPException(status_code=500, detail="Error loading system status page")


@router.get("/setup", response_class=HTMLResponse)
async def setup_wizard(
    request: Request,
    _: bool = Depends(optional_api_key_auth)
):
    """Initial setup wizard page."""
    try:
        return templates.TemplateResponse("setup_wizard.html", {
            "request": request,
            "title": "Setup Wizard"
        })
    except Exception as e:
        logger.error(f"Error rendering setup wizard: {e}")
        raise HTTPException(status_code=500, detail="Error loading setup wizard")


# Helper function to add context to all templates
def add_global_context(request: Request, context: dict) -> dict:
    """Add global context variables to template context."""
    settings = get_settings()
    
    context.update({
        "request": request,
        "settings": {
            "app_name": "CalDAV Sync Microservice",
            "version": "1.0.0",
            "debug": settings.development.debug,
            "api_docs_enabled": settings.development.enable_api_docs
        }
    })
    
    return context
