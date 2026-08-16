@echo off
setlocal
if "%~2"=="" (
  echo Usage: run_smoke.bat X265_EXE BASKETBALLDRIVE_YUV [OUTPUT_DIR]
  exit /b 2
)
for %%I in ("%~1") do set "ENC=%%~fI"
for %%I in ("%~2") do set "YUV=%%~fI"
if "%~3"=="" (set "OUT=%TEMP%\x265-hw-hme-smoke") else (for %%I in ("%~3") do set "OUT=%%~fI")

if not exist "%OUT%" mkdir "%OUT%"
if not exist "%ENC%" (
  echo Encoder was not found: %ENC%
  exit /b 1
)
if not exist "%YUV%" (
  echo YUV was not found: %YUV%
  exit /b 1
)

"%ENC%" --input "%YUV%" --input-res 1920x1080 --fps 50 --frames 2 ^
  --preset medium --tune zerolatency --qp 32 --ctu 32 --min-cu-size 8 ^
  --no-rect --no-amp --max-tu-size 32 --tu-inter-depth 1 --bframes 0 ^
  --ref 1 --no-weightp --no-weightb --keyint 250 --min-keyint 250 ^
  --no-scenecut --frame-threads 1 --no-early-skip --rskip 0 --limit-refs 0 ^
  --hw-hme --hw-hme-pme-range 32,28 --hw-hme-ime-range 12,12 ^
  --hw-hme-pme-cost-mode 1 --hw-hme-pme-rate-scale 256 ^
  --hw-hme-pme-texture 8,24 --hw-hme-pme-attractor 1 --hw-hme-stats ^
  -o "%OUT%\BasketballDrive_qp32_hw.hevc"

endlocal
