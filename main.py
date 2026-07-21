import asyncio
import datetime
import argparse
import logging
import os
import pandas as pd
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from playwright.async_api import async_playwright
from src.engine import run_pipeline, universal_parser, validate_data, get_domain_config
from src.processor import process_to_silver, generate_summary
from src.settings import config

logger = logging.getLogger("system")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def build_paginated_url(base_url: str, page_num: int, site_cfg: dict) -> str:
    pagination_pattern = site_cfg.get("pagination_pattern")
    page_param = site_cfg.get("pagination_param", "page")
    if pagination_pattern:
        return pagination_pattern.format(base_url=base_url.rstrip('/'), base_clean=base_url.rstrip('/'), i=page_num)
    parsed = urlparse(base_url)
    query_dict = parse_qs(parsed.query)
    query_dict[page_param] = [str(page_num)]
    new_query = urlencode(query_dict, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def save_checkpoint(records, filename="datastore_checkpoint.csv"):
    if not records:
        return
    df = pd.DataFrame(records)
    # Deduplicate dynamically on core identifiers to prevent pollution
    subset_keys = [col for col in ["job_title", "company", "link"] if col in df.columns]
    if subset_keys:
        df.drop_duplicates(subset=subset_keys, keep="first", inplace=True)
    df.to_csv(filename, index=False)


async def get_links_from_page(page, url, site_cfg):
    container_selector = site_cfg.get('container', 'body')
    try:
        await page.goto(url, timeout=getattr(config, 'TIMEOUT_MS', 45000), wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")
        links = await page.eval_on_selector_all(
            f"{container_selector} a[href]",
            "elements => elements.map(e => e.href)"
        )
        return list(set(links))
    except Exception as e:
        logger.error(f"[-] Link discovery failed on {url}: {e}")
        return []


async def main(target_url: str, item_limit: int):
    logger.info(f"[*] Starting production system pipeline. Target: {target_url} | Target Limit: {item_limit}")

    domain, site_cfg = get_domain_config(target_url)
    strategy = site_cfg.get("strategy", "detail")

    accumulated_data = []
    consecutive_empty_pages = 0
    max_empty_retries = 5  # Increased tolerance for large-scale runs
    current_page = site_cfg.get("start_page", 1)

    checkpoint_filename = f"checkpoint_{domain.replace('.', '_')}.csv"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=getattr(config, 'HEADLESS_MODE', True))
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

        try:
            if strategy == "json":
                logger.info(f"[*] API strategy detected. Executing direct extraction...")
                raw_data = await run_pipeline([target_url], parse_item_func=universal_parser, browser=browser)
                if raw_data:
                    accumulated_data = raw_data[:item_limit]
            else:
                while len(accumulated_data) < item_limit:
                    # Memory Leak Prevention: Recycle context and page every 10 pages at scale
                    if current_page > 1 and current_page % 10 == 0:
                        logger.info(f"[*] Memory maintenance: Recycling browser context at page {current_page}...")
                        await page.close()
                        await context.close()
                        context = await browser.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                        )
                        page = await context.new_page()
                        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

                    page_url = build_paginated_url(target_url, current_page, site_cfg) if current_page > 1 else target_url
                    logger.info(f"[*] Processing Page {current_page}: {page_url} | Progress: {len(accumulated_data)}/{item_limit}")

                    batch_items = []
                    if strategy in ["index", "rss"]:
                        try:
                            await page.goto(page_url, wait_until="domcontentloaded", timeout=45000)

                            container_sel = site_cfg.get("container", "body")
                            if container_sel:
                                await page.wait_for_selector(container_sel, state="attached", timeout=15000)

                            if site_cfg.get("auto_scroll", True):
                                await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                                await asyncio.sleep(1.5)

                            raw_batch = await universal_parser(page, page_url)
                            
                            # FIXED: Capture the validated/cleaned data output properly
                            batch_items = validate_data(raw_batch, page_url) or []

                            stamp = datetime.datetime.now().isoformat()
                            for item in batch_items:
                                item.setdefault("scraped_at", stamp)

                        except Exception as nav_err:
                            logger.warning(f"[!] Extraction warning for {page_url}: {nav_err}")
                            batch_items = []
                    else:
                        detail_links = await get_links_from_page(page, page_url, site_cfg)
                        if detail_links:
                            needed_slots = item_limit - len(accumulated_data)
                            target_links = detail_links[:needed_slots]
                            raw_detail_batch = await run_pipeline(target_links, parse_item_func=universal_parser, browser=browser)
                            batch_items = validate_data(raw_detail_batch, page_url) or []

                    if not batch_items:
                        consecutive_empty_pages += 1
                        logger.warning(f"[!] Zero valid records extracted from page {current_page}.")
                        if consecutive_empty_pages >= max_empty_retries:
                            logger.warning("[!] Reached maximum consecutive empty pages. Halting crawl sequence.")
                            break
                    else:
                        consecutive_empty_pages = 0
                        # Respect the overall item limit per batch append
                        slots_remaining = item_limit - len(accumulated_data)
                        accumulated_data.extend(batch_items[:slots_remaining])
                        
                        # Incremental checkpoint flush to protect data at scale
                        save_checkpoint(accumulated_data, checkpoint_filename)

                    current_page += 1

        finally:
            await context.close()
            await browser.close()

    if accumulated_data:
        final_data = accumulated_data[:item_limit]
        logger.info("[*] Generating market analytics summary...")
        generate_summary(final_data)
        logger.info("[*] Committing data to storage files...")
        process_to_silver(final_data)
        
        # Cleanup checkpoint file upon successful completion
        if os.path.exists(checkpoint_filename):
            os.remove(checkpoint_filename)
            
        logger.info(f"[*] Pipeline finished successfully. Total records processed: {len(final_data)}")
    else:
        logger.warning("[!] Data extraction engine finished with empty results. No files generated.")


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(description="Professional Data Extraction System")
    cli_parser.add_argument("--urls", nargs='+', required=True, help="List of starting URLs")
    cli_parser.add_argument("--limit", type=int, default=20, help="Max total items to collect")
    args = cli_parser.parse_args()

    for target_url in args.urls:
        asyncio.run(main(target_url, args.limit))