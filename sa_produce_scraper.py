"""
sa_produce_scraper.py
----------------------
Scrapes daily fresh produce prices (tomatoes, chillies, peppers) from:
  - Joburg Market:   https://www.joburgmarket.co.za/jhb-market/dailyprices.php
  - Pretoria Market: https://www.tshwane.gov.za/?page_id=10509

Saves:
  - prices_joburg_YYYY-MM-DD.csv
  - prices_pretoria_YYYY-MM-DD.csv
  - produce_prices_master.csv   (running historical dataset, appended to)
  - page_source_joburg.html / page_source_pretoria.html (debug snapshots)

Run:
  python sa_produce_scraper.py

If tables come back empty, open the page_source_*.html snapshot, find
where the price table lives, and update the CSS selectors marked
"UPDATE ME" below.
"""

import os
import re
import time
from datetime import date

import pandas as pd
from selenium import webdriver
from git_autocommit import commit_and_push
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

TARGET_PRODUCE = ["tomato", "chilli", "chili", "pepper"]

MARKETS = {
    "joburg": {
        "name": "Joburg Market",
        "url": "https://www.joburgmarket.co.za/jhb-market/dailyprices.php",
        # UPDATE ME: CSS selector for the <table> holding the price data.
        # Inspect page_source_joburg.html (Ctrl+U / F12) and search "tomato".
        "table_selector": "table",
    },
    "pretoria": {
        "name": "Pretoria Market",
        "url": "https://www.tshwane.gov.za/?page_id=10509",
        # UPDATE ME: same idea for the Tshwane page. This site sometimes
        # links out to a PDF instead of an HTML table -- if so, this
        # scraper will save the page source and you'll need pdfplumber
        # to pull the PDF link and parse it separately.
        "table_selector": "table",
    },
}

MASTER_CSV = "produce_prices_master.csv"
TODAY = date.today().isoformat()


# --------------------------------------------------------------------------
# Browser setup
# --------------------------------------------------------------------------

def build_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------

def scrape_market(market_key: str, headless: bool = True) -> tuple[pd.DataFrame, str]:
    """
    Loads a market's price page, waits for content, saves the raw HTML for
    debugging, and returns (dataframe_of_target_produce_rows, raw_html).
    """
    cfg = MARKETS[market_key]
    driver = build_driver(headless=headless)
    rows_df = pd.DataFrame()
    html = ""

    try:
        print(f"Scraping {cfg['name']}...")
        driver.get(cfg["url"])

        # Give the page (and any JS-rendered tables) time to load.
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "table"))
            )
        except Exception:
            # Page may not use a <table> at all -- fall back to a fixed wait.
            time.sleep(5)

        html = driver.page_source

        # Save a snapshot for debugging regardless of parse success.
        snapshot_path = f"page_source_{market_key}.html"
        with open(snapshot_path, "w", encoding="utf-8") as f:
            f.write(html)

        # Try pandas' HTML table parser first -- it's forgiving of most
        # standard <table> markup and saves us writing manual XPath/CSS.
        try:
            tables = pd.read_html(html)
        except ValueError:
            tables = []

        if not tables:
            print(f"  No tables found on {cfg['name']} page (see {snapshot_path}).")
            return rows_df, html

        # Combine all tables, then filter to rows mentioning our target produce.
        combined = pd.concat(tables, ignore_index=True, sort=False)
        combined.columns = [str(c).strip().lower() for c in combined.columns]

        # Find a column that looks like it holds the produce/commodity name.
        name_col = None
        for col in combined.columns:
            if any(key in col for key in ["produce", "commodity", "product", "description", "item"]):
                name_col = col
                break
        if name_col is None:
            name_col = combined.columns[0]

        pattern = "|".join(TARGET_PRODUCE)
        mask = combined[name_col].astype(str).str.contains(pattern, case=False, na=False, regex=True)
        rows_df = combined[mask].copy()

        rows_df["market"] = cfg["name"]
        rows_df["date_scraped"] = TODAY

        print(f"  Found {len(rows_df)} matching rows at {cfg['name']}.")

    finally:
        driver.quit()

    return rows_df, html


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    all_rows = []

    for market_key in MARKETS:
        rows, _html = scrape_market(market_key, headless=True)
        if not rows.empty:
            out_path = f"prices_{market_key}_{TODAY}.csv"
            rows.to_csv(out_path, index=False)
            print(f"  Saved {out_path}")
            all_rows.append(rows)

    if not all_rows:
        print("No data scraped today -- check the page_source_*.html snapshots.")
        return

    today_df = pd.concat(all_rows, ignore_index=True, sort=False)

    if os.path.exists(MASTER_CSV):
        master_df = pd.read_csv(MASTER_CSV)
        master_df = pd.concat([master_df, today_df], ignore_index=True, sort=False)
        # Drop exact duplicate rows in case the scraper is re-run same day.
        master_df = master_df.drop_duplicates()
    else:
        master_df = today_df

    master_df.to_csv(MASTER_CSV, index=False)
    print(f"Master CSV updated: {len(master_df)} total records")

    commit_and_push([MASTER_CSV], f"Add {TODAY} price data")


if __name__ == "__main__":
    main()
