# ONLY32 保守门控研究包

本研究在完整三层或原三选二之前增加 ONLY32 出口。输入只包含 QP 和 32x32 原始 8-bit Y；U/V 不参与判断。

## 入口

- `train_only32_gate.py`：Class B 训练、A/C/E 独立验证、阈值扫描。
- `export_tree_header.py`：导出 x265 C++ 或 C99 整数比较树。
- `analyze_only32_results.py`：计算三段/10 点 BD-rate 和 ONLY32 选中概率。
- `verify_portable_all.py`：逐 CTU 对比 C99 与 x265 分值/决策。
- `../../../results/intra/only32/model/`：深度 6 模型和阈值指标。
- `../../../results/intra/only32/`：实际编码 BD-rate 与选中率结果。
- `portable_c/`：三出口 C99 API；推荐阈值 94。

## 两种部署口径

`gate3294`：分值 >=94 时只搜索 Intra32，否则回退完整 32/16/8。用于隔离验证新增门控损失。

`cascade3294`：分值 >=94 时只搜索 Intra32，否则回到原高两层/低两层选择器。用于最终级联部署。

## 关键结果

- 纯门控 17 序列 10 点平均 BD-rate：+0.0209%；最差单序列 +0.3735%。
- 纯门控完整 CTU 加权 ONLY32 选中率：9.506%；标签精度 96.87%。
- 级联相对原三选二的增量 BD-rate：+0.0499%。
- 级联相对完整三层 anchor 的总 BD-rate：+1.0273%，因此“最终级联总损失 <0.5%”未达到；超出部分主要来自原三选二基线，而非新增 ONLY32 门控。
- C99 在 17 序列、10 个正式 QP、247,400 个完整 CTU 上与 x265 零差异。

## 运行

```text
python train_only32_gate.py --results WORK_RESULTS --output WORK_MODEL --depth 6 --min-leaf 500
python export_tree_header.py --model WORK_MODEL/only32_tree.json --out intra_only32_gate.h
python analyze_only32_results.py --results WORK_RESULTS --output WORK_REPORT
python verify_portable_all.py --exe VERIFY_ONLY32_EXE --manifest MANIFEST --results WORK_RESULTS
```
