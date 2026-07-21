from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Dict, Any, List, Optional

class Settings(BaseSettings):
    # --- System Architecture Paths ---
    # Optimized to resolve strictly to the project root regardless of execution directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    BRONZE_PATH: Path = BASE_DIR / "data" / "bronze"
    SILVER_PATH: Path = BASE_DIR / "data" / "silver"
    LOG_PATH: Path = BASE_DIR / "logs"
    
    # --- Execution Constraints ---
    CONCURRENCY: int = 3
    MAX_ITEMS: int = 160
    TIMEOUT_MS: int = 45000
    HEADLESS_MODE: bool = False
    BYPASS_CACHE: bool = False
    
    # --- Storefront Scroll Metrics ---
    SCROLL_STEPS: int = 15
    SCROLL_DELAY: float = 0.8
    
    # --- Browser/Network Stealth Fingerprinting ---
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    VIEWPORT: Dict[str, int] = {"width": 1920, "height": 1080}
    BROWSER_ARGS: List[str] = [
        "--no-sandbox", 
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--start-maximized",
        "--disable-dev-shm-usage" # Added to prevent memory crashes during deep pagination
    ]
    HTTP_HEADERS: Dict[str, str] = {
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1"
    }
    
    # --- Adaptive Resilience ---
    FALLBACK_GATEWAY: str = "https://api.allorigins.win/get?url={url}"
    PROXY_CONFIG: Optional[Dict[str, str]] = None

    # --- Domain Mapping & Intelligence Schemas ---
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
            "strategy": "json",
            "container": "jobs", 
            "fields": {
                "job_title": "title",
                "company": "company_name",
                "link": "url"
            }
        },
        "gymshark.com": {
            "strategy": "index",
            "container": "article[class*='product-card'], div[class*='product-card']", 
            "fields": {
                "title": "[class*='title'], [class*='name'], h3",
                "price": "[class*='price'], span[class*='Price']"
            },
            "strip_url_query": False,
            "dedup_keys": ["title", "price"],
            "pagination_param": "page",
            "start_page": 1,
            "items_per_page": 60,
            "pagination_pattern": "{base_clean}?page={i}"
        },
        "allbirds.com": {
            "strategy": "index",
            "container": "div[data-product-card]", 
            "fields": {
                "title": {"attribute": "data-product-name"},
                "model": {"attribute": "data-product-name"},
                "color": "p[data-product-colorway], span[class*='color'], p[class*='text-xs']",
                "price": "span.text-red, span[class*='text-red'], span[class*='price'], p span.font-medium, span.font-semibold",
                "link": {"selector": "a[href*='/products/']", "attribute": "href"}
            },
            "strip_url_query": False,
            "dedup_keys": ["title", "source_url"],
            "pagination_param": "page",
            "start_page": 1,
            "pagination_pattern": "{base_clean}?page={i}"
        },
        "weworkremotely.com": {
            "strategy": "index",
            "container": "section.jobs article, div.job, a.listing-link--unlocked, li.feature",
            "fields": {
                "job_title": "h3.new-listing__header_title, span.title, h3, .job-title",
                "company": "p.new-listing__company-name, span.company, .company-name",
                "link": {"selector": "a", "attribute": "href"}
            },
            "strip_url_query": True,
            "dedup_keys": ["job_title", "company"],
            "start_page": 1,
            "pagination_param": "page",
            "pagination_pattern": "{base_clean}?page={i}"
        },
        "data.wa.gov": {
        "strategy": "index",
        "container": "div.slick-row, div.presenter-row, tr",
        "fields": {
            "make": "div.column-make, td.make, span.make",
            "model": "div.column-model, td.model, span.model",
            "model_year": "div.column-model_year, td.model_year, span.model_year",
            "electric_range": "div.column-electric_range, td.electric_range, span.electric_range",
            "link": {"selector": "a", "attribute": "href"}
        },
        "strip_url_query": True,
        "dedup_keys": ["make", "model", "model_year"],
        "start_page": 1,
        "pagination_param": "page",
        "pagination_pattern": "{base_clean}?page={i}"
        },
    }

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

config = Settings()
