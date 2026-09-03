@echo off
setlocal

for %%I in ("%~dp0..") do set "WULFRAM_CORE_ROOT=%%~fI"
if not defined WULFRAM_PYTHON set "WULFRAM_PYTHON=python"

cmake -S "%WULFRAM_CORE_ROOT%\physics" -B "%WULFRAM_CORE_ROOT%\build\physics-x64" -A x64 -DWULFRAM_PHYSICS_BUILD_PYTHON=ON -DWULFRAM_PHYSICS_BUILD_TESTS=OFF "-DPython3_EXECUTABLE=%WULFRAM_PYTHON%"
if errorlevel 1 exit /b %ERRORLEVEL%
cmake --build "%WULFRAM_CORE_ROOT%\build\physics-x64" --config RelWithDebInfo --target WulframPhysicsPython
exit /b %ERRORLEVEL%
