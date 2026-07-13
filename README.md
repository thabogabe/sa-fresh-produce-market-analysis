# SA Fresh Produce Market Analysis

Scrapes daily fresh produce prices (tomatoes, chillies, peppers, onions, garlic, potatoes,
spinach) from South Africa's two largest fresh produce markets — the
[Joburg Market](https://www.joburgmarket.co.za/jhb-market/dailyprices.php) and the
[Pretoria Market](https://www.tshwane.gov.za/?page_id=10509) — and runs time-series price
analysis on the collected data.

The pipeline runs daily, appending each day's data to a master CSV, then feeding it into a
5-panel dashboard showing price trends, market comparisons, volatility, and today's price
against the month-to-date average.

## Project files

| File | Purpose |
|---|---|
| `sa_produce_scraper.py` | Selenium scraper — fetches both markets |
| `rainfall_data.py` | Fetches daily rainfall for the market cities (Open-Meteo) |
| `fresh_produce_analysis.py` | Analysis & dashboard — reads the master CSV |
| `produce_prices_master.csv` | Running historical dataset (auto-built by the scraper) |
| `rainfall_master.csv` | Running daily rainfall dataset (auto-built by `rainfall_data.py`) |

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
2. Price volatility (rolling standard deviation)
3. Daily rainfall per major growing region (Gauteng, Limpopo, Mpumalanga, KwaZulu-Natal,
   Western Cape, Free State)
4. Joburg Market vs Pretoria Market price comparison
5. Latest snapshot — average price by produce type
6. Today's price vs this month's average price (month-to-date)

Run `python rainfall_data.py` to fetch/update rainfall data before generating the dashboard —
it backfills from the earliest date in the price data, so rainfall history lines up with
however much price history you already have. Uses
[Open-Meteo's free Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
(no key needed) rather than the SA Weather Service, which has no free public API for
historical rainfall — its climate database is accessible only via a paid/manual request form.

**Caveats:**
- Rainfall is tracked per *region* (several major growing areas), not per market city only —
  farmers supplying Joburg/Pretoria Market come from across the country, not just Gauteng.
  Regions are kept as separate series rather than averaged together, since the Western Cape's
  winter-rainfall climate runs opposite the rest of the country's summer-rainfall pattern.
- Still not commodity-specific: the price data doesn't say which region a given batch of
  produce actually came from, so this is regional context, not a precise "this crop's
  rainfall" figure. Pretoria's sales drill-down did track a `PROVINCE` per sale, which would
  have been the real fix — but that data source turned out to be a dead end (see below).

Both scripts auto-commit and push their output (`produce_prices_master.csv`,
`produce_dashboard.png`) to this repo after each run, via `git_autocommit.py`. This is
best-effort — if git isn't configured or there's no network, it just prints a warning and
the script still exits normally.

### Debugging empty results

Market sites occasionally change their HTML structure. Each scraper run saves
`page_source_<market>.html` — open it in a browser to find where the price table moved, then
update the CSS selectors in `sa_produce_scraper.py` marked `UPDATE ME`.

**Known limitation — Pretoria Market (investigated and abandoned):** Tshwane's data lives
behind a 3-level ASP.NET search/drill-down (product name → product match → grade/container/
mass SKU variant → per-SKU sales stats). The drill-down mechanics were fully solved — see the
comment above `MARKETS["pretoria"]` in `sa_produce_scraper.py` for exactly how — but after
scanning 177 SKU/grade combinations across tomatoes, onions and potatoes (staples that should
sell daily) with a correct "does this page have data" detector, every single one was empty.
The site's own Historic Data report throws a JS alert ("No Results Found... not available")
for a date over a year in the past, too. This isn't a scraping bug — the system has no real
transaction data behind it for any date tried, live or historical. Not pursuing this data
source further.

## Automating daily runs

Joburg Market updates prices between 12:00 and 13:00 on weekdays, and doesn't trade on
Sundays at all. This project runs Monday–Saturday at 14:10 to leave room for update delays —
re-scraping on a day with no new prices is harmless since `produce_prices_master.csv` drops
exact duplicate rows. `sa_produce_scraper.py` also refuses to run on a Sunday even if
triggered manually (or by a `StartWhenAvailable` catch-up run), so Friday/Saturday's leftover
page content never gets stamped with a bogus Sunday date.

**Windows (Task Scheduler):** a task named `Fresh Produce Scraper` is registered to run
`run_scraper.bat` at 14:10, Monday through Saturday, which `cd`s into the project folder and
runs the scraper, the rainfall fetch, and the dashboard rebuild in sequence, appending output
to `scraper_log.txt` (gitignored). To recreate it on another machine:

```powershell
$action = New-ScheduledTaskAction -Execute "C:\path\to\project\run_scraper.bat" -WorkingDirectory "C:\path\to\project"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday,Saturday -At 14:10
Register-ScheduledTask -TaskName "Fresh Produce Scraper" -Action $action -Trigger $trigger
```

**Mac/Linux (cron):**
```
10 14 * * 1-6 /path/to/venv/bin/python /path/to/sa_produce_scraper.py >> scraper_log.txt 2>&1
```

## Roadmap

- [ ] Build 3+ months of daily data for meaningful seasonal analysis
- [x] Overlay rainfall/drought data against price spikes (Open-Meteo, not SA Weather Service — see Usage)
- [ ] Correlate EskomSePush load-shedding stage history against price jumps
- [ ] Export to Power BI for an interactive dashboard
- [x] Expand `TARGET_PRODUCE` to onions, garlic, potatoes, spinach

## Stack

Python 3 · Selenium · pandas · matplotlib · seaborn
