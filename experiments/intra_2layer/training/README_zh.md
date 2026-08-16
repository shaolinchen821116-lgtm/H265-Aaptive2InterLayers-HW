# Intra32/16/8 两层选择决策树复现包

## 1. 环境

- 8-bit I420/YUV420 原始序列。
- 带 `INTRA2STAT` 插桩的 x265 研究版本。
- Python 3.9+；安装 `requirements.txt` 中的 NumPy。
- C99 编译器用于验证导出的整数树。

## 2. 目录与关键入口

- `sequence_manifest_example.csv`：跨平台序列清单模板。
- `collect_anchor_stats.py`：运行完整三层 anchor，采集 CTU 标签和特征。
- `prepare_dataset.py`：字段检查、边界 CTU 排除、训练/验证集输出和 SHA-256。
- `train_two_layer_tree.py`：确定性 CART 训练及分类指标输出。
- `export_two_layer_c.py`：模型 JSON 转整数 C 比较树。
- `run_pipeline.bat`：Windows 一键示例。
- `portable_c/`：本研究使用的 C99 特征提取、决策和验证程序。

## 3. 最短复现命令

```text
python collect_anchor_stats.py --manifest sequence_manifest.csv --x265 /path/to/x265 --output work/raw --qps 10:51 --jobs 1
python prepare_dataset.py --manifest sequence_manifest.csv --stats-root work/raw --output work/dataset
python train_two_layer_tree.py --train work/dataset/train.csv --validation work/dataset/validation.csv --output work/model --depth 4 --min-leaf 800 --cutoffs 30 35 40 45 50
python export_two_layer_c.py --model work/model/two_layer_tree.json --output work/model/two_layer_tree_generated.inc
```

训练后必须把候选阈值集成到编码器，使用实际码流和 Y-PSNR 计算 BD-rate；不能只按分类正确率选阈值。本研究最终采用 LOW_SCORE >= 40。

## 4. 输入和输出

清单输入列：`sequence,class,path,width,height,fps,split`。

每个 CTU 的原始统计列：`mode,ctu_addr,x,y,qp,selected,oracle,leaf32,leaf16,leaf8,sad32,sad16,sad8,grad_h,grad_v,laplacian,edge4,edge8,edge16,edge32,qstep_q8,high_cost_q8,low_cost_q8,rd_cost[,only32_score]`。

标签规则：`leaf32>0 -> high`；否则 `leaf8>0 -> low`；全为 16x16 时为 `both`。`both` 在训练分类损失中排除，在总体正确率中视为高/低均正确。

关键输出：`train.csv`、`validation.csv`、`dataset_report.json`、`two_layer_tree.json`、`classification_metrics.csv` 和生成的 C include。

## 5. 复现纪律

保持编码配置、第一帧、QP 范围、位深、边界处理和特征公式一致。训练集与验证集必须按序列隔离，不能随机打散 CTU 后再划分。最终记录模型 JSON、阈值、数据 SHA-256、编译器版本和 x265 代码版本。
