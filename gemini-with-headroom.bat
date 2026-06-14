@echo off
REM Launch any Gemini tool with Headroom proxy
REM Start the proxy first, then set the base URL

start /B headroom proxy --port 8787 --log-level info
timeout /t 3 /nobreak >nul

echo Headroom proxy running on port 8787
echo Set your Gemini client to use: http://localhost:8787/v1
echo.
echo Press any key to stop the proxy...
pause >nul
taskkill /f /im headroom.exe 2>nul
