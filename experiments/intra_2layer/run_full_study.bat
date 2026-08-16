@echo off
setlocal

if not defined STUDY_PYTHON set "STUDY_PYTHON=python"
if "%~3"=="" (
  echo Usage: run_full_study.bat X265_SOURCE_ROOT YUV_ROOT OUTPUT_ROOT
  exit /b 2
)
for %%I in ("%~1") do set "X265_ROOT=%%~fI"
for %%I in ("%~2") do set "YUV_ROOT=%%~fI"
for %%I in ("%~3") do set "OUT_ROOT=%%~fI"
set "X265_EXE=%X265_ROOT%\build\intra2-ninja\x265.exe"

call "%~dp0build_research.bat" "%X265_ROOT%"
if errorlevel 1 exit /b 1

rem QP10..51 anchor scan: used for fitting and RDO agreement statistics.
"%STUDY_PYTHON%" "%~dp0run_experiments.py" ^
  --encoder "%X265_EXE%" --yuv-root "%YUV_ROOT%" --output "%OUT_ROOT%" ^
  --qps 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 ^
  --modes all --stats-modes all --jobs 4
if errorlevel 1 exit /b 1

rem Formal four-point overlapping QP segments and ten-point overall curve.
"%STUDY_PYTHON%" "%~dp0run_experiments.py" ^
  --encoder "%X265_EXE%" --yuv-root "%YUV_ROOT%" --output "%OUT_ROOT%" ^
  --qps 10 16 20 24 28 32 36 40 44 48 ^
  --modes low adaptive40 --jobs 4
if errorlevel 1 exit /b 1

"%STUDY_PYTHON%" "%~dp0analyze_results.py" --results "%OUT_ROOT%" --output "%OUT_ROOT%\report_data"
if errorlevel 1 exit /b 1
"%STUDY_PYTHON%" "%~dp0analyze_validation_sets.py" --results "%OUT_ROOT%" --output "%OUT_ROOT%\validation_report_data"
exit /b %errorlevel%
