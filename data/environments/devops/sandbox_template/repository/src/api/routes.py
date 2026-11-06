"""API route registration and URL mapping."""
from flask import Blueprint
from . import handlers


def register_routes(app):
    """
    Register all API routes with the Flask application.
    
    Args:
        app: Flask application instance
    """
    # Create API blueprint
    api = Blueprint('api', __name__, url_prefix='/api/v1')
    
    # User management endpoints
    api.add_url_rule('/users', 'list_users', handlers.list_users, methods=['GET'])
    api.add_url_rule('/users/<int:user_id>', 'get_user', handlers.get_user, methods=['GET'])
    api.add_url_rule('/users', 'create_user', handlers.create_user, methods=['POST'])
    
    # Dashboard endpoint
    api.add_url_rule('/dashboard', 'dashboard', handlers.get_dashboard_data, methods=['GET'])
    
    # Data export endpoint (placeholder for PR #24 implementation)
    # This endpoint will be implemented in PR #24 to add CSV export functionality
    # api.add_url_rule('/export', 'export_data', handlers.export_data, methods=['GET'])
    
    # Register blueprint
    app.register_blueprint(api)
    
    return app
