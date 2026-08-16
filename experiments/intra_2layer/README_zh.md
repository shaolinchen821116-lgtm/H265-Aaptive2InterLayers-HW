# x265 Intra 32/16/8 三层选两层研究

本目录给出只依赖当前 32×32 CTU 原始亮度像素和 QP 的两层选择器，以及完整的拟合、编码和 BD-rate 分析流程。

## 已实现的模式

- `all`：anchor，完整搜索 Intra32/Intra16/Intra8。
- `high`：只允许 Intra32/Intra16。
- `low`：只允许 Intra16/Intra8。
- `adaptive`：按原始像素和 QP，在高两层与低两层之间选择；最终默认风险阈值为 40。
- `adaptiveNN`：实验用阈值，例如 `adaptive30`、`adaptive40`。

所有模式都关闭 Intra4，且让 Intra TU 尺寸等于 CU 尺寸，从而关闭 intra RQT。选择器使用的是“像素相对自身块均值的 SAD”，不是 HEVC 帧内预测残差 SAD。

## 文件

- `../../x265_overlay/source/encoder/intra_layer_selector.h`：最终整数决策树和特征提取。
- `../../x265_overlay/source/encoder/analysis.cpp`：CTU 决策、层限制和统计输出接入。
- `../../x265_overlay/source/common/cudata.cpp`：实验模式下关闭 intra RQT。
- `build_research.bat`：构建研究版 x265。
- `run_experiments.py`：单帧 Class B 编码批处理。
- `fit_selector.py`：QP10～51 的阈值与浅层树拟合。
- `analyze_results.py`：BD-rate 与 RDO 判断正确率计算。
- `run_full_study.bat`：从构建、全 QP anchor 扫描到报告点编码的一键脚本。
- `REPORT_zh.md`：方案、实验方法、逐序列结果和移植说明。

## 复现实验

需要 Python 3 和 NumPy。构建和数据路径都由命令行显式传入。

```bat
experiments\intra_2layer\run_full_study.bat X265_SOURCE_ROOT YUV_ROOT OUTPUT_ROOT
```

也可以只编码报告所需的 10 个 QP 点：

```bat
python experiments\intra_2layer\run_experiments.py ^
  --encoder X265_EXE --yuv-root YUV_ROOT --output OUTPUT_ROOT ^
  --qps 10 16 20 24 28 32 36 40 44 48 ^
  --modes all low adaptive40 --jobs 4
```

结果和汇总数据写入命令行指定的 `OUTPUT_ROOT`。详细跨平台训练流程见 `training/README_zh.md`。
