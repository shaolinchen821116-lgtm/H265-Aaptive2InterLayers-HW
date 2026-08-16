# Hardware-oriented x265 PME/IME/FME and adaptive two-layer search

Research implementation for a hardware-friendly HEVC encoder based on x265. The main path implements hierarchical inter search (PME → IME → FME), followed by AMVP/Merge comparison, for square 32×32, 16×16, and 8×8 CU/PU/TU. It also includes an integer decision tree that selects the high two layers (32/16) or low two layers (16/8) on P frames.

The repository contains:

- an x265 source overlay with command-line controls;
- portable C reference implementations for hardware migration;
- experiment, BD-rate analysis, parameter-sweep, and tree-training scripts;
- compact CSV/JSON results for HEVC Class A/B/C/E;
- Chinese design, reproduction, and final Word reports;
- the earlier intra two-layer and conservative `only32` study used by the same x265 snapshot.

Headline 30-frame ABCE result (1 I + 29 P, QP 22/27/32/37): optimized PME is **−0.973% BD-rate** versus native x265; optimized PME plus the adaptive P-layer selector is **+0.510% BD-rate** versus native x265. The adaptive selector alone is **+1.498% BD-rate** versus full three-layer hardware HME at **1.397×** measured encoding speed. These are short-sequence research results and should be revalidated on the target workload and hardware.

For the full documentation, see [中文说明](README_zh.md), [algorithm design](docs/DESIGN_zh.md), [results](docs/RESULTS_zh.md), and [reproduction guide](docs/REPRODUCE_zh.md).

## Quick start

1. Obtain a compatible x265 source tree. The exact local baseline archive is identified in [BASELINE.md](BASELINE.md).
2. Apply the overlay on Windows:

   ```powershell
   .\tools\apply_overlay.ps1 -X265Root D:\path\to\x265
   ```

3. Build x265 normally, then run the smoke test or experiment scripts with an explicit encoder path and an edited sequence manifest.

Raw YUV files, encoded bitstreams, executables, logs, and large CTU datasets are intentionally excluded. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).
