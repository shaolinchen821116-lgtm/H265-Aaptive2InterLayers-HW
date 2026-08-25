# 实验结果摘要

## 1. Inter 测试条件

- 序列：HEVC Class A/B/C/E，共 17 个。
- 帧数：每个编码点 30 帧，结构为 1 个 I 帧 + 29 个 P 帧。
- 码率点：固定 QP 22/27/32/37。
- 配置：`medium`、`zerolatency`、单参考、无 B 帧、CTU32、最小 CU8、关闭 Rect/AMP。
- 指标：按 Y-PSNR 计算四点 BD-rate；负数优于参考，正数表示码率损失。
- 速度：x265 日志中的实测编码速度比，只用于观察软件复杂度趋势。

“原生 anchor”是不启用本仓库 HW-HME 的 x265。“完整三层”启用优化 HW-HME，但仍搜索 32/16/8 三层；它是 P 帧选层实验的直接参考。

## 2. PME 优化结果

最终自适应 PME 相对原生 anchor 的结果如下：

| Class | 序列 | BD-rate (%) |
|---|---|---:|
| A | PeopleOnStreet | -1.392 |
| A | Traffic | -1.208 |
| B | BasketballDrive | -0.565 |
| B | BQTerrace | -1.940 |
| B | Cactus | -0.526 |
| B | Kimono1 | -0.131 |
| B | ParkScene | -0.398 |
| C | BasketballDrill | -1.537 |
| C | BQMall | -1.198 |
| C | PartyScene | -0.544 |
| C | RaceHorses | -1.380 |
| E | FourPeople | -0.566 |
| E | Johnny | -1.736 |
| E | KristenAndSara | -0.734 |
| E | vidyo1 | -1.073 |
| E | vidyo3 | -0.741 |
| E | vidyo4 | -0.876 |
| **全部** | **算术平均** | **-0.973** |

Class 平均分别为 A `−1.300%`、B `−0.712%`、C `−1.165%`、E `−0.954%`。17 个序列都没有出现正 BD-rate 损失，最接近零的是 Kimono1 `−0.131%`。

旧 PME 平均为 `−0.711%`，但 BasketballDrive 为 `+2.028%`。引入 QP lambda、纹理权重和 AMVP attractor 后，BasketballDrive 改善到 `−0.565%`，说明固定零 attractor 和乘法代价是运动序列风险的主要来源之一。

原始数值见：

- `results/inter/pme_legacy/`
- `results/inter/pme_adaptive/`
- `results/inter/pme_sweep/`

## 3. P 帧两层选择

相对优化 HW-HME 的完整 32/16/8 三层：

| 策略 | 平均 BD-rate | 最差序列 | 最差 BD-rate | 平均速度比 | 高/低选择率 |
|---|---:|---|---:|---:|---:|
| 强制高两层 32/16 | +10.378% | BQMall | +24.578% | 1.963× | 100% / 0% |
| 强制低两层 16/8 | +4.102% | KristenAndSara | +8.259% | 1.121× | 0% / 100% |
| 自适应树，cutoff 50 | **+1.498%** | KristenAndSara | **+2.356%** | **1.397×** | **52.214% / 47.786%** |

自适应树的逐序列 BD-rate：

| Class | 序列 | BD-rate (%) |
|---|---|---:|
| A | PeopleOnStreet | 1.425 |
| A | Traffic | 2.294 |
| B | BasketballDrive | 1.418 |
| B | BQTerrace | 0.956 |
| B | Cactus | 1.193 |
| B | Kimono1 | 1.765 |
| B | ParkScene | 1.788 |
| C | BasketballDrill | 1.429 |
| C | BQMall | 1.311 |
| C | PartyScene | 0.414 |
| C | RaceHorses | 0.958 |
| E | FourPeople | 1.469 |
| E | Johnny | 2.037 |
| E | KristenAndSara | 2.356 |
| E | vidyo1 | 1.584 |
| E | vidyo3 | 1.850 |
| E | vidyo4 | 1.219 |
| **全部** | **算术平均** | **1.498** |

优化 PME 的收益会抵消部分选层损失。“优化 PME + 自适应两层”相对原生 anchor 的平均 BD-rate 为 **+0.510%**；逐序列范围为 BQTerrace `−0.998%` 到 Kimono1 `+1.631%`。因此平均目标已小于 1%，但不能声称每个运动序列均小于 1%；需要针对 Kimono1、ParkScene、Traffic 等序列继续做风险门控或第三层回退。

原始数值见 `results/inter/layer_sweep/` 和 `results/inter/classb_layer_sweep/`。

### 3.1 P 帧高一层保守门控

在原自适应高两层/低两层之前增加 CU32-only 门控。最终采用深度 6 整数 CART 和 cutoff 92：

| 指标 | 结果 |
|---|---:|
| 相对完整三层平均 BD-rate | +1.500% |
| 相对原两层自适应增量 BD-rate | **+0.002%** |
| 17 序列中最差增量 | **+0.080%（vidyo1）** |
| 实际 CU32-only 率 | 6.425% |
| Class B 留一序列触发精度 | 92.841% |
| Class A/C/E 独立触发精度 | 93.390% |

强制 CU32-only 的平均损失为 +35.860%，最差 BQMall 为 +77.450%，所以该模式只用作边界对照。较激进 cutoff 89 的 CU32-only 率为 15.707%、平均增量为 +0.042%，但 vidyo1 增量达到 +0.784%；最终选择 cutoff 92 是为了控制逐序列最差风险。

完整训练、输入输出格式、流程图和逐序列表见 `P_INTER_ONLY32_TRAINING_RESULTS_zh.md`；精简结果见 `results/inter/only32_abce_30f/`。

## 4. 决策正确率

Class B 采集 448,800 个 CU32 样本，标签来自完整三层最终 RDO：

| 指标 | 结果 |
|---|---:|
| 原始 RDO 低两层标签率 | 37.779% |
| 树预测低两层率 | 49.577% |
| 留一序列交叉验证正确率 | 73.264% |
| 原低层样本误选高层率 | 19.770% |

“判断正确率”衡量结构标签一致性，不等同于 BD-rate。对于编码器而言，少量代价很高的误判可能比大量低风险误判更重要，所以发布阈值最终应同时受 BD-rate 和风险序列约束，而不是只追求分类准确率。

### 4.1 多尺度 mode 8 更新结果

新版使用 CU32、4 个 CU16 和 16 个 CU8 的 29 维整数特征，Class B 留一序列 cutoff 45 的正确率为 `77.731%`、平衡正确率为 `79.305%`、低层召回率为 `84.880%`。冻结 Class B 模型在 Class A/C/E 共 652,960 个独立样本上的正确率为 `84.834%`。

真实 30 帧 ABCE 测试中，mode 8 相对 P 帧完整三层平均 `+0.966% BD-rate`，Class A/B/C/E 分别为 `+1.010% / +1.050% / +0.767% / +1.014%`，最差为 Kimono1 `+1.606%`。I 帧 mode 0/8 第一帧码流 SHA-256 相同，确认 intra32/intra16/intra8 未被 P 帧门控裁剪。

### 4.2 层次 cost-only mode 9

用户指定公式使用 `J=SAD+sqrt(lambda)×MVD_bits`，四个 8×8 中取最小值乘 4 作为每个 16×16 的估计，并计入 1/5 个 split bits。Class B 435,600 个有效样本上，低层选择率 `58.073%`，而 RDO 低层标签率仅 `35.894%`；判断正确率 `67.794%`，真实高层误选低层 `42.418%`。真实 30 帧 Class B 平均 `+1.659% BD-rate`，最差 Kimono1 `+2.837%`。

这说明主要问题并非缺少 QPstep 或 sqrt(lambda)，而是 `4×min(J8)` 在同组四个 8×8 的 SAD、纹理或 MV 不一致时系统性低估低层路径。cost-rooted 候选树已经输出到 `results/inter/hybrid_cost_tree_classb/`，其 cutoff 45 Class B 留一正确率为 `76.294%`，仍低于 mode 8，且尚无真实 BD-rate，不能作为已发布结果。

## 5. Intra 研究归档

仓库同时保留了前期仅使用原始 32×32 YUV420 块和 QP 的 Intra 选层研究，以便同一硬件编码器复用特征提取结构。完整表格在 `results/intra/` 和 DOCX 报告中。

- A/C/E 验证集的两层自适应方案，10 个 QP 点总体平均 BD-rate 为 `+1.094%`。
- `only32` 保守门控 `gate3294` 在 ABCE 17 序列上的 10 点平均 BD-rate 为 `+0.021%`。
- `only32` 平均选中率为 `9.506%`，被选块相对完整 RDO 的正确率为 `96.866%`。

Intra 的 QP 分段仍按用户定义：低段 `{10,16,20,24}`、中段 `{24,28,32,36}`、高段 `{36,40,44,48}`，允许 24 和 36 在相邻段重复。

## 6. 结论边界

所有结果来自第一阶段短序列实验。30 帧足以暴露部分运动风险，但不能覆盖场景切换、长时参考漂移、噪声、摄像机大幅运动和所有硬件带宽限制。正式定型建议至少增加到 100–300 帧，并单独报告随机访问/低延迟、不同参考数、10-bit 和目标平台功耗/带宽。
