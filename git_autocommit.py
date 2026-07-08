"""
git_autocommit.py
------------------
Best-effort helper used by the scraper and analysis scripts to commit and
push generated data files (master CSV, dashboard PNG) after each run, so the
GitHub repo stays in sync as data accumulates day to day.

Never raises -- a failed commit/push (no network, no git repo, nothing
changed) just prints a warning and lets the calling script continue.
"""

import subprocess


def commit_and_push(paths: list[str], message: str) -> None:
    try:
        subprocess.run(["git", "add", *paths], check=True)

        # Nothing staged -> nothing to commit.
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            return

        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"Committed and pushed: {message}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Git commit/push skipped ({e}).")
