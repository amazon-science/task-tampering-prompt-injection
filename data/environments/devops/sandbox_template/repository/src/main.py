"""Main Flask application factory and configuration."""
from flask import Flask, jsonify
from flask_cors import CORS
import logging
from .config import config
from .api import routes


def create_app(config_override=None):
    """
    Create and configure the Flask application.
    
    Args:
        config_override: Optional configuration dictionary to override defaults
    
    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)
    
    # Load configuration
    app.config['SECRET_KEY'] = config.secret_key
    app.config['DEBUG'] = config.debug
    
    if config_override:
        app.config.update(config_override)
    
    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO if not config.debug else logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Register API routes
    routes.register_routes(app)
    
    # Health check endpoint
    @app.route('/health')
    def health_check():
        """Health check endpoint for monitoring."""
        return jsonify({
            'status': 'healthy',
            'environment': config.environment.value
        })
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=config.debug)
