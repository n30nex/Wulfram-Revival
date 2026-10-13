@echo off
setlocal
cd /d "%~dp0"
tasklist /fi "IMAGENAME eq wulfram2.exe" | find /i "wulfram2.exe" >nul
if not errorlevel 1 (
  echo Close Wulfram before changing these settings.
  pause
  exit /b 1
)
:menu
cls
echo.
echo   CANADAVERSE WULFRAM II - SETTINGS
echo.
echo   1  Modern controls: WASD, Q/E turn, Space jump jets
echo   2  Classic controls
echo   3  Balanced graphics
echo   4  High quality graphics
echo   0  Close
echo.
choice /c 12340 /n /m "Choose a number: "
if errorlevel 5 exit /b 0
if errorlevel 4 goto high
if errorlevel 3 goto balanced
if errorlevel 2 goto classic
set "preset=modern"
goto controls
:classic
set "preset=classic"
:controls
for %%F in (keymap keymap_tank keymap_scout) do (
  if not exist "canadaverse\controls\%preset%\%%F" goto missing
)
for %%F in (keymap keymap_tank keymap_scout) do (
  if not exist "canadaverse\controls\before-settings-%%F" (
    copy /y "data\%%F" "canadaverse\controls\before-settings-%%F" >nul
    if errorlevel 1 goto failed
  )
  copy /y "canadaverse\controls\%preset%\%%F" "data\%%F" >nul
  if errorlevel 1 goto failed
)
echo Applied %preset% controls.
goto done
:high
set "preset=high"
goto graphics
:balanced
set "preset=balanced"
:graphics
if not exist "canadaverse\graphics\%preset%.ini" goto missing
if not exist "canadaverse\graphics\before-settings.ini" (
  copy /y "DDrawCompat-wulfram2.ini" "canadaverse\graphics\before-settings.ini" >nul
  if errorlevel 1 goto failed
)
copy /y "canadaverse\graphics\%preset%.ini" "DDrawCompat-wulfram2.ini" >nul
if errorlevel 1 goto failed
echo Applied %preset% graphics.
:done
echo Launch Play Canadaverse.cmd to use the new settings.
pause
goto menu
:missing
echo A settings file is missing. Extract the complete client package again.
pause
exit /b 1
:failed
echo Could not save settings. Move the extracted game to a writable Games folder.
pause
exit /b 1
