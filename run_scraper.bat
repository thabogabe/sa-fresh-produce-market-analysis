@echo off
cd /d "%~dp0"
"venv\Scripts\python.exe" sa_produce_scraper.py >> scraper_log.txt 2>&1
"venv\Scripts\python.exe" fresh_produce_analysis.py >> scraper_log.txt 2>&1
