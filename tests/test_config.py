"""
Tests for configuration system.

Tests multi-source configuration loading, validation, and settings management.
"""

import pytest
import os
import tempfile
import yaml
from unittest.mock import patch

from app.config import Settings, get_settings


class TestSettings:
    """Test the Settings configuration class."""
    
    def test_default_settings(self):
        """Test default settings values."""
        settings = Settings()
        
        assert settings.environment == "development"
        assert settings.database.url == "sqlite:///./caldav_sync.db"
        assert settings.server.host == "0.0.0.0"
        assert settings.server.port == 8000
        assert settings.sync.default_interval_minutes == 5
        assert settings.sync.default_sync_window_days == 30
        assert settings.api.rate_limit_per_minute == 60
        assert settings.development.debug is False
        assert settings.development.enable_api_docs is True
    
    def test_environment_override(self):
        """Test environment variable override."""
        with patch.dict(os.environ, {
            'ENVIRONMENT': 'production',
            'SERVER_HOST': '127.0.0.1',
            'SERVER_PORT': '9000',
            'DATABASE_URL': 'postgresql://test:test@localhost/test',
            'SYNC_DEFAULT_INTERVAL_MINUTES': '10',
            'API_RATE_LIMIT_PER_MINUTE': '120',
            'DEVELOPMENT_DEBUG': 'true',
            'SECURITY_API_KEY': 'test-api-key'
        }):
            settings = Settings()
            
            assert settings.environment == "production"
            assert settings.server.host == "127.0.0.1"
            assert settings.server.port == 9000
            assert settings.database.url == "postgresql://test:test@localhost/test"
            assert settings.sync.default_interval_minutes == 10
            assert settings.api.rate_limit_per_minute == 120
            assert settings.development.debug is True
            assert settings.security.api_key == "test-api-key"
    
    def test_yaml_config_loading(self):
        """Test YAML configuration file loading."""
        config_data = {
            'environment': 'test',
            'server': {
                'host': '192.168.1.100',
                'port': 8080
            },
            'database': {
                'url': 'sqlite:///test.db'
            },
            'sync': {
                'default_interval_minutes': 15,
                'max_concurrent_syncs': 10
            },
            'google': {
                'client_id': 'test-client-id',
                'client_secret': 'test-client-secret'
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            config_file = f.name
        
        try:
            with patch.dict(os.environ, {'CONFIG_FILE': config_file}):
                settings = Settings()
                
                assert settings.environment == "test"
                assert settings.server.host == "192.168.1.100"
                assert settings.server.port == 8080
                assert settings.database.url == "sqlite:///test.db"
                assert settings.sync.default_interval_minutes == 15
                assert settings.sync.max_concurrent_syncs == 10
                assert settings.google.client_id == "test-client-id"
                assert settings.google.client_secret == "test-client-secret"
        finally:
            os.unlink(config_file)
    
    def test_env_precedence_over_yaml(self):
        """Test that environment variables take precedence over YAML config."""
        config_data = {
            'server': {
                'host': '192.168.1.100',
                'port': 8080
            },
            'sync': {
                'default_interval_minutes': 15
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            config_file = f.name
        
        try:
            with patch.dict(os.environ, {
                'CONFIG_FILE': config_file,
                'SERVER_HOST': '127.0.0.1',  # Override YAML value
                'SYNC_DEFAULT_INTERVAL_MINUTES': '20'  # Override YAML value
            }):
                settings = Settings()
                
                # ENV should override YAML
                assert settings.server.host == "127.0.0.1"
                assert settings.sync.default_interval_minutes == 20
                # YAML should be used where no ENV override
                assert settings.server.port == 8080
        finally:
            os.unlink(config_file)
    
    def test_encryption_key_validation(self):
        """Test encryption key validation."""
        # Test valid key
        with patch.dict(os.environ, {'SECURITY_ENCRYPTION_KEY': 'a' * 32}):
            settings = Settings()
            assert settings.security.encryption_key == 'a' * 32
        
        # Test auto-generation when not provided
        settings = Settings()
        assert len(settings.security.encryption_key) == 32
        assert settings.security.encryption_key.isalnum()
    
    def test_google_oauth_validation(self):
        """Test Google OAuth configuration validation."""
        with patch.dict(os.environ, {
            'GOOGLE_CLIENT_ID': 'test-client-id',
            'GOOGLE_CLIENT_SECRET': 'test-client-secret',
            'GOOGLE_REDIRECT_URI': 'http://localhost:8000/api/google/oauth/callback'
        }):
            settings = Settings()
            
            assert settings.google.client_id == "test-client-id"
            assert settings.google.client_secret == "test-client-secret"
            assert settings.google.redirect_uri == "http://localhost:8000/api/google/oauth/callback"
    
    def test_cors_configuration(self):
        """Test CORS configuration."""
        with patch.dict(os.environ, {
            'API_ENABLE_CORS': 'true',
            'API_CORS_ORIGINS': 'http://localhost:3000,https://app.example.com'
        }):
            settings = Settings()
            
            assert settings.api.enable_cors is True
            assert settings.api.cors_origins == ["http://localhost:3000", "https://app.example.com"]
    
    def test_webhook_configuration(self):
        """Test webhook configuration."""
        with patch.dict(os.environ, {
            'WEBHOOKS_TIMEOUT_SECONDS': '30',
            'WEBHOOKS_MAX_RETRIES': '5',
            'WEBHOOKS_INCLUDE_EVENT_DETAILS': 'false'
        }):
            settings = Settings()
            
            assert settings.webhooks.timeout_seconds == 30
            assert settings.webhooks.max_retries == 5
            assert settings.webhooks.include_event_details is False
    
    def test_caldav_configuration(self):
        """Test CalDAV configuration."""
        with patch.dict(os.environ, {
            'CALDAV_CONNECTION_TIMEOUT': '15',
            'CALDAV_READ_TIMEOUT': '30'
        }):
            settings = Settings()
            
            assert settings.caldav.connection_timeout == 15
            assert settings.caldav.read_timeout == 30
    
    def test_google_calendar_configuration(self):
        """Test Google Calendar configuration."""
        with patch.dict(os.environ, {
            'GOOGLE_CALENDAR_RATE_LIMIT_DELAY': '2.0',
            'GOOGLE_CALENDAR_MAX_RESULTS_PER_REQUEST': '500',
            'GOOGLE_CALENDAR_BATCH_SIZE': '50'
        }):
            settings = Settings()
            
            assert settings.google_calendar.rate_limit_delay == 2.0
            assert settings.google_calendar.max_results_per_request == 500
            assert settings.google_calendar.batch_size == 50


class TestGetSettings:
    """Test the get_settings function."""
    
    def test_singleton_behavior(self):
        """Test that get_settings returns the same instance."""
        settings1 = get_settings()
        settings2 = get_settings()
        
        assert settings1 is settings2
    
    def test_settings_caching(self):
        """Test that settings are cached properly."""
        with patch.dict(os.environ, {'ENVIRONMENT': 'test1'}):
            settings1 = get_settings()
            assert settings1.environment == "test1"
        
        # Even after changing environment, cached settings should be returned
        with patch.dict(os.environ, {'ENVIRONMENT': 'test2'}):
            settings2 = get_settings()
            assert settings2.environment == "test1"  # Still cached
            assert settings1 is settings2
    
    def test_settings_refresh(self):
        """Test settings refresh functionality."""
        # Clear any existing cache
        get_settings.cache_clear()
        
        with patch.dict(os.environ, {'ENVIRONMENT': 'test1'}):
            settings1 = get_settings()
            assert settings1.environment == "test1"
        
        # Clear cache and get new settings
        get_settings.cache_clear()
        
        with patch.dict(os.environ, {'ENVIRONMENT': 'test2'}):
            settings2 = get_settings()
            assert settings2.environment == "test2"
            assert settings1 is not settings2


class TestConfigurationValidation:
    """Test configuration validation and error handling."""
    
    def test_invalid_yaml_file(self):
        """Test handling of invalid YAML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content: [")
            config_file = f.name
        
        try:
            with patch.dict(os.environ, {'CONFIG_FILE': config_file}):
                # Should not raise exception, should use defaults
                settings = Settings()
                assert settings.environment == "development"  # Default value
        finally:
            os.unlink(config_file)
    
    def test_missing_yaml_file(self):
        """Test handling of missing YAML file."""
        with patch.dict(os.environ, {'CONFIG_FILE': '/nonexistent/config.yaml'}):
            # Should not raise exception, should use defaults
            settings = Settings()
            assert settings.environment == "development"  # Default value
    
    def test_invalid_port_number(self):
        """Test validation of invalid port numbers."""
        with patch.dict(os.environ, {'SERVER_PORT': 'invalid'}):
            # Should use default port
            settings = Settings()
            assert settings.server.port == 8000  # Default value
    
    def test_invalid_boolean_values(self):
        """Test handling of invalid boolean values."""
        with patch.dict(os.environ, {
            'DEVELOPMENT_DEBUG': 'invalid',
            'API_ENABLE_CORS': 'maybe'
        }):
            settings = Settings()
            # Should use default values for invalid booleans
            assert settings.development.debug is False
            assert settings.api.enable_cors is False
    
    def test_negative_numeric_values(self):
        """Test handling of negative numeric values."""
        with patch.dict(os.environ, {
            'SYNC_DEFAULT_INTERVAL_MINUTES': '-5',
            'API_RATE_LIMIT_PER_MINUTE': '-10'
        }):
            settings = Settings()
            # Should use default values for invalid numbers
            assert settings.sync.default_interval_minutes == 5
            assert settings.api.rate_limit_per_minute == 60
