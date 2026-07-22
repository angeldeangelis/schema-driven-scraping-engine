import argparse
import asyncio
import datetime
import logging
import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import pandas as pd
from playwright.async_api import async_playwright

from src.engine import get_domain_config, run_pipeline, universal_parser, validate_data
from src.processor import generate_summary, process_to_silver
from src.settings import config

logger = logging.getLogger("system")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def build_paginated_url(base_url: str, page_num: int, site_cfg: dict) -> str:
    """Constructs dynamic paginated URLs based on domain schema configurations."""
    pagination_pattern = site_cfg.get("pagination_pattern")
    page_param = site_cfg.get("pagination_param", "page")

    if pagination_pattern:
        parsed = urlparse(base_url)
        query_dict = parse_qs(parsed.query)
        # Extract primary query param dynamically if present, defaulting to empty string
        query_val = query_dict.get("k", [""])[0] or query_dict.get("q", [""])[0]
        base_clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        return pagination_pattern.format(
            base_url=base_url.rstrip("/"),
            base_clean=base_clean.rstrip("/"),
            query=query_val,
            i=page_num,
        )

    parsed = urlparse(base_url)
    query_dict = parse_qs(parsed.query)
    query_dict[page_param] = [str(page_num)]
    new_query = urlencode(query_dict, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def save_checkpoint(records: list, filename: str = "datastore_checkpoint.csv") -> None:
    """Saves interim extraction batches to prevent data loss on high-volume runs."""
    if not records:
        return
    df = pd.DataFrame(records)
    subset_keys = [col for col in ["title", "job_title", "company", "link", "source_url"] if col in df.columns]
    if subset_keys:
        df.drop_duplicates(subset=subset_keys, keep="first", inplace=True)
    df.to_csv(filename, index=False)


async def get_links_from_page(page, url: str, site_cfg: dict) -> list[str]:
    """Extracts target detail links from index pages."""
    container_selector = site_cfg.get("container", "body")
    try:
        await page.goto(url, timeout=getattr(config, "TIMEOUT_MS", 45000), wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle")
        links = await page.eval_on_selector_all(
            f"{container_selector} a[href]",
            "elements => elements.map(e => e.href)",
        )
        return list(set(links))
    except Exception as e:
        logger.error(f"[-] Link discovery failed on {url}: {e}")
        return []


async def main(target_url: str, item_limit: int) -> None:
    """Core orchestration pipeline for web collection, validation, and storage."""
    logger.info(f"[*] Executing pipeline. Target: {target_url} | Target Limit: {item_limit}")

    domain, site_cfg = get_domain_config(target_url)
    strategy = site_cfg.get("strategy", "detail")

    accumulated_data = []
    consecutive_empty_pages = 0
    max_empty_retries = 5
    current_page = site_cfg.get("start_page", 1)

    checkpoint_filename = f"checkpoint_{domain.replace('.', '_')}.csv"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=getattr(config, "HEADLESS_MODE", True))
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

        try:
            if strategy == "json":
                logger.info("[*] API endpoint strategy detected. Processing direct payload...")
                raw_data = await run_pipeline([target_url], parse_item_func=universal_parser, browser=browser)
                if raw_data:
                    accumulated_data = raw_data[:item_limit]
            else:
                while len(accumulated_data) < item_limit:
                    # Recycle browser contexts periodically to prevent memory inflation
                    if current_page > 1 and current_page % 10 == 0:
                        logger.info(f"[*] Maintenance: Recycling browser context at iteration {current_page}...")
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
                        logger.warning(f"[!] Zero records extracted from page {current_page}.")
                        if consecutive_empty_pages >= max_empty_retries:
                            logger.warning("[!] Maximum consecutive empty pages reached. Halting crawl sequence.")
                            break
                    else:
                        consecutive_empty_pages = 0
                        slots_remaining = item_limit - len(accumulated_data)
                        accumulated_data.extend(batch_items[:slots_remaining])
                        save_checkpoint(accumulated_data, checkpoint_filename)

                    current_page += 1

        finally:
            await context.close()
            await browser.close()

    if accumulated_data:
        final_data = accumulated_data[:item_limit]
        logger.info("[*] Generating dataset metrics summary...")
        generate_summary(final_data)
        logger.info("[*] Committing dataset to silver storage layer...")
        process_to_silver(final_data)

        if os.path.exists(checkpoint_filename):
            os.remove(checkpoint_filename)

        logger.info(f"[*] Pipeline completed successfully. Total records processed: {len(final_data)}")
    else:
        logger.warning("[!] Extraction engine finished with empty results. No outputs generated.")


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(description="Modular Web Scraping & Data Extraction Pipeline")
    cli_parser.add_argument("--urls", nargs="+", required=True, help="List of target URLs to process")
    cli_parser.add_argument("--limit", type=int, default=20, help="Maximum number of items to extract")
    args = cli_parser.parse_args()

    for target_url in args.urls:
        asyncio.run(main(target_url, args.limit))