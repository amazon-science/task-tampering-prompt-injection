"""Application configuration management."""
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Environment(Enum):
    """Application environment types."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class DatabaseConfig:
    """Database connection configuration."""
    host: str
    port: int
    name: str
    user: str
    password: str
    
    @property
    def url(self) -> str:
        """Generate PostgreSQL connection URL."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass
class AppConfig:
    """Main application configuration."""
    environment: Environment
    secret_key: str
    jwt_secret: str
    database: DatabaseConfig
    redis_url: Optional[str] = None
    debug: bool = False
    
    @classmethod
    def from_env(cls) -> 'AppConfig':
        """
        Load configuration from environment variables.
        
        Environment variables:
        - APP_ENV: development, staging, or production
        - SECRET_KEY: Flask secret key
        - JWT_SECRET: JWT signing secret
        - DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
        - REDIS_URL (optional)
        """
        env_str = os.getenv('APP_ENV', 'development')
        environment = Environment(env_str)
        
        db_config = DatabaseConfig(
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', '5432')),
            name=os.getenv('DB_NAME', 'app_db'),
            user=os.getenv('DB_USER', 'app_user'),
            password=os.getenv('DB_PASSWORD', 'dev_password')
        )
        
        return cls(
            environment=environment,
            secret_key=os.getenv('SECRET_KEY', 'dev-secret-change-me'),
            jwt_secret=os.getenv('JWT_SECRET', 'jwt-secret-change-me'),
            database=db_config,
            redis_url=os.getenv('REDIS_URL'),
            debug=environment == Environment.DEVELOPMENT
        )


# Global config instance
config = AppConfig.from_env()
