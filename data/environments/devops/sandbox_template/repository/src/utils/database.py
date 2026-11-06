"""Database utilities and mock session for sandbox testing."""
from typing import Dict, List, Any, Optional
from contextlib import contextmanager


class MockQuery:
    """Mock query builder for testing without real database."""
    
    def __init__(self, table: str, session: 'MockSession'):
        self.table = table
        self.session = session
        self._limit = None
        self._offset = None
        self._filters = {}
    
    def filter(self, **kwargs):
        """Add filter conditions to query."""
        self._filters.update(kwargs)
        return self
    
    def limit(self, count: int):
        """Set query result limit."""
        self._limit = count
        return self
    
    def offset(self, count: int):
        """Set query result offset."""
        self._offset = count
        return self
    
    def all(self) -> List[Dict]:
        """Execute query and return all results."""
        data = self.session.get_table_data(self.table)
        
        # Apply filters
        if self._filters:
            data = [row for row in data if all(
                row.get(k) == v for k, v in self._filters.items()
            )]
        
        # Apply offset and limit
        if self._offset:
            data = data[self._offset:]
        if self._limit:
            data = data[:self._limit]
        
        return data
    
    def first(self) -> Optional[Dict]:
        """Execute query and return first result."""
        results = self.all()
        return results[0] if results else None


class MockSession:
    """Mock database session for testing."""
    
    def __init__(self):
        self._data = {
            'users': self._generate_mock_users(),
            'sessions': [],
            'api_requests': []
        }
    
    def _generate_mock_users(self) -> List[Dict]:
        """Generate mock user data."""
        return [
            {'id': i, 'username': f'user{i}', 'email': f'user{i}@example.com', 'role': 'user'}
            for i in range(1, 101)
        ]
    
    def query(self, table: str) -> MockQuery:
        """Create a query for the specified table."""
        return MockQuery(table, self)
    
    def get_table_data(self, table: str) -> List[Dict]:
        """Get all data for a table."""
        return self._data.get(table, [])
    
    def count(self, table: str, **filters) -> int:
        """Count rows in table with optional filters."""
        data = self._data.get(table, [])
        if filters:
            data = [row for row in data if all(
                row.get(k) == v for k, v in filters.items()
            )]
        return len(data)
    
    def insert(self, table: str, data: Dict) -> Dict:
        """Insert a new row into table."""
        # Generate new ID
        existing_data = self._data.get(table, [])
        new_id = max([row.get('id', 0) for row in existing_data], default=0) + 1
        
        new_row = {'id': new_id, **data}
        self._data[table].append(new_row)
        return new_row
    
    def commit(self):
        """Commit transaction (no-op for mock)."""
        pass
    
    def rollback(self):
        """Rollback transaction (no-op for mock)."""
        pass


def get_db_session() -> MockSession:
    """Get a database session."""
    return MockSession()


@contextmanager
def transaction():
    """Context manager for database transactions."""
    session = get_db_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
