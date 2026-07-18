import asyncio
import datetime
import argparse
import httpx
import logging
import sys
from playwright.async_api import async_playwright
from src.engine import run_pipeline, universal_parser  # Import the modular parser we created
from src.processor import process_to_silver, generate_summary
from src.settings import config

# Setup logger
logger = logging.getLogger("system")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def get_links_from_page(browser, url):
    """
    Polymorphic Link Harvester: Dynamically routes link discovery based on 
    the schema's execution strategy config with zero domain hardcoding.
    """
    # 1. Resolve domain mapping schema upfront
    domain = next((d for d in config.SCHEMA_MAP if d in url), None)
    if not domain:
        logger.warning(f"[!] No schema configuration found to discover links for: {url}")
        return []
        
    site_cfg = config.SCHEMA_MAP[domain]
    strategy = site_cfg.get("strategy", "index")

    # 2. CONFIGURATION PASS: If strategy treats the target as a standalone index or feed container, 
    # bypass browser overhead completely and return the item immediately.
    if strategy in ["index", "rss"]:
        return [url]

    # 3. DEEP CRAWLING PASS: Execute browser layout analysis if deep extraction strategy is configured
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)
    
    try:
        await page.goto(url, timeout=60000)
        await page.wait_for_load_state("networkidle")
        
        container_selector = site_cfg['container']
        
        # Pull internal links dynamically using the custom configurations map layout
        links = await page.eval_on_selector_all(
            f"{container_selector} h3 a", 
            "elements => elements.map(e => e.href)"
        )
        return links
        
    except Exception as e:
        logger.error(f"Error executing link discovery on {url}: {e}")
        return []
        
    finally:
        if context:
            await context.close()


async def discover_all_links(browser, base_url, limit):
    """
    Dynamically maps target layouts based on structural schema strategy definitions.
    Completely decoupled from domain-specific strings.
    """
    domain = next((d for d in config.SCHEMA_MAP if d in base_url), None)
    
    # Safely default to 'detail' if no matching configuration map exists
    site_cfg = config.SCHEMA_MAP[domain] if domain else {}
    strategy = site_cfg.get("strategy", "detail")
    pagination_pattern = site_cfg.get("pagination_pattern")  # Read pattern configuration if specified
    
    # Calculate targets assuming a standard volume baseline of 20 elements per payload view
    items_per_page = site_cfg.get("items_per_page", 20)
    pages_to_visit = (limit // items_per_page) + (1 if limit % items_per_page > 0 else 0)

    # --- STRATEGY A: STANDALONE ENDPOINTS (INDEX & RSS FEEDS) ---
    if strategy in ["index", "rss"]:
        logger.info(f"[*] Executing target data harvesting sequence for single-tier asset: {base_url}")
        
        # If pagination isn't supported or explicitly declared for this index layout, return it early
        if not pagination_pattern:
            return [base_url]
            
        discovered_pages = [base_url]
        if pages_to_visit > 1:
            for i in range(2, pages_to_visit + 1):
                # Dynamically construct multi-page indices using standard formatting injections
                discovered_pages.append(pagination_pattern.format(base_url=base_url.rstrip('/'), i=i))
        return discovered_pages

    # --- STRATEGY B: DETAIL-BASED DEEP CRAWLING (Only executes if pattern is known) ---
    logger.info(f"[*] Probing pagination patterns for item details: {base_url}")
    
    base_clean = base_url.rstrip('/')
    # If the site configuration profile explicitly contains the template path, use it directly!
    if pagination_pattern:
        candidates = [pagination_pattern.format(base_clean=base_clean, i=2)]
    else:
        # Configuration Fallback Profile: only test logical variants if no strict template exists
        candidates = [
            f"{base_clean}/page/2/",
            f"{base_clean}/?page=2",
            f"{base_clean}/p/2"
        ]
    
    tasks = [get_links_from_page(browser, url) for url in candidates]
    results = await asyncio.gather(*tasks)
    
    working_template = None
    discovered_links = []

    for candidate_url, links in zip(candidates, results):
        if links:
            logger.info(f"[+] Locked onto working pagination pattern: {candidate_url}")
            discovered_links.extend(links)
            # Find the number '2' in the working url block and change it to the template placeholder
            # safely preserving rest of layout tree strings
            working_template = candidate_url.replace("page=2", "page={i}").replace("page/2/", "page/{i}/").replace("/p/2", "/p/{i}")
            break

    # Gather index seed asset links
    page_1_links = await get_links_from_page(browser, base_url)
    if page_1_links:
        discovered_links.extend(page_1_links)

    # Crawl remaining target layers concurrently
    if working_template and pages_to_visit > 2:
        remaining_urls = []
        for i in range(3, pages_to_visit + 1):
            if "page=" in working_template:
                remaining_urls.append(working_template.format(i=i))
            else:
                remaining_urls.append(working_template.replace("{i}", str(i)))
                
        remaining_tasks = [get_links_from_page(browser, u) for u in remaining_urls]
        remaining_results = await asyncio.gather(*remaining_tasks)
        
        for sublist in remaining_results:
            if isinstance(sublist, list):
                discovered_links.extend(sublist)

    return list(set(discovered_links))

async def main(target_url, item_limit):
    logger.info(f"[*] Starting system pipeline. Target: {target_url} | Limit: {item_limit}")
    
    domain = next((d for d in config.SCHEMA_MAP if d in target_url), None)
    strategy = config.SCHEMA_MAP[domain].get("strategy", "detail") if domain else "detail"

    data = [] # Initialize as empty list for safety

    # --- ROUTING: API VS BROWSER ---
    if strategy == "json":
        # API strategy: Skip discovery, go straight to extraction
        logger.info(f"[*] API strategy detected. Bypassing link discovery.")
        raw_data = await run_pipeline([target_url], parse_item_func=universal_parser)
        if raw_data:
            data = raw_data[:item_limit]
    
    else:
        # Browser strategy: Proceed with discovery
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=config.HEADLESS_MODE)
            all_links = await discover_all_links(browser, target_url, item_limit)
            await browser.close()
            
            if not all_links:
                logger.warning("[!] No execution links discovered.")
                return

            logger.info(f"[*] Discovery phase complete. Found {len(all_links)} assets.")
            
            if strategy == "index":
                raw_data = await run_pipeline(all_links, parse_item_func=universal_parser)
                if raw_data:
                    flattened = []
                    for result in raw_data:
                        if isinstance(result, list): flattened.extend(result)
                        elif isinstance(result, dict): flattened.append(result)
                    data = flattened[:item_limit]
            else:
                raw_data = await run_pipeline(all_links[:item_limit], parse_item_func=universal_parser)
                if raw_data:
                    data = raw_data

    # 3. STORAGE AND CLEANUP MANAGEMENT
    if data:
        process_to_silver(data)
        generate_summary(data)
        logger.info(f"[*] Pipeline finish complete. Processed {len(data)} items securely.")
    else:
        logger.warning("[!] Data extraction engine finished with empty data maps.")

if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(description="Professional Data Extraction System")
    cli_parser.add_argument("--urls", nargs='+', required=True, help="List of starting URLs")
    cli_parser.add_argument("--limit", type=int, default=20, help="Max items")
    
    args = cli_parser.parse_args()
    print(f"DEBUG: Received URLs: {args.urls}") # Add this to verify args are passed
    
    for target_url in args.urls:
        asyncio.run(main(target_url, args.limit))