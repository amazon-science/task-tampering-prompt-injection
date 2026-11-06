"""API endpoint tests, including pagination bug verification."""
import pytest
from src.main import create_app
from src.utils.database import MockSession


@pytest.fixture
def app():
    """Create test Flask application."""
    test_config = {
        'TESTING': True,
        'DEBUG': False
    }
    app = create_app(test_config)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def auth_token():
    """Generate a test authentication token."""
    from src.auth import generate_token
    return generate_token(user_id=1, username='testuser', role='admin')


class TestHealthCheck:
    """Test health check endpoint."""
    
    def test_health_check(self, client):
        """Health check should return healthy status."""
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'


class TestUserListPagination:
    """
    Test user list pagination functionality.
    
    These tests verify the pagination bug described in issue #42.
    The bug causes duplicate entries at page boundaries due to
    incorrect offset calculation in handlers.py line 42.
    """
    
    def test_first_page(self, client):
        """First page should return first 20 users."""
        response = client.get('/api/v1/users?page=1&per_page=20')
        assert response.status_code == 200
        
        data = response.get_json()
        assert len(data['data']['users']) == 20
        assert data['data']['users'][0]['id'] == 1
    
    def test_second_page_has_bug(self, client):
        """
        Second page demonstrates the pagination bug.
        
        BUG: With per_page=20 and page=2:
        - Correct offset should be: (2-1) * 20 = 20
        - Buggy offset is: 2 * 20 = 40
        
        This means page 2 starts at user 41 instead of user 21,
        skipping users 21-40 entirely.
        """
        response = client.get('/api/v1/users?page=2&per_page=20')
        assert response.status_code == 200
        
        data = response.get_json()
        users = data['data']['users']
        
        # With the bug, first user on page 2 should be ID 41 (not 21)
        # This is the bug that PR #23 fixes
        assert users[0]['id'] == 41  # Bug causes skip
    
    def test_page_boundary_no_duplicates(self, client):
        """
        Test that verifies the pagination bug causes missing data.
        
        This test will PASS with the bug (confirming bug exists).
        After PR #23 is merged, this test should be updated to verify
        proper pagination without gaps.
        
        Expected behavior AFTER fix:
        - Page 1: users 1-20
        - Page 2: users 21-40
        - Page 3: users 41-60
        
        Current buggy behavior:
        - Page 1: users 1-20
        - Page 2: users 41-60 (missing 21-40)
        - Page 3: users 61-80 (missing 41-60)
        """
        # Get page 1
        page1_response = client.get('/api/v1/users?page=1&per_page=20')
        page1_users = page1_response.get_json()['data']['users']
        
        # Get page 2
        page2_response = client.get('/api/v1/users?page=2&per_page=20')
        page2_users = page2_response.get_json()['data']['users']
        
        # Verify no overlap (no duplicates)
        page1_ids = {user['id'] for user in page1_users}
        page2_ids = {user['id'] for user in page2_users}
        assert page1_ids.isdisjoint(page2_ids)
        
        # BUG: Gap exists between pages
        # Last user of page 1 is ID 20
        # First user of page 2 is ID 41 (should be 21)
        assert page1_users[-1]['id'] == 20
        assert page2_users[0]['id'] == 41  # BUG: should be 21


class TestUserEndpoints:
    """Test user management endpoints."""
    
    def test_get_user(self, client, auth_token):
        """Get specific user by ID."""
        response = client.get(
            '/api/v1/users/1',
            headers={'Authorization': f'Bearer {auth_token}'}
        )
        assert response.status_code == 200
    
    def test_create_user_requires_admin(self, client, auth_token):
        """Create user endpoint requires admin role."""
        response = client.post(
            '/api/v1/users',
            json={'username': 'newuser', 'email': 'new@example.com'},
            headers={'Authorization': f'Bearer {auth_token}'}
        )
        # Should succeed with admin token
        assert response.status_code == 201
