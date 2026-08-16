# Inter HME 实验目录

本目录提供四类脚本：

1. `run_classb.py`：运行原生 anchor 或硬件 HME，记录 x265 CSV、日志、JSON 元数据和总表 `runs.csv`。
2. `analyze_results.py`：由匹配的 QP 点生成逐点比较、逐序列和逐 Class BD-rate。
3. `run_pme_sweep.py`：扫描 PME 码率缩放和 attractor 组合。
4. `train_inter_layer_tree.py`、`run_inter_layer_sweep.py`：由完整三层 RDO 标签训练整数树，并比较高两层、低两层和自适应两层。

`sequence_manifest.csv` 是 Class B 示例，`sequence_manifest_abce.csv` 是 17 序列示例。二者只描述数据，不包含 YUV；运行前修改 `path` 列。

便携 C 参考实现位于 `portable_c/`。它用于验证精度换算、搜索窗口、代价函数和 AMVP attractor 选择，可独立于 x265 编译。

详细命令见仓库根目录的 `docs/REPRODUCE_zh.md`。
