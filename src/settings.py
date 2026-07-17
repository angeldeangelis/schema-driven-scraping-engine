from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, List

class Settings(BaseSettings):
    # Base paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    BRONZE_PATH: Path = BASE_DIR / "data" / "bronze"
    SILVER_PATH: Path = BASE_DIR / "data" / "silver"
    LOG_PATH: Path = BASE_DIR / "logs"
    
    # Execution constants
    CONCURRENCY: int = 3
    MAX_ITEMS: int = 120
    
    # 1. SCHEMA FINGERPRINTS: Map domains to their structural rules
    # This allows your validator to act dynamically without hardcoding
    SCHEMA_MAP: Dict[str, List[str]] = {
        "books.toscrape.com": ["title", "price"],
        "another-job-site.com": ["job_title", "salary_range", "location"]
    }

    # 2. ENVIRONMENT CONFIG: Load secrets (like proxy API keys) from a .env file
    # Prevents sensitive credentials from being committed to Git
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

config = Settings()