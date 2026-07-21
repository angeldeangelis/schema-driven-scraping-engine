import re
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
from datetime import datetime, date
import hashlib

config.BRONZE_PATH.mkdir(parents=True, exist_ok=True)
config.SILVER_PATH.mkdir(parents=True, exist_ok=True)

def get_nested_value(dictionary, dot_path, default='N/A'):
    """Resolves dot-notation and index keys for nested dictionary structures."""
    keys = dot_path.split('.')
    return_val = dictionary
    try:
        for key in keys:
            if isinstance(return_val, list):
                return_val = return_val[int(key)]
            else:
                return_val = return_val[key]
        return return_val
    except (KeyError, TypeError, ValueError, IndexError):
        return default

def resolve_url_netloc(url: str) -> str:
    """The one place that turns a URL into a clean domain string (used for cache paths)."""
    return url.split("//")[-1].split("/")[0].replace("www.", "")

def get_domain_config(url: str):
    """
    Single source of truth for URL -> SCHEMA_MAP lookup.
    """
    netloc = resolve_url_netloc(url)
    if netloc in config.SCHEMA_MAP:
        return netloc, config.SCHEMA_MAP[netloc]
    for key, cfg in config.SCHEMA_MAP.items():
        if key in url:
            return key, cfg
    return None, {}

def validate_data(data_items, source_url):
    """
    Production-grade soft validator: filters out severely malformed rows 
    while preserving partial records to prevent data loss at 5,000+ scale.
    """
    if not data_items or not isinstance(data_items, list):
        logging.warning(f"[!] Validation failed: No data items or invalid format for {source_url}")
        return []

    _, site_cfg = get_domain_config(source_url)
    fields_cfg = site_cfg.get('fields', {})
    if not fields_cfg:
        return data_items
        
    primary_key = list(fields_cfg.keys())[0]
    
    valid_items = []
    malformed_count = 0
    
    for item in data_items:
        val = str(item.get(primary_key, '')).strip()
        # Soft fallback validation: allow partial data if link or company is present
        if not val or val == 'N/A':
            if not item.get('link') and not item.get('company'):
                malformed_count += 1
                continue
            else:
                item[primary_key] = "N/A - Pending Review"
        valid_items.append(item)
        
    if malformed_count > 0:
        logging.warning(f"[*] Validation gracefully handled {malformed_count} malformed/empty elements from grid.")

    return valid_items

async def universal_parser(page_or_soup, source_url):
    domain, site_cfg = get_domain_config(source_url)
    if not site_cfg:
        logging.warning(f"[!] No schema configuration found for: {source_url}")
        return []
        
    container_selector = site_cfg.get('container', 'item')
    fields_cfg = site_cfg.get('fields', {})
    field_keys = list(fields_cfg.keys())
    primary_key = field_keys[0] if field_keys else None
    
    CLEAN_TITLE_REGEX = r'^\d+(\.\d+)?\s*'
    
    # --- PATH C: PARSING PROGRAMMATIC JSON APIS ---
    if isinstance(page_or_soup, dict):
        try:
            extracted_items = []
            records = get_nested_value(page_or_soup, container_selector, [])
            if not isinstance(records, list):
                records = [records] if records else []
            
            for record in records:
                item_data = {'source_url': source_url}
                for key, data_key in fields_cfg.items():
                    val = get_nested_value(record, data_key, 'N/A')
                    cleaned_val = str(val).strip()
                    if key == 'title' or key == 'job_title':
                        cleaned_val = re.sub(CLEAN_TITLE_REGEX, '', cleaned_val)
                    item_data[key] = cleaned_val
                extracted_items.append(item_data)
            return extracted_items
        except Exception as e:
            logging.error(f"[-] JSON structural parsing failed: {e}")
            return []

    # --- PATH A: PARSING CACHED SOUP / STATIC STRINGS ---
    elif isinstance(page_or_soup, BeautifulSoup):
        extracted_items = []
        is_rss = site_cfg.get("strategy") == "rss" or page_or_soup.find('rss') or page_or_soup.find('feed')
        
        containers = []
        if is_rss:
            containers = page_or_soup.find_all(container_selector)
        else:
            for selector_part in [s.strip() for s in container_selector.split(",")]:
                found_containers = page_or_soup.select(selector_part)
                if found_containers:
                    containers.extend(found_containers)
                    break 
        
        for container in containers:
            item_data = {'source_url': source_url}
            for key, selector in fields_cfg.items():
                # Handle dictionary rules inside BeautifulSoup parsing path safely
                if isinstance(selector, dict):
                    sel = selector.get("selector")
                    attr = selector.get("attribute")
                elif isinstance(selector, list):
                    sel, attr = ", ".join(selector), None
                else:
                    sel, attr = selector, None

                element = container
                if sel:
                    for sub_sel in [s.strip() for s in sel.split(",")]:
                        element = container.find(sub_sel) if is_rss else container.select_one(sub_sel)
                        if element:
                            break

                if attr:
                    raw_text = element.get(attr, '') if element else ''
                else:
                    raw_text = element.get_text(strip=True) if element else ''
                    
                normalized_text = " ".join(str(raw_text).split())
                
                if key in ['title', 'job_title']:
                    normalized_text = re.sub(CLEAN_TITLE_REGEX, '', normalized_text)
                    
                item_data[key] = normalized_text if normalized_text else 'N/A'
            
            extracted_items.append(item_data)
        return extracted_items

    # --- PATH B: PARSING LIVE PLAYWRIGHT PAGE ---
    else:
        actual_url = page_or_soup.url
        try:
            await page_or_soup.wait_for_selector(container_selector, timeout=3000, state="attached")
        except Exception:
            logging.info(f"[*] Proceeding with immediate extraction: {actual_url}")

        js_fields = []
        for key, rule in fields_cfg.items():
            safe_key = json.dumps(key)

            if isinstance(rule, dict):
                sel = rule.get("selector")
                attr = rule.get("attribute")
            elif isinstance(rule, list):
                sel, attr = ", ".join(rule), None
            else:
                sel, attr = rule, None

            safe_sel = json.dumps(sel) if sel else None
            safe_attr = json.dumps(attr) if attr else None

            if safe_sel and safe_attr:
                if attr == "href":
                    getter = f"(() => {{ const el = e.querySelector({safe_sel}); return el ? (el.href || '') : ''; }})()"
                else:
                    getter = f"(() => {{ const el = e.querySelector({safe_sel}); return el ? (el.getAttribute({safe_attr}) || '') : ''; }})()"
            elif safe_attr and not safe_sel:
                if attr == "href":
                    getter = "(e.href || '')"
                else:
                    getter = f"(e.getAttribute({safe_attr}) || '')"
            elif safe_sel and not safe_attr:
                getter = f"(() => {{ const el = e.querySelector({safe_sel}); return el && el.textContent ? el.textContent.trim().replace(/\\s+/g, ' ') : ''; }})()"
            else:
                # Fallback: if container itself holds text directly (like We Work Remotely anchor tags)
                getter = "(() => { return e.textContent ? e.textContent.trim().replace(/\\s+/g, ' ') : ''; })()"

            if key in ['title', 'job_title']:
                js_fields.append(
                    f"{safe_key}: (() => {{ "
                    f"  let txt = {getter}; "
                    f"  if (!txt) return 'N/A'; "
                    f"  txt = txt.trim().replace(/\\s+/g, ' '); "
                    f"  return txt.replace(/^\\d+(\\.\\d+)?\\s*/, '').trim(); "
                    f"}})()"
                )
            else:
                js_fields.append(f"{safe_key}: ({getter} || 'N/A')")

        js_payload = ", ".join(js_fields)
        safe_url = json.dumps(actual_url)
        js_query = f"elements => elements.map(e => {{ return {{ 'source_url': {safe_url}, {js_payload} }}; }})"

        return await page_or_soup.eval_on_selector_all(container_selector, js_query)

async def get_item(browser, url, parse_item_func, retries=2):
    netloc = resolve_url_netloc(url)
    _, schema = get_domain_config(url)
    strategy = schema.get("strategy", "detail")
    strip_query = schema.get("strip_url_query", True)
    bypass_cache = getattr(config, 'BYPASS_CACHE', False)

    today = date.today().isoformat()
    raw_dir = config.BRONZE_PATH / netloc / today
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    clean_hash_url = url if not strip_query else url.split("?")[0]
    url_hash = hashlib.md5(clean_hash_url.encode('utf-8')).hexdigest()[:16]
    
    file_ext = "json" if strategy == "json" else "html"
    existing_files = list(raw_dir.glob(f"{url_hash}_*.{file_ext}"))
    
    # --- 1. LOCAL CACHE LAYER ---
    if existing_files and not bypass_cache:
        logging.info(f"[*] Parsing cached {strategy.upper()} asset file for {url}")
        try:
            with open(existing_files[0], "r", encoding="utf-8") as f:
                file_content = f.read()
                if strategy == "json":
                    parsed_payload = json.loads(file_content)
                else:
                    parsed_payload = BeautifulSoup(file_content, "html.parser")
                    
                data_items = await parse_item_func(parsed_payload, url)  
                validated_items = validate_data(data_items, url)
                if validated_items:
                    for item in validated_items:
                        item.update({"source_url": url, "scraped_at": "CACHED"})
                    return validated_items
        except Exception as e:
            logging.error(f"[-] Cache read execution failed for {url}: {e}")

    # --- 2. NETWORK LIVE HARVESTING SEQUENCE ---
    for attempt in range(retries):
        context = await browser.new_context(
            viewport=getattr(config, 'VIEWPORT', {"width": 1920, "height": 1080}),
            proxy=getattr(config, 'PROXY_CONFIG', None)
        )
        page = await context.new_page()
        
        try:
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)
            
            clean_domain = url.split("//")[-1].split("/")[0]
            base_domain_url = f"https://{clean_domain}"
            
            logging.info(f"[*] Pre-warming connection session via: {base_domain_url}")
            await page.goto(base_domain_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)
            
            logging.info(f"[*] Dispatching browser context to data target: {url}")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=getattr(config, 'TIMEOUT_MS', 45000))
            
            target_selector = schema.get("wait_for_selector") or schema.get("container")
            if target_selector:
                try:
                    await page.wait_for_selector(target_selector, timeout=5000)
                except Exception:
                    await asyncio.sleep(1.5)

            scroll_steps = getattr(config, 'SCROLL_STEPS', 5)
            scroll_delay = getattr(config, 'SCROLL_DELAY', 0.5)
            
            for scroll_step in range(scroll_steps):
                await page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(scroll_delay)  
            
            await asyncio.sleep(1.0) 
            
            if response and response.status == 403:
                raw_payload = await page.evaluate(f'async (target_url) => {{ const r = await fetch(target_url); return await r.text(); }}', url)
            else:
                if strategy == "json":
                    raw_payload = await page.evaluate("() => document.body.innerText")
                else:
                    raw_payload = await page.content()
            
            if strategy == "json":
                parsed_data = json.loads(raw_payload.strip())
                data_items = await parse_item_func(parsed_data, url)
            else:
                parsed_data = BeautifulSoup(raw_payload, "html.parser")
                data_items = await parse_item_func(parsed_data, url)
            
            validated_items = validate_data(data_items, url)
            if validated_items:
                timestamp_str = datetime.now().strftime('%H%M%S')
                filename = raw_dir / f"{url_hash}_{timestamp_str}.{file_ext}"
                with open(filename, "w", encoding="utf-8") as f: 
                    f.write(raw_payload.strip() if strategy == "json" else raw_payload)
                    
                current_iso = datetime.now().isoformat()
                for item in validated_items:
                    item.update({"source_url": url, "scraped_at": current_iso})
                
                return validated_items 
            else:
                raise ValueError("Extracted schema entries failed validation logic checks.")
                
        except Exception as e:
            logging.error(f"[-] Connection attempt {attempt+1} failed for {url}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(3)
        finally:
            try:
                await context.close()
            except Exception:
                pass
            
    return None

async def run_pipeline(urls, parse_item_func=universal_parser, browser=None):
    owns_browser = browser is None
    playwright_ctx = None

    if owns_browser:
        playwright_ctx = await async_playwright().start()
        browser_args = getattr(config, 'BROWSER_ARGS', ["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        browser = await playwright_ctx.chromium.launch(
            headless=getattr(config, 'HEADLESS_MODE', True), args=browser_args
        )

    try:
        semaphore = asyncio.Semaphore(getattr(config, 'CONCURRENCY', 3))

        async def worker(url):
            async with semaphore:
                return await get_item(browser, url, parse_item_func)

        tasks = [worker(u) for u in urls[:getattr(config, 'MAX_ITEMS', 5000)]]
        results = await asyncio.gather(*tasks)

        flattened_results = []
        for res in results:
            if res is not None:
                flattened_results.extend(res)
        return flattened_results
    finally:
        if owns_browser:
            await browser.close()
            await playwright_ctx.stop()

async def add_jitter(min_seconds=1, max_seconds=3):
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))