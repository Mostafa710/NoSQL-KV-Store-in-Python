@echo off
REM Run throughput benchmark (server must be running on 4000). Then run durability (starts its own server).
cd /d "%~dp0\.."
echo === Throughput (ensure server is running: scripts\start_server.bat) ===
python benchmarks\bench_throughput.py --port 4000 --out benchmarks\throughput.json
echo.
echo === Durability (starts server on 4001) ===
python benchmarks\bench_durability.py --port 4001 --duration 15 --out benchmarks\durability.json
