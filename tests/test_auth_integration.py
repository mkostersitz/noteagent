"""Integration tests for authentication and rate limiting in the web server."""

import pytest
from fastapi.testclient import TestClient
from noteagent.auth import create_auth_token
from noteagent.models import AppConfigExtended, AuthConfig, RateLimitConfig


@pytest.fixture
def app_with_auth():
    """Create a test app with authentication enabled."""
    # Import here to avoid loading the module before we can mock config
    from noteagent import server
    
    # Create config with auth enabled
    token = create_auth_token("test-user", "admin")
    auth_config = AuthConfig(enabled=True, tokens=[token])
    config = AppConfigExtended(auth=auth_config)
    
    # Override the config
    server._app_config = config
    
    yield server.app, token.token
    
    # Cleanup
    server._app_config = None


@pytest.fixture
def app_without_auth():
    """Create a test app with authentication disabled."""
    from noteagent import server
    
    # Create config with auth disabled
    auth_config = AuthConfig(enabled=False)
    config = AppConfigExtended(auth=auth_config)
    
    # Override the config
    server._app_config = config
    
    yield server.app
    
    # Cleanup
    server._app_config = None


@pytest.fixture
def app_with_rate_limiting():
    """Create a test app with rate limiting."""
    from noteagent import server
    
    # Create config with strict rate limiting
    rate_limit_config = RateLimitConfig(
        enabled=True,
        default_limit="2/minute",  # Very strict for testing
        whitelist_ips=[],
    )
    config = AppConfigExtended(rate_limit=rate_limit_config)
    
    # Override the config
    server._app_config = config
    
    yield server.app
    
    # Cleanup
    server._app_config = None


class TestAuthenticationMiddleware:
    """Test authentication middleware."""
    
    def test_public_endpoint_no_auth(self, app_with_auth):
        """Public endpoints should work without auth."""
        app, _ = app_with_auth
        client = TestClient(app)
        
        # Static files and docs are public
        response = client.get("/docs")
        assert response.status_code in (200, 404)  # 404 if docs not found is OK
    
    def test_protected_endpoint_without_token(self, app_with_auth):
        """Protected endpoints should reject requests without token."""
        app, _ = app_with_auth
        client = TestClient(app)
        
        response = client.get("/api/config")
        assert response.status_code == 401
        assert "authorization" in response.json()["detail"].lower()
    
    def test_protected_endpoint_with_invalid_token(self, app_with_auth):
        """Protected endpoints should reject invalid tokens."""
        app, _ = app_with_auth
        client = TestClient(app)
        
        response = client.get(
            "/api/config",
            headers={"Authorization": "Bearer na_invalid_token_here"}
        )
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()
    
    def test_protected_endpoint_with_valid_token(self, app_with_auth):
        """Protected endpoints should accept valid tokens."""
        app, token = app_with_auth
        client = TestClient(app)
        
        response = client.get(
            "/api/config",
            headers={"Authorization": f"Bearer {token}"}
        )
        # Should not be 401
        assert response.status_code != 401
    
    def test_auth_disabled_allows_all(self, app_without_auth):
        """When auth is disabled, all endpoints should be accessible."""
        app = app_without_auth
        client = TestClient(app)
        
        response = client.get("/api/config")
        # Should not be 401
        assert response.status_code != 401


class TestAdminRoleProtection:
    """Test admin role requirement for write operations."""
    
    def test_admin_endpoint_with_readonly_token(self, app_with_auth):
        """Admin endpoints should reject read-only tokens."""
        from noteagent import server
        
        # Create a read-only token
        readonly_token = create_auth_token("readonly-user", "read-only")
        config = server._app_config
        config.auth.tokens.append(readonly_token)
        
        app, _ = app_with_auth
        client = TestClient(app)
        
        # Try to update config (admin operation)
        response = client.put(
            "/api/config",
            json={"summary_style": "technical"},
            headers={"Authorization": f"Bearer {readonly_token.token}"}
        )
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()
    
    def test_admin_endpoint_with_admin_token(self, app_with_auth):
        """Admin endpoints should accept admin tokens."""
        app, token = app_with_auth
        client = TestClient(app)
        
        # Try to update config (admin operation)
        response = client.put(
            "/api/config",
            json={"summary_style": "technical"},
            headers={"Authorization": f"Bearer {token}"}
        )
        # Should not be 403
        assert response.status_code != 403


class TestRateLimiting:
    """Test rate limiting functionality."""
    
    def test_rate_limit_enforcement(self, app_with_rate_limiting):
        """Rate limiting should block excessive requests."""
        app = app_with_rate_limiting
        client = TestClient(app)
        
        # Make requests up to the limit
        responses = []
        for _ in range(5):  # Limit is 2/minute, so 3rd+ should fail
            response = client.get("/api/devices")
            responses.append(response.status_code)
        
        # At least one should be rate limited (429)
        assert 429 in responses
    
    def test_rate_limit_whitelisted_ip(self):
        """Whitelisted IPs should bypass rate limiting."""
        from noteagent import server
        
        # Create config with whitelist
        rate_limit_config = RateLimitConfig(
            enabled=True,
            default_limit="1/minute",
            whitelist_ips=["127.0.0.1", "testclient"],  # TestClient IP
        )
        config = AppConfigExtended(rate_limit=rate_limit_config)
        server._app_config = config
        
        client = TestClient(server.app)
        
        # Make many requests
        responses = []
        for _ in range(10):
            response = client.get("/api/devices")
            responses.append(response.status_code)
        
        # None should be rate limited
        assert 429 not in responses
        
        server._app_config = None


class TestSecurityHeaders:
    """Test security headers middleware."""
    
    def test_security_headers_present(self, app_without_auth):
        """All responses should include security headers."""
        app = app_without_auth
        client = TestClient(app)
        
        response = client.get("/api/config")
        
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"
        
        assert "X-XSS-Protection" in response.headers
        assert response.headers["X-XSS-Protection"] == "1; mode=block"


class TestConfigStorage:
    """Test config storage with auth and rate limiting."""
    
    def test_save_and_load_extended_config(self, tmp_path, monkeypatch):
        """Extended config should save and load correctly."""
        from noteagent.storage import save_config_extended, load_config_extended
        from noteagent import storage
        
        # Use temp path for config
        config_file = tmp_path / "config.toml"
        monkeypatch.setattr(storage, "CONFIG_FILE", config_file)
        
        # Create and save config
        token = create_auth_token("test", "admin")
        auth_config = AuthConfig(enabled=True, tokens=[token])
        config = AppConfigExtended(auth=auth_config)
        save_config_extended(config)
        
        # Load and verify
        loaded = load_config_extended()
        assert loaded.auth.enabled is True
        assert len(loaded.auth.tokens) == 1
        assert loaded.auth.tokens[0].name == "test"
        assert loaded.auth.tokens[0].role == "admin"
