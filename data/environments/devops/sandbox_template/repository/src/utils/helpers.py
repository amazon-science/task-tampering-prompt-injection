"""Utility helper functions for common operations."""
import re
from typing import Any, Dict, List
from html import escape


def sanitize_input(value: str) -> str:
    """
    Sanitize user input to prevent XSS attacks.
    
    Args:
        value: Input string to sanitize
    
    Returns:
        Sanitized string safe for output
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Escape HTML special characters
    value = escape(value)
    
    # Remove any null bytes
    value = value.replace('\x00', '')
    
    # Limit length
    max_length = 1000
    if len(value) > max_length:
        value = value[:max_length]
    
    return value.strip()


def format_response(data: Any, status: str = 'success') -> Dict:
    """
    Format API response in consistent structure.
    
    Args:
        data: Response data (can be dict, list, or primitive)
        status: Response status ('success' or 'error')
    
    Returns:
        Formatted response dictionary
    """
    return {
        'status': status,
        'data': data
    }


def paginate_results(items: List[Any], page: int = 1, per_page: int = 20) -> Dict:
    """
    Paginate a list of items.
    
    Args:
        items: List of items to paginate
        page: Page number (1-indexed)
        per_page: Items per page
    
    Returns:
        Dictionary with paginated results and metadata
    """
    total = len(items)
    total_pages = (total + per_page - 1) // per_page
    
    # Correct pagination calculation
    start = (page - 1) * per_page
    end = start + per_page
    
    page_items = items[start:end]
    
    return {
        'items': page_items,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': total_pages
        }
    }


def validate_email(email: str) -> bool:
    """
    Validate email address format.
    
    Args:
        email: Email address string
    
    Returns:
        True if valid email format
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def format_datetime(dt) -> str:
    """
    Format datetime object to ISO 8601 string.
    
    Args:
        dt: Datetime object
    
    Returns:
        ISO 8601 formatted string
    """
    try:
        return dt.isoformat()
    except (AttributeError, TypeError):
        return str(dt)
