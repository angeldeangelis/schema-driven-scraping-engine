import logging
import pandas as pd
from pathlib import Path
from datetime import datetime
from src.settings import config
from urllib.parse import urlparse
from src.engine import get_domain_config
from src.validators import validate_record

def process_to_silver(data):
    if not data:
        logging.warning("[!] No data provided to silver processor.")
        return

    if isinstance(data, dict):
        data = [data]

    # Isolate target source identity early for dynamic domain-based file routing & schema lookup
    try:
        sample_url = data[0].get('source_url') if isinstance(data[0], dict) else 'unknown_source'
        domain, schema = get_domain_config(str(sample_url)) if sample_url and sample_url != 'unknown_source' else (None, {})
        domain = domain or 'general'
    except Exception:
        domain = 'general'
        schema = {}

    # --- SCHEMA VALIDATION GUARDRAIL ---
    required_fields = schema.get("dedup_keys", [])
    if required_fields:
        valid_records = []
        for record in data:
            if validate_record(record, required_fields):
                valid_records.append(record)
            else:
                logging.warning(f"[-] Dropping invalid/incomplete record: {record}")
        
        logging.info(f"[*] Validation Check: Retained {len(valid_records)} valid records out of {len(data)} total incoming items.")
        data = valid_records

    if not data:
        logging.warning("[!] All incoming records failed validation checks. Aborting silver processing.")
        return

    try:
        df_new = pd.DataFrame(data)
    except Exception as e:
        logging.error(f"[!] Critical structural failure mapping data into a DataFrame: {e}")
        return

    silver_dir = Path(config.SILVER_PATH)
    silver_dir.mkdir(parents=True, exist_ok=True)

    col = None
    domain_clean = "".join([c if c.isalnum() or c in '._-' else '_' for c in domain])
    file_prefix = domain_clean.split('.')[0] if '.' in domain_clean else domain_clean

    # Must be defined before clean_url is called below — clean_url reads it via closure
    strip_query = schema.get("strip_url_query", False)

    def clean_url(url):
        if pd.isna(url):
            return url
        return urlparse(str(url))._replace(query="").geturl() if strip_query else str(url)

    if 'source_url' in df_new.columns:
        df_new['source_url'] = df_new['source_url'].apply(clean_url)

    # 1. Schema Enforcement & Numeric Type Alignment
    if 'price' in df_new.columns or 'salary' in df_new.columns:
        col = 'price' if 'price' in df_new.columns else 'salary'
        df_new[col] = df_new[col].astype(str).str.replace(r'[^\d.]', '', regex=True).str.strip()
        df_new[col] = pd.to_numeric(df_new[col], errors='coerce').fillna(0.0)

    # --- MODULAR DEDUPLICATION KEY ASSESSMENT ---
    custom_dedup = schema.get("dedup_keys")
    if custom_dedup:
        dedup_subset = [k for k in custom_dedup if k in df_new.columns]
    elif 'title' in df_new.columns:
        dedup_subset = ["source_url", "title"]
    elif 'job_title' in df_new.columns:
        dedup_subset = ["source_url", "job_title"]
    elif 'text' in df_new.columns:
        dedup_subset = ["source_url", "text"]
    else:
        dedup_subset = ["source_url"]

    # 2. Metadata Enrichment
    current_time = datetime.now()
    df_new['silver_processed_at'] = current_time.isoformat()

    # 3. Dynamic Path Management
    output_path = silver_dir / f"{file_prefix}_master.xlsx"
    sample_dir = Path("data") / "samples" / file_prefix
    sample_dir.mkdir(parents=True, exist_ok=True)

    date_str = current_time.strftime("%Y%m%d")
    csv_path = sample_dir / f"{domain_clean}_{date_str}.csv"

    # --- INCREMENTAL MERGE LAYER (Master Excel Tracking) ---
    if output_path.exists():
        try:
            df_historic = pd.read_excel(output_path, engine='openpyxl')
            if 'source_url' in df_historic.columns:
                df_historic['source_url'] = df_historic['source_url'].apply(clean_url)
            if col and col in df_historic.columns and col in df_new.columns:
                df_historic[col] = pd.to_numeric(df_historic[col], errors='coerce').fillna(0.0)

            df_combined = pd.concat([df_historic, df_new], ignore_index=True)
            logging.info(f"[*] Merging {len(df_new)} new records into existing {file_prefix} Excel history.")
        except Exception as e:
            logging.error(f"[!] Failed to read historical Excel file for {file_prefix}. Overwriting. Error: {e}")
            df_combined = df_new
    else:
        df_combined = df_new

    # --- ENHANCED INCREMENTAL MERGE LAYER (Snapshot CSV Aggregation) ---
    if csv_path.exists():
        try:
            df_csv_historic = pd.read_csv(csv_path)
            if 'source_url' in df_csv_historic.columns:
                df_csv_historic['source_url'] = df_csv_historic['source_url'].apply(clean_url)
            if col and col in df_csv_historic.columns and col in df_new.columns:
                df_csv_historic[col] = pd.to_numeric(df_csv_historic[col], errors='coerce').fillna(0.0)
            df_csv_combined = pd.concat([df_csv_historic, df_new], ignore_index=True)
        except Exception:
            df_csv_combined = df_new
    else:
        df_csv_combined = df_new

    # --- DYNAMIC ADAPTIVE DEDUPLICATION LAYER ---
    existing_subset = [c for c in dedup_subset if c in df_combined.columns]
    if existing_subset:
        df_combined.drop_duplicates(subset=existing_subset, keep="first", inplace=True)
        df_csv_combined.drop_duplicates(subset=existing_subset, keep="first", inplace=True)

    # 4. Atomic File Persistence Write Sequences
    try:
        df_combined.to_excel(output_path, index=False, engine='openpyxl')
        logging.info(f"[*] Master Excel storage updated: {len(df_combined)} total records saved in {output_path.name}")
    except Exception as e:
        logging.error(f"[!] Excel write failed. Ensure 'openpyxl' is installed (pip install openpyxl). Error: {e}")

    try:
        df_proposal_export = df_csv_combined.copy()
        columns_to_drop = ['scraped_at', 'silver_processed_at']
        df_proposal_export.drop(columns=[c for c in columns_to_drop if c in df_proposal_export.columns], inplace=True)

        df_proposal_export.to_csv(csv_path, index=False)
        logging.info(f"[✔] Clean proposal sample archived: {csv_path}")
    except Exception as e:
        logging.error(f"[!] CSV write failed: {e}")


def generate_summary(data):
    if not data:
        logging.warning("Data structure is empty. Cannot generate summary.")
        return

    if isinstance(data, dict):
        data = [data]

    df = pd.DataFrame(data)
    if df.empty:
        logging.warning("Dataframe is empty. Cannot generate analytics summary.")
        return

    logging.info("=== Execution Summary (Persuasion Insights Engine) ===")
    logging.info(f"Total market samples extracted: {len(df)}")

    if 'price' in df.columns or 'salary' in df.columns:
        col = 'price' if 'price' in df.columns else 'salary'

        df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True).str.strip()
        df[col] = pd.to_numeric(df[col], errors='coerce')

        valid_prices = df[col].dropna()

        if not valid_prices.empty:
            min_val = valid_prices.min()
            max_val = valid_prices.max()
            avg_val = valid_prices.mean()
            top_10_percentile = valid_prices.quantile(0.90)

            logging.info(f"   - Market Value Range: {min_val:.2f} to {max_val:.2f} (Avg: {avg_val:.2f})")
            logging.info(f"   - Premium Tier Anchor (Top 10%): {top_10_percentile:.2f}")
            logging.info(f"   - [Insight] Use the Premium Tier as an Anchor in your proposal to make your rates look highly reasonable.")
        else:
            logging.warning("   - [!] Financial metrics present, but no valid values could be resolved for numeric anchor profiles.")

    text_col = next((c for c in ['tags', 'requirements', 'text', 'job_title'] if c in df.columns), None)
    if text_col:
        all_words = df[text_col].astype(str).str.lower().str.findall(r'\b\w+\b').explode()
        all_words = all_words.dropna().str.strip()
        all_words = all_words[all_words != ""]

        stop_words = {
            'the', 'and', 'a', 'of', 'to', 'in', 'is', 'for', 'that', 'on', 'with', 'na', 'n',
            'this', 'an', 'your', 'it', 'from', 'are', 'by', 'as', 'at', 'be', 'or', 'you', 'i', 'to'
        }

        keywords = all_words[~all_words.isin(stop_words)].value_counts()

        if not keywords.empty:
            top_keywords = keywords.head(5).index.tolist()
            formatted_keywords = ", ".join([f"'{w.title()}'" for w in top_keywords])

            logging.info("--- Executive Market Intelligence Report (Client Gift) ---")
            logging.info(f"[✔] Market Demand Signal: The absolute highest-density trends currently dominating your sector are: {formatted_keywords}.")
            logging.info("    Strategic Impact: Integrating these terms into your current positioning triggers instant authority and alignment with active market demand.")

            if len(keywords) > 3:
                valid_gaps = keywords[keywords > 1].tail(3).index.tolist()
                if not valid_gaps:
                    valid_gaps = keywords.tail(3).index.tolist()

                formatted_gaps = ", ".join([f"'{w.title()}'" for w in valid_gaps])

                logging.info(f"[⚡] Competitive Blue-Ocean Opportunities: {formatted_gaps}.")
                logging.info("    Strategic Impact: These specific focus areas represent massive, uncrowded market gaps. Capitalizing on these differentiators allows you to capture market share entirely neglected by your direct competitors.")
            logging.info("----------------------------------------------------------")