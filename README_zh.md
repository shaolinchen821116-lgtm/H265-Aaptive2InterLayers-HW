# 面向硬件的 x265 多级运动搜索与自适应两层选择

本仓库整理了基于 x265 的硬件友好型 HEVC 编码研究成果。主线是在 P 帧中实现 `PME → IME → FME` 三级搜索，并对 32×32、16×16、8×8 的正方形 CU/PU/TU 做层级对齐；FME 结果进入 AMVP 编码，再与 Merge 模式进行原有 RDO 比较。在此基础上，用小型整数决策树在每个 CU32 上选择高两层（32/16）或低两层（16/8）。

## 仓库内容

- `x265_overlay/`：相对基线 x265 的完整覆盖文件，可直接合入同一源代码快照。
- `experiments/inter_hw_hme/`：ABCE 批量编码、BD-rate、PME 参数扫描、P 帧选层采数和训练脚本。
- `experiments/inter_hw_hme/portable_c/`：独立 C 参考模型及单元测试，便于 RTL/其他 H.265 平台对拍。
- `results/inter/`：精简后的汇总 CSV、决策树 JSON/文本；不包含 YUV、码流和大体积逐 CTU 数据。
- `experiments/intra_2layer/`、`results/intra/`：前期 Intra 32/16/8 三层选两层及 `only32` 保守门控研究。
- `docs/`：设计说明、复现实验说明、结果摘要和最终 DOCX 报告。

## 核心结论

测试集为 HEVC Class A/B/C/E 共 17 个序列，每个点编码 30 帧（1I+29P），`medium + zerolatency`、固定 QP、单参考、无 B 帧、CTU32、最小 CU8、关闭 Rect/AMP，QP 为 22/27/32/37。

- 自适应 PME 相对原生 x265：17 序列平均 Y-PSNR BD-rate 为 **−0.973%**，各序列均未出现正损失。
- 旧 PME 在 BasketballDrive 上为 **+2.028%**；优化后为 **−0.565%**。
- 自适应两层相对完整 32/16/8 三层硬件 HME：平均 **+1.498% BD-rate**，实测速度比 **1.397×**，高/低两层选择比例为 **52.214% / 47.786%**。
- “优化 PME + 自适应两层”相对原生 x265：平均 **+0.510% BD-rate**。
- 决策树训练样本 448,800 个 CU32；留一序列交叉验证正确率 **73.264%**。

这些结论来自短序列研究，速度比受主机负载影响；流片或产品定型前，应增加帧数、运动类型、分辨率与目标 QP，并在目标带宽/流水线约束下复核。

## 快速使用

先查看 [基线说明](BASELINE.md)。在 Windows PowerShell 中将覆盖文件合入干净的 x265 源码树：

```powershell
.\tools\apply_overlay.ps1 -X265Root D:\path\to\x265
```

脚本默认会在目标 x265 根目录创建带时间戳的备份。随后按 x265 原有方式构建。示例运行：

```powershell
python .\experiments\inter_hw_hme\run_classb.py `
  --encoder D:\path\to\x265\build\inter-hw-ninja\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest_abce.csv `
  --frames 30 --qps 22,27,32,37 --modes baseline,hw `
  --pme-cost-mode 1 --pme-rate-scale 256 `
  --pme-texture 8,24 --pme-attractor 1 `
  --output D:\work\abce_adaptive_30f
```

请先编辑 manifest 中的 `path` 列，使其指向本机 YUV。完整步骤见 [复现说明](docs/REPRODUCE_zh.md)，算法与精度换算见 [设计说明](docs/DESIGN_zh.md)，逐序列结果见 [结果摘要](docs/RESULTS_zh.md)。

## 主要控制接口

- `--hw-hme`：启用三级硬件友好搜索。
- `--hw-hme-pme-range 32,28`：1/4 分辨率图上的 PME 半径。
- `--hw-hme-ime-range 12,12`：全分辨率整数像素 IME 半径。
- `--hw-hme-pme-cost-mode 0|1`：旧乘法代价或自适应加法代价。
- `--hw-hme-pme-rate-scale 256`：PME 码率项 Q8 缩放。
- `--hw-hme-pme-texture 8,24`：平均梯度的两级阈值；三档权重在参考实现中为 256/160/96。
- `--hw-hme-pme-attractor 0|1|2`：零向量、AMVP 或两者取小。
- `--hw-hme-inter-layers 0..4`：完整三层/高两层/低两层/自适应/标签采集。
- `--hw-hme-layer-cutoff 50`：整数树的低两层概率阈值。
- `--hw-hme-stats`：输出各级搜索与选层统计。

## 许可与数据

`x265_overlay/` 含有修改后的 x265 文件，适用 x265/GPL 条款；详见 [NOTICE.md](NOTICE.md) 和 [x265-COPYING.txt](third_party/x265-COPYING.txt)。测试序列不随仓库分发。
