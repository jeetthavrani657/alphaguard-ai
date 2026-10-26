@echo off
rem Daily forward-test run (FORWARD_TEST.md). Started by the Windows task
rem "NSE-ForwardTest-Daily"; safe to double-click to run by hand.
rem
rem Research only: logs what the frozen rule WOULD have done. Places no orders.
rem
rem Runs from this folder, so the project can be moved without editing this
rem file -- but the Python path below is the one that has the project's
rem packages installed (pandas, yfinance, statsmodels, scipy); if Python is
rem ever reinstalled elsewhere, update it here.
rem
rem Output: the full console report overwrites reports\output\forward_last_run.log
rem (the validator prints a long per-stock report, so history is NOT kept in
rem this log). The history of the NUMBERS is reports\output\forward_snapshots.csv,
rem which gains one row per data date.

cd /d "%~dp0"
if not exist "reports\output" mkdir "reports\output"

rem Health check FIRST (research\health_check.py): it judges the footprints the PREVIOUS run left (fresh files,
rem no crashed step, the Windows task's last result), so a silent failure shows up on the web app's status
rem bar. It reads files only; it fetches nothing. Output overwrites reports\output\health_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\health_check.py > "reports\output\health_last_run.log" 2>&1
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\forward_log.py > "reports\output\forward_last_run.log" 2>&1
set FORWARD_RESULT=%ERRORLEVEL%

rem Forward paper books (FORWARD_BOOKS.md): the frozen momentum and Smallcap MA candidates, run on
rem data that did not exist when they were frozen. Research only; places no orders. Independent of
rem the steps around it. Output overwrites reports\output\forward_books_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\forward_books.py > "reports\output\forward_books_last_run.log" 2>&1

rem Display prices for the stocks nothing above updates (data\refresh_display.py): the Midcap 150 and Smallcap 250 stocks whose research cache is more than 5 days behind get about four
rem months of recent prices in data\display_cache\, a folder of its own that only the latest-closes step below reads. The research cache is NOT touched, so no result changes. About 3 minutes;
rem one stock failing never stops the rest, and it never changes FORWARD_RESULT. Output overwrites reports\output\display_refresh_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" data\refresh_display.py > "reports\output\display_refresh_last_run.log" 2>&1

rem Latest closes for the web app's stock pages (webapp\backend\latest_prices.py): reads the price cache the step above just updated and writes
rem webapp\snapshots\latest_prices.json, for DISPLAY only (no result reads it). A few seconds; it never changes FORWARD_RESULT. Output overwrites reports\output\latest_prices_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m webapp.backend.latest_prices > "reports\output\latest_prices_last_run.log" 2>&1

rem Forward paper tracking of the three multi-asset advisory profiles (ADVISORY.md; research\advisory_forward.py).
rem --refresh downloads fresh ETF and Bitcoin prices first. Research only; places no orders. Independent of the
rem steps around it. Output overwrites reports\output\advisory_forward_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\advisory_forward.py --refresh > "reports\output\advisory_forward_last_run.log" 2>&1

rem Also accumulate the point-in-time news archive (research\news_logger.py). It is independent
rem of the forward test: if one fails the other has still run. Its output overwrites
rem reports\output\news_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\news_logger.py > "reports\output\news_last_run.log" 2>&1

rem Weekly point-in-time archive of free yfinance fundamentals (research\fundamentals_snapshot.py). The
rem script gates itself to once every 7 days, so calling it daily costs nothing. Output overwrites
rem reports\output\fundamentals_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\fundamentals_snapshot.py > "reports\output\fundamentals_last_run.log" 2>&1

rem Go-live gates (research\golive_gates.py, GO_LIVE_GATES.md): reads the result files the steps above wrote and says which gates each paper rule meets; the web app's
rem Paper trading page shows it. It places no order and unlocks nothing, and never changes FORWARD_RESULT. Output overwrites reports\output\golive_gates_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\golive_gates.py > "reports\output\golive_gates_last_run.log" 2>&1

rem Track record (research\track_record.py): checks, from the git history, that the idea ledger and the forward files were never rewritten, for the web app's Track record page.
rem It reads files and git only, changes nothing and never changes FORWARD_RESULT. Output overwrites reports\output\track_record_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\track_record.py > "reports\output\track_record_last_run.log" 2>&1

rem The public track-record page (research\public_page.py): rewrites docs\index.html, one static page with the checks above, for GitHub Pages. It only writes that file; nothing is pushed by this step.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\public_page.py > "reports\output\public_page_last_run.log" 2>&1

rem Publish that page (research\publish_page.py), approved by the owner on 2026-10-26. It commits and pushes ONLY docs\index.html, and only when the branch is main and level with origin/main (so it never pushes
rem work that has not been approved), never forces, undoes its own commit if a push fails, refuses an unsafe page, and is switched off by a file named AUTO_PUBLISH_OFF in this folder. It cannot stop this run.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\publish_page.py > "reports\output\publish_page_last_run.log" 2>&1

rem Phone alerts (research\alerts.py). LAST on purpose: it only reads the files the steps above wrote and sends a short Telegram message to the owner's
rem own bot, and only if ALPHAGUARD_TELEGRAM_TOKEN and ALPHAGUARD_TELEGRAM_CHAT_ID are set as Windows environment variables. Without them it sends nothing and
rem writes what it would have sent to reports\output\alerts_log.txt. It never changes FORWARD_RESULT. Output overwrites reports\output\alerts_last_run.log.
"C:\Users\Jeet\AppData\Local\Python\pythoncore-3.14-64\python.exe" research\alerts.py > "reports\output\alerts_last_run.log" 2>&1

exit /b %FORWARD_RESULT%
