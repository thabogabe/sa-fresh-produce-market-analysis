# SA Fresh Produce Market Analysis

Scrapes daily fresh produce prices (tomatoes, chillies, peppers) from South Africa's two largest
fresh produce markets — the [Joburg Market](https://www.joburgmarket.co.za/jhb-market/dailyprices.php)
and the [Pretoria Market](https://www.tshwane.gov.za/?page_id=10509) — and runs time-series price
analysis on the collected data.

The pipeline runs daily, appending each day's data to a master CSV, then feeding it into a
4-panel dashboard showing price trends, market comparisons and volatility.

## Project files

| File | Purpose |
|---|---|
| `sa_produce_scraper.py` | Selenium scraper — fetches both markets |
| `fresh_produce_analysis.py` | Analysis & dashboard — reads the master CSV |
| `produce_prices_master.csv` | Running historical dataset (auto-built by the scraper) |

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
```

Google Chrome must be installed — Selenium drives it to load the JavaScript-heavy market pages.
ChromeDriver is installed automatically by `webdriver-manager` on first run.

## Usage

Run the scraper to pull today's prices and update the master CSV:

```bash
python sa_produce_scraper.py
```

Generate the dashboard from all data collected so far:

```bash
python fresh_produce_analysis.py
```

This produces `produce_dashboard.png` with:
1. Price trend over time per produce type
2. Joburg Market vs Pretoria Market price comparison
3. Price volatility (rolling standard deviation)
4. Latest snapshot — average price by produce type

### Debugging empty results

Market sites occasionally change their HTML structure. Each scraper run saves
`page_source_<market>.html` — open it in a browser to find where the price table moved, then
update the CSS selectors in `sa_produce_scraper.py` marked `UPDATE ME`.

## Automating daily runs

Joburg Market updates prices between 12:00 and 13:00 on weekdays.

**Windows (Task Scheduler):** create a daily trigger at 13:00 that runs
`venv\Scripts\python.exe sa_produce_scraper.py` with the project folder as the start-in directory.

**Mac/Linux (cron):**
```
0 13 * * 1-5 /path/to/venv/bin/python /path/to/sa_produce_scraper.py
```

## Roadmap

- [ ] Build 3+ months of daily data for meaningful seasonal analysis
- [ ] Overlay SA Weather Service rainfall/drought data against price spikes
- [ ] Correlate EskomSePush load-shedding stage history against price jumps
- [ ] Export to Power BI for an interactive dashboard
- [ ] Expand `TARGET_PRODUCE` to onions, garlic, potatoes, spinach

## Stack

Python 3 · Selenium · pandas · matplotlib · seaborn
