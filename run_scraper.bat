@echo off
cd /d "%~dp0"
echo ================ %date% %time% ================ >> scraper_log.txt
"venv\Scripts\python.exe" sa_produce_scraper.py >> scraper_log.txt 2>&1
set SCRAPER_EXIT=%errorlevel%
"venv\Scripts\python.exe" fresh_produce_analysis.py >> scraper_log.txt 2>&1
rem Exit with the scraper's own code (not the dashboard rebuild's) so a
rem failed scrape shows up as a real Task Scheduler failure, even though
rem the dashboard still gets rebuilt from whatever data already exists.
exit /b %SCRAPER_EXIT%
