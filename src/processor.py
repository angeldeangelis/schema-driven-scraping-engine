import pandas as pd
import json
from pathlib import Path
from src.settings import config
from datetime import datetime
import logging

import pandas as pd
import logging
from datetime import datetime
from pathlib import Path
from src.settings import config

def process_to_silver(data):
    if not data:
        logging.warning("[!] No data provided to silver processor.")
        return

    Path(config.SILVER_PATH).mkdir(parents=True, exist_ok=True)
    df_new = pd.DataFrame(data)
    
    # 1. Schema Enforcement & Dynamic File Routing
    if 'price' in df_new.columns:
        # Coerce to numeric, turning errors into NaN, then handle missing values
        df_new['price'] = pd.to_numeric(df_new['price'].replace(r'[£$]', '', regex=True), errors='coerce')
        df_new['price'] = df_new['price'].fillna(0.0)
        
        # Route to books storage
        file_prefix = "books"
        dedup_subset = ["source_url", "title"]
    elif 'author' in df_new.columns or 'text' in df_new.columns:
        # Route to quotes storage
        file_prefix = "quotes"
        dedup_subset = ["source_url", "text"]
    else:
        # Fallback for general jobs/proposals
        file_prefix = "proposal_data"
        dedup_subset = ["source_url"]
    
    # 2. Metadata Enrichment: Always track when the silver record was minted
    df_new['silver_processed_at'] = datetime.now().isoformat()
    
    # 3. Dynamic Path Management: Keep target types completely separated
    output_path = Path(config.SILVER_PATH) / f"{file_prefix}_master.parquet"
    csv_path = Path("data") / f"{file_prefix}_sample.csv"
    csv_path.parent.mkdir(exist_ok=True)
    
    # --- INCREMENTAL MERGE LAYER (Per Isolated File) ---
    # Load and combine historical data ONLY for this specific data type
    if output_path.exists():
        try:
            df_historic = pd.read_parquet(output_path)
            df_combined = pd.concat([df_historic, df_new], ignore_index=True)
            logging.info(f"[*] Merging {len(df_new)} new records into existing {file_prefix} history.")
        except Exception as e:
            logging.error(f"[!] Failed to read historical Parquet file for {file_prefix}. Overwriting. Error: {e}")
            df_combined = df_new
    else:
        df_combined = df_new

    # De-duplicate using the dynamically chosen subset to avoid mixing rules
    df_combined.drop_duplicates(subset=dedup_subset, keep="first", inplace=True)
    # -----------------------------------------------------

    # 4. Atomic Operations: Save back to the isolated files
    df_combined.to_parquet(output_path, index=False)
    df_combined.to_csv(csv_path, index=False)
    
    logging.info(f"[*] Silver layer updated: {len(df_combined)} total cumulative records saved in {output_path.name}")

# Add this to src/processor.py
def generate_summary(data):
    df = pd.DataFrame(data)
    
    if df.empty:
        logging.warning("Data is empty. Cannot generate summary.")
        return

    logging.info("=== Execution Summary (Persuasion Insights Engine) ===")
    logging.info(f"Total market samples extracted: {len(df)}")

    # STRATEGY 1: Numeric/Financial Context (e.g., Prices, Salaries)
    if 'price' in df.columns or 'salary' in df.columns:
        col = 'price' if 'price' in df.columns else 'salary'
        df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True).astype(float)
        
        # Persuasion Metrics: Contrast & Anchoring
        min_val = df[col].min()
        max_val = df[col].max()
        avg_val = df[col].mean()
        top_10_percentile = df[col].quantile(0.90)
        
        logging.info(f"   - Market Value Range: {min_val:.2f} to {max_val:.2f} (Avg: {avg_val:.2f})")
        logging.info(f"   - Premium Tier Anchor (Top 10%): {top_10_percentile:.2f}")
        logging.info(f"   - [Insight] Use the Premium Tier as an Anchor in your proposal to make your rates look highly reasonable.")

    # STRATEGY 2: Text/Textual Context (e.g., Tags, Job Requirements, Keywords)
    text_col = next((c for c in ['tags', 'requirements', 'text', 'job_title'] if c in df.columns), None)
    if text_col:
        # 1. Clean and tokenize text data
        all_words = df[text_col].astype(str).str.lower().str.findall(r'\b\w+\b').explode()
        
        # Expanded stop words list to make the client report look highly professional
        stop_words = {
            'the', 'and', 'a', 'of', 'to', 'in', 'is', 'for', 'that', 'on', 'with', 'na', 'n', 
            'this', 'an', 'your', 'it', 'from', 'are', 'by', 'as', 'at', 'be', 'or', 'you'
        }
        keywords = all_words[~all_words.isin(stop_words)].value_counts()
        
        top_keywords = keywords.head(5).index.tolist()
        
        # 2. Format names nicely for the client presentation
        formatted_keywords = ", ".join([f"'{w.title()}'" for w in top_keywords])
        
        # 3. Client-Facing Persuasion Output
        logging.info("--- Executive Market Intelligence Report (Client Gift) ---")
        logging.info(f"[✔] Market Demand Signal: The absolute highest-density trends currently dominating your sector are: {formatted_keywords}.")
        logging.info("    Strategic Impact: Integrating these terms into your current positioning triggers instant authority and alignment with active market demand.")
        
        if len(keywords) > 3:
            # Isolate genuine low-frequency gaps, avoiding the absolute rarest 1-count typos
            valid_gaps = keywords[keywords > 1].tail(3).index.tolist()
            if not valid_gaps:
                valid_gaps = keywords.tail(3).index.tolist()
                
            formatted_gaps = ", ".join([f"'{w.title()}'" for w in valid_gaps])
            
            logging.info(f"[⚡] Competitive Blue-Ocean Opportunities: {formatted_gaps}.")
            logging.info("    Strategic Impact: These specific focus areas represent massive, uncrowded market gaps. Capitalizing on these differentiators allows you to capture market share entirely neglected by your direct competitors.")
        logging.info("----------------------------------------------------------")
        