@echo off
setlocal
if "%~1"=="" (
  echo Usage: build_research.bat X265_SOURCE_ROOT
  echo Run from a Visual Studio developer command prompt with CMake and Ninja on PATH.
  exit /b 2
)
for %%I in ("%~1") do set "ROOT=%%~fI"
cmake -S "%ROOT%\source" -B "%ROOT%\build\intra2-ninja" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DENABLE_CLI=ON ^
  -DENABLE_SHARED=OFF ^
  -DHIGH_BIT_DEPTH=OFF
if errorlevel 1 exit /b 1

cmake --build "%ROOT%\build\intra2-ninja" --target cli --parallel
exit /b %errorlevel%
