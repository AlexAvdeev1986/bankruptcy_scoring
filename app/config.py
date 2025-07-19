import os
from typing import List
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://user:password@localhost/bankruptcy_db"
    PROXY_LIST: List[str] = []
    PROXY_ROTATION_ENABLED: bool = True
    MAX_RETRIES: int = 3
    REQUEST_TIMEOUT: int = 30
    MIN_DEBT_AMOUNT: int = 250000
    MIN_SCORE_THRESHOLD: int = 50
    INPUT_DATA_PATH: str = "./data/input"
    OUTPUT_DATA_PATH: str = "./data/output"
    LOGS_PATH: str = "./data/logs"
    BATCH_SIZE: int = 10000
    MAX_CONCURRENT_REQUESTS: int = 50

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

    def __init__(self, **values):
        super().__init__(**values)
        # Преобразование строки прокси в список
        if isinstance(self.PROXY_LIST, str):
            self.PROXY_LIST = [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]

settings = Settings()
