from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, Any, List, Optional

class Settings(BaseSettings):
    # Base paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    BRONZE_PATH: Path = BASE_DIR / "data" / "bronze"
    SILVER_PATH: Path = BASE_DIR / "data" / "silver"
    LOG_PATH: Path = BASE_DIR / "logs"
    
    # --- Execution Constants ---
    CONCURRENCY: int = 3
    MAX_ITEMS: int = 120
    TIMEOUT_MS: int = 45000
    HEADLESS_MODE: bool = False
    
    # --- Browser/Network Fingerprinting ---
    USER_AGENT: str = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    VIEWPORT: Dict[str, int] = {"width": 1920, "height": 1080}
    BROWSER_ARGS: List[str] = [
        "--no-sandbox", 
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--start-maximized"
    ]
    HTTP_HEADERS: Dict[str, str] = {
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1"
    }
    
    # --- Adaptive Resilience ---
    # {url} placeholder allows the engine to inject the target dynamically
    FALLBACK_GATEWAY: str = "https://api.allorigins.win/get?url={url}"
    PROXY_CONFIG: Optional[Dict[str, str]] = None # Format: {"server": "http://ip:port"}

    # --- Data Schemas ---
    SCHEMA_MAP: Dict[str, Dict[str, Any]] = {
        "quotes.toscrape.com": {
            "strategy": "index",
            "container": ".quote",
            "fields": {"text": ".text", "author": ".author"}
        },
        "remote.co": {
            "strategy": "index",
            "container": "a.job-row",
            "fields": {
                "job_title": ".card-title",
                "company": ".co-name",
                "link": "href"
            }
        },
        "remotive.com": {
            "strategy": "json",  # Changed from "rss" to "json"
            "container": "jobs", # Maps to the 'jobs' list in the API response
            "fields": {
                "job_title": "title",
                "company": "company_name",
                "link": "url"
            }
        }
    }

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

config = Settings()