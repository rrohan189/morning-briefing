@echo off
cd /d C:\Users\rohan\Desktop\ClaudeCode\morning_briefing
if not exist logs mkdir logs

echo [%date% %time%] Starting Morning Intelligence pipeline >> logs\run.log

REM Phase 1 (collect + validate) → Phase 2 (LLM) → Phase 3 (render HTML)
python run_pipeline.py >> logs\run.log 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] ERROR: Pipeline failed with exit code %errorlevel% >> logs\run.log
    exit /b %errorlevel%
)

REM Get today's date in YYYY-MM-DD format
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set dt=%%I
set BRIEFING_DATE=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%

REM Send briefing via email (auto-inlines CSS for Gmail)
python send-briefing.py "output\briefing-%BRIEFING_DATE%.html" >> logs\run.log 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] ERROR: Email send failed with exit code %errorlevel% >> logs\run.log
    exit /b %errorlevel%
)

echo [%date% %time%] Pipeline complete - briefing sent >> logs\run.log
