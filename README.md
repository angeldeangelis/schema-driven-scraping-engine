<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Playwright-Async-green.svg" alt="Playwright">
  <img src="https://img.shields.io/badge/Pandas-Data%20Processing-orange.svg" alt="Pandas">
  <img src="https://img.shields.io/badge/OpenPyXL-Excel%20Output-brightgreen.svg" alt="OpenPyXL">
</p>

<h1 align="center">⚙️ Config-Driven Web Scraping Engine</h1>

<p align="center">
  <em>A schema-driven data extraction pipeline built on async Playwright — add a new target site by writing a config block, not new code.</em>
</p>

---

## What This Is

Most scraping projects start as a script and die as technical debt: one file per site, duplicated logic everywhere, and a rewrite every time a page structure changes. This engine inverts that. Every site is a **declarative schema**. The pipeline logic never changes — only the config does.

But this isn't just a scraper. It's a **market intelligence infrastructure**. The output isn't raw JSON or CSV dumps. It's a **structured intelligence brief** that answers strategic questions before the client asks them.

---

## Production Benchmarks

Real extraction runs against live, protected marketplaces. No cached data. No synthetic tests.

| Target | Records | Pages | Price Range | Anomalies Detected | Extraction Time |
|--------|---------|-------|-------------|-------------------|-----------------|
| **eBay** (laptops) | 480 | 9 | $0.99 – $4,395 | 10 statistical outliers | ~60s |
| **WeWorkRemotely** (remote jobs) | 50 | 1 | N/A | N/A | ~5s |

**Intelligence output per run:**
- Price distribution analysis (min, max, mean, median, p90, std)
- Keyword clustering and low-density signal detection
- Entity concentration mapping (competitive landscape)
- Statistical anomaly identification (>3σ outlier detection)
- **Calibrated strategic question** derived from data gaps

---

## The Architecture

```
                    ┌─────────────────────┐
                    │   SCHEMA_MAP (JSON)  │
                    │  (config per domain) │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Strategy Router     │
                    │  json / index / rss   │
                    │      / detail         │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
       ┌────────────┐   ┌────────────┐   ┌──────────────┐
       │  Async      │   │  Universal  │   │  Bronze Cache │
       │  Playwright │──▶│   Parser    │──▶│  (raw HTML/   │
       │  Harvester  │   │ (3 formats) │   │   JSON, dated)│
       └────────────┘   └────────────┘   └──────────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Validation Layer    │
                    │ (schema-aware filter) │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Silver Processor     │
                    │ dedup + merge + type  │
                    │      coercion         │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Market Intelligence  │
                    │       Brief           │
                    │ (Excel, 4 sheets)     │
                    └───────────────────────┘
```

### Bronze → Silver → Intelligence

- **Bronze**: Immutable raw cache. Re-process without re-hitting the target.
- **Silver**: Deduplicated, type-coerced, incrementally merged master dataset.
- **Intelligence**: Narrative analysis, competitive signals, and strategic questions.

---

## Key Features

🎯 **Schema-driven extraction, three formats, one parser**  
A single `universal_parser` handles JSON APIs, cached static HTML (BeautifulSoup), and live JS-rendered pages (Playwright). Switching a site from "needs a full browser" to "has a JSON endpoint" is a one-line config change.

⚡ **Concurrency-controlled async harvesting**  
Semaphore-managed worker pool, not naive `asyncio.gather` on every URL. Configurable limits prevent the frequency-based throttling that gets naive scrapers banned.

🕵️ **Stealth session architecture**  
Webdriver flag masking, realistic fingerprint consistency, randomized scroll simulation, and 403-triggered fallback fetch — built for sites that actively detect automation.

💾 **Bronze → Silver data layering**  
Raw responses cached to disk before parsing. Re-processing (new dedup logic, fixed parser) never requires re-hitting the target. Structured output lands in incrementally merged Excel masters.

🔁 **Incremental merge + adaptive deduplication**  
Every run merges against existing history. Dedup keys are configurable per-schema (title+URL, job title+company, etc.) with domain-appropriate fallbacks.

🛡️ **Resilient by default**  
Retry with backoff, empty-page circuit breaker, graceful 403 fallback, and safe browser context cleanup even on failure.

---

## Quick Start

```bash
git clone https://github.com/angeldeangelis/schema-driven-scraping-engine.git
cd schema-driven-scraping-engine
pip install -r requirements.txt
playwright install chromium
python main.py --urls "https://quotes.toscrape.com" --limit 50
```

Output lands in `data/silver/` — a master Excel file with full history, plus a dated CSV snapshot in `data/samples/`.

---

## Adding a New Target Site

Open `src/settings.py`, add an entry to `SCHEMA_MAP`:

```python
"example-shop.com": {
    "strategy": "index",
    "container": "div[data-product-card]",
    "fields": {
        "title": {"attribute": "data-product-name"},
        "price": "span[class*='price']",
        "link": {"selector": "a[href*='/products/']", "attribute": "href"}
    },
    "dedup_keys": ["title", "source_url"],
    "pagination_pattern": "{base_clean}?page={i}"
}
```

Run it. No new Python files. No new parsing branches. That's the entire integration surface.

---

## What This Isn't

This is an **engine**, not a plug-and-play scraper for every site on the internet.

- Sites with aggressive bot-detection (Cloudflare challenge pages, heavy fingerprinting) may need additional evasion tuning.
- Selectors are inherently site-specific — you'll always need to inspect the target DOM and write a schema.
- What this removes is everything *around* that: browser orchestration, concurrency management, caching, deduplication, incremental storage, and intelligence synthesis — so you're only ever solving the one problem that's actually unique to your target.

---

## Available for Hire

I build and operate custom data intelligence pipelines for competitive analysis, pricing monitoring, lead generation, and market research.

- **Upwork**: [Hire me](upwork.com/freelancers/~015591486ae29424db?__cf_chl_rt_tk=J37qIhQS5fdtCDRVnvz6aBkuzDkY23v3pDdWUBWXT7U-1784932063-1.0.1.1-1KmkkgkaLStbFMyQhD_4CVHzew54yZ7SxaBQnf4eXZQ)
- **Email**: angeldeangelis1@gmail.com

If your project involves extracting structured intelligence from messy web environments, I can probably help.

---

## Tech Stack

| Layer | Tool |
|-------|------|
| Browser automation | Playwright (async) |
| Parsing | BeautifulSoup4 + native Playwright DOM evaluation |
| Data processing | Pandas |
| Config management | Pydantic Settings |
| Output | OpenPyXL (Excel) + CSV |
