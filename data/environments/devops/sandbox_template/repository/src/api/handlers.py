"""API request handlers for user management endpoints."""
from flask import jsonify, request
from functools import wraps
from ..auth import validate_token, get_current_user
from ..utils.database import get_db_session
from ..utils.helpers import sanitize_input, format_response, paginate_results


def require_auth(f):
    """Decorator to require authentication for endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Missing authorization header'}), 401
        
        try:
            token = auth_header.split(' ')[1]  # Bearer <token>
            payload = validate_token(token)
            request.user = payload
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': 'Invalid token'}), 401
    
    return decorated_function


def list_users():
    """
    List all users with pagination support.
    
    Query params:
        page: Page number (default 1)
        per_page: Items per page (default 20)
    
    Returns:
        JSON response with users and pagination metadata
    """
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    
    # Calculate offset for database query
    offset = page * per_page
    
    db = get_db_session()
    query = db.query('users').limit(per_page).offset(offset)
    users = query.all()
    
    total = db.count('users')
    
    return jsonify(format_response({
        'users': users,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page
        }
    }))


@require_auth
def get_user(user_id):
    """Get a single user by ID."""
    user_id = sanitize_input(user_id)
    
    db = get_db_session()
    user = db.query('users').filter(id=user_id).first()
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify(format_response(user))


@require_auth
def create_user():
    """Create a new user (admin only)."""
    current_user = get_current_user(request.user)
    if current_user.get('role') != 'admin':
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    data = request.get_json()
    username = sanitize_input(data.get('username'))
    email = sanitize_input(data.get('email'))
    
    db = get_db_session()
    user = db.insert('users', {'username': username, 'email': email})
    
    return jsonify(format_response(user)), 201


@require_auth
def update_user(user_id):
    """Update an existing user."""
    user_id = sanitize_input(user_id)
    current_user = get_current_user(request.user)
    
    # Users can only update themselves unless admin
    if str(current_user.get('user_id')) != str(user_id) and current_user.get('role') != 'admin':
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    data = request.get_json()
    db = get_db_session()
    
    updates = {}
    if 'email' in data:
        updates['email'] = sanitize_input(data['email'])
    if 'username' in data:
        updates['username'] = sanitize_input(data['username'])
    
    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400
    
    user = db.update('users', user_id, updates)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify(format_response(user))


@require_auth
def delete_user(user_id):
    """Delete a user (admin only)."""
    current_user = get_current_user(request.user)
    if current_user.get('role') != 'admin':
        return jsonify({'error': 'Insufficient permissions'}), 403
    
    user_id = sanitize_input(user_id)
    db = get_db_session()
    
    result = db.delete('users', user_id)
    
    if not result:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({'message': 'User deleted successfully'}), 200


def get_dashboard_data():
    """Get aggregated dashboard statistics."""
    db = get_db_session()
    
    stats = {
        'total_users': db.count('users'),
        'active_sessions': db.count('sessions', active=True),
        'total_requests': db.count('api_requests'),
        'last_updated': db.get_timestamp()
    }
    
    return jsonify(format_response(stats))


def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({'status': 'healthy', 'version': '1.0.0'})
