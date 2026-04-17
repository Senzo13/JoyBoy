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
echo       [1]  Setup complet (premiere fois / reparer)
echo.
echo       [2]  Demarrer rapidement
echo.
echo       [Q]  Quitter
echo.
echo.
set /p choice="       Choix: "

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
    echo    [!] Setup a boucle 3 fois sans succes.
    echo    [!] Certains packages n'ont pas pu etre installes ou repares.
    echo    [!] Retour au menu pour eviter une boucle automatique.
    echo.
    pause
    goto menu
)
echo.
echo    ================================================================
echo                    SETUP - Installation  (tentative %SETUP_RETRIES%/3)
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
set "PYTHON_NEEDS_INSTALL=0"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_NEEDS_INSTALL=1"
) else (
    "%PYTHON_EXE%" -c "import venv" >nul 2>nul
    if errorlevel 1 set "PYTHON_NEEDS_INSTALL=1"
)

if "%PYTHON_NEEDS_INSTALL%"=="1" (
    echo    [0/4] Python non trouve, telechargement...
    echo.

    if exist "%PYTHON_DIR%" rmdir /s /q "%PYTHON_DIR%" 2>nul
    if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul
    mkdir "%PYTHON_TMP%"

    REM Download Python with visible curl progress
    echo           Telechargement de Python 3.12 portable...
    curl.exe -L --progress-bar -o "%PYTHON_ZIP%" "%PYTHON_URL%"
    if errorlevel 1 (
        echo    [ERREUR] Echec du telechargement de Python
        echo    Verifiez votre connexion internet
        pause
        goto menu
    )

    if not exist "%PYTHON_ZIP%" (
        echo    [ERREUR] Echec du telechargement de Python
        echo    Verifiez votre connexion internet
        pause
        goto menu
    )

    REM Extract python-build-standalone archive
    echo           Extraction...
    tar.exe -xzf "%PYTHON_ZIP%" -C "%PYTHON_TMP%"
    if errorlevel 1 (
        echo    [ERREUR] Echec extraction Python
        echo    Archive invalide ou extraction Windows indisponible.
        del "%PYTHON_ZIP%" 2>nul
        if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul
        pause
        goto menu
    )
    if not exist "%PYTHON_TMP%\python" (
        echo    [ERREUR] Archive Python inattendue: dossier python introuvable
        del "%PYTHON_ZIP%" 2>nul
        if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul
        pause
        goto menu
    )
    move "%PYTHON_TMP%\python" "%PYTHON_DIR%" >nul

    REM Cleanup
    del "%PYTHON_ZIP%" 2>nul
    if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul

    if not exist "%PYTHON_EXE%" (
        echo    [ERREUR] Python extrait mais python.exe introuvable
        echo    Chemin attendu: %PYTHON_EXE%
        pause
        goto menu
    )
    "%PYTHON_EXE%" -c "import venv; import ensurepip" >nul 2>nul
    if errorlevel 1 (
        echo    [ERREUR] Python portable incomplet: venv/pip indisponible
        echo    Supprime le dossier python312 puis relance le setup.
        pause
        goto menu
    )

    echo    [OK] Python 3.12 installe localement
    echo.
) else (
    echo    [0/4] Python local OK
)

REM Decide which Python to use.
REM The venv must use Python 3.12. Otherwise recreate it before activation,
REM so check_deps never tries to remove the active venv.
set "VENV_OK=0"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -VV | findstr /B /C:"Python 3.12" >nul
    if not errorlevel 1 set "VENV_OK=1"
)

if "%VENV_OK%"=="1" (
    echo    [1/4] Environnement virtuel existant detecte
    set "PYTHON=venv\Scripts\python.exe"
) else (
    if exist "venv" (
        echo    [1/4] Venv incompatible detecte, recreation...
        rmdir /s /q "venv" 2>nul
        if exist "venv" (
            echo    [ERREUR] Impossible de supprimer l'ancien venv.
            echo    Ferme les terminaux JoyBoy/Python qui l'utilisent puis relance.
            pause
            goto menu
        )
    ) else (
        echo    [1/4] Creation de l'environnement virtuel...
    )
    "%PYTHON_EXE%" -m venv venv
    if exist "venv\Scripts\python.exe" (
        set "PYTHON=venv\Scripts\python.exe"
    ) else (
        echo    [ERREUR] Impossible de creer le venv Python 3.12
        echo    Python utilise: %PYTHON_EXE%
        pause
        goto menu
    )
)

echo    [2/4] Bootstrap dependances + verification...
echo.
"%PYTHON%" scripts\bootstrap.py setup
set CHECK_RESULT=%errorlevel%

REM Code 99 means Python/venv was recreated
if %CHECK_RESULT%==99 (
    echo.
    echo    [!] Venv recree - Relancement du setup...
    timeout /t 3 >nul
    goto setup
)

REM Code >= 1 means setup needs another verification pass
if %CHECK_RESULT% GEQ 1 (
    echo.
    echo    [!] Setup incomplet ou en erreur (code %CHECK_RESULT%) - Verification...
    timeout /t 3 >nul
    goto setup
)

echo.
echo    ================================================================
echo                    Setup termine !
echo    ================================================================
echo.
set "SETUP_RETRIES=0"
timeout /t 2 >nul
goto start

:start
cls
REM Use venv if available, otherwise portable Python
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=python312\python.exe"
)
if not exist "%PY%" (
    echo.
    echo    [!] Python local introuvable.
    echo    [!] Lance "Setup complet" une premiere fois pour creer le venv.
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
echo    [!] GPU NVIDIA detecte mais PyTorch CUDA indisponible dans ce venv.
echo    [!] Lance "Setup complet" depuis le menu pour reparer PyTorch CUDA.
echo    [!] JoyBoy demarre quand meme pour eviter une boucle automatique.
echo.
timeout /t 5 >nul
:skip_cuda_repair_check

REM Quick check: install Ollama if missing
where ollama >nul 2>&1
if not errorlevel 1 goto skip_ollama_install
echo.
echo    Ollama non detecte, telechargement...
"%PY%" -c "import subprocess,os,urllib.request;p=os.path.join(os.environ.get('TEMP','.'),'OllamaSetup.exe');urllib.request.urlretrieve('https://ollama.com/download/OllamaSetup.exe',p);subprocess.run([p,'/VERYSILENT','/NORESTART'],timeout=120);os.path.exists(p) and os.remove(p)"
echo    [OK] Ollama installe
echo.
:skip_ollama_install

"%PY%" web/app.py
set EXIT_CODE=%errorlevel%

REM Code 42 means backend requested restart; close this window
if %EXIT_CODE%==42 (
    echo    Restart en cours...
    exit
)

echo.
echo    ================================================================
echo                    Serveur arrete
echo    ================================================================
echo.
pause
goto menu

:quit
exit
