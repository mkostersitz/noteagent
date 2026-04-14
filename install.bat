@echo off
setlocal EnableDelayedExpansion

REM NoteAgent Windows Installer
REM Version 0.1.6

set "VERSION=0.1.6"
set "REPO_URL=https://github.com/mkostersitz/noteagent"
set "INSTALL_DIR=%USERPROFILE%\.noteagent"
set "MODEL_DIR=%INSTALL_DIR%\models"
set "VENV_DIR=%INSTALL_DIR%\venv"

echo.
echo ================================================================
echo                    NoteAgent Installer
echo                          v%VERSION%
echo ================================================================
echo.

REM Check for Python
echo [INFO] Checking prerequisites...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required but not found
    echo Please install Python from https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [SUCCESS] Python %PYTHON_VERSION% found

REM Check for Rust
rustc --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Rust is required but not found
    echo Please install Rust from https://rustup.rs/
    exit /b 1
)

for /f "tokens=2" %%i in ('rustc --version') do set RUST_VERSION=%%i
echo [SUCCESS] Rust %RUST_VERSION% found

REM Check for Git
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is required but not found
    echo Please install Git from https://git-scm.com/downloads
    exit /b 1
)

echo [SUCCESS] Git found

REM Create directories
echo [INFO] Creating installation directories...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

REM Clone repository
echo [INFO] Cloning NoteAgent repository...
set "TEMP_CLONE=%TEMP%\noteagent-%RANDOM%"
git clone --depth 1 --branch main "%REPO_URL%" "%TEMP_CLONE%"
if errorlevel 1 (
    echo [ERROR] Failed to clone repository
    exit /b 1
)
echo [SUCCESS] Repository cloned

REM Create virtual environment
echo [INFO] Creating Python virtual environment...
python -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment
    exit /b 1
)
echo [SUCCESS] Virtual environment created

REM Activate venv
call "%VENV_DIR%\Scripts\activate.bat"

REM Install Python dependencies
echo [INFO] Installing Python dependencies...
python -m pip install --upgrade pip setuptools wheel --quiet
pip install maturin --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    exit /b 1
)
echo [SUCCESS] Dependencies installed

REM Build Rust extension
echo [INFO] Building Rust audio extension...
cd /d "%TEMP_CLONE%\noteagent-audio"
maturin develop --release
if errorlevel 1 (
    echo [ERROR] Failed to build Rust extension
    exit /b 1
)
echo [SUCCESS] Rust extension built

REM Install NoteAgent
echo [INFO] Installing NoteAgent package...
cd /d "%TEMP_CLONE%"
pip install -e ".[dev]" --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install NoteAgent
    exit /b 1
)
echo [SUCCESS] NoteAgent installed

REM Download Whisper model
echo [INFO] Downloading Whisper base.en model...
set "MODEL_FILE=%MODEL_DIR%\base.en.pt"
if not exist "%MODEL_FILE%" (
    powershell -Command "(New-Object Net.WebClient).DownloadFile('https://openaipublic.azureedge.net/main/whisper/models/25a8566e1d0c1e2231d1c762132cd20e0f96a85d16145c3a00adf5d1ac670ead/base.en.pt', '%MODEL_FILE%')"
    if errorlevel 1 (
        echo [ERROR] Failed to download model
        exit /b 1
    )
    echo [SUCCESS] Model downloaded
) else (
    echo [INFO] Model already exists
)

REM Copy source files
echo [INFO] Copying files...
xcopy /E /I /Q "%TEMP_CLONE%" "%INSTALL_DIR%\src"
echo [SUCCESS] Files copied

REM Create launcher batch file
echo [INFO] Creating launcher script...
set "LAUNCHER=%INSTALL_DIR%\noteagent.bat"
(
    echo @echo off
    echo call "%VENV_DIR%\Scripts\activate.bat"
    echo set NOTEAGENT_MODEL_DIR=%MODEL_DIR%
    echo python -m noteagent.cli %%*
) > "%LAUNCHER%"
echo [SUCCESS] Launcher created at %LAUNCHER%

REM Create config directory
set "CONFIG_DIR=%USERPROFILE%\.config\noteagent"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"

set "CONFIG_FILE=%CONFIG_DIR%\config.toml"
if not exist "%CONFIG_FILE%" (
    echo [INFO] Creating default configuration...
    (
        echo # NoteAgent Configuration
        echo.
        echo [storage]
        echo path = "~/notes/noteagent"
        echo.
        echo [audio]
        echo sample_rate = 16000
        echo channels = 1
        echo device = ""
        echo.
        echo [transcription]
        echo model = "base.en"
        echo language = "en"
        echo quality = "balanced"
        echo.
        echo [server]
        echo host = "127.0.0.1"
        echo port = 8765
        echo.
        echo [auth]
        echo enabled = false
        echo token_header = "Authorization"
        echo token_prefix = "Bearer"
        echo.
        echo [rate_limit]
        echo enabled = true
        echo default_limit = "100/minute"
        echo whitelist_ips = ["127.0.0.1", "::1"]
    ) > "%CONFIG_FILE%"
    echo [SUCCESS] Configuration created
)

REM Cleanup
rmdir /s /q "%TEMP_CLONE%" 2>nul

REM Print summary
echo.
echo ================================================================
echo.
echo  [SUCCESS] NoteAgent v%VERSION% installed successfully!
echo.
echo ================================================================
echo.
echo Installation Details:
echo   * Install directory: %INSTALL_DIR%
echo   * Virtual env:       %VENV_DIR%
echo   * Models:            %MODEL_DIR%
echo   * Config:            %CONFIG_FILE%
echo.
echo Quick Start:
echo   1. Add to PATH or use full path:
echo      %LAUNCHER%
echo.
echo   2. Verify installation:
echo      call %LAUNCHER% --help
echo.
echo   3. Start recording:
echo      call %LAUNCHER% record
echo.
echo   4. Start web UI:
echo      call %LAUNCHER% serve
echo.
echo To add to PATH, add this directory to your system PATH:
echo   %INSTALL_DIR%
echo.

pause
