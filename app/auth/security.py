"""
API security and authentication for CalDAV Sync Microservice.

Handles API key authentication with localhost exception and request validation.
"""

from typing import Optional
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import ipaddress

from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.exceptions import AuthenticationError, AuthorizationError

logger = get_logger("security")
security = HTTPBearer(auto_error=False)


def is_localhost(host: str) -> bool:
    """
    Check if the given host is localhost or internal network.
    
    Args:
        host: Host address to check
        
    Returns:
        True if host is localhost or internal network, False otherwise
    """
    try:
        # Handle IPv6 localhost
        if host in ['localhost', '127.0.0.1', '::1']:
            return True
        
        # Check if it's a loopback address
        ip = ipaddress.ip_address(host)
        if ip.is_loopback:
            return True
        
        # Check if it's a private/internal network address
        # This includes Docker networks (172.x.x.x), private networks (192.168.x.x, 10.x.x.x)
        if ip.is_private:
            return True
            
        return False
    
    except ValueError:
        # Not a valid IP address, check if it's localhost hostname
        return host.lower() == 'localhost'


def get_client_host(request: Request) -> str:
    """
    Get the client host from the request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Client host address
    """
    # Check for forwarded headers (reverse proxy)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # Take the first IP in the chain
        return forwarded_for.split(',')[0].strip()
    
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip.strip()
    
    # Fall back to direct client host
    return request.client.host if request.client else 'unknown'


def require_api_key_unless_localhost(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> bool:
    """
    Require API key for non-localhost requests.
    
    Args:
        request: FastAPI request object
        credentials: HTTP authorization credentials
        
    Returns:
        True if authenticated
        
    Raises:
        HTTPException: If authentication fails
    """
    settings = get_settings()
    client_host = get_client_host(request)
    
    # Allow localhost without API key
    if is_localhost(client_host):
        logger.debug(f"Allowing localhost request from {client_host}")
        return True
    
    # Require API key for external requests
    if not settings.security.api_key:
        logger.warning("API key not configured but external request received")
        raise HTTPException(
            status_code=401,
            detail="API key authentication required but not configured"
        )
    
    if not credentials:
        logger.warning(f"Missing API key for external request from {client_host}")
        raise HTTPException(
            status_code=401,
            detail="API key required for external requests",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    if credentials.credentials != settings.security.api_key:
        logger.warning(f"Invalid API key for request from {client_host}")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    logger.debug(f"API key authenticated for request from {client_host}")
    return True


def optional_api_key_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> bool:
    """
    Optional API key authentication (doesn't raise exceptions).
    
    Args:
        request: FastAPI request object
        credentials: HTTP authorization credentials
        
    Returns:
        True if authenticated (including localhost), False otherwise
    """
    try:
        return require_api_key_unless_localhost(request, credentials)
    except HTTPException:
        return False


def require_google_auth():
    """
    Dependency to require valid Google authentication.
    
    Returns:
        True if Google OAuth is valid
        
    Raises:
        HTTPException: If Google authentication is not valid
    """
    from app.auth.google_oauth import get_oauth_manager
    
    oauth_manager = get_oauth_manager()
    credentials = oauth_manager.get_valid_credentials()
    
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Google Calendar authentication required. Please complete OAuth flow."
        )
    
    return True


def get_request_info(request: Request) -> dict:
    """
    Get request information for logging.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Dictionary with request information
    """
    client_host = get_client_host(request)
    
    return {
        "method": request.method,
        "url": str(request.url),
        "client_host": client_host,
        "is_localhost": is_localhost(client_host),
        "user_agent": request.headers.get("User-Agent"),
        "forwarded_for": request.headers.get("X-Forwarded-For"),
        "real_ip": request.headers.get("X-Real-IP")
    }


from starlette.middleware.base import BaseHTTPMiddleware

class SecurityMiddleware(BaseHTTPMiddleware):
    """Middleware for security logging and rate limiting."""
    
    def __init__(self, app):
        super().__init__(app)
        self.settings = get_settings()
    
    async def dispatch(self, request: Request, call_next):
        """Process request with security checks."""
        request_info = get_request_info(request)
        
        # Log request if configured
        if self.settings.development.log_all_requests:
            logger.info(f"Request: {request_info}")
        
        # Process request
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Add CORS headers if enabled
        if self.settings.api.enable_cors:
            origin = request.headers.get("Origin")
            if origin and (origin in self.settings.api.cors_origins or "*" in self.settings.api.cors_origins):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            elif "*" in self.settings.api.cors_origins:
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        
        return response


def create_api_key() -> str:
    """
    Generate a secure API key.
    
    Returns:
        Generated API key
    """
    import secrets
    import string
    
    # Generate a 32-character API key
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(32))


def validate_api_key_format(api_key: str) -> bool:
    """
    Validate API key format.
    
    Args:
        api_key: API key to validate
        
    Returns:
        True if format is valid
    """
    if not api_key:
        return False
    
    # Check length (should be at least 16 characters)
    if len(api_key) < 16:
        return False
    
    # Check that it contains only alphanumeric characters
    return api_key.isalnum()


# Rate limiting (simple in-memory implementation)
class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self):
        self.requests = {}  # {client_ip: [timestamp, ...]}
        self.settings = get_settings()
    
    def is_allowed(self, client_ip: str) -> bool:
        """
        Check if request is allowed based on rate limit.
        
        Args:
            client_ip: Client IP address
            
        Returns:
            True if request is allowed
        """
        import time
        
        now = time.time()
        window = 60  # 1 minute window
        limit = self.settings.api.rate_limit_per_minute
        
        # Clean old requests
        if client_ip in self.requests:
            self.requests[client_ip] = [
                timestamp for timestamp in self.requests[client_ip]
                if now - timestamp < window
            ]
        else:
            self.requests[client_ip] = []
        
        # Check if limit exceeded
        if len(self.requests[client_ip]) >= limit:
            return False
        
        # Add current request
        self.requests[client_ip].append(now)
        return True


# Global rate limiter instance
rate_limiter = RateLimiter()


def check_rate_limit(request: Request) -> bool:
    """
    Check rate limit for request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        True if request is allowed
        
    Raises:
        HTTPException: If rate limit exceeded
    """
    client_host = get_client_host(request)
    
    # Skip rate limiting for localhost
    if is_localhost(client_host):
        return True
    
    if not rate_limiter.is_allowed(client_host):
        logger.warning(f"Rate limit exceeded for {client_host}")
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": "60"}
        )
    
    return True
