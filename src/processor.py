import pandas as pd
import json
from pathlib import Path
from src.settings import config
from datetime import datetime
import logging

def process_to_silver(data):
    if not data:
        logging.warning("[!] No data provided to silver processor.")
        return

    Path(config.SILVER_PATH).mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(data)
    
    # 1. Schema Enforcement: Ensure critical types exist before processing
    if 'price' in df.columns:
        # Coerce to numeric, turning errors into NaN, then handle missing values
        df['price'] = pd.to_numeric(df['price'].replace(r'[£$]', '', regex=True), errors='coerce')
        df['price'] = df['price'].fillna(0.0)
    
    # 2. Metadata Enrichment: Always track when the silver record was minted
    df['silver_processed_at'] = datetime.now().isoformat()
    
    # 3. Path Management: Use Path objects for consistency
    output_path = Path(config.SILVER_PATH) / 'books_master.parquet'
    csv_path = Path("data") / "proposal_data_sample.csv"
    csv_path.parent.mkdir(exist_ok=True)
    
    # 4. Atomic Operations: Save and log
    df.to_parquet(output_path, index=False)
    df.to_csv(csv_path, index=False)
    
    logging.info(f"[*] Silver layer updated: {len(df)} records at {output_path}")

# Add this to src/processor.py
def generate_summary(data):
    # 1. Convert the raw list of dictionaries into a Pandas DataFrame
    df = pd.DataFrame(data)
    
    if df.empty:
        logging.warning("Data is empty. Cannot generate summary.")
        return

    # 2. Clean the price column if it exists (strip currency symbols and convert to float)
    if 'price' in df.columns:
        # This regex keeps only digits and the decimal point
        df['price'] = df['price'].astype(str).str.replace(r'[^\d.]', '', regex=True).astype(float)
        avg_price = df['price'].mean()
    else:
        avg_price = 0

    # 3. Print or log your summary
    logging.info("=== Execution Summary ===")
    logging.info(f"Total items extracted: {len(df)}")
    logging.info(f"Average price: {avg_price:.2f}")