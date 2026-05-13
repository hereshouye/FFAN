@echo off
chcp 65001 >nul
REM FFAN - Windows Build Script (onefile, minimal)
REM Output: dist\FFAN.exe (single file, ~15-20MB)
REM        + release\ folder with exe + docs ready to distribute

setlocal

echo === [1/4] Check PyInstaller ===
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo Installing PyInstaller...
  pip install pyinstaller
  if errorlevel 1 (
    echo [!] Install failed. Run: pip install pyinstaller
    pause
    exit /b 1
  )
)

echo.
echo === [2/4] Cleaning previous build ===
if exist build   rmdir /s /q build
if exist dist    rmdir /s /q dist
if exist release rmdir /s /q release

echo.
echo === [3/4] Building onefile exe ===
pyinstaller build.spec --clean --noconfirm
if errorlevel 1 (
  echo [!] Build failed
  pause
  exit /b 1
)

echo.
echo === [4/4] Assembling release package ===
mkdir release
copy /Y dist\FFAN.exe release\FFAN.exe >nul
copy /Y intro.html             release\使用说明.html       >nul
copy /Y QUICKSTART.txt         release\快速开始.txt        >nul 2>nul
copy /Y BOUNDARIES.md          release\AI边界.md           >nul 2>nul

echo.
echo === Done ===
for %%I in (release\FFAN.exe) do echo Exe size: %%~zI bytes
echo.
echo Release package: release\
dir /B release\
echo.
echo Distribution:
echo   - Zip the release\ folder and send to users
echo   - Or copy release\FFAN.exe + release\*.html alone
echo.
echo First-run behavior:
echo   - Creates data\ next to exe
echo   - Seeds coach\persona.json + coach\kb\psychology\ from bundle
echo   - User clicks "Refresh" in UI to download asset dicts (~5min, optional)
echo.
echo Backwards compat:
echo   - Users with old data\ folder: just place data\ next to new exe
echo   - V1 layout (_cache/, YYYY-MM-DD/) still readable
echo.
pause
