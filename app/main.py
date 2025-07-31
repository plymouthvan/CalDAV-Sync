"""
Main FastAPI application for CalDAV Sync Microservice.

Configures the FastAPI app with all routers, middleware, and startup/shutdown events.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from app.config import get_settings
from app.database import get_database_manager
from app.sync.scheduler import get_sync_scheduler
from app.sync.webhook import get_webhook_retry_processor
from app.auth.security import SecurityMiddleware
from app.utils.logging import get_logger
from app.utils.exceptions import (
    CalDAVError, GoogleCalendarError, SyncError, 
    AuthenticationError, AuthorizationError
)

# Import API routers
from app.api import caldav, google, mappings, sync, status
from app.api.models import ErrorResponse, ValidationErrorResponse

# Import UI router
from app.ui import router as ui_router

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    settings = get_settings()
    
    # Startup
    logger.info("Starting CalDAV Sync Microservice...")
    
    try:
        # Validate required configuration
        logger.info("Validating configuration...")
        config_errors = settings.validate_required_settings()
        if config_errors:
            logger.error(f"Configuration validation failed: {config_errors}")
            raise ValueError(f"Missing required configuration: {', '.join(config_errors)}")
        logger.info("Configuration validation passed")
        
        # Test encryption key format
        logger.info("Testing encryption key...")
        logger.info(f"ENCRYPTION_KEY value: '{settings.security.encryption_key}'")
        logger.info(f"ENCRYPTION_KEY length: {len(settings.security.encryption_key) if settings.security.encryption_key else 'None'}")
        logger.info(f"ENCRYPTION_KEY type: {type(settings.security.encryption_key)}")
        
        try:
            from cryptography.fernet import Fernet
            encoded_key = settings.security.encryption_key.encode()
            logger.info(f"Encoded key length: {len(encoded_key)} bytes")
            logger.info(f"Encoded key (first 20 chars): {encoded_key[:20]}...")
            
            test_fernet = Fernet(encoded_key)
            logger.info("Encryption key format is valid")
        except Exception as e:
            logger.error(f"Invalid encryption key format: {e}")
            logger.error(f"Fernet requires a 32-byte URL-safe base64-encoded key")
            logger.error(f"Current key appears to be plain text, not base64-encoded")
            raise ValueError(f"Invalid ENCRYPTION_KEY format: {e}")
        
        # Log database configuration
        import os
        logger.info(f"=== DATABASE CONFIGURATION DEBUG ===")
        logger.info(f"DATABASE_URL environment variable: {os.environ.get('DATABASE_URL', 'NOT SET')}")
        logger.info(f"Resolved database URL: {settings.database.url}")
        
        # Check data directory
        data_dir = "/app/data"
        logger.info(f"Data directory exists: {os.path.exists(data_dir)}")
        if os.path.exists(data_dir):
            logger.info(f"Data directory contents: {os.listdir(data_dir)}")
        
        # Initialize database
        logger.info("Initializing database...")
        try:
            db_manager = get_database_manager()
            db_manager.create_tables()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
        
        # Start scheduler
        logger.info("Starting sync scheduler...")
        try:
            scheduler = get_sync_scheduler()
            await scheduler.start()
            logger.info("Sync scheduler started successfully")
        except Exception as e:
            logger.error(f"Sync scheduler startup failed: {e}")
            raise
        
        # Start webhook retry processor
        logger.info("Starting webhook retry processor...")
        try:
            webhook_processor = get_webhook_retry_processor()
            await webhook_processor.start()
            logger.info("Webhook retry processor started successfully")
        except Exception as e:
            logger.error(f"Webhook retry processor startup failed: {e}")
            raise
        
        logger.info("CalDAV Sync Microservice startup complete")
        
    except Exception as e:
        logger.error(f"Startup failed with error: {type(e).__name__}: {e}")
        logger.error(f"Full error details:", exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down CalDAV Sync Microservice...")
    
    try:
        # Stop webhook retry processor
        webhook_processor = get_webhook_retry_processor()
        await webhook_processor.stop()
        logger.info("Webhook retry processor stopped")
        
        # Stop scheduler
        scheduler = get_sync_scheduler()
        await scheduler.stop()
        logger.info("Sync scheduler stopped")
        
        logger.info("CalDAV Sync Microservice shutdown complete")
        
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    
    # Create FastAPI app
    app = FastAPI(
        title="CalDAV Sync Microservice",
        description="Synchronizes CalDAV calendars with Google Calendar",
        version="1.0.0",
        docs_url="/docs" if settings.development.enable_api_docs else None,
        redoc_url="/redoc" if settings.development.enable_api_docs else None,
        openapi_url="/openapi.json" if settings.development.enable_api_docs else None,
        lifespan=lifespan
    )
    
    # Add CORS middleware
    if settings.api.enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
    
    # Add security middleware
    app.add_middleware(SecurityMiddleware)
    
    # Include API routers
    app.include_router(caldav.router, prefix="/api")
    app.include_router(google.router, prefix="/api")
    app.include_router(mappings.router, prefix="/api")
    app.include_router(sync.router, prefix="/api")
    app.include_router(status.router, prefix="/api")
    
    # Include UI router
    app.include_router(ui_router)
    
    # Add OAuth callback route at root level for Google OAuth
    @app.get("/oauth/callback")
    async def oauth_callback_redirect(request: Request):
        """Redirect OAuth callback to the API endpoint."""
        from fastapi.responses import RedirectResponse
        query_params = str(request.url.query)
        return RedirectResponse(url=f"/api/google/oauth/callback?{query_params}")
    
    # Mount static files (for web UI)
    try:
        app.mount("/static", StaticFiles(directory="app/static"), name="static")
    except RuntimeError:
        # Static directory doesn't exist yet - will be created with web UI
        pass
    
    # Add exception handlers
    add_exception_handlers(app)
    
    return app


def add_exception_handlers(app: FastAPI):
    """Add custom exception handlers to the FastAPI app."""
    
    @app.exception_handler(CalDAVError)
    async def caldav_exception_handler(request: Request, exc: CalDAVError):
        """Handle CalDAV-related errors."""
        logger.warning(f"CalDAV error: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "CalDAV Error",
                "detail": str(exc),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    @app.exception_handler(GoogleCalendarError)
    async def google_exception_handler(request: Request, exc: GoogleCalendarError):
        """Handle Google Calendar-related errors."""
        logger.warning(f"Google Calendar error: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "Google Calendar Error",
                "detail": str(exc),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    @app.exception_handler(SyncError)
    async def sync_exception_handler(request: Request, exc: SyncError):
        """Handle sync-related errors."""
        logger.error(f"Sync error: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Sync Error",
                "detail": str(exc),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    @app.exception_handler(AuthenticationError)
    async def auth_exception_handler(request: Request, exc: AuthenticationError):
        """Handle authentication errors."""
        logger.warning(f"Authentication error: {exc}")
        return JSONResponse(
            status_code=401,
            content={
                "error": "Authentication Error",
                "detail": str(exc),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    @app.exception_handler(AuthorizationError)
    async def authz_exception_handler(request: Request, exc: AuthorizationError):
        """Handle authorization errors."""
        logger.warning(f"Authorization error: {exc}")
        return JSONResponse(
            status_code=403,
            content={
                "error": "Authorization Error",
                "detail": str(exc),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """Handle validation errors."""
        logger.warning(f"Validation error: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "error": "Validation Error",
                "detail": str(exc),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: HTTPException):
        """Handle 404 errors."""
        logger.warning(f"404 error for path: {request.url.path}")
        return JSONResponse(
            status_code=404,
            content={
                "error": "Not Found",
                "detail": "The requested resource was not found",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: HTTPException):
        """Handle internal server errors."""
        logger.error(f"Internal server error: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": "An unexpected error occurred",
                "timestamp": datetime.utcnow().isoformat()
            }
        )


# Create the app instance
app = create_app()


def main():
    """Main entry point for running the application."""
    settings = get_settings()
    
    # Configure uvicorn
    config = {
        "app": "app.main:app",
        "host": settings.server.host,
        "port": settings.server.port,
        "reload": settings.development.debug,
        "log_level": "info" if not settings.development.debug else "debug",
        "access_log": settings.development.log_all_requests,
    }
    
    # Add SSL configuration if provided
    if settings.server.ssl_cert_file and settings.server.ssl_key_file:
        config.update({
            "ssl_certfile": settings.server.ssl_cert_file,
            "ssl_keyfile": settings.server.ssl_key_file
        })
    
    logger.info(f"Starting server on {settings.server.host}:{settings.server.port}")
    
    # Run the server
    uvicorn.run(**config)


if __name__ == "__main__":
    main()
