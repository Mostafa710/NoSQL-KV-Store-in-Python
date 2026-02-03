@echo off
REM Start 3-node cluster: 2 secondaries then primary. Run each in a separate terminal.
cd /d "%~dp0\.."
echo Run in 3 terminals:
echo   Terminal 1: python -m server.main --port 4001 --data-dir ./data1
echo   Terminal 2: python -m server.main --port 4002 --data-dir ./data2
echo   Terminal 3: python -m server.main --port 4000 --data-dir ./data0 --secondaries http://127.0.0.1:4001,http://127.0.0.1:4002
echo.
echo Then use client with --port 4000 (primary).
