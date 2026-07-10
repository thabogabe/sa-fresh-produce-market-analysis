"""
rainfall_data.py
------------------
Fetches daily rainfall (mm) for the market cities from Open-Meteo's free
Historical Weather API (open-meteo.com/en/docs/historical-weather-api).

The SA Weather Service has no free public API for historical rainfall --
their climate database is accessible only via a paid/manual data request
form -- so this is the practical substitute. No API key or signup needed.

Backfills from the earliest date_scraped in produce_prices_master.csv (or
wherever rainfall_master.csv last left off) up to today, so rainfall
history lines up with the price history already collected -- unlike
prices, decades of rainfall history are available immediately, so there's
no need to wait and accumulate it day by day.

CAVEAT: produce sold at a market isn't necessarily grown in that market's
city. These coordinates are Johannesburg/Pretoria themselves, used as a
Gauteng Highveld regional weather proxy -- not the actual rainfall at
whichever farm a given batch of produce came from.

Run:
  python rainfall_data.py

Saves:
  rainfall_master.csv
"""

import os
from datetime import date

import pandas as pd
import requests

from git_autocommit import commit_and_push

RAINFALL_MASTER_CSV = "rainfall_master.csv"
PRODUCE_MASTER_CSV = "produce_prices_master.csv"
TODAY = date.today().isoformat()

MARKET_COORDS = {
    "Joburg Market": (-26.20, 28.05),
    "Pretoria Market": (-25.75, 28.19),
}
TIMEZONE = "Africa/Johannesburg"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_rainfall(lat: float, lon: float, start_date: str, end_date: str) -> pd.DataFrame:
    resp = requests.get(ARCHIVE_URL, params={
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "precipitation_sum",
        "timezone": TIMEZONE,
    }, timeout=30)
    resp.raise_for_status()
    daily = resp.json()["daily"]
    return pd.DataFrame({
        "date": pd.to_datetime(daily["time"]),
        "rainfall_mm": daily["precipitation_sum"],
    })


def _earliest_needed_date() -> str:
    """Backfill from the earliest date we have price data for, so rainfall
    history lines up with what's already in produce_prices_master.csv."""
    if os.path.exists(PRODUCE_MASTER_CSV):
        prices = pd.read_csv(PRODUCE_MASTER_CSV)
        if "date_scraped" in prices.columns and not prices.empty:
            return pd.to_datetime(prices["date_scraped"]).min().date().isoformat()
    return TODAY


def main():
    if os.path.exists(RAINFALL_MASTER_CSV):
        existing = pd.read_csv(RAINFALL_MASTER_CSV, parse_dates=["date"])
    else:
        existing = pd.DataFrame(columns=["date", "market", "rainfall_mm"])

    all_rows = [existing] if not existing.empty else []
    updated = False

    for market_name, (lat, lon) in MARKET_COORDS.items():
        have = existing.loc[existing["market"] == market_name, "date"] if not existing.empty else pd.Series(dtype="datetime64[ns]")
        start = _earliest_needed_date() if have.empty else (have.max() + pd.Timedelta(days=1)).date().isoformat()

        if start > TODAY:
            print(f"  {market_name}: rainfall already up to date.")
            continue

        print(f"Fetching rainfall for {market_name} ({start} to {TODAY})...")
        try:
            df = fetch_rainfall(lat, lon, start, TODAY)
        except Exception as e:
            print(f"  Could not fetch rainfall for {market_name} ({e}).")
            continue

        df["market"] = market_name
        all_rows.append(df[["date", "market", "rainfall_mm"]])
        updated = True
        print(f"  Got {len(df)} day(s).")

    if not all_rows:
        print("No rainfall data fetched.")
        return

    combined = pd.concat(all_rows, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "market"], keep="last").sort_values(["market", "date"])
    combined.to_csv(RAINFALL_MASTER_CSV, index=False)
    print(f"Rainfall master CSV updated: {len(combined)} total records")

    if updated:
        commit_and_push([RAINFALL_MASTER_CSV], f"Add rainfall data through {TODAY}")


if __name__ == "__main__":
    main()
