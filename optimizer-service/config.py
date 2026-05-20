"""Configuration management for the optimization service."""
import os
from typing import List


class Config:
    """Application configuration."""
    
    # CORS
    CORS_ORIGINS: List[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    
    # File validation
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024
    
    # Rate limiting
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    RATE_LIMIT_PERIOD: str = os.getenv("RATE_LIMIT_PERIOD", "1 minute")
    
    # OSRM circuit breaker
    OSRM_MAX_RETRIES: int = int(os.getenv("OSRM_MAX_RETRIES", "3"))
    OSRM_RETRY_BACKOFF_BASE: float = float(os.getenv("OSRM_RETRY_BACKOFF_BASE", "1.0"))
    OSRM_FAILURE_CACHE_MINUTES: int = int(os.getenv("OSRM_FAILURE_CACHE_MINUTES", "5"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


config = Config()
