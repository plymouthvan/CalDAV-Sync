"""
Database models and setup for CalDAV Sync Microservice.

Uses SQLAlchemy with SQLite for lightweight, embedded storage.
Includes models for CalDAV accounts, Google OAuth tokens, calendar mappings,
event mappings, and sync logs.
"""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.dialects.sqlite import UUID
from cryptography.fernet import Fernet

from app.config import get_settings

Base = declarative_base()


class CalDAVAccount(Base):
    """CalDAV account credentials and configuration."""
    __tablename__ = "caldav_accounts"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)  # User-friendly name
    username = Column(String, nullable=False)
    password_encrypted = Column(Text, nullable=False)  # Encrypted password
    base_url = Column(String, nullable=False)
    verify_ssl = Column(Boolean, default=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_tested_at = Column(DateTime, nullable=True)
    last_test_success = Column(Boolean, nullable=True)
    
    # Relationships
    mappings = relationship("CalendarMapping", back_populates="caldav_account", cascade="all, delete-orphan")
    
    def set_password(self, password: str, encryption_key: str):
        """Encrypt and store password."""
        fernet = Fernet(encryption_key.encode())
        self.password_encrypted = fernet.encrypt(password.encode()).decode()
    
    def get_password(self, encryption_key: str) -> str:
        """Decrypt and return password."""
        fernet = Fernet(encryption_key.encode())
        return fernet.decrypt(self.password_encrypted.encode()).decode()


class GoogleOAuthToken(Base):
    """Google OAuth tokens for Calendar API access."""
    __tablename__ = "google_oauth_tokens"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_type = Column(String, default="Bearer")
    expires_at = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=True)  # JSON array of scopes
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def set_access_token(self, token: str, encryption_key: str):
        """Encrypt and store access token."""
        fernet = Fernet(encryption_key.encode())
        self.access_token_encrypted = fernet.encrypt(token.encode()).decode()
    
    def get_access_token(self, encryption_key: str) -> str:
        """Decrypt and return access token."""
        fernet = Fernet(encryption_key.encode())
        return fernet.decrypt(self.access_token_encrypted.encode()).decode()
    
    def set_refresh_token(self, token: str, encryption_key: str):
        """Encrypt and store refresh token."""
        fernet = Fernet(encryption_key.encode())
        self.refresh_token_encrypted = fernet.encrypt(token.encode()).decode()
    
    def get_refresh_token(self, encryption_key: str) -> Optional[str]:
        """Decrypt and return refresh token."""
        if not self.refresh_token_encrypted:
            return None
        fernet = Fernet(encryption_key.encode())
        return fernet.decrypt(self.refresh_token_encrypted.encode()).decode()


class CalendarMapping(Base):
    """Mapping between CalDAV calendar and Google Calendar."""
    __tablename__ = "calendar_mappings"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    caldav_account_id = Column(String, ForeignKey("caldav_accounts.id"), nullable=False)
    caldav_calendar_id = Column(String, nullable=False)  # CalDAV calendar identifier
    caldav_calendar_name = Column(String, nullable=False)  # Display name
    google_calendar_id = Column(String, nullable=False)  # Google Calendar ID
    google_calendar_name = Column(String, nullable=False)  # Display name
    sync_direction = Column(String, nullable=False, default="caldav_to_google")  # caldav_to_google, google_to_caldav, bidirectional
    sync_window_days = Column(Integer, default=30)  # Days forward to sync
    sync_interval_minutes = Column(Integer, default=5)  # Sync frequency
    webhook_url = Column(String, nullable=True)  # Optional webhook URL
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, nullable=True)  # success, partial_failure, failure
    
    # Relationships
    caldav_account = relationship("CalDAVAccount", back_populates="mappings")
    event_mappings = relationship("EventMapping", back_populates="calendar_mapping", cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="calendar_mapping", cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_caldav_account_calendar', 'caldav_account_id', 'caldav_calendar_id'),
        Index('idx_google_calendar', 'google_calendar_id'),
        Index('idx_enabled_mappings', 'enabled'),
    )


class EventMapping(Base):
    """Mapping between CalDAV event and Google Calendar event."""
    __tablename__ = "event_mappings"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mapping_id = Column(String, ForeignKey("calendar_mappings.id"), nullable=False)
    caldav_uid = Column(String, nullable=False)  # CalDAV event UID
    google_event_id = Column(String, nullable=True)  # Google Calendar event ID
    recurrence_id = Column(String, nullable=True)  # For recurring event instances
    last_caldav_modified = Column(DateTime, nullable=True)
    last_google_updated = Column(DateTime, nullable=True)
    sync_direction_last = Column(String, nullable=True)  # Which direction was last synced
    event_hash = Column(String, nullable=True)  # Hash of event content for change detection
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    calendar_mapping = relationship("CalendarMapping", back_populates="event_mappings")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_mapping_caldav_uid', 'mapping_id', 'caldav_uid'),
        Index('idx_mapping_google_id', 'mapping_id', 'google_event_id'),
        Index('idx_caldav_uid', 'caldav_uid'),
        Index('idx_google_event_id', 'google_event_id'),
    )


class SyncLog(Base):
    """Log of sync operations for audit and debugging."""
    __tablename__ = "sync_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mapping_id = Column(String, ForeignKey("calendar_mappings.id"), nullable=False)
    direction = Column(String, nullable=False)  # caldav_to_google, google_to_caldav, bidirectional
    status = Column(String, nullable=False)  # success, partial_failure, failure
    inserted_count = Column(Integer, default=0)
    updated_count = Column(Integer, default=0)
    deleted_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    webhook_sent = Column(Boolean, default=False)
    webhook_status = Column(String, nullable=True)  # success, failure, pending
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    # Relationships
    calendar_mapping = relationship("CalendarMapping", back_populates="sync_logs")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_mapping_started', 'mapping_id', 'started_at'),
        Index('idx_status_started', 'status', 'started_at'),
        Index('idx_webhook_pending', 'webhook_status'),
    )


class WebhookRetry(Base):
    """Queue for webhook retry attempts."""
    __tablename__ = "webhook_retries"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sync_log_id = Column(String, ForeignKey("sync_logs.id"), nullable=False)
    webhook_url = Column(String, nullable=False)
    payload = Column(Text, nullable=False)  # JSON payload
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_retry_at = Column(DateTime, nullable=False)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_next_retry', 'next_retry_at'),
        Index('idx_attempt_count', 'attempt_count'),
    )


class DatabaseManager:
    """Database connection and session management."""
    
    def __init__(self, database_url: Optional[str] = None):
        settings = get_settings()
        self.database_url = database_url or settings.database.url
        self.echo = settings.database.echo
        
        self.engine = create_engine(
            self.database_url,
            echo=self.echo,
            pool_pre_ping=True,  # Verify connections before use
            connect_args={"check_same_thread": False} if "sqlite" in self.database_url else {}
        )
        
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    def create_tables(self):
        """Create all database tables."""
        Base.metadata.create_all(bind=self.engine)
    
    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()
    
    def close(self):
        """Close database connections."""
        self.engine.dispose()


# Global database manager instance
db_manager = DatabaseManager()


def get_db() -> Session:
    """Dependency to get database session."""
    db = db_manager.get_session()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """Initialize database tables."""
    db_manager.create_tables()


def get_database_manager() -> DatabaseManager:
    """Get the global database manager instance."""
    return db_manager
