"""
github_traffic_log.py
-----------------------
Logs this repo's GitHub traffic stats (page views, clones) to a local CSV.
GitHub itself only retains 14 days of traffic history (Insights -> Traffic
in the web UI, or the /traffic/views and /traffic/clones API endpoints) --
running this daily builds a permanent record beyond that window.

Uses the `gh` CLI (already authenticated as the repo owner) rather than
handling GitHub API auth directly -- traffic stats require push access to
the repo, which only the owner/collaborators have; they're not public.

Run:
  python github_traffic_log.py

Saves:
  github_traffic_log.csv
"""

import json
import os
import subprocess
from datetime import date

import pandas as pd

from git_autocommit import commit_and_push

REPO = "thabogabe/sa-fresh-produce-market-analysis"
LOG_CSV = "github_traffic_log.csv"
TODAY = date.today().isoformat()


def _gh_api(endpoint: str) -> dict:
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/{endpoint}"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def main():
    try:
        views = _gh_api("traffic/views")
        clones = _gh_api("traffic/clones")
    except FileNotFoundError:
        print("gh CLI not found -- can't fetch traffic stats.")
        return
    except subprocess.CalledProcessError as e:
        print(f"Could not fetch GitHub traffic stats ({e.stderr.strip()}).")
        return

    views_by_date = {v["timestamp"][:10]: v for v in views.get("views", [])}
    clones_by_date = {c["timestamp"][:10]: c for c in clones.get("clones", [])}
    all_dates = sorted(set(views_by_date) | set(clones_by_date))

    rows = []
    for d in all_dates:
        v = views_by_date.get(d, {})
        c = clones_by_date.get(d, {})
        rows.append({
            "date": d,
            "views": v.get("count", 0),
            "unique_views": v.get("uniques", 0),
            "clones": c.get("count", 0),
            "unique_clones": c.get("uniques", 0),
        })
    fetched = pd.DataFrame(rows)

    if os.path.exists(LOG_CSV):
        existing = pd.read_csv(LOG_CSV, dtype={"date": str})
        combined = pd.concat([existing, fetched], ignore_index=True)
    else:
        combined = fetched

    # A day's count keeps climbing until the day is over, so a later fetch
    # for a date we've already logged is more accurate, not a duplicate --
    # keep the newest reading per date rather than the first.
    combined = combined.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    combined.to_csv(LOG_CSV, index=False)
    print(f"Traffic log updated: {len(combined)} day(s) on record.")

    commit_and_push([LOG_CSV], f"Log GitHub traffic through {TODAY}")


if __name__ == "__main__":
    main()
