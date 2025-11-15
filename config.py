"""
Configuration management for AI-Augmented Web Scraper
"""
from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    APP_NAME: str = "AI-Augmented Web Scraper"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Services
    GATEWAY_HOST: str = "0.0.0.0"
    GATEWAY_PORT: int = 8000
    
    DISCOVERY_URL: str = "http://discovery-agent:8001"
    EXTRACTION_URL: str = "http://extraction-agent:8002"
    VISION_URL: str = "http://vision-agent:8003"
    CAMOUFOX_URL: str = "http://camoufox-agent:8004"
    MODEL_MANAGER_URL: str = "http://model-manager:8005"
    
    # Ollama
    OLLAMA_HOST: str = "http://ollama:11434"
    OLLAMA_TIMEOUT: int = 300
    
    # Models Configuration
    VISION_MODEL: str = "llava"
    LLM_MODEL: str = "llama3.1"
    EMBEDDING_MODEL: str = "bge-m3"
    CODE_MODEL: str = "deepseek-coder"
    RAG_MODEL: str = "llama3-chatqa"
    
    # MongoDB
    MONGODB_URL: str = "mongodb://mongodb:27017"
    MONGODB_DB: str = "webscraper"
    
    # Redis
    REDIS_URL: str = "redis://redis:6379"
    
    # Storage
    DATA_DIR: str = "/data"
    MODELS_DIR: str = "/models"
    
    # Scraping
    MAX_CONCURRENT_REQUESTS: int = 10
    REQUEST_TIMEOUT: int = 30
    USER_AGENT: str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    
    # Processing
    MAX_RETRIES: int = 3
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
