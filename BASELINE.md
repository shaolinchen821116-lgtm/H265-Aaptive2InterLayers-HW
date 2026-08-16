# Baseline identification

The overlay was prepared against the local x265 source snapshot named `x265-master.zip` used for the experiments. The archive did not expose a reliable upstream Git commit identifier, so the archive digest is recorded instead:

```text
SHA-256  9EF751CE01BE74A89DD050E3EDFC3DFE5ECF548DDA021E934DE434D93D89A754
```

For exact reproduction, apply `x265_overlay/` to the same snapshot. Applying it to a different x265 revision may require a manual three-way merge, especially in `analysis.cpp`, `search.cpp`, `param.cpp`, and the public parameter structure in `x265.h`.
