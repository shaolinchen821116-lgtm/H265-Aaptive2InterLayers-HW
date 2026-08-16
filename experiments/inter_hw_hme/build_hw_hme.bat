@echo off
setlocal
if "%~1"=="" (
  echo Usage: build_hw_hme.bat X265_SOURCE_ROOT
  echo Run from a Visual Studio developer command prompt with CMake and Ninja on PATH.
  exit /b 2
)
for %%I in ("%~1") do set "ROOT=%%~fI"
if not exist "%ROOT%\source\x265.h" (
  echo Invalid x265 source root: %ROOT%
  exit /b 2
)
cmake -S "%ROOT%\source" -B "%ROOT%\build\inter-hw-ninja" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=OFF -DENABLE_CLI=ON || exit /b 1
cmake --build "%ROOT%\build\inter-hw-ninja" -j 8 || exit /b 1

echo Built: %ROOT%\build\inter-hw-ninja\x265.exe
endlocal
