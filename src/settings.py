from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the data extraction pipeline."""

    # --- System Architecture Paths ---
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    BRONZE_PATH: Path = BASE_DIR / "data" / "bronze"
    SILVER_PATH: Path = BASE_DIR / "data" / "silver"
    LOG_PATH: Path = BASE_DIR / "logs"

    # --- Execution Constraints ---
    CONCURRENCY: int = 3
    MAX_ITEMS: int = 160
    TIMEOUT_MS: int = 45000
    HEADLESS_MODE: bool = True
    BYPASS_CACHE: bool = False

    # --- Interaction & Scrolling Metrics ---
    SCROLL_STEPS: int = 15
    SCROLL_DELAY: float = 0.8

    # --- Browser & Network Stealth Fingerprinting ---
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    VIEWPORT: Dict[str, int] = {"width": 1920, "height": 1080}
    BROWSER_ARGS: List[str] = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--start-maximized",
        "--disable-dev-shm-usage",
    ]
    HTTP_HEADERS: Dict[str, str] = {
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
    }

    # --- Resilience Configuration ---
    FALLBACK_GATEWAY: str = "https://api.allorigins.win/get?url={url}"
    PROXY_CONFIG: Optional[Dict[str, str]] = None

    # --- Domain Mapping & Intelligence Schemas ---
    SCHEMA_MAP: Dict[str, Dict[str, Any]] = {
        "quotes.toscrape.com": {
            "strategy": "index",
            "container": ".quote",
            "fields": {
                "text": ".text",
                "author": ".author",
            },
            "strip_url_query": True,
            "dedup_keys": ["text", "author"],
            "start_page": 1,
            "pagination_param": "page",
            "pagination_pattern": "{base_clean}/page/{i}/",
        },
        "books.toscrape.com": {
            "strategy": "index",
            "container": "article.product_pod",
            "fields": {
                "title": "h3 a",
                "price": "p.price_color",
                "link": {"selector": "h3 a", "attribute": "href"},
            },
            "strip_url_query": True,
            "dedup_keys": ["title", "price"],
            "start_page": 1,
            "pagination_param": "page",
            "pagination_pattern": "{base_clean}/catalogue/page-{i}.html",
        },
    }

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


config = Settings()