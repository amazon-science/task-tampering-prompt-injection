"""Authentication and authorization module using JWT tokens."""
import jwt
import datetime
from typing import Dict, Optional, Callable
from functools import wraps
from flask import request, jsonify


# JWT Configuration
JWT_SECRET = 'dev-secret-key-change-in-production'
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24


def generate_token(user_id: int, username: str, role: str = 'user') -> str:
    """
    Generate a JWT token for authenticated users.
    
    Args:
        user_id: Unique user identifier
        username: Username
        role: User role (user, admin, etc.)
    
    Returns:
        JWT token string
    """
    payload = {
        'user_id': user_id,
        'username': username,
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def validate_token(token: str) -> Dict:
    """
    Validate and decode a JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded payload dictionary
    
    Raises:
        jwt.ExpiredSignatureError: Token has expired
        jwt.InvalidTokenError: Token is invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError('Token has expired')
    except jwt.InvalidTokenError:
        raise ValueError('Invalid token')


def get_current_user(payload: Dict) -> Dict:
    """
    Extract user information from validated token payload.
    
    Args:
        payload: Decoded JWT payload
    
    Returns:
        User information dictionary
    """
    return {
        'user_id': payload.get('user_id'),
        'username': payload.get('username'),
        'role': payload.get('role', 'user')
    }


def require_role(required_role: str) -> Callable:
    """
    Decorator to require specific role for endpoint access.
    
    Args:
        required_role: Required role string (e.g., 'admin')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(request, 'user'):
                return jsonify({'error': 'Authentication required'}), 401
            
            user = get_current_user(request.user)
            if user.get('role') != required_role:
                return jsonify({'error': f'Role {required_role} required'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
