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

    # Joburg/Pretoria market tables report "total value sold", "total qty sold"
    # and "total kg sold" (with month-to-date figures appended) rather than a
    # plain price column. We divide by kg, not the "qty sold" unit count --
    # produce is sold in mixed, commodity-specific packaging (pockets,
    # crates, bags), so a raw "price per unit" tells a farmer nothing about
    # what quantity that price bought. Rand-per-kg is the one figure that's
    # comparable across commodities and packaging.
    value_col = next((c for c in df.columns if "value sold" in c), None)
    kg_col = next((c for c in df.columns if "kg sold" in c), None)
    qty_col = next((c for c in df.columns if "qty sold" in c or "quantity sold" in c), None)
    denom_col = kg_col or qty_col

    if value_col and denom_col:
        value_sold = df[value_col].apply(daily_figure)
        denom_sold = df[denom_col].apply(daily_figure)
        df["price"] = value_sold / denom_sold.replace(0, pd.NA)
        df["price_unit"] = "R/kg" if denom_col == kg_col else "R/unit sold"

        # The scraper also splits out "<name> mtd" cumulative columns --
        # derive a month-to-date average price the same way.
        mtd_value_col, mtd_denom_col = f"{value_col} mtd", f"{denom_col} mtd"
        if mtd_value_col in df.columns and mtd_denom_col in df.columns:
            mtd_value = df[mtd_value_col].apply(daily_figure)
            mtd_denom = df[mtd_denom_col].apply(daily_figure)
            df["mtd_price"] = mtd_value / mtd_denom.replace(0, pd.NA)
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
        df["price_unit"] = "R"

    # Track each specific product on its own line/bar (e.g. "Red Peppers"
    # and "Green Peppers" separately) rather than folding it into a broad
    # "Peppers" bucket -- averaging different products (or fresh vs.
    # processed goods, like dried tomatoes at ~R300/kg vs. fresh at ~R18/kg)
    # together produces a number that doesn't correspond to anything a
    # farmer actually sells.
    TRACKED_KEYWORDS = [
        "tomato", "chilli", "chili", "pepper", "onion", "garlic", "potato", "spinach", "bean",
        "ginger", "lettuce", "cabbage", "cucumber", "broccoli", "pumpkin", "carrot", "beetroot",
        "butternut",
    ]
    # Joburg Market reports some line items as an undifferentiated mix of
    # otherwise-unrelated produce (e.g. corn, beans and snap peas lumped
    # into one row) rather than as a single product. A price derived from
    # that isn't attributable to anything a farmer actually grows or
    # sells, and at the low volumes these catch-all rows move, the R/kg
    # figure swings wildly (one day it was R1,024/kg) -- exclude them.
    EXCLUDED_PRODUCTS = ["corn/beans/snap peas"]
    is_tracked = df["produce_name"].astype(str).str.lower().apply(
        lambda name: any(k in name for k in TRACKED_KEYWORDS)
        and not any(x in name for x in EXCLUDED_PRODUCTS)
    )
    df = df[is_tracked]
    df["produce_category"] = df["produce_name"].astype(str).str.strip().str.title()

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

def _label_bars(ax, fmt: str = "%.1f") -> None:
    for container in ax.containers:
        ax.bar_label(container, fmt=fmt, fontsize=7, padding=3)


def build_dashboard(df: pd.DataFrame, out_path: str = OUTPUT_IMAGE) -> None:
    # Prices are Rand-per-kg wherever the source data allows it (see
    # load_data) -- surface that unit everywhere so it's never ambiguous
    # what quantity/packaging a price refers to.
    price_unit = df["price_unit"].mode().iat[0] if "price_unit" in df.columns and not df["price_unit"].mode().empty else "R"

    has_dates = "date_scraped" in df.columns and df["date_scraped"].notna().any()

    # Tracking individual products (not broad buckets) means this list keeps
    # growing -- 40+ rows/lines now, more as new produce gets added. Bar
    # panels get one horizontal row per product (so labels never overlap,
    # unlike rotated vertical bar labels), sized to the actual count instead
    # of a fixed height, and a log price scale so a R2/kg item and a
    # R300/kg item are both still legible on the same chart.
    n_categories = max(df["produce_category"].nunique(), 1)
    bar_h = max(4.0, n_categories * 0.32)
    top_h = max(4.5, n_categories * 0.09)
    fig_h = top_h + 1.9 + bar_h * 3
    fig = plt.figure(figsize=(15, fig_h))
    gs = fig.add_gridspec(4, 2, height_ratios=[top_h, bar_h, bar_h, bar_h],
                           hspace=0.4, wspace=0.25, top=1 - 1.4 / fig_h, bottom=0.01)
    ax_trend = fig.add_subplot(gs[0, 0])
    ax_vol = fig.add_subplot(gs[0, 1])
    ax_market = fig.add_subplot(gs[1, :])
    ax_snapshot = fig.add_subplot(gs[2, :])
    ax_mtd = fig.add_subplot(gs[3, :])

    fig.suptitle(f"SA Fresh Produce Price Dashboard ({price_unit})",
                 fontsize=16, fontweight="bold")

    # matplotlib's default color cycle only has 10 colors before repeating;
    # tab20+tab20b covers up to 40 distinct products before that happens.
    category_colors = (sns.color_palette("tab20", 20) + sns.color_palette("tab20b", 20))[:n_categories]

    # 1. Price trend over time per produce type
    if has_dates:
        ax_trend.set_prop_cycle(color=category_colors)
        trend = df.groupby(["date_scraped", "produce_category"])["price"].mean().reset_index()
        for category, sub in trend.groupby("produce_category"):
            ax_trend.plot(sub["date_scraped"], sub["price"], marker="o", markersize=3,
                          linewidth=1, label=category)
        ax_trend.set_title("Price Trend Over Time")
        ax_trend.set_xlabel("Date")
        ax_trend.set_ylabel(f"Avg. Price ({price_unit}, log scale)")
        ax_trend.set_yscale("log")
        _format_date_axis(ax_trend, trend["date_scraped"])
        ax_trend.tick_params(axis="x", rotation=45)
    else:
        ax_trend.text(0.5, 0.5, "Not enough dated data yet", ha="center", va="center")
        ax_trend.set_title("Price Trend Over Time")

    # 2. Volatility (rolling std dev), if enough dated observations exist
    if has_dates:
        ax_vol.set_prop_cycle(color=category_colors)
        pivot = df.pivot_table(index="date_scraped", columns="produce_category",
                                values="price", aggfunc="mean").sort_index()
        rolling_std = pivot.rolling(window=3, min_periods=1).std()
        for category in rolling_std.columns:
            ax_vol.plot(rolling_std.index, rolling_std[category], marker="o", markersize=3,
                        linewidth=1, label=category)
        ax_vol.set_title("Price Volatility (3-point Rolling Std Dev)")
        ax_vol.set_xlabel("Date")
        ax_vol.set_ylabel(f"Std. Dev. ({price_unit})")
        _format_date_axis(ax_vol, pivot.index.to_series())
        ax_vol.tick_params(axis="x", rotation=45)

        # One shared legend for both line panels (same color mapping) in
        # the right margin -- a legend per panel had nowhere wide enough
        # to go between the two side-by-side plots and was getting clipped
        # to single characters.
        ncol = 1 if n_categories <= 15 else 2 if n_categories <= 30 else 3
        handles, labels = ax_trend.get_legend_handles_labels()
        fig.legend(handles, labels, loc="center left", bbox_to_anchor=(1.005, 0.5),
                   bbox_transform=ax_vol.transAxes, fontsize=6.5, ncol=ncol,
                   columnspacing=1, handlelength=1.3, borderaxespad=0)
    else:
        ax_vol.text(0.5, 0.5, "Need multiple days of data\nto compute volatility",
                    ha="center", va="center")
        ax_vol.set_title("Price Volatility")

    latest_date = df["date_scraped"].max() if has_dates else None
    latest = df[df["date_scraped"] == latest_date] if has_dates else df
    title_suffix = f" ({latest_date.strftime('%d %b %Y')})" if has_dates else ""

    # Sort every bar panel by today's price, high to low, so the same
    # product order is used throughout the dashboard -- once you find
    # "Carrots" in one panel, it's in the same place in the others.
    order = (latest.groupby("produce_category")["price"].mean()
             .sort_values(ascending=False).index.tolist())

    # 3. Market comparison (Joburg vs Pretoria)
    market_compare = df.groupby(["market", "produce_category"])["price"].mean().reset_index()
    sns.barplot(data=market_compare, y="produce_category", x="price", hue="market",
                order=order, ax=ax_market)
    ax_market.set_title("Joburg vs Pretoria — Avg. Price")
    ax_market.set_ylabel("")
    ax_market.set_xlabel(f"Avg. Price ({price_unit}, log scale)")
    ax_market.set_xscale("log")
    _label_bars(ax_market)

    # 4. Latest snapshot — average price by produce type
    snapshot = latest.groupby("produce_category")["price"].mean().reindex(order).reset_index()
    sns.barplot(data=snapshot, y="produce_category", x="price", hue="produce_category",
                order=order, palette="viridis", legend=False, ax=ax_snapshot)
    ax_snapshot.set_title(f"Latest Snapshot — Avg. Price{title_suffix}")
    ax_snapshot.set_ylabel("")
    ax_snapshot.set_xlabel(f"Avg. Price ({price_unit}, log scale)")
    ax_snapshot.set_xscale("log")
    _label_bars(ax_snapshot)

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
        sns.barplot(data=mtd_compare, y="produce_category", x="value", hue="metric",
                    order=order, ax=ax_mtd)
        ax_mtd.set_title(f"Today's Price vs Month-to-Date Average{title_suffix}")
        ax_mtd.set_ylabel("")
        ax_mtd.set_xlabel(f"Price ({price_unit}, log scale)")
        ax_mtd.set_xscale("log")
        ax_mtd.legend(title="", fontsize=8)
        _label_bars(ax_mtd)
    else:
        ax_mtd.text(0.5, 0.5, "No month-to-date figures in this data yet",
                     ha="center", va="center")
        ax_mtd.set_title("Today's Price vs Month-to-Date Average")

    # bbox_inches="tight" so the trend/volatility legends placed outside
    # the axes don't get clipped off the saved image.
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
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
