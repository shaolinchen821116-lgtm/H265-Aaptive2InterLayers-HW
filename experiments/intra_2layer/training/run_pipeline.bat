@echo off
setlocal
if "%~3"=="" (
  echo Usage: run_pipeline.bat X265_EXE MANIFEST OUTPUT_ROOT
  exit /b 2
)
set "X265_EXE=%~1"
set "MANIFEST=%~2"
set "OUT_ROOT=%~3"
python collect_anchor_stats.py --manifest "%MANIFEST%" --x265 "%X265_EXE%" --output "%OUT_ROOT%\raw" --qps 10:51 --jobs 1
if errorlevel 1 exit /b 1
python prepare_dataset.py --manifest "%MANIFEST%" --stats-root "%OUT_ROOT%\raw" --output "%OUT_ROOT%\dataset"
if errorlevel 1 exit /b 1
python train_two_layer_tree.py --train "%OUT_ROOT%\dataset\train.csv" --validation "%OUT_ROOT%\dataset\validation.csv" --output "%OUT_ROOT%\model" --depth 4 --min-leaf 800 --cutoffs 30 35 40 45 50
exit /b %errorlevel%
