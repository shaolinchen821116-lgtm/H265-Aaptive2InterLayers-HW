# Inter HME 实验目录

本目录提供四类脚本：

1. `run_classb.py`：运行原生 anchor 或硬件 HME，记录 x265 CSV、日志、JSON 元数据和总表 `runs.csv`。
2. `analyze_results.py`：由匹配的 QP 点生成逐点比较、逐序列和逐 Class BD-rate。
3. `run_pme_sweep.py`：扫描 PME 码率缩放和 attractor 组合。
4. `train_inter_layer_tree.py`、`run_inter_layer_sweep.py`：由完整三层 RDO 标签训练整数树，并比较高两层、低两层、自适应两层和 CU32-only 级联。
5. `train_inter_only32_gate.py`：训练深度 6 的保守 CU32-only CART，同时导出 JSON、C++ 和 ISO C99 模型。
6. `evaluate_inter_only32_gate.py`：在不重训模型的条件下，对独立 mode-4 日志计算触发精度、召回率和误触发率。
7. `train_inter_multiscale_tree.py`、`evaluate_inter_multiscale_tree.py`：训练/独立验证 29 维多尺度代价敏感 CART。
8. `analyze_inter_hierarchy_cost.py`：分析 `J32` 与 `4×min(J8)` 层次 cost-only 规则。
9. `train_inter_hybrid_cost_tree.py`：强制层次 cost 为根节点，再用纹理/SAD/MV 一致性训练修正子树。

`sequence_manifest.csv` 是 Class B 示例，`sequence_manifest_abce.csv` 是 17 序列示例。二者只描述数据，不包含 YUV；运行前修改 `path` 列。

便携 C 参考实现位于 `portable_c/`。它用于验证精度换算、搜索窗口、代价函数、AMVP attractor 和三级选层，可独立于 x265 编译。`inter_only32_gate_model.h` 由训练脚本生成，不应手工编辑。

P 帧模式：`0` 完整三层；`1` 强制高两层；`2` 强制低两层；`3` 旧版 CU32 自适应；`4` 旧标签；`5` CU32-only；`6` CU32-only 级联；`7` 多尺度完整三层标签；`8` 多尺度 CART；`9` 层次 cost-only。当前高/低两层推荐为 mode 8、cutoff 45；mode 9 是研究基线。

详细命令见仓库根目录的 `docs/REPRODUCE_zh.md`、`docs/P_INTER_MULTISCALE_2LAYER_OPTIMIZATION_zh.md` 和 `docs/P_INTER_HIERARCHY_COST_BASELINE_zh.md`。
