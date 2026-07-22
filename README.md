# ⚙️ Config-Driven Web Scraping Engine

**A schema-driven data extraction pipeline built on async Playwright — add a new target site by writing a config block, not new code.**

Most scraping projects start as a script and die as technical debt: one file per site, duplicated logic everywhere, and a rewrite every time a page structure changes. This engine inverts that. Every site is a declarative schema. The pipeline logic never changes — only the config does.

---

## The Problem This Solves

Scraping breaks in predictable ways:

- **Sites load content dynamically** — static HTML parsers miss 30-40% of real data
- **Anti-bot systems throttle by frequency**, not just User-Agent — naive concurrency gets you IP-banned in minutes
- **Every new target site means new code** — unless the extraction logic is decoupled from the target's structure
- **Re-running a scrape duplicates data** — unless deduplication and incremental merging are built in from day one, not bolted on later

This engine was built to solve all four at the architecture level, not with one-off patches.

---

## How It Works

```
                    ┌─────────────────────┐
                    │     SCHEMA_MAP       │
                    │  (config, per domain)│
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
                    │  Excel + CSV Output   │
                    │  (incremental, atomic)│
                    └───────────────────────┘
```

**One target site = one schema entry.** No new Python files, no new parsing logic.

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

That's the entire integration surface for a new site.

---

## Key Features

**🎯 Schema-driven extraction, three formats, one parser**
A single `universal_parser` handles JSON APIs, cached static HTML (BeautifulSoup), and live JS-rendered pages (Playwright) — the same field-mapping schema works across all three, so switching a site from "needs a full browser" to "has a JSON endpoint" is a one-line config change, not a rewrite.

**⚡ Concurrency-controlled async harvesting**
Semaphore-managed worker pool, not naive `asyncio.gather` on every URL at once. Configurable concurrency limits prevent the exact frequency-based throttling that gets naive scrapers IP-banned.

**🕵️ Stealth session handling**
Webdriver flag masking, realistic session pre-warming, randomized scroll simulation, and 403-triggered fallback fetch — built for sites that actively try to detect automation, not just static pages.

**💾 Bronze → Silver data layering**
Raw responses are cached to disk (`bronze/`) before any parsing happens, timestamped and hashed by URL. This means re-processing a scrape (new dedup logic, fixed parser bug) never requires re-hitting the target site. Validated, structured output lands in `silver/` — Excel master files with full history, plus clean per-run CSV snapshots.

**🔁 Incremental merge + adaptive deduplication**
Every run merges against existing history rather than overwriting it. Dedup keys are configurable per-schema (title+URL, job title+company, whatever fits the domain) with sane fallbacks when a schema doesn't specify one.

**🛡️ Resilient by default**
Retry logic with backoff, empty-page circuit breaker (halts pagination after N consecutive empty results instead of looping forever), graceful fallback fetch on 403 responses, and safe browser context cleanup even on failure.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Browser automation | Playwright (async) |
| HTTP fallback | HTTPX |
| Parsing | BeautifulSoup4 + native Playwright DOM evaluation |
| Data processing | Pandas |
| Config management | Pydantic Settings |
| Output | OpenPyXL (Excel) + CSV |

---

## Quick Start

```bash
git clone https://github.com/angeldeangelis/schema-driven-scraping-engine.git
cd schema-driven-scraping-engine
pip install -r requirements.txt
playwright install chromium
```

```bash
python main.py --urls "https://quotes.toscrape.com" --limit 50
```

Output lands in `data/silver/` — a master Excel file with full history, plus a dated CSV snapshot in `data/samples/`.

---

## Adding a New Target Site

1. Open `src/settings.py`
2. Add an entry to `SCHEMA_MAP` keyed by domain
3. Define `strategy` (`json` / `index` / `rss` / `detail`), `container`, and `fields`
4. Run it

No new Python files. No new parsing branches. That's the entire point of the architecture.

---

## What This Isn't

This is a boilerplate engine, not a plug-and-play scraper for every site on the internet. Sites with aggressive bot-detection (Cloudflare challenge pages, heavy fingerprinting) may need additional evasion tuning beyond what's here. Selectors are inherently site-specific — you'll always need to inspect your target's DOM and write a schema for it. What this engine removes is everything *around* that: the browser orchestration, the concurrency management, the caching, the deduplication, the incremental storage — so you're only ever solving the one problem that's actually unique to your target.

---

## License

MIT — use it, fork it, adapt it. If it saves you the week it took to build, that's the point.

---

Built and maintained by [Ángel de Angelis](https://github.com/angeldeangelis). Questions or want a version tailored to a specific pipeline? [Reach out](#).
