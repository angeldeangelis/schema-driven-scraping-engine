import asyncio, logging, datetime, random
from pathlib import Path
from bs4 import BeautifulSoup 
from playwright.async_api import async_playwright
from src.settings import config

config.BRONZE_PATH.mkdir(parents=True, exist_ok=True)
config.SILVER_PATH.mkdir(parents=True, exist_ok=True)


def validate_data(data, source_url):
    """
    Validates data based on the schema mapping defined in settings.
    """
    # 1. Determine which fields are required based on the domain
    # We look for the domain in our global config schema map
    required_fields = next(
        (fields for domain, fields in config.SCHEMA_MAP.items() if domain in source_url), 
        ['title', 'price'] # Fallback default
    )
    
    # 2. Perform the validation
    return all(data.get(field) for field in required_fields)

async def get_item(browser, url, parse_item_func, retries=2):
    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    today = datetime.date.today().isoformat()
    raw_dir = config.BRONZE_PATH / domain / today
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    url_hash = str(hash(url))
    existing_files = list(raw_dir.glob(f"{url_hash}_*.html"))
    
    # --- PATH 2: CACHE HIT ---
    if existing_files:
        logging.info(f"[*] Parsing cached file for {url}")
        with open(existing_files[0], "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
            data = await parse_item_func(soup)  # Added await here since parse_item_func is async
            data.update({"source_url": url, "scraped_at": "CACHED"})
            return data if validate_data(data, url) else None

    # --- PATH 1: LIVE SCRAPE ---
    for attempt in range(retries):
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # 1. APPLY STEALTH (Manual Injection)
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            # 2. NAVIGATE
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await add_jitter(1, 3) 
            
            # 3. SCRAPE (The Data Extraction)
            raw_data = await page.content()
            filename = raw_dir / f"{url_hash}_{datetime.datetime.now().strftime('%H%M%S')}.html"
            with open(filename, "w", encoding="utf-8") as f: 
                f.write(raw_data)
            
            data = await parse_item_func(page)
            
            # 4. VALIDATE & RETURN
            if validate_data(data, url):
                data.update({
                    "source_url": url, 
                    "scraped_at": datetime.datetime.now().isoformat()
                })
                return data # Success!
            
            logging.warning(f"Validation failed for {url} on attempt {attempt+1}")
            
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed for {url}: {e}")
            await asyncio.sleep(5)
        finally:
            # This closes the context ONLY after the scrape attempt is finished
            await context.close()
            
    return None
            
async def run_pipeline(urls, parse_item_func):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 1. Semaphore manages your concurrency/rate limits
        semaphore = asyncio.Semaphore(config.CONCURRENCY)
        
        async def worker(url):
            async with semaphore: 
                return await get_item(browser, url, parse_item_func)
        
        # 2. Limit the batch size and initiate tasks
        tasks = [worker(u) for u in urls[:config.MAX_ITEMS]]
        
        # 3. Execution and gathering results
        results = await asyncio.gather(*tasks)
        
        await browser.close()
        
        # 4. Return clean data: filter None (failed scrapes/validations)
        return [r for r in results if r is not None]

async def add_jitter(min_seconds=1, max_seconds=3):
    """Wait for a random time to simulate human behavior."""
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))