@echo off
setlocal
where cl >nul 2>nul
if errorlevel 1 (
  echo Run this script from a Visual Studio developer command prompt.
  exit /b 2
)
cl /nologo /O2 /W4 /TC /std:c11 intra_layer_selector.c verify_selector.c /Fe:verify_selector.exe
if errorlevel 1 exit /b 1
cl /nologo /O2 /W4 /TC /std:c11 intra_layer_selector.c verify_only32.c /Fe:verify_only32.exe
exit /b %errorlevel%
