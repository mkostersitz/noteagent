"""Tests for authentication and rate limiting."""

import pytest
from datetime import datetime, timedelta
from noteagent.auth import (
    generate_token,
    validate_token,
    is_admin_role,
    is_read_only_role,
    create_auth_token,
)
from noteagent.models import AuthToken, AuthConfig, RateLimitConfig, AppConfigExtended


class TestTokenGeneration:
    """Test token generation and validation."""
    
    def test_generate_token_format(self):
        """Generated tokens should have na_ prefix and be base64-like."""
        token = generate_token()
        assert token.startswith("na_")
        assert len(token) > 20  # Should be reasonably long
        
    def test_generate_token_uniqueness(self):
        """Each generated token should be unique."""
        tokens = [generate_token() for _ in range(10)]
        assert len(set(tokens)) == 10  # All unique
    
    def test_create_auth_token_admin(self):
        """Create an admin token."""
        token = create_auth_token("test-admin", "admin")
        assert token.name == "test-admin"
        assert token.role == "admin"
        assert token.token.startswith("na_")
        assert token.created_at is not None
        assert token.expires_at is None
    
    def test_create_auth_token_readonly(self):
        """Create a read-only token."""
        token = create_auth_token("test-readonly", "read-only")
        assert token.name == "test-readonly"
        assert token.role == "read-only"
    
    def test_create_auth_token_with_expiration(self):
        """Create a token with expiration."""
        expires = datetime.now() + timedelta(days=30)
        token = create_auth_token("test-expiring", "admin", expires)
        assert token.expires_at == expires
    
    def test_create_auth_token_invalid_role(self):
        """Invalid role should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid role"):
            create_auth_token("test", "superuser")


class TestTokenValidation:
    """Test token validation."""
    
    def test_validate_valid_token(self):
        """Valid token should be accepted."""
        token = create_auth_token("test", "admin")
        valid_tokens = [token]
        
        result = validate_token(token.token, valid_tokens)
        assert result is not None
        assert result.name == "test"
    
    def test_validate_invalid_token(self):
        """Invalid token should be rejected."""
        token = create_auth_token("test", "admin")
        valid_tokens = [token]
        
        result = validate_token("na_invalid_token", valid_tokens)
        assert result is None
    
    def test_validate_with_bearer_prefix(self):
        """Token with Bearer prefix should be validated."""
        token = create_auth_token("test", "admin")
        valid_tokens = [token]
        
        result = validate_token(f"Bearer {token.token}", valid_tokens)
        assert result is not None
        assert result.name == "test"
    
    def test_validate_expired_token(self):
        """Expired token should be rejected."""
        past = datetime.now() - timedelta(days=1)
        token = create_auth_token("test", "admin", past)
        valid_tokens = [token]
        
        result = validate_token(token.token, valid_tokens)
        assert result is None
    
    def test_validate_not_yet_expired_token(self):
        """Token expiring in the future should be accepted."""
        future = datetime.now() + timedelta(days=30)
        token = create_auth_token("test", "admin", future)
        valid_tokens = [token]
        
        result = validate_token(token.token, valid_tokens)
        assert result is not None
    
    def test_validate_empty_token(self):
        """Empty token should be rejected."""
        result = validate_token("", [])
        assert result is None
    
    def test_validate_empty_token_list(self):
        """Validation against empty token list should fail."""
        token = create_auth_token("test", "admin")
        result = validate_token(token.token, [])
        assert result is None


class TestRoleChecks:
    """Test role checking functions."""
    
    def test_is_admin_role_admin(self):
        """Admin token should pass admin check."""
        token = create_auth_token("test", "admin")
        assert is_admin_role(token) is True
    
    def test_is_admin_role_readonly(self):
        """Read-only token should fail admin check."""
        token = create_auth_token("test", "read-only")
        assert is_admin_role(token) is False
    
    def test_is_admin_role_none(self):
        """None token should fail admin check."""
        assert is_admin_role(None) is False
    
    def test_is_read_only_role_readonly(self):
        """Read-only token should pass read-only check."""
        token = create_auth_token("test", "read-only")
        assert is_read_only_role(token) is True
    
    def test_is_read_only_role_admin(self):
        """Admin token should fail read-only check."""
        token = create_auth_token("test", "admin")
        assert is_read_only_role(token) is False
    
    def test_is_read_only_role_none(self):
        """None token should fail read-only check."""
        assert is_read_only_role(None) is False


class TestAuthConfig:
    """Test authentication configuration models."""
    
    def test_auth_config_defaults(self):
        """Auth config should have sensible defaults."""
        config = AuthConfig()
        assert config.enabled is False
        assert config.tokens == []
        assert config.token_header == "Authorization"
        assert config.token_prefix == "Bearer"
    
    def test_auth_config_with_tokens(self):
        """Auth config should accept tokens."""
        token = create_auth_token("test", "admin")
        config = AuthConfig(enabled=True, tokens=[token])
        assert config.enabled is True
        assert len(config.tokens) == 1
        assert config.tokens[0].name == "test"


class TestRateLimitConfig:
    """Test rate limiting configuration models."""
    
    def test_rate_limit_config_defaults(self):
        """Rate limit config should have sensible defaults."""
        config = RateLimitConfig()
        assert config.enabled is True
        assert config.default_limit == "100/minute"
        assert config.endpoints == []
        assert "127.0.0.1" in config.whitelist_ips
        assert "::1" in config.whitelist_ips
    
    def test_rate_limit_config_custom(self):
        """Rate limit config should accept custom values."""
        config = RateLimitConfig(
            enabled=False,
            default_limit="50/second",
            whitelist_ips=["10.0.0.1"],
        )
        assert config.enabled is False
        assert config.default_limit == "50/second"
        assert config.whitelist_ips == ["10.0.0.1"]


class TestAppConfigExtended:
    """Test extended app config with auth and rate limiting."""
    
    def test_extended_config_defaults(self):
        """Extended config should include auth and rate limit configs."""
        config = AppConfigExtended()
        assert config.auth is not None
        assert config.rate_limit is not None
        assert config.auth.enabled is False
        assert config.rate_limit.enabled is True
    
    def test_extended_config_with_custom_auth(self):
        """Extended config should accept custom auth config."""
        token = create_auth_token("test", "admin")
        auth_config = AuthConfig(enabled=True, tokens=[token])
        config = AppConfigExtended(auth=auth_config)
        assert config.auth.enabled is True
        assert len(config.auth.tokens) == 1
    
    def test_extended_config_serialization(self):
        """Extended config should serialize to JSON."""
        token = create_auth_token("test", "admin", datetime.now() + timedelta(days=30))
        auth_config = AuthConfig(enabled=True, tokens=[token])
        config = AppConfigExtended(auth=auth_config)
        
        # Should be serializable
        data = config.model_dump(mode='json')
        assert data['auth']['enabled'] is True
        assert len(data['auth']['tokens']) == 1
        assert isinstance(data['auth']['tokens'][0]['created_at'], str)
