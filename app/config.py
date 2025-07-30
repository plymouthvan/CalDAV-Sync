"""
Configuration management for CalDAV Sync Microservice.

Supports multiple configuration sources with precedence:
1. Environment variables (highest priority)
2. config.yaml file
3. Database settings
4. Default values (lowest priority)
"""

import os
import yaml
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ServerConfig(BaseSettings):
    """Server configuration settings."""
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)
    reload: bool = Field(default=False)
    base_url: str = Field(default="http://localhost:8000")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class DatabaseConfig(BaseSettings):
    """Database configuration settings."""
    url: str = Field(default="sqlite:///./caldav_sync.db")
    echo: bool = Field(default=False)
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class GoogleConfig(BaseSettings):
    """Google OAuth and Calendar API configuration."""
    client_id: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_ID")
    client_secret: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    scopes: List[str] = Field(default=["https://www.googleapis.com/auth/calendar"])
    redirect_uri: str = Field(default="/oauth/callback")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class SecurityConfig(BaseSettings):
    """Security and encryption configuration."""
    api_key: Optional[str] = Field(default=None)
    secret_key: Optional[str] = Field(default="test-secret-key")
    encryption_key: Optional[str] = Field(default="test-encryption-key-32-chars-long")
    require_auth_for_external: bool = Field(default=True)
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class SyncConfig(BaseSettings):
    """Sync operation configuration."""
    default_interval_minutes: int = Field(default=5, env="DEFAULT_SYNC_INTERVAL_MINUTES")
    default_sync_window_days: int = Field(default=30, env="DEFAULT_SYNC_WINDOW_DAYS")
    max_concurrent_mappings: int = Field(default=5, env="MAX_CONCURRENT_MAPPINGS")
    batch_size: int = Field(default=100, env="SYNC_BATCH_SIZE")
    retry_attempts: int = Field(default=3, env="SYNC_RETRY_ATTEMPTS")
    retry_delay_seconds: int = Field(default=60, env="SYNC_RETRY_DELAY_SECONDS")


class WebhookConfig(BaseSettings):
    """Webhook configuration."""
    timeout_seconds: int = Field(default=30, env="WEBHOOK_TIMEOUT_SECONDS")
    max_retries: int = Field(default=3, env="WEBHOOK_MAX_RETRIES")
    retry_delays: List[int] = Field(default=[30, 300, 1800])  # 30s, 5m, 30m
    include_event_details: bool = Field(default=True, env="WEBHOOK_INCLUDE_EVENT_DETAILS")


class APIConfig(BaseSettings):
    """API configuration."""
    rate_limit_per_minute: int = Field(default=60, env="API_RATE_LIMIT_PER_MINUTE")
    enable_cors: bool = Field(default=True, env="API_ENABLE_CORS")
    cors_origins: List[str] = Field(default=["*"])


class LoggingConfig(BaseSettings):
    """Logging configuration."""
    level: str = Field(default="INFO", env="LOG_LEVEL")
    format: str = Field(default="json", env="LOG_FORMAT")  # json or text
    log_webhook_failures: bool = Field(default=True, env="LOG_WEBHOOK_FAILURES")
    log_conflict_resolutions: bool = Field(default=True, env="LOG_CONFLICT_RESOLUTIONS")
    log_sync_summaries: bool = Field(default=True, env="LOG_SYNC_SUMMARIES")


class CalDAVConfig(BaseSettings):
    """CalDAV client configuration."""
    connection_timeout: int = Field(default=30, env="CALDAV_CONNECTION_TIMEOUT")
    read_timeout: int = Field(default=60, env="CALDAV_READ_TIMEOUT")
    max_retries: int = Field(default=3, env="CALDAV_MAX_RETRIES")
    verify_ssl: bool = Field(default=True, env="CALDAV_VERIFY_SSL")


class GoogleCalendarConfig(BaseSettings):
    """Google Calendar API configuration."""
    batch_size: int = Field(default=50, env="GOOGLE_CALENDAR_BATCH_SIZE")
    rate_limit_delay: float = Field(default=0.1, env="GOOGLE_CALENDAR_RATE_LIMIT_DELAY")
    max_results_per_request: int = Field(default=2500, env="GOOGLE_CALENDAR_MAX_RESULTS")


class UIConfig(BaseSettings):
    """Web UI configuration."""
    theme: str = Field(default="light", env="UI_THEME")  # light or dark
    items_per_page: int = Field(default=20, env="UI_ITEMS_PER_PAGE")
    auto_refresh_interval: int = Field(default=30, env="UI_AUTO_REFRESH_INTERVAL")


class DevelopmentConfig(BaseSettings):
    """Development-only configuration."""
    mock_caldav: bool = Field(default=False, env="DEV_MOCK_CALDAV")
    mock_google: bool = Field(default=False, env="DEV_MOCK_GOOGLE")
    log_all_requests: bool = Field(default=False, env="DEV_LOG_ALL_REQUESTS")
    enable_api_docs: bool = Field(default=True, env="DEV_ENABLE_API_DOCS")


class Settings:
    """Main configuration class that aggregates all config sections."""
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or "config.yaml"
        self._yaml_config = self._load_yaml_config()
        
        # Initialize all configuration sections
        self.server = self._init_config(ServerConfig)
        self.database = self._init_config(DatabaseConfig)
        self.google = self._init_config(GoogleConfig)
        self.security = self._init_config(SecurityConfig)
        self.sync = self._init_config(SyncConfig)
        self.webhooks = self._init_config(WebhookConfig)
        self.api = self._init_config(APIConfig)
        self.logging = self._init_config(LoggingConfig)
        self.caldav = self._init_config(CalDAVConfig)
        self.google_calendar = self._init_config(GoogleCalendarConfig)
        self.ui = self._init_config(UIConfig)
        self.development = self._init_config(DevelopmentConfig)
    
    def _load_yaml_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file if it exists."""
        config_path = Path(self.config_file)
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Warning: Failed to load {self.config_file}: {e}")
                return {}
        return {}
    
    def _init_config(self, config_class):
        """Initialize a configuration section with YAML overrides."""
        # Get the section name from the class name (remove 'Config' suffix)
        section_name = config_class.__name__.lower().replace('config', '')
        
        # Get YAML values for this section
        yaml_values = self._yaml_config.get(section_name, {})
        
        # Create the config instance with YAML values as defaults
        # Environment variables will still take precedence
        return config_class(**yaml_values)
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.server.debug
    
    def validate_required_settings(self) -> List[str]:
        """Validate that all required settings are present."""
        errors = []
        
        # Debug logging
        print(f"DEBUG: google.client_id = '{self.google.client_id}' (type: {type(self.google.client_id)})")
        print(f"DEBUG: google.client_secret = '{self.google.client_secret}' (type: {type(self.google.client_secret)})")
        print(f"DEBUG: security.secret_key = '{self.security.secret_key}' (type: {type(self.security.secret_key)})")
        print(f"DEBUG: security.encryption_key = '{self.security.encryption_key}' (type: {type(self.security.encryption_key)})")
        
        if not self.google.client_id:
            errors.append("GOOGLE_CLIENT_ID is required")
        
        if not self.google.client_secret:
            errors.append("GOOGLE_CLIENT_SECRET is required")
        
        if not self.security.secret_key:
            errors.append("SECRET_KEY is required")
        
        if not self.security.encryption_key:
            errors.append("ENCRYPTION_KEY is required")
        
        return errors


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings


def reload_settings(config_file: Optional[str] = None) -> Settings:
    """Reload settings from configuration sources."""
    global settings
    settings = Settings(config_file)
    return settings
