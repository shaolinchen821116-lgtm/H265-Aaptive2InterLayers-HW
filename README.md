# Hardware-oriented x265 PME/IME/FME and adaptive two-layer search

Research implementation for a hardware-friendly HEVC encoder based on x265. The main path implements hierarchical inter search (PME → IME → FME), followed by AMVP/Merge comparison, for square 32×32, 16×16, and 8×8 CU/PU/TU. It includes integer trees that select CU32-only, high two layers (32/16), or low two layers (16/8) on P frames.

The repository contains:

- a complete, buildable modified x265 source snapshot in `x265/`;
- an x265 source overlay with the same command-line controls for porting;
- portable C reference implementations for hardware migration;
- experiment, BD-rate analysis, parameter-sweep, and tree-training scripts;
- compact CSV/JSON results for HEVC Class A/B/C/E;
- Chinese design, reproduction, and final Word reports;
- the earlier intra two-layer and conservative `only32` study used by the same x265 snapshot.

Headline 30-frame ABCE result (1 I + 29 P, QP 22/27/32/37): the original CU32-only high2/low2 selector is **+1.498% BD-rate** versus full three-layer hardware HME; the new cost-sensitive multiscale selector (mode 8, cutoff 45) reduces this to **+0.966%** across 17 sequences. Its frozen Class-B model reaches **84.834%** independent decision accuracy on Class A/C/E. The requested hierarchy-cost-only baseline, `SAD + sqrt(lambda) * MVD_bits` with `4 * min(J8)` aggregation (mode 9), is **+1.659%** on Class B and is retained as a training baseline rather than the recommendation. I pictures always keep intra32/intra16/intra8 enabled.

For the full documentation, see [中文说明](README_zh.md), [algorithm design](docs/DESIGN_zh.md), [results](docs/RESULTS_zh.md), [reproduction guide](docs/REPRODUCE_zh.md), and the [final Word report](docs/P帧多尺度与层次Cost两层选择_测试与训练报告_zh.docx).

## Quick start

1. Build the included modified x265 source from a Visual Studio developer prompt:

   ```powershell
   cmake -S .\x265\source -B .\x265\build\hw -G Ninja `
     -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=OFF -DENABLE_CLI=ON
   cmake --build .\x265\build\hw
   ```

2. Alternatively, apply the overlay to another compatible x265 source tree:

   ```powershell
   .\tools\apply_overlay.ps1 -X265Root D:\path\to\x265
   ```

3. Run the experiment scripts with an explicit encoder path and an edited sequence manifest. Mode 8 with cutoff 45 is the validated high2/low2 setting; mode 7 collects full-three-layer labels, and mode 9 is the hierarchy-cost-only baseline.

Raw YUV files, encoded bitstreams, executables, logs, and large CTU datasets are intentionally excluded. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).
