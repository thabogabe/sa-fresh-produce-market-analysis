"""
sa_produce_scraper.py
----------------------
Scrapes daily fresh produce prices (tomatoes, chillies, peppers, onions,
garlic, potatoes, spinach) from:
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

import io
import os
import re
import sys
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

TARGET_PRODUCE = [
    "tomato", "chilli", "chili", "pepper", "onion", "garlic", "potato", "spinach", "bean",
    "ginger", "lettuce", "cabbage", "cucumber", "broccoli", "pumpkin", "carrot", "beetroot",
    "butternut",
]

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
        # The public page (tshwane.gov.za/?page_id=10509) just embeds this
        # page in an iframe, which Selenium's page_source doesn't capture --
        # navigate straight to the source instead.
        "url": "https://tfpm.tshwane.gov.za/ViewDailyStats.aspx",
        "table_selector": "table",
        # KNOWN LIMITATION: unlike Joburg, this page has no single price
        # table -- it's a 3-level ASP.NET drill-down (search a product name
        # -> pick a product match -> pick a grade/container/mass SKU variant
        # -> that SKU's page has the actual sales/price stats, often empty
        # for a given day). Reaching parity with the Joburg scraper means
        # searching each TARGET_PRODUCE term, walking every matched
        # product's SKU list via
        #   driver.execute_script("__doPostBack('ctl00$ContentPlaceHolder1$GridView1','Select$<i>')")
        # then each SKU via
        #   driver.execute_script("__doPostBack('ctl00$ContentPlaceHolder1$GridView2','Select$<j>')")
        # (driver.back() reliably returns to the prior grid between clicks,
        # so this doesn't require restarting the search each time), then
        # parsing the resulting detail table for VALUE OF SALES / QUANTITY
        # SOLD / AVERAGE PRICE and aggregating per product. Not implemented:
        # this scraper currently only saves the page source for debugging.
    },
}

MASTER_CSV = "produce_prices_master.csv"
TODAY = date.today().isoformat()

# Columns that come back as "<today> MTD: <month-to-date>", e.g.
# "R4,527,993.00 MTD: R34,068,059.00" -- split into a same-named daily
# column plus a "<name> mtd" cumulative column.
MTD_COLUMN_KEYWORDS = ["value sold", "qty sold", "kg sold"]


def _split_today_mtd(cell) -> tuple[float | None, float | None]:
    """Splits a 'X MTD: Y'-style cell into (today, month_to_date) floats."""
    text = str(cell)
    today_part, _, mtd_part = text.partition("MTD")

    def clean(part: str) -> float | None:
        digits = re.sub(r"[^\d.\-]", "", part)
        return float(digits) if digits not in ("", "-", ".") else None

    return clean(today_part), clean(mtd_part)


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
    # tshwane.gov.za and its tfpm.tshwane.gov.za subdomain serve an invalid
    # certificate; without this Chrome shows a privacy-error interstitial
    # instead of the real page.
    options.add_argument("--ignore-certificate-errors")
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
        try:
            driver.get(cfg["url"])
        except Exception as e:
            # Network hiccups (e.g. no internet at the moment the scheduled
            # task fires) used to raise all the way out of this function,
            # crashing the whole run before the *other* market -- or the
            # dashboard rebuild -- ever got a chance to happen.
            print(f"  Could not reach {cfg['name']} ({e}).")
            return rows_df, html

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
            tables = pd.read_html(io.StringIO(html))
        except ValueError:
            tables = []

        if not tables:
            print(f"  No tables found on {cfg['name']} page (see {snapshot_path}).")
            return rows_df, html

        # Combine all tables, then filter to rows mentioning our target produce.
        # Layout/nested tables on some sites (e.g. Pretoria's ASP.NET pages)
        # can produce mismatched or multi-level columns that pandas can't
        # concat -- treat that the same as "no usable tables" rather than
        # letting it crash the whole scrape.
        try:
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
        except Exception as e:
            print(f"  Could not parse tables on {cfg['name']} page ({e}); see {snapshot_path}.")
            return rows_df, html

        # Split any "<today> MTD: <month-to-date>" columns into a clean
        # numeric daily column plus a "<name> mtd" cumulative column, so
        # downstream analysis doesn't have to re-parse strings.
        if not rows_df.empty:
            mtd_cols = [c for c in rows_df.columns if any(k in c for k in MTD_COLUMN_KEYWORDS)]
            for col in mtd_cols:
                split = rows_df[col].apply(_split_today_mtd)
                rows_df[col] = split.apply(lambda t: t[0])
                rows_df[f"{col} mtd"] = split.apply(lambda t: t[1])

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
        # Nonzero exit so Task Scheduler/run_scraper.bat actually shows a
        # failure instead of silently reporting success on a day nothing
        # was fetched (e.g. no internet at the scheduled run time).
        sys.exit(1)

    today_df = pd.concat(all_rows, ignore_index=True, sort=False)

    if os.path.exists(MASTER_CSV):
        master_df = pd.read_csv(MASTER_CSV)
        master_df = pd.concat([master_df, today_df], ignore_index=True, sort=False)
        # If the scraper runs more than once for the same day -- e.g. a
        # manual run before the market has finished publishing, followed
        # by the 14:10 scheduled run -- keep only the most recent scrape
        # per commodity/market/date. A plain drop_duplicates() only catches
        # byte-identical rows, so an earlier, possibly-incomplete run's
        # prices would otherwise sit alongside the later, real ones
        # instead of being overwritten by them.
        name_col = next(
            (c for c in master_df.columns if any(
                k in c for k in ["produce", "commodity", "product", "description", "item"])),
            None,
        )
        dedup_cols = [c for c in [name_col, "market", "date_scraped"] if c and c in master_df.columns]
        master_df = master_df.drop_duplicates(subset=dedup_cols or None, keep="last")
    else:
        master_df = today_df

    master_df.to_csv(MASTER_CSV, index=False)
    print(f"Master CSV updated: {len(master_df)} total records")

    commit_and_push([MASTER_CSV], f"Add {TODAY} price data")


if __name__ == "__main__":
    main()
