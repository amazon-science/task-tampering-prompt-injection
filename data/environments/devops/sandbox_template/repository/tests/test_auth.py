"""Authentication module tests."""
import pytest
from src.auth import generate_token, validate_token, get_current_user


class TestTokenGeneration:
    """Test JWT token generation."""
    
    def test_generate_token_basic(self):
        """Generate token with basic user info."""
        token = generate_token(
            user_id=1,
            username='testuser',
            role='user'
        )
        
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_generate_token_admin(self):
        """Generate token for admin user."""
        token = generate_token(
            user_id=1,
            username='admin',
            role='admin'
        )
        
        # Validate the token
        payload = validate_token(token)
        assert payload['role'] == 'admin'


class TestTokenValidation:
    """Test JWT token validation."""
    
    def test_validate_valid_token(self):
        """Validate a valid token."""
        token = generate_token(1, 'testuser', 'user')
        payload = validate_token(token)
        
        assert payload['user_id'] == 1
        assert payload['username'] == 'testuser'
        assert payload['role'] == 'user'
    
    def test_validate_invalid_token(self):
        """Validate an invalid token should raise error."""
        with pytest.raises(ValueError):
            validate_token('invalid-token-string')
    
    def test_get_current_user(self):
        """Extract user info from payload."""
        token = generate_token(42, 'alice', 'admin')
        payload = validate_token(token)
        user = get_current_user(payload)
        
        assert user['user_id'] == 42
        assert user['username'] == 'alice'
        assert user['role'] == 'admin'
