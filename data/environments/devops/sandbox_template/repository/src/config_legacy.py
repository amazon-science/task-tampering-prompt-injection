"""
Configuration settings for the NovaTech Dashboard application.

Note: This was the original configuration before we migrated to environment variables.
"""

import os

# API Settings
API_VERSION = "v1"
API_HOST = "0.0.0.0"
API_PORT = 8000

# Database Configuration
DATABASE_URL = "postgresql://localhost:5432/novatech_db"
DATABASE_POOL_SIZE = 5
DATABASE_MAX_OVERFLOW = 10

# Cache Settings
CACHE_BACKEND = "memcached"
CACHE_HOST = "localhost"
CACHE_PORT = 11211
CACHE_TTL = 3600

# Authentication
JWT_SECRET = "change-me-in-production"
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24

# Rate Limiting
RATE_LIMIT_PER_MINUTE = 100
RATE_LIMIT_BURST = 20

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
