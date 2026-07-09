"""
fresh_produce_analysis.py
--------------------------
Reads produce_prices_master.csv (built by sa_produce_scraper.py) and
generates a 5-panel dashboard PNG:

  1. Price trend over time per produce type
  2. Price comparison: Joburg Market vs Pretoria Market
  3. Price volatility (rolling standard deviation)
  4. Latest snapshot: average price by produce type (bar chart)
  5. Today's price vs this month's average price (smooths out day-to-day
     noise using the market's own month-to-date sales figures)

Run:
  python fresh_produce_analysis.py

Output:
  produce_dashboard.png
"""

import re
import sys

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from git_autocommit import commit_and_push

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

    def daily_figure(cell: str):
        """Extract today's number from cells like 'R4,527,993.00 MTD: R34,068,059.00'."""
        today_part = str(cell).split("MTD")[0]
        digits = re.sub(r"[^\d.\-]", "", today_part)
        return float(digits) if digits not in ("", "-", ".") else None

    # Joburg/Pretoria market tables report "total value sold" and "total qty sold"
    # (with month-to-date figures appended) rather than a plain price column --
    # derive an average price per unit sold from those.
    value_col = next((c for c in df.columns if "value sold" in c), None)
    qty_col = next((c for c in df.columns if "qty sold" in c or "quantity sold" in c), None)

    if value_col and qty_col:
        value_sold = df[value_col].apply(daily_figure)
        qty_sold = df[qty_col].apply(daily_figure)
        df["price"] = value_sold / qty_sold.replace(0, pd.NA)

        # The scraper also splits out "<name> mtd" cumulative columns --
        # derive a month-to-date average price the same way.
        mtd_value_col, mtd_qty_col = f"{value_col} mtd", f"{qty_col} mtd"
        if mtd_value_col in df.columns and mtd_qty_col in df.columns:
            mtd_value = df[mtd_value_col].apply(daily_figure)
            mtd_qty = df[mtd_qty_col].apply(daily_figure)
            df["mtd_price"] = mtd_value / mtd_qty.replace(0, pd.NA)
        else:
            df["mtd_price"] = pd.NA
    else:
        # Fallback: look for an explicit price/average column.
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
        df["mtd_price"] = pd.NA

    # Bucket produce into the categories we track (mirrors the scraper's
    # TARGET_PRODUCE list).
    def bucket(name: str) -> str:
        name = str(name).lower()
        if "tomato" in name:
            return "Tomatoes"
        if "chilli" in name or "chili" in name:
            return "Chillies"
        if "pepper" in name:
            return "Peppers"
        if "onion" in name:
            return "Onions"
        if "garlic" in name:
            return "Garlic"
        if "potato" in name:
            return "Potatoes"
        if "spinach" in name:
            return "Spinach"
        return "Other"

    df["produce_category"] = df["produce_name"].apply(bucket)
    df = df[df["produce_category"] != "Other"]

    if "market" not in df.columns:
        df["market"] = "Unknown"

    return df.dropna(subset=["price"])


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

def _format_date_axis(ax, dates: pd.Series) -> None:
    """
    Unambiguous "08 Jul 2026" tick labels (day before month, spelled out,
    so it can't be misread as month-first), with the axis bounded tightly
    to the real data range instead of matplotlib's autoscale -- which, with
    only one or two points, was padding out to a multi-year range full of
    dates with no data.
    """
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %Y"))
    unique_dates = pd.Series(dates.dropna().unique()).sort_values()
    min_date, max_date = unique_dates.iloc[0], unique_dates.iloc[-1]
    pad = pd.Timedelta(days=1) if min_date == max_date else (max_date - min_date) * 0.05
    ax.set_xlim(min_date - pad, max_date + pad)
    if len(unique_dates) <= 15:
        # One tick per actual scrape date -- avoids duplicate same-day
        # labels that AutoDateLocator adds when the span is only a day
        # or two.
        ax.set_xticks(unique_dates)
    else:
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))

def build_dashboard(df: pd.DataFrame, out_path: str = OUTPUT_IMAGE) -> None:
    fig = plt.figure(figsize=(14, 15))
    gs = fig.add_gridspec(3, 2)
    axes = np.array([[fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])],
                      [fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1])]])
    ax_mtd = fig.add_subplot(gs[2, :])
    fig.suptitle("SA Fresh Produce Price Dashboard",
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
        _format_date_axis(ax, trend["date_scraped"])
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
        _format_date_axis(ax, pivot.index.to_series())
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

    # 5. Today's price vs this month's average -- smooths out day-to-day
    # noise using the market's own month-to-date sales figures.
    has_mtd = "mtd_price" in latest.columns and latest["mtd_price"].notna().any()
    if has_mtd:
        mtd_compare = latest.groupby("produce_category")[["price", "mtd_price"]].mean().reset_index()
        mtd_compare = mtd_compare.melt(id_vars="produce_category",
                                        value_vars=["price", "mtd_price"],
                                        var_name="metric", value_name="value")
        mtd_compare["metric"] = mtd_compare["metric"].map(
            {"price": "Today", "mtd_price": "Month-to-Date Avg."})
        sns.barplot(data=mtd_compare, x="produce_category", y="value", hue="metric", ax=ax_mtd)
        ax_mtd.set_title(f"Today's Price vs Month-to-Date Average{title_suffix}")
        ax_mtd.set_xlabel("")
        ax_mtd.set_ylabel("Price")
        ax_mtd.legend(title="")
    else:
        ax_mtd.text(0.5, 0.5, "No month-to-date figures in this data yet",
                     ha="center", va="center")
        ax_mtd.set_title("Today's Price vs Month-to-Date Average")

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(out_path, dpi=150)
    print(f"Dashboard saved to {out_path}")

    commit_and_push([out_path], "Update price dashboard")


def main():
    df = load_data()
    if df.empty:
        print("No matching produce rows found in the master CSV.")
        sys.exit(1)
    build_dashboard(df)


if __name__ == "__main__":
    main()
