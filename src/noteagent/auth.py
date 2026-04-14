"""Authentication token management utilities."""

from __future__ import annotations

import base64
import secrets
from datetime import datetime
from typing import Optional

from noteagent.models import AuthToken


def generate_token() -> str:
    """Generate a secure random token with na_ prefix.
    
    Returns a 256-bit (32-byte) token encoded as base64 with na_ prefix.
    Example: na_xK7fE9mP2qR5tY8wZ3vN6jH4gL1sA0dF_
    """
    random_bytes = secrets.token_bytes(32)
    encoded = base64.urlsafe_b64encode(random_bytes).decode('ascii').rstrip('=')
    return f"na_{encoded}"


def validate_token(token: str, valid_tokens: list[AuthToken]) -> Optional[AuthToken]:
    """Validate a token against the list of valid tokens.
    
    Args:
        token: The token to validate
        valid_tokens: List of valid AuthToken objects
    
    Returns:
        The matching AuthToken if valid, None otherwise
    """
    if not token:
        return None
    
    # Strip Bearer prefix if present
    if token.startswith("Bearer "):
        token = token[7:]
    
    for auth_token in valid_tokens:
        if secrets.compare_digest(token, auth_token.token):
            # Check expiration if set
            if auth_token.expires_at:
                if datetime.now() > auth_token.expires_at:
                    return None  # Token expired
            return auth_token
    
    return None


def is_admin_role(auth_token: Optional[AuthToken]) -> bool:
    """Check if the token has admin role."""
    if not auth_token:
        return False
    return auth_token.role == "admin"


def is_read_only_role(auth_token: Optional[AuthToken]) -> bool:
    """Check if the token has read-only role."""
    if not auth_token:
        return False
    return auth_token.role == "read-only"


def create_auth_token(name: str, role: str = "admin", expires_at: Optional[datetime] = None) -> AuthToken:
    """Create a new auth token.
    
    Args:
        name: Human-readable name for the token
        role: Role ('admin' or 'read-only')
        expires_at: Optional expiration datetime
    
    Returns:
        New AuthToken object
    """
    if role not in ("admin", "read-only"):
        raise ValueError(f"Invalid role: {role}. Must be 'admin' or 'read-only'")
    
    token = generate_token()
    return AuthToken(
        token=token,
        name=name,
        role=role,
        created_at=datetime.now(),
        expires_at=expires_at,
    )
