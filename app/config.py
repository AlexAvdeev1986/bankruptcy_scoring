# app/config.py
import os
from typing import List
from pydantic import BaseSettings, Field

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(
        default="postgresql://user:password@db:5432/bankruptcy_db",
        env="DATABASE_URL"
    )
    
    # Proxy settings
    PROXY_LIST: List[str] = []
    PROXY_ROTATION_ENABLED: bool = True
    MAX_RETRIES: int = 3
    REQUEST_TIMEOUT: int = 30
    
    # External sources
    FSSP_BASE_URL: str = "https://fssp.gov.ru"
    FEDRESURS_API_URL: str = "https://fedresurs.ru/backend/companies"
    ROSREESTR_API_URL: str = "https://rosreestr.gov.ru/api"
    COURT_API_URL: str = "https://api.courts.ru"
    TAX_API_URL: str = "https://service.nalog.ru"
    
    # Scoring settings
    MIN_DEBT_AMOUNT: int = 250000
    MIN_SCORE_THRESHOLD: int = 50
    
    # File paths
    INPUT_DATA_PATH: str = "/app/data/input"
    OUTPUT_DATA_PATH: str = "/app/data/output"
    LOGS_PATH: str = "/app/data/logs"
    
    # Processing settings
    BATCH_SIZE: int = 10000
    MAX_CONCURRENT_REQUESTS: int = 50
    
    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

settings = Settings()
