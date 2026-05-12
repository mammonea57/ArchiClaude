@echo off
REM ArchiClaude UE5 pipeline launcher for Windows (MSI GE76)
REM
REM Double-click this file (or run from cmd) to fire the full pipeline :
REM   Blender (cloud Modal) -> USD export -> UE5 (local Windows) -> PNG -> validate
REM
REM Prerequisites :
REM   - Python 3.10+ in PATH (Python from python.org or Microsoft Store)
REM   - Modal CLI installed and authenticated (`pip install modal && modal token new`)
REM   - UE5 5.4+ installed via Epic Games Launcher
REM   - The render-service venv exists (or python -m venv .venv && pip install requirements)
REM
REM Usage :
REM   run_pipeline.bat               -> uses ITER=500 default
REM   run_pipeline.bat 501            -> uses ITER=501

setlocal

REM Script directory (this .bat) -> repo root is 4 levels up
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..\..\..\

REM Iteration number (optional first arg, defaults to 500)
set ITER=%1
if "%ITER%"=="" set ITER=500

echo.
echo ============================================================
echo  ArchiClaude UE5 pipeline -- iter #%ITER%
echo ============================================================
echo Repo root : %REPO_ROOT%
echo.

REM Activate venv if present
if exist "%REPO_ROOT%apps\render-service\.venv\Scripts\activate.bat" (
    call "%REPO_ROOT%apps\render-service\.venv\Scripts\activate.bat"
    echo (venv activated)
) else (
    echo (no venv detected, using system Python)
)

cd /d "%REPO_ROOT%"

REM Run the orchestrator
python apps\render-service\ue5\run_pipeline_ue5.py --iter %ITER%
set RC=%ERRORLEVEL%

echo.
if %RC% NEQ 0 (
    echo Pipeline failed with exit code %RC%
) else (
    echo Pipeline complete.
)

REM Generate side-by-side comparison
if exist "refs\renders\2026-05-11_iter%ITER%_ue5.png" (
    python apps\render-service\ue5\compare_side_by_side.py ^
        --new refs\renders\2026-05-11_iter%ITER%_ue5.png ^
        --output refs\renders\2026-05-11_iter%ITER%_comparison.png
    echo Comparison saved.
)

pause
endlocal
exit /b %RC%
