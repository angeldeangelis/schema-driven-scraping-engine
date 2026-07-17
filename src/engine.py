import asyncio, logging, datetime
from pathlib import Path
from bs4 import BeautifulSoup 
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from src.settings import config

config.BRONZE_PATH.mkdir(parents=True, exist_ok=True)
config.SILVER_PATH.mkdir(parents=True, exist_ok=True)

def validate_data(data, source_url):
    """
    Validates data based on the structural fingerprint of the source URL.
    """
    # 1. Map URLs to their required structural signatures (Fingerprinting)
    schema_map = {
        "freelance.com": ['title', 'price'],
        "jobboard.net": ['job_title', 'compensation', 'location']
    }
    
    # 2. Determine the ruleset dynamically
    # Default to a basic set if the source is unknown
    required_fields = next((fields for url, fields in schema_map.items() if url in source_url), ['title', 'price'])
    
    # 3. Perform the validation
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
            
            # --- IMPROVEMENT: USE THE INJECTED PARSER ---
            # Instead of hardcoding h1/price_color, we call the function passed in
            data = parse_item_func(soup)
            
            # Add metadata
            data.update({"source_url": url, "scraped_at": "CACHED"})
            
            # --- IMPROVEMENT: USE THE DYNAMIC VALIDATOR ---
            return data if validate_data(data, url) else None

    # --- PATH 1: LIVE SCRAPE ---
    for attempt in range(retries):
        context = await browser.new_context()
        await Stealth().apply_stealth_async(context)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            raw_data = await page.content()
            filename = raw_dir / f"{url_hash}_{datetime.datetime.now().strftime('%H%M%S')}.html"
            with open(filename, "w", encoding="utf-8") as f: 
                f.write(raw_data)
            
            # Use the parser with the live page object
            data = await parse_item_func(page)
            
            # Use the dynamic validator with the source URL fingerprint
            if validate_data(data, url):
                data.update({
                    "source_url": url, 
                    "scraped_at": datetime.datetime.now().isoformat()
                })
                return data
            
            logging.warning(f"Validation failed for {url} on attempt {attempt+1}")
            return None # Or continue to next attempt if validation failed
            
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed for {url}: {e}")
            await asyncio.sleep(5)
        finally:
            await context.close()
            
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