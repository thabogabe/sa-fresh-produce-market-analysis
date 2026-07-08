"""
fresh_produce_analysis.py
--------------------------
Reads produce_prices_master.csv (built by sa_produce_scraper.py) and
generates a 4-panel dashboard PNG:

  1. Price trend over time per produce type
  2. Price comparison: Joburg Market vs Pretoria Market
  3. Price volatility (rolling standard deviation)
  4. Latest snapshot: average price by produce type (bar chart)

Run:
  python fresh_produce_analysis.py

Output:
  produce_dashboard.png
"""

import sys

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

MASTER_CSV = "produce_prices_master.csv"
OUTPUT_IMAGE = "produce_dashboard.png"

sns.set_style("whitegrid")


# --------------------------------------------------------------------------
# Load + clean
# --------------------------------------------------------------------------

def load_data(path: str = MASTER_CSV) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        print(f"'{path}' not found. Run sa_produce_scraper.py first to build it.")
        sys.exit(1)

    df.columns = [str(c).strip().lower() for c in df.columns]

    if "date_scraped" in df.columns:
        df["date_scraped"] = pd.to_datetime(df["date_scraped"], errors="coerce")

    # Identify the produce-name column (mirrors the scraper's logic).
    name_col = next(
        (c for c in df.columns if any(k in c for k in
            ["produce", "commodity", "product", "description", "item"])),
        df.columns[0],
    )
    df = df.rename(columns={name_col: "produce_name"})

    # Identify a numeric price column.
    price_col = next(
        (c for c in df.columns if "price" in c or "avg" in c or "average" in c),
        None,
    )
    if price_col is None:
        print("Could not find a price column in the master CSV. "
              "Check the scraper output columns and update this script.")
        sys.exit(1)

    # Coerce price to numeric, stripping currency symbols/commas if present.
    df["price"] = (
        df[price_col]
        .astype(str)
        .str.replace(r"[^\d\.\-]", "", regex=True)
        .replace("", None)
        .astype(float)
    )

    # Bucket produce into the three categories we track.
    def bucket(name: str) -> str:
        name = str(name).lower()
        if "tomato" in name:
            return "Tomatoes"
        if "chilli" in name or "chili" in name:
            return "Chillies"
        if "pepper" in name:
            return "Peppers"
        return "Other"

    df["produce_category"] = df["produce_name"].apply(bucket)
    df = df[df["produce_category"] != "Other"]

    if "market" not in df.columns:
        df["market"] = "Unknown"

    return df.dropna(subset=["price"])


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

def build_dashboard(df: pd.DataFrame, out_path: str = OUTPUT_IMAGE) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("SA Fresh Produce Price Dashboard — Tomatoes | Chillies | Peppers",
                 fontsize=15, fontweight="bold")

    has_dates = "date_scraped" in df.columns and df["date_scraped"].notna().any()

    # 1. Price trend over time per produce type
    ax = axes[0, 0]
    if has_dates:
        trend = df.groupby(["date_scraped", "produce_category"])["price"].mean().reset_index()
        for category, sub in trend.groupby("produce_category"):
            ax.plot(sub["date_scraped"], sub["price"], marker="o", label=category)
        ax.set_title("Price Trend Over Time")
        ax.set_xlabel("Date")
        ax.set_ylabel("Avg. Price")
        ax.legend()
        ax.tick_params(axis="x", rotation=45)
    else:
        ax.text(0.5, 0.5, "Not enough dated data yet", ha="center", va="center")
        ax.set_title("Price Trend Over Time")

    # 2. Market comparison
    ax = axes[0, 1]
    market_compare = df.groupby(["market", "produce_category"])["price"].mean().reset_index()
    sns.barplot(data=market_compare, x="produce_category", y="price", hue="market", ax=ax)
    ax.set_title("Joburg vs Pretoria — Avg. Price")
    ax.set_xlabel("")
    ax.set_ylabel("Avg. Price")

    # 3. Volatility (rolling std dev), if enough dated observations exist
    ax = axes[1, 0]
    if has_dates:
        pivot = df.pivot_table(index="date_scraped", columns="produce_category",
                                values="price", aggfunc="mean").sort_index()
        rolling_std = pivot.rolling(window=3, min_periods=1).std()
        for category in rolling_std.columns:
            ax.plot(rolling_std.index, rolling_std[category], marker="o", label=category)
        ax.set_title("Price Volatility (3-point Rolling Std Dev)")
        ax.set_xlabel("Date")
        ax.set_ylabel("Std. Dev.")
        ax.legend()
        ax.tick_params(axis="x", rotation=45)
    else:
        ax.text(0.5, 0.5, "Need multiple days of data\nto compute volatility",
                ha="center", va="center")
        ax.set_title("Price Volatility")

    # 4. Latest snapshot — average price by produce type
    ax = axes[1, 1]
    if has_dates:
        latest_date = df["date_scraped"].max()
        latest = df[df["date_scraped"] == latest_date]
        title_suffix = f" ({latest_date.date()})"
    else:
        latest = df
        title_suffix = ""
    snapshot = latest.groupby("produce_category")["price"].mean().reset_index()
    sns.barplot(data=snapshot, x="produce_category", y="price", ax=ax, palette="viridis")
    ax.set_title(f"Latest Snapshot — Avg. Price{title_suffix}")
    ax.set_xlabel("")
    ax.set_ylabel("Avg. Price")

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(out_path, dpi=150)
    print(f"Dashboard saved to {out_path}")


def main():
    df = load_data()
    if df.empty:
        print("No matching produce rows found in the master CSV.")
        sys.exit(1)
    build_dashboard(df)


if __name__ == "__main__":
    main()
