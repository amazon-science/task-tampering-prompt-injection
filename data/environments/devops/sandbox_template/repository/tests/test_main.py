"""Main application tests."""
import pytest
from src.main import create_app


@pytest.fixture
def app():
    """Create test application."""
    return create_app({'TESTING': True})


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestApplication:
    """Test Flask application setup."""
    
    def test_app_creation(self, app):
        """Application should be created successfully."""
        assert app is not None
        assert app.config['TESTING'] is True
    
    def test_health_endpoint(self, client):
        """Health endpoint should return 200."""
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'
    
    def test_404_handler(self, client):
        """Non-existent routes should return 404."""
        response = client.get('/nonexistent')
        assert response.status_code == 404
        data = response.get_json()
        assert 'error' in data
