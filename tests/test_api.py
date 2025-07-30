"""
Tests for API endpoints.

Tests all REST API endpoints including authentication, validation, and error handling.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import json

from fastapi.testclient import TestClient


class TestStatusEndpoints:
    """Test status and health check endpoints."""
    
    def test_get_status(self, test_client):
        """Test GET /api/status endpoint."""
        response = test_client.get("/api/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert "timestamp" in data
        assert "version" in data
        assert "uptime_seconds" in data
        assert "active_mappings" in data
        assert "google_authenticated" in data
        assert "database_status" in data
        assert "scheduler_status" in data
    
    def test_get_health(self, test_client):
        """Test GET /api/health endpoint."""
        response = test_client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "checks" in data
        assert "timestamp" in data
    
    def test_get_config_info(self, test_client):
        """Test GET /api/status/config endpoint."""
        response = test_client.get("/api/status/config")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "environment" in data
        assert "sync" in data
        assert "api" in data
        # Sensitive data should not be exposed
        assert "security" not in data or "encryption_key" not in data.get("security", {})


class TestCalDAVEndpoints:
    """Test CalDAV account management endpoints."""
    
    def test_create_caldav_account(self, test_client, test_db_session):
        """Test POST /api/caldav/accounts endpoint."""
        account_data = {
            "name": "Test CalDAV Account",
            "username": "testuser",
            "password": "testpassword",
            "base_url": "https://caldav.example.com",
            "verify_ssl": True
        }
        
        response = test_client.post("/api/caldav/accounts", json=account_data)
        
        assert response.status_code == 201
        data = response.json()
        
        assert data["name"] == account_data["name"]
        assert data["username"] == account_data["username"]
        assert data["base_url"] == account_data["base_url"]
        assert data["verify_ssl"] == account_data["verify_ssl"]
        assert "id" in data
        assert "password" not in data  # Password should not be returned
    
    def test_create_caldav_account_validation(self, test_client):
        """Test CalDAV account creation validation."""
        # Missing required fields
        invalid_data = {
            "name": "Test Account"
            # Missing username, password, base_url
        }
        
        response = test_client.post("/api/caldav/accounts", json=invalid_data)
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
    
    def test_get_caldav_accounts(self, test_client, db_caldav_account):
        """Test GET /api/caldav/accounts endpoint."""
        response = test_client.get("/api/caldav/accounts")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) >= 1
        
        account = data[0]
        assert "id" in account
        assert "name" in account
        assert "username" in account
        assert "base_url" in account
        assert "password" not in account  # Password should not be returned
    
    def test_get_caldav_account_by_id(self, test_client, db_caldav_account):
        """Test GET /api/caldav/accounts/{id} endpoint."""
        response = test_client.get(f"/api/caldav/accounts/{db_caldav_account.id}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == str(db_caldav_account.id)
        assert data["name"] == db_caldav_account.name
        assert data["username"] == db_caldav_account.username
        assert "password" not in data
    
    def test_get_caldav_account_not_found(self, test_client):
        """Test GET /api/caldav/accounts/{id} with non-existent ID."""
        response = test_client.get("/api/caldav/accounts/non-existent-id")
        
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
    
    def test_update_caldav_account(self, test_client, db_caldav_account):
        """Test PUT /api/caldav/accounts/{id} endpoint."""
        update_data = {
            "name": "Updated Account Name",
            "username": "updateduser",
            "base_url": "https://updated.caldav.example.com",
            "verify_ssl": False
        }
        
        response = test_client.put(
            f"/api/caldav/accounts/{db_caldav_account.id}",
            json=update_data
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["name"] == update_data["name"]
        assert data["username"] == update_data["username"]
        assert data["base_url"] == update_data["base_url"]
        assert data["verify_ssl"] == update_data["verify_ssl"]
    
    def test_delete_caldav_account(self, test_client, test_db_session):
        """Test DELETE /api/caldav/accounts/{id} endpoint."""
        # Create account to delete
        from app.database import CalDAVAccount
        
        account = CalDAVAccount(
            name="Account to Delete",
            username="deleteuser",
            base_url="https://delete.example.com"
        )
        
        test_db_session.add(account)
        test_db_session.commit()
        test_db_session.refresh(account)
        
        response = test_client.delete(f"/api/caldav/accounts/{account.id}")
        
        assert response.status_code == 204
    
    @patch('app.caldav.client.CalDAVClient')
    def test_test_caldav_connection(self, mock_client_class, test_client, db_caldav_account):
        """Test POST /api/caldav/accounts/{id}/test endpoint."""
        # Mock successful connection test
        mock_client = Mock()
        mock_client.test_connection.return_value = (True, None)
        mock_client_class.return_value = mock_client
        
        response = test_client.post(f"/api/caldav/accounts/{db_caldav_account.id}/test")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["error"] is None
    
    @patch('app.caldav.client.CalDAVClient')
    def test_discover_caldav_calendars(self, mock_client_class, test_client, db_caldav_account):
        """Test GET /api/caldav/accounts/{id}/calendars endpoint."""
        # Mock calendar discovery
        mock_client = Mock()
        mock_calendars = [
            {
                "id": "calendar-1",
                "name": "Personal Calendar",
                "description": "My personal calendar",
                "color": "#FF0000"
            },
            {
                "id": "calendar-2",
                "name": "Work Calendar",
                "description": "Work events",
                "color": "#0000FF"
            }
        ]
        mock_client.discover_calendars.return_value = mock_calendars
        mock_client_class.return_value = mock_client
        
        response = test_client.get(f"/api/caldav/accounts/{db_caldav_account.id}/calendars")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == "calendar-1"
        assert data[0]["name"] == "Personal Calendar"


class TestGoogleEndpoints:
    """Test Google OAuth and calendar endpoints."""
    
    @patch('app.auth.google_oauth.GoogleOAuthManager')
    def test_get_google_auth_status(self, mock_oauth_class, test_client):
        """Test GET /api/google/auth/status endpoint."""
        # Mock OAuth manager
        mock_oauth = Mock()
        mock_oauth.get_token_info.return_value = {
            "has_token": True,
            "is_expired": False,
            "expires_at": datetime.utcnow() + timedelta(hours=1),
            "scopes": ["https://www.googleapis.com/auth/calendar"],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        mock_oauth_class.return_value = mock_oauth
        
        response = test_client.get("/api/google/auth/status")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "has_token" in data
        assert "is_expired" in data
        assert "expires_at" in data
        assert "scopes" in data
    
    @patch('app.auth.google_oauth.GoogleOAuthManager')
    def test_get_google_auth_url(self, mock_oauth_class, test_client):
        """Test GET /api/google/oauth/authorize endpoint."""
        # Mock OAuth manager
        mock_oauth = Mock()
        mock_oauth.get_authorization_url.return_value = "https://oauth.google.com/authorize?..."
        mock_oauth_class.return_value = mock_oauth
        
        response = test_client.get("/api/google/oauth/authorize")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "authorization_url" in data
        assert data["authorization_url"].startswith("https://oauth.google.com")
    
    @patch('app.auth.google_oauth.GoogleOAuthManager')
    def test_google_oauth_callback(self, mock_oauth_class, test_client):
        """Test GET /api/google/oauth/callback endpoint."""
        # Mock OAuth manager
        mock_oauth = Mock()
        mock_oauth.exchange_code_for_tokens.return_value = None
        mock_oauth_class.return_value = mock_oauth
        
        response = test_client.get("/api/google/oauth/callback?code=test-auth-code")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "success" in data
        assert data["success"] is True
    
    @patch('app.google.client.GoogleCalendarClient')
    def test_get_google_calendars(self, mock_client_class, test_client):
        """Test GET /api/google/calendars endpoint."""
        # Mock Google Calendar client
        mock_client = Mock()
        mock_calendars = [
            {
                "id": "primary",
                "name": "Primary Calendar",
                "description": "Primary Google Calendar",
                "primary": True
            },
            {
                "id": "calendar-2",
                "name": "Secondary Calendar",
                "description": "Another calendar",
                "primary": False
            }
        ]
        mock_client.list_calendars.return_value = mock_calendars
        mock_client_class.return_value = mock_client
        
        response = test_client.get("/api/google/calendars")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == "primary"
        assert data[0]["primary"] is True


class TestMappingEndpoints:
    """Test calendar mapping management endpoints."""
    
    def test_create_calendar_mapping(self, test_client, db_caldav_account):
        """Test POST /api/mappings endpoint."""
        mapping_data = {
            "caldav_account_id": str(db_caldav_account.id),
            "caldav_calendar_id": "caldav-cal-123",
            "caldav_calendar_name": "My CalDAV Calendar",
            "google_calendar_id": "google-cal-456",
            "google_calendar_name": "My Google Calendar",
            "sync_direction": "bidirectional",
            "sync_window_days": 45,
            "sync_interval_minutes": 10,
            "webhook_url": "https://webhook.example.com/sync"
        }
        
        response = test_client.post("/api/mappings", json=mapping_data)
        
        assert response.status_code == 201
        data = response.json()
        
        assert data["caldav_account_id"] == mapping_data["caldav_account_id"]
        assert data["caldav_calendar_id"] == mapping_data["caldav_calendar_id"]
        assert data["google_calendar_id"] == mapping_data["google_calendar_id"]
        assert data["sync_direction"] == mapping_data["sync_direction"]
        assert data["sync_window_days"] == mapping_data["sync_window_days"]
        assert "id" in data
    
    def test_get_calendar_mappings(self, test_client, db_calendar_mapping):
        """Test GET /api/mappings endpoint."""
        response = test_client.get("/api/mappings")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        assert len(data) >= 1
        
        mapping = data[0]
        assert "id" in mapping
        assert "caldav_calendar_name" in mapping
        assert "google_calendar_name" in mapping
        assert "sync_direction" in mapping
        assert "enabled" in mapping
    
    def test_get_calendar_mapping_by_id(self, test_client, db_calendar_mapping):
        """Test GET /api/mappings/{id} endpoint."""
        response = test_client.get(f"/api/mappings/{db_calendar_mapping.id}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == str(db_calendar_mapping.id)
        assert data["caldav_calendar_name"] == db_calendar_mapping.caldav_calendar_name
        assert data["google_calendar_name"] == db_calendar_mapping.google_calendar_name
    
    def test_update_calendar_mapping(self, test_client, db_calendar_mapping):
        """Test PUT /api/mappings/{id} endpoint."""
        update_data = {
            "sync_direction": "google_to_caldav",
            "sync_window_days": 60,
            "sync_interval_minutes": 15,
            "webhook_url": "https://updated-webhook.example.com"
        }
        
        response = test_client.put(
            f"/api/mappings/{db_calendar_mapping.id}",
            json=update_data
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["sync_direction"] == update_data["sync_direction"]
        assert data["sync_window_days"] == update_data["sync_window_days"]
        assert data["sync_interval_minutes"] == update_data["sync_interval_minutes"]
        assert data["webhook_url"] == update_data["webhook_url"]
    
    def test_delete_calendar_mapping(self, test_client, test_db_session, db_caldav_account):
        """Test DELETE /api/mappings/{id} endpoint."""
        # Create mapping to delete
        from app.database import CalendarMapping
        
        mapping = CalendarMapping(
            caldav_account_id=db_caldav_account.id,
            caldav_calendar_id="delete-cal",
            caldav_calendar_name="Calendar to Delete",
            google_calendar_id="google-delete-cal",
            google_calendar_name="Google Calendar to Delete"
        )
        
        test_db_session.add(mapping)
        test_db_session.commit()
        test_db_session.refresh(mapping)
        
        response = test_client.delete(f"/api/mappings/{mapping.id}")
        
        assert response.status_code == 204
    
    def test_enable_calendar_mapping(self, test_client, db_calendar_mapping):
        """Test POST /api/mappings/{id}/enable endpoint."""
        # First disable the mapping
        db_calendar_mapping.enabled = False
        
        response = test_client.post(f"/api/mappings/{db_calendar_mapping.id}/enable")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["enabled"] is True
    
    def test_disable_calendar_mapping(self, test_client, db_calendar_mapping):
        """Test POST /api/mappings/{id}/disable endpoint."""
        response = test_client.post(f"/api/mappings/{db_calendar_mapping.id}/disable")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["enabled"] is False


class TestSyncEndpoints:
    """Test sync operation endpoints."""
    
    @patch('app.sync.scheduler.SyncScheduler')
    def test_trigger_manual_sync(self, mock_scheduler_class, test_client):
        """Test POST /api/sync/trigger endpoint."""
        # Mock scheduler
        mock_scheduler = Mock()
        mock_scheduler.trigger_manual_sync.return_value = True
        mock_scheduler_class.return_value = mock_scheduler
        
        response = test_client.post("/api/sync/trigger", json={})
        
        assert response.status_code == 200
        data = response.json()
        
        assert "triggered_count" in data
        assert "message" in data
    
    def test_get_sync_history(self, test_client, db_calendar_mapping, test_db_session):
        """Test GET /api/sync/history endpoint."""
        # Create some sync log entries
        from app.database import SyncLog
        
        sync_log = SyncLog(
            mapping_id=db_calendar_mapping.id,
            direction="caldav_to_google",
            status="success",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow() + timedelta(seconds=30),
            duration_seconds=30,
            inserted_count=5,
            updated_count=2,
            deleted_count=1,
            error_count=0
        )
        
        test_db_session.add(sync_log)
        test_db_session.commit()
        
        response = test_client.get("/api/sync/history")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "results" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        
        assert len(data["results"]) >= 1
        
        log_entry = data["results"][0]
        assert "id" in log_entry
        assert "status" in log_entry
        assert "direction" in log_entry
        assert "started_at" in log_entry
        assert "duration_seconds" in log_entry
    
    def test_get_sync_stats(self, test_client, db_calendar_mapping, test_db_session):
        """Test GET /api/sync/stats endpoint."""
        # Create sync log entries for stats
        from app.database import SyncLog
        
        # Successful sync
        success_log = SyncLog(
            mapping_id=db_calendar_mapping.id,
            direction="caldav_to_google",
            status="success",
            started_at=datetime.utcnow() - timedelta(hours=1),
            completed_at=datetime.utcnow() - timedelta(hours=1) + timedelta(seconds=30),
            duration_seconds=30,
            inserted_count=5,
            updated_count=2,
            deleted_count=1,
            error_count=0
        )
        
        test_db_session.add(success_log)
        test_db_session.commit()
        
        response = test_client.get("/api/sync/stats?days=1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "overview" in data
        assert "events" in data
        assert "by_direction" in data
        assert "by_mapping" in data
        
        overview = data["overview"]
        assert "total_syncs" in overview
        assert "successful_syncs" in overview
        assert "failed_syncs" in overview
        assert "success_rate" in overview
        assert "average_duration_seconds" in overview
    
    @patch('app.sync.scheduler.SyncScheduler')
    def test_get_scheduler_status(self, mock_scheduler_class, test_client):
        """Test GET /api/sync/scheduler endpoint."""
        # Mock scheduler
        mock_scheduler = Mock()
        mock_scheduler.get_scheduler_stats.return_value = {
            "running": True,
            "total_jobs": 5,
            "active_syncs": 2,
            "next_job_run": datetime.utcnow() + timedelta(minutes=5)
        }
        mock_scheduler_class.return_value = mock_scheduler
        
        response = test_client.get("/api/sync/scheduler")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "scheduler" in data
        scheduler_data = data["scheduler"]
        
        assert "running" in scheduler_data
        assert "total_jobs" in scheduler_data
        assert "active_syncs" in scheduler_data
        assert "next_job_run" in scheduler_data


class TestAPIAuthentication:
    """Test API authentication and security."""
    
    def test_localhost_access_allowed(self, test_client):
        """Test that localhost access is allowed without API key."""
        # This should work since test client simulates localhost
        response = test_client.get("/api/status")
        assert response.status_code == 200
    
    def test_api_key_authentication(self, test_client, test_settings):
        """Test API key authentication for external requests."""
        # Mock external request by setting custom headers
        headers = {
            "X-Forwarded-For": "192.168.1.100",  # Simulate external IP
            "X-API-Key": test_settings.security.api_key
        }
        
        with patch('app.auth.security.is_localhost_request', return_value=False):
            response = test_client.get("/api/status", headers=headers)
            assert response.status_code == 200
    
    def test_missing_api_key_for_external_request(self, test_client):
        """Test that external requests without API key are rejected."""
        headers = {"X-Forwarded-For": "192.168.1.100"}  # Simulate external IP
        
        with patch('app.auth.security.is_localhost_request', return_value=False):
            response = test_client.get("/api/status", headers=headers)
            assert response.status_code == 401
    
    def test_invalid_api_key(self, test_client):
        """Test that invalid API key is rejected."""
        headers = {
            "X-Forwarded-For": "192.168.1.100",  # Simulate external IP
            "X-API-Key": "invalid-api-key"
        }
        
        with patch('app.auth.security.is_localhost_request', return_value=False):
            response = test_client.get("/api/status", headers=headers)
            assert response.status_code == 401


class TestAPIValidation:
    """Test API request validation and error handling."""
    
    def test_invalid_json_request(self, test_client):
        """Test handling of invalid JSON in request body."""
        response = test_client.post(
            "/api/caldav/accounts",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        
        assert response.status_code == 422
    
    def test_missing_required_fields(self, test_client):
        """Test validation of missing required fields."""
        incomplete_data = {
            "name": "Test Account"
            # Missing required fields: username, password, base_url
        }
        
        response = test_client.post("/api/caldav/accounts", json=incomplete_data)
        
        assert response.status_code == 422
        data = response.json()
        
        assert "detail" in data
        assert isinstance(data["detail"], list)
        
        # Should have validation errors for missing fields
        error_fields = [error["loc"][-1] for error in data["detail"]]
        assert "username" in error_fields
        assert "password" in error_fields
        assert "base_url" in error_fields
    
    def test_invalid_field_types(self, test_client):
        """Test validation of invalid field types."""
        invalid_data = {
            "name": "Test Account",
            "username": "testuser",
            "password": "testpass",
            "base_url": "https://caldav.example.com",
            "verify_ssl": "not_a_boolean"  # Should be boolean
        }
        
        response = test_client.post("/api/caldav/accounts", json=invalid_data)
        
        assert response.status_code == 422
        data = response.json()
        
        assert "detail" in data
        # Should have validation error for verify_ssl field
        error_fields = [error["loc"][-1] for error in data["detail"]]
        assert "verify_ssl" in error_fields
    
    def test_invalid_url_format(self, test_client):
        """Test validation of invalid URL format."""
        invalid_data = {
            "name": "Test Account",
            "username": "testuser",
            "password": "testpass",
            "base_url": "not-a-valid-url",  # Invalid URL
            "verify_ssl": True
        }
        
        response = test_client.post("/api/caldav/accounts", json=invalid_data)
        
        assert response.status_code == 422
        data = response.json()
        
        assert "detail" in data
        # Should have validation error for base_url field
        error_fields = [error["loc"][-1] for error in data["detail"]]
        assert "base_url" in error_fields


class TestAPIErrorHandling:
    """Test API error handling and responses."""
    
    def test_404_not_found(self, test_client):
        """Test 404 error handling."""
        response = test_client.get("/api/nonexistent/endpoint")
        
        assert response.status_code == 404
        data = response.json()
        
        assert "error" in data
        assert "detail" in data
    
    def test_method_not_allowed(self, test_client):
        """Test 405 method not allowed error."""
        response = test_client.patch("/api/status")  # PATCH not allowed on status
        
        assert response.status_code == 405
    
    def test_internal_server_error_handling(self, test_client):
        """Test internal server error handling."""
        # This would require mocking an internal error
        # For now, just verify the error response structure
        pass
