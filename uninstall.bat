@echo off
setlocal EnableDelayedExpansion

REM NoteAgent Windows Uninstaller

set "INSTALL_DIR=%USERPROFILE%\.noteagent"
set "CONFIG_DIR=%USERPROFILE%\.config\noteagent"
set "DATA_DIR=%USERPROFILE%\notes\noteagent"

echo.
echo ================================================================
echo                   NoteAgent Uninstaller
echo ================================================================
echo.

echo [WARNING] This will remove NoteAgent from your system
echo.
echo The following will be deleted:
echo   * %INSTALL_DIR%
echo.
echo The following will be preserved (you can delete manually if desired):
echo   * %CONFIG_DIR% (configuration)
echo   * %DATA_DIR% (your sessions and recordings)
echo.

set /p CONFIRM="Continue with uninstallation? [y/N] "
if /i not "%CONFIRM%"=="y" (
    echo [INFO] Uninstallation cancelled
    exit /b 0
)

echo.
echo [INFO] Uninstalling NoteAgent...

REM Stop any running server
if exist "%INSTALL_DIR%\.server.pid" (
    set /p PID=<"%INSTALL_DIR%\.server.pid"
    echo [INFO] Stopping running server (PID: !PID!)...
    taskkill /PID !PID! /F >nul 2>&1
    timeout /t 1 /nobreak >nul
)

REM Remove installation directory
if exist "%INSTALL_DIR%" (
    echo [INFO] Removing %INSTALL_DIR%...
    rmdir /s /q "%INSTALL_DIR%" 2>nul
    if exist "%INSTALL_DIR%" (
        echo [ERROR] Failed to remove %INSTALL_DIR%
        echo Please close any programs using files in this directory and try again.
        pause
        exit /b 1
    )
    echo [SUCCESS] Removed %INSTALL_DIR%
) else (
    echo [INFO] Installation directory not found
)

echo.
echo [SUCCESS] NoteAgent has been uninstalled
echo.
echo [INFO] Configuration and data preserved at:
echo   * %CONFIG_DIR%
echo   * %DATA_DIR%
echo.
echo To remove these as well, run:
echo   rmdir /s /q "%CONFIG_DIR%"
echo   rmdir /s /q "%DATA_DIR%"
echo.

pause
