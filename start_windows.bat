@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Auto restart mode used by backend. Do not stop on interactive repair prompts.
if /i "%1"=="--restart" (
    set "JOYBOY_SKIP_CUDA_REPAIR_PROMPT=1"
    goto start
)

REM Relaunch in Windows Terminal when available
if not defined WT_SESSION (
    where wt >nul 2>&1
    if not errorlevel 1 (
        wt new-tab -p "Command Prompt" cmd /k "cd /d %~dp0 && %~nx0"
        exit /b
    )
)

:menu
cls
echo.
echo                                     ████████
echo                                    █████████
echo                                    ██████████
echo                                   ████████████
echo                             ███████████████████████
echo               ███       ███████████████████████████████         ███
echo             █████████████████████████████████████████████████████
echo            ███████████████████████            █████████████████   ███
echo            ██████████████████                      ██████████   ██████
echo            ███████████████                            ██████  ███████
echo             ████████████                                 █  ████████
echo             █████████                ███████               █████████
echo            █████████           ██████████████████           █████████
echo           ████████           ██████████████████████           ████████
echo          ████████          ████████████████████████            ████████
echo          ███████         ████████████████████████   ███         ███████
echo         ███████         ███████████████████████   ██████         ███████
echo         ███████        ██████████████████████   █████████        ███████
echo        ████████       ██████████████████████   ███████████        ███████
echo   ████████████        ████                            ████        ███████████
echo  █████████████  ███████████████████████    ██████████████████████ █████████████
echo  █████████████ ███████████████████████   ██████████████████████████████████████
echo  █████████████       █████                            █████       █████████████
echo  █████████████        ████                            ████        █████████████
echo     ██████████        ████                            ████        ███████████
echo         ███████        ████                          ████        ████████
echo         ███████         ████                        ████         ███████
echo          ███████         ██                       █████         ████████
echo          ████████           █████               ██████         ████████
echo           ████████          ████████████████████████          ████████
echo            ████████            ██████████████████            ████████
echo             ████████               ██████████              ██████████
echo             ███████  ██                                  ███████████
echo             █████   █████                              ██████████████
echo            ████   ██████████                        █████████████████
echo            ███  █████████████████              ███████████████████████
echo               ███████████████████████████████████████████████████████
echo              █████      ████████████████████████████████      █████
echo            █                ████████████████████████
echo          █                        ████████████
echo                                    ██████████
echo                                    █████████
echo                                     ████████
echo.
echo    ========================================================================
echo.
echo                              J O Y B O Y
echo.
echo                      "Dream. Create. Be Free."
echo.
echo                100%% Local  -  Zero Cloud  -  No Limits
echo.
echo    ========================================================================
echo.
echo.
echo       [1]  Full setup (first run / repair)
echo.
echo       [2]  Quick start
echo.
echo       [Q]  Quit
echo.
echo.
set /p choice="       Choice: "

if /i "%choice%"=="1" goto menu_setup
if /i "%choice%"=="2" goto start
if /i "%choice%"=="q" goto quit
goto menu

:menu_setup
set "SETUP_RETRIES=0"
goto setup

:setup
cls
REM Retry counter prevents infinite setup loops
if not defined SETUP_RETRIES set SETUP_RETRIES=0
set /a SETUP_RETRIES+=1
if %SETUP_RETRIES% GTR 3 (
    echo.
    echo    [!] Setup ran 3 times without success.
    echo    [!] Some packages could not be installed or repaired.
    echo    [!] Returning to the menu to avoid an automatic loop.
    echo.
    pause
    goto menu
)
echo.
echo    ================================================================
echo                    SETUP - Installation  (attempt %SETUP_RETRIES%/3)
echo    ================================================================
echo.

REM ============================================
REM STEP 0: Check/install portable Python
REM ============================================
set "PYTHON_DIR=python312"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PYTHON_URL=https://github.com/indygreg/python-build-standalone/releases/download/20241206/cpython-3.12.8+20241206-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
set "PYTHON_ZIP=python312.tar.gz"
set "PYTHON_TMP=python312_temp"
set "SETUP_LOG=.joyboy\logs\windows_setup_last.log"
set "PYTHON_NEEDS_INSTALL=0"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_NEEDS_INSTALL=1"
) else (
    "%PYTHON_EXE%" -c "import venv" >nul 2>nul
    if errorlevel 1 set "PYTHON_NEEDS_INSTALL=1"
)

if "%PYTHON_NEEDS_INSTALL%"=="1" (
    echo    [0/4] Python not found, downloading...
    echo.

    if exist "%PYTHON_DIR%" rmdir /s /q "%PYTHON_DIR%" 2>nul
    if exist "%PYTHON_DIR%" (
        echo    [ERROR] Could not remove the old portable Python.
        echo    Close any JoyBoy/Python terminals using it, then run setup again.
        pause
        goto menu
    )
    if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul
    if exist "%PYTHON_TMP%" (
        echo    [ERROR] Could not clean the temporary Python folder.
        echo    Delete %PYTHON_TMP%, then run setup again.
        pause
        goto menu
    )
    mkdir "%PYTHON_TMP%"
    if errorlevel 1 (
        echo    [ERROR] Could not create the temporary Python folder.
        pause
        goto menu
    )

    REM Download Python with visible curl progress
    echo           Downloading portable Python 3.12...
    curl.exe -L --retry 5 --retry-delay 2 --connect-timeout 30 --progress-bar -o "%PYTHON_ZIP%" "%PYTHON_URL%"
    if errorlevel 1 (
        echo    [ERROR] Python download failed
        echo    Check your internet connection
        pause
        goto menu
    )

    if not exist "%PYTHON_ZIP%" (
        echo    [ERROR] Python download failed
        echo    Check your internet connection
        pause
        goto menu
    )

    REM Extract python-build-standalone archive
    echo           Extracting...
    tar.exe -xzf "%PYTHON_ZIP%" -C "%PYTHON_TMP%"
    if errorlevel 1 (
        echo    [ERROR] Python extraction failed
        echo    Invalid archive or Windows extraction is unavailable.
        del "%PYTHON_ZIP%" 2>nul
        if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul
        pause
        goto menu
    )
    if not exist "%PYTHON_TMP%\python" (
        echo    [ERROR] Unexpected Python archive: python folder not found
        del "%PYTHON_ZIP%" 2>nul
        if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul
        pause
        goto menu
    )
    move "%PYTHON_TMP%\python" "%PYTHON_DIR%" >nul

    REM Cleanup
    del "%PYTHON_ZIP%" 2>nul
    if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul

    echo    [OK] Python 3.12 installed locally
    echo.
) else (
    echo    [0/4] Local Python OK
)

echo    [1/4] Checking / creating the venv...
"%PYTHON_EXE%" scripts\windows_venv.py ensure
if errorlevel 1 (
    echo.
    echo    [ERROR] Venv is not working.
    echo    Full log: %SETUP_LOG%
    echo.
    pause
    goto menu
)
set "PYTHON=venv\Scripts\python.exe"

echo    [2/4] Installing dependencies + verification...
echo.
"%PYTHON%" scripts\bootstrap.py setup
set CHECK_RESULT=%errorlevel%

REM Code 99 means Python/venv was recreated
if %CHECK_RESULT%==99 (
    echo.
    echo    [!] Venv recreated - restarting setup...
    timeout /t 3 >nul
    goto setup
)

REM Code >= 1 means setup needs another verification pass
if %CHECK_RESULT% GEQ 1 (
    echo.
    echo    [!] Setup incomplete or failed ^(code %CHECK_RESULT%^) - verifying again...
    timeout /t 3 >nul
    goto setup
)

echo.
echo    ================================================================
echo                    Setup complete!
echo    ================================================================
echo.
set "SETUP_RETRIES=0"
timeout /t 2 >nul
goto start

:start
cls
REM Normal app start must use the venv; portable Python only bootstraps setup.
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    echo.
    echo    [!] JoyBoy venv not found.
    echo    [!] Run "Full setup" once to create the venv.
    echo.
    pause
    goto menu
)

REM If NVIDIA exists but PyTorch is CPU-only, image/video acceleration is limited.
REM Warn without auto-switching to setup, otherwise a failed repair loops forever.
if "%JOYBOY_SKIP_CUDA_REPAIR_PROMPT%"=="1" goto skip_cuda_repair_check
where nvidia-smi >nul 2>&1
if errorlevel 1 goto skip_cuda_repair_check
"%PY%" -c "import sys; import torch; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>nul
if not errorlevel 1 goto skip_cuda_repair_check
echo.
echo    [!] NVIDIA GPU detected, but PyTorch CUDA is unavailable in this venv.
echo    [!] Run "Full setup" from the menu to repair PyTorch CUDA.
echo    [!] JoyBoy will still start to avoid an automatic setup loop.
echo.
timeout /t 5 >nul
:skip_cuda_repair_check

REM Quick check: install Ollama if missing
where ollama >nul 2>&1
if not errorlevel 1 goto skip_ollama_install
echo.
echo    Ollama not detected, downloading...
"%PY%" -c "import subprocess,os,urllib.request;p=os.path.join(os.environ.get('TEMP','.'),'OllamaSetup.exe');urllib.request.urlretrieve('https://ollama.com/download/OllamaSetup.exe',p);subprocess.run([p,'/VERYSILENT','/NORESTART'],timeout=120);os.path.exists(p) and os.remove(p)"
echo    [OK] Ollama installed
echo.
:skip_ollama_install

"%PY%" web/app.py
set EXIT_CODE=%errorlevel%

REM Code 42 means backend requested restart; close this window
if %EXIT_CODE%==42 (
    echo    Restarting...
    exit
)

echo.
echo    ================================================================
echo                    Server stopped
echo    ================================================================
echo.
pause
goto menu

:quit
exit
