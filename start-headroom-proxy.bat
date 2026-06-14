@echo off
REM ============================================================
REM Headroom Proxy — compresses all AI tool outputs automatically
REM
REM Start this FIRST, then launch your AI tools.
REM ColumnarFold (58% synthetic / 49% real-world savings) runs
REM automatically on every JSON tool output.
REM ============================================================

echo.
echo  Starting Headroom Proxy on port 8787...
echo  ColumnarFold compression enabled by default.
echo.
echo  To use with Claude Code:   headroom wrap claude
echo  To use with Codex:         headroom wrap codex
echo  To use with any tool:      set OPENAI_BASE_URL=http://localhost:8787/v1
echo.

headroom proxy --port 8787 --log-level info
