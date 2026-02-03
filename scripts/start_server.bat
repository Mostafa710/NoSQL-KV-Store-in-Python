@echo off
REM Start KV-Store server (Windows)
cd /d "%~dp0\.."
python -m server.main --host 127.0.0.1 --port 4000 --data-dir ./data %*
