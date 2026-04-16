@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Mode restart automatique (appelé par le backend)
if /i "%1"=="--restart" goto start

:: Si on n'est pas déjà dans Windows Terminal, se relancer dedans
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

if /i "%choice%"=="1" goto setup
if /i "%choice%"=="2" goto start
if /i "%choice%"=="q" goto quit
goto menu

:setup
cls
:: Compteur de retries pour eviter boucle infinie
if not defined SETUP_RETRIES set SETUP_RETRIES=0
set /a SETUP_RETRIES+=1
if %SETUP_RETRIES% GTR 3 (
    echo.
    echo    [!] Setup a boucle 3 fois sans succes.
    echo    [!] Certains packages n'ont pas pu etre installes.
    echo    [!] Demarrage quand meme...
    echo.
    timeout /t 3 >nul
    goto start
)
echo.
echo    ================================================================
echo                    SETUP - Installation  (tentative %SETUP_RETRIES%/3)
echo    ================================================================
echo.

:: ============================================
:: ETAPE 0: Verifier/Installer Python embarque
:: ============================================
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

    :: Telecharger Python avec curl (barre de progression visible)
    echo           Telechargement de Python 3.12 portable...
    curl.exe -L --progress-bar -o "%PYTHON_ZIP%" "%PYTHON_URL%"

    if not exist "%PYTHON_ZIP%" (
        echo    [ERREUR] Echec du telechargement de Python
        echo    Verifiez votre connexion internet
        pause
        goto menu
    )

    :: Extraire l'archive python-build-standalone
    echo           Extraction...
    tar.exe -xzf "%PYTHON_ZIP%" -C "%PYTHON_TMP%"
    if exist "%PYTHON_TMP%\python" (
        move "%PYTHON_TMP%\python" "%PYTHON_DIR%" >nul
    )

    :: Nettoyer
    del "%PYTHON_ZIP%" 2>nul
    if exist "%PYTHON_TMP%" rmdir /s /q "%PYTHON_TMP%" 2>nul

    echo    [OK] Python 3.12 installe localement
    echo.
) else (
    echo    [0/4] Python local OK
)

:: Determiner quel Python utiliser
:: Le venv doit utiliser Python 3.12. Sinon on le recrée AVANT activation,
:: pour éviter que check_deps tente de supprimer le venv en cours d'utilisation.
set "VENV_OK=0"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -VV | findstr /B /C:"Python 3.12" >nul
    if not errorlevel 1 set "VENV_OK=1"
)

if "%VENV_OK%"=="1" (
    echo    [1/4] Environnement virtuel existant detecte
    call venv\Scripts\activate.bat
    set "PYTHON=python"
) else (
    if exist "venv" (
        echo    [1/4] Venv incompatible detecte, recreation...
        rmdir /s /q "venv" 2>nul
    ) else (
        echo    [1/4] Creation de l'environnement virtuel...
    )
    "%PYTHON_EXE%" -m venv venv
    if exist "venv\Scripts\python.exe" (
        call venv\Scripts\activate.bat
        set "PYTHON=python"
    ) else (
        echo    [ERREUR] Impossible de creer le venv Python 3.12
        pause
        goto menu
    )
)

echo    [2/4] Bootstrap dependances + verification...
echo.
"%PYTHON%" scripts\bootstrap.py setup
set CHECK_RESULT=%errorlevel%

:: Si code 99 = Python/venv a été recréé
if %CHECK_RESULT%==99 (
    echo.
    echo    [!] Venv recree - Relancement du setup...
    timeout /t 3 >nul
    goto setup
)

:: Si code >= 1 = packages installés
if %CHECK_RESULT% GEQ 1 (
    echo.
    echo    [!] Installation en cours - Verification...
    timeout /t 3 >nul
    goto setup
)

echo.
echo    ================================================================
echo                    Setup termine !
echo    ================================================================
echo.
timeout /t 2 >nul
goto start

:start
cls
:: Utiliser le venv si existant, sinon Python embarqué
if exist "venv\Scripts\python.exe" (
    call venv\Scripts\activate.bat
    set "PY=python"
) else (
    set "PY=python312\python.exe"
)

:: Si une carte NVIDIA existe mais que le venv a un PyTorch CPU-only,
:: le démarrage rapide mènera à "Torch not compiled with CUDA enabled".
:: On bascule donc automatiquement vers le setup/réparation.
where nvidia-smi >nul 2>&1
if errorlevel 1 goto skip_cuda_repair_check
"%PY%" -c "import sys; import torch; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>nul
if not errorlevel 1 goto skip_cuda_repair_check
echo.
echo    [!] GPU NVIDIA detecte mais PyTorch CUDA indisponible dans ce venv.
echo    [!] Lancement du setup pour reparer PyTorch CUDA...
echo.
timeout /t 2 >nul
goto setup
:skip_cuda_repair_check

:: Quick check: installer ollama si manquant
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

:: Si code 42 = restart demandé, fermer cette fenêtre
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
