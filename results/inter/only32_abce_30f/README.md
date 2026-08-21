# P-frame CU32-only gate, ABCE 30-frame results

Test set: HEVC Class A/B/C/E, 17 sequences, 30 frames per point (1 I + 29 P), fixed QP 22/27/32/37. BD-rate uses luma PSNR.

| Configuration | BD-rate vs full3 | Increment vs adaptive two-layer | CU32-only selected | Speed vs full3 |
|---|---:|---:|---:|---:|
| Forced CU32-only | +35.860% | — | 100% | 3.280x |
| Cascade, cutoff 89 | +1.542% | +0.042% | 15.707% | 1.385x |
| Cascade, cutoff 92 (recommended) | +1.500% | +0.002% | 6.425% | 1.397x |

For cutoff 92, every sequence is below +0.5% incremental BD-rate versus the existing adaptive two-layer selector; the worst is vidyo1 at +0.080%.

- `cutoff92_vs_full3/`: recommended cascade against complete 32/16/8 search.
- `cutoff92_vs_two_layer/`: incremental effect of the CU32-only gate.
- `cutoff89_*`: more aggressive alternative.
- `forced_only32_vs_full3/`: boundary-control experiment.
- `classb_threshold_sweep/`: Class B threshold selection summary.

See `docs/P_INTER_ONLY32_TRAINING_RESULTS_zh.md` for the algorithm, training format, validation, and migration guide.
