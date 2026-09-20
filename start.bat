@echo off
setlocal
rem ==== Qwen LiveTranslate Caption Launcher (ASCII-only for codepage safety) ====
set PY=python
set DIR=%~dp0

if "%DASHSCOPE_API_KEY%"=="" (
  echo [ERROR] DASHSCOPE_API_KEY not set yet.
  echo Run this ONCE in PowerShell, then re-double-click this file:
  echo     setx DASHSCOPE_API_KEY "sk-your-key-here"
  pause
  exit /b 1
)

cd /d "%DIR%"
"%PY%" main.py
