@echo off
cd /d C:\Users\rohan\Desktop\ClaudeCode\morning_briefing

echo [%date% %time%] Starting Morning Intelligence briefing >> logs\run.log

claude --dangerously-skip-permissions -p "Generate today's Morning Intelligence briefing following the spec in morning-briefing-spec.md. Run Phase 1 with self-review checkpoint (no human present). Then generate Phase 2, save the HTML to output/briefing-%date:~-4%-%date:~4,2%-%date:~7,2%.html, and run 'python send-briefing.py output/briefing-%date:~-4%-%date:~4,2%-%date:~7,2%.html' to email it." >> logs\run.log 2>&1

echo [%date% %time%] Finished >> logs\run.log
