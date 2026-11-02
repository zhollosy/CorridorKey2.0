@echo off
rem CorridorKey Studio launcher. Double-click, or drop clips/folders onto this file.
cd /d "%~dp0"

if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" corridorkey_studio.py %*
) else (
    start "" pythonw corridorkey_studio.py %*
)
