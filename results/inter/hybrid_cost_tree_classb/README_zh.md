# cost-rooted 混合树：Class B 训练产物

本目录保存 `train_inter_hybrid_cost_tree.py` 在 Class B mode 7 数据上的候选训练结果。模型把用户指定的层次 cost 判决 `J32 < J8_to_32` 固定为根节点，再在根节点两侧分别使用 QP、cost 裕量、SAD、纹理活动度和 MV 一致性训练修正子树。

训练配置：最大深度 7、最小叶节点 256、低层标签权重 1.5。按序列留一交叉验证、cutoff 45 的结果为：有效样本 435,600，准确率 76.294%，平衡准确率 78.137%，低层召回率 84.668%，真实低层误选高层 15.332%。这低于当前 mode 8 在相同 Class B 数据上的 77.731% 准确率，因此只能视为训练候选，尚未集成为新的运行 mode，也没有真实 BD-rate 结论。

文件说明：

- `inter_hybrid_tree.json` / `.txt`：机器可读和人工可读树。
- `inter_hybrid_cost_gate_model.h`：自动导出的整数 C/C++ 头文件。
- `inter_hybrid_thresholds_cv.csv`：不同 cutoff 的总体交叉验证。
- `inter_hybrid_sequence_cv.csv`：逐序列留一结果。
- `inter_hybrid_feature_usage.csv`：分裂次数和加权 Gini 收益。

复现命令：

```powershell
python .\experiments\inter_hw_hme\train_inter_hybrid_cost_tree.py `
  D:\work\classb_mode7\runs.csv `
  --output D:\work\hybrid_cost_tree `
  --max-depth 7 --min-leaf 256 --low-weight 1.5 `
  --recommended-cutoff 45
```

候选树若要替换 mode 8，必须先完成 A/C/E 固定模型独立验证，再编入 x265 运行 30 帧和 100–300 帧真实 BD-rate。不能仅凭本目录的分类指标发布。
