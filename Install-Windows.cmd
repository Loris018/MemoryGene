@echo off
setlocal
cd /d "%~dp0" || exit /b 1
chcp 65001 >nul
where py >nul 2>&1
if not errorlevel 1 (
  set "mg_python=py -3"
) else (
  set "mg_python=python"
)
%mg_python% -c "import sys; sys.exit(sys.version_info < (3,10))" || goto :python_missing
if not exist ".venv\Scripts\python.exe" %mg_python% -m venv .venv
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -q -e . || goto :failed
if not defined MEMORYGENE_DEMO_WORKSPACE set "MEMORYGENE_DEMO_WORKSPACE=%USERPROFILE%\MemoryGene-Demo"
if not defined MEMORYGENE_DEMO_DB set "MEMORYGENE_DEMO_DB=%USERPROFILE%\.memorygene\projects\starter\decisions.sqlite"
".venv\Scripts\python.exe" scripts\bind_project.py --workspace "%MEMORYGENE_DEMO_WORKSPACE%" --db "%MEMORYGENE_DEMO_DB%" --name mg_starter --grok --turn-hooks || goto :failed
echo {"task":"poster"}| ".venv\Scripts\python.exe" -m memorygene.project project_read --db "%MEMORYGENE_DEMO_DB%" >nul || goto :failed
echo Ready. Open this folder in your assistant: "%MEMORYGENE_DEMO_WORKSPACE%"
if not defined CI pause
exit /b 0
:python_missing
echo Install Python 3.10 or newer from python.org and run this file again.
:failed
echo Installation did not finish. See the message above.
if not defined CI pause
exit /b 1
