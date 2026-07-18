import asyncio
import httpx
import logging
import datetime
import random
import json
from pathlib import Path
from bs4 import BeautifulSoup 
from playwright.async_api import async_playwright
from src.settings import config

# Ensure directories exist dynamically based on config
config.BRONZE_PATH.mkdir(parents=True, exist_ok=True)
config.SILVER_PATH.mkdir(parents=True, exist_ok=True)


def validate_data(data_items, source_url):
    """
    Validates data adaptively based purely on the configured schema.
    """
    if not data_items or not isinstance(data_items, list):
        return False

    domain = next((d for d in config.SCHEMA_MAP if d in source_url), None)
    
    # If no domain schema exists, we assume success if data was parsed by a fallback
    if not domain:
        return len(data_items) > 0

    fields_cfg = config.SCHEMA_MAP[domain].get('fields', {})
    if not fields_cfg:
        return len(data_items) > 0

    # Ensure at least the first defined field (usually the primary key) exists
    primary_key = list(fields_cfg.keys())[0]
    
    for item in data_items:
        if not item.get(primary_key) or item.get(primary_key) == 'N/A':
            return False
            
    return True


async def universal_parser(page_or_soup, source_url):
    """
    Polymorphic extraction engine handling JSON, Soup, or Playwright objects.
    """
    domain = next((d for d in config.SCHEMA_MAP if d in source_url), None)
    if not domain:
        logging.warning(f"[!] No schema configuration found for: {source_url}")
        return []
        
    site_cfg = config.SCHEMA_MAP[domain]
    container_selector = site_cfg.get('container', 'item')
    fields_cfg = site_cfg.get('fields', {})
    field_keys = list(fields_cfg.keys())
    primary_key = field_keys[0] if field_keys else None
    
    # --- PATH C: PARSING PROGRAMMATIC JSON APIS ---
    # This path triggers when the input is a dict (from httpx.get().json())
    if isinstance(page_or_soup, dict):
        try:
            extracted_items = []
            # Access the list under the 'container' key defined in SCHEMA_MAP
            records = page_or_soup.get(container_selector, [])
            
            for record in records:
                item_data = {'source_url': source_url}
                for key, data_key in fields_cfg.items():
                    # Handle nested keys or direct values
                    item_data[key] = str(record.get(data_key, 'N/A')).strip()
                extracted_items.append(item_data)
            return extracted_items
        except Exception as e:
            logging.error(f"[-] JSON structural parsing failed: {e}")
            return []

    # --- PATH A: PARSING CACHED SOUP / STATIC STRINGS ---
    if isinstance(page_or_soup, BeautifulSoup):
        # ... (Your existing BeautifulSoup logic remains perfectly valid) ...
        extracted_items = []
        is_rss = site_cfg.get("strategy") == "rss" or page_or_soup.find('rss') or page_or_soup.find('feed')
        containers = page_or_soup.find_all(container_selector) if is_rss else page_or_soup.select(container_selector)
        
        for container in containers:
            item_data = {'source_url': source_url}
            for key, selector in fields_cfg.items():
                selectors = [selector] if isinstance(selector, str) else selector
                element = None
                for sel in selectors:
                    element = container.find(sel) if is_rss else container.select_one(sel)
                    if element: break
                raw_text = element.get_text(strip=True) if element else ''
                item_data[key] = " ".join(raw_text.split())
            
            if (primary_key and item_data.get(primary_key)) or not primary_key:
                extracted_items.append(item_data)
        return extracted_items

    # --- PATH B: PARSING LIVE PLAYWRIGHT PAGE ---
    else:
        # ... (Your existing Playwright logic remains perfectly valid) ...
        actual_url = page_or_soup.url
        try:
            await page_or_soup.wait_for_selector(container_selector, timeout=2000, state="attached")
        except Exception:
            logging.info(f"[*] Proceeding with immediate extraction: {actual_url}")
        
        js_fields = []
        for key, sel in fields_cfg.items():
            sanitized_sel = ", ".join(sel) if isinstance(sel, list) else sel
            js_fields.append(f"'{key}': (() => {{ const el = e.querySelector('{sanitized_sel}'); return el && el.textContent ? el.textContent.trim().replace(/\\s+/g, ' ') : ''; }})()")
        
        js_payload = ", ".join(js_fields)
        js_query = f"elements => elements.map(e => {{ return {{ 'source_url': '{actual_url}', {js_payload} }}; }})"
        
        return await page_or_soup.eval_on_selector_all(container_selector, js_query)


import httpx # Ensure this is imported at the top of engine.py
import json

async def get_item(browser, url, parse_item_func, retries=2):
    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    
    # --- PATH: API BYPASS ---
    schema = config.SCHEMA_MAP.get(domain, {})
    if schema.get("strategy") == "json":
        logging.info(f"[*] Executing direct API fetch for: {url}")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                data_items = await parse_item_func(data, url)
                
                if validate_data(data_items, url):
                    for item in data_items:
                        item.update({"source_url": url, "scraped_at": datetime.datetime.now().isoformat()})
                    return data_items
        except Exception as e:
            logging.error(f"[-] API Fetch failed for {url}: {e}")
            return None

    # --- BROWSER CACHE & RENDER PATH (For HTML sites) ---
    today = datetime.date.today().isoformat()
    raw_dir = config.BRONZE_PATH / domain / today
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    url_hash = str(abs(hash(url)))
    existing_files = list(raw_dir.glob(f"{url_hash}_*.html"))
    
    # CACHE HIT
    if existing_files:
        logging.info(f"[*] Parsing cached file for {url}")
        try:
            with open(existing_files[0], "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
                data_items = await parse_item_func(soup, url)  
                if validate_data(data_items, url):
                    for item in data_items:
                        item.update({"source_url": url, "scraped_at": "CACHED"})
                    return data_items
        except Exception as e:
            logging.error(f"Cache read failed for {url}: {e}")

    # LIVE SCRAPE
    for attempt in range(retries):
        proxy_config = getattr(config, 'PROXY_CONFIG', None)
        context = await browser.new_context(
            user_agent=getattr(config, 'USER_AGENT', "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36"),
            viewport=getattr(config, 'VIEWPORT', {"width": 1920, "height": 1080}),
            proxy=proxy_config,
            extra_http_headers=getattr(config, 'HTTP_HEADERS', {"Upgrade-Insecure-Requests": "1"})
        )
        page = await context.new_page()
        
        try:
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=getattr(config, 'TIMEOUT_MS', 45000))
            
            if response and response.status == 403:
                fallback_url = getattr(config, 'FALLBACK_GATEWAY', None)
                if fallback_url:
                    logging.warning(f"[!] Blocked (403). Routing through un-fingerprinted gateway...")
                    await page.goto(fallback_url.format(url=url), wait_until="domcontentloaded", timeout=30000)
                    raw_html = await page.locator("body").text_content()
                else:
                    raw_html = await page.content()
            else:
                raw_html = await page.content()
            
            filename = raw_dir / f"{url_hash}_{datetime.datetime.now().strftime('%H%M%S')}.html"
            with open(filename, "w", encoding="utf-8") as f: 
                f.write(raw_html)
            
            if "Access Denied" in raw_html or not raw_html:
                raise ValueError("Firewall block detected.")
            
            data_items = await parse_item_func(BeautifulSoup(raw_html, "html.parser"), url)
            
            if validate_data(data_items, url):
                for item in data_items:
                    item.update({"source_url": url, "scraped_at": datetime.datetime.now().isoformat()})
                return data_items 
                
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed for {url}: {e}")
            await add_jitter(1, 3)
        finally:
            await context.close()
            
    return None


async def run_pipeline(urls, parse_item_func=universal_parser):
    async with async_playwright() as p:
        # Pull browser arguments from config to remove hardcoding
        browser_args = getattr(config, 'BROWSER_ARGS', ["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        is_headless = getattr(config, 'HEADLESS_MODE', False)
        
        browser = await p.chromium.launch(
            headless=is_headless, 
            args=browser_args
        )
        semaphore = asyncio.Semaphore(config.CONCURRENCY)
        
        async def worker(url):
            async with semaphore: 
                return await get_item(browser, url, parse_item_func)
        
        tasks = [worker(u) for u in urls[:config.MAX_ITEMS]]
        results = await asyncio.gather(*tasks)
        
        await browser.close()
        
        flattened_results = []
        for res in results:
            if res is not None:
                flattened_results.extend(res)
                
        return flattened_results


async def add_jitter(min_seconds=1, max_seconds=3):
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))