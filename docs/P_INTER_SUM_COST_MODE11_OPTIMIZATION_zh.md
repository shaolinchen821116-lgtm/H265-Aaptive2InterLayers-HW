# P帧原始CU8 Cost求和与多特征优化（mode 10/11）

## 结论

本轮针对旧公式 `4 × min(J8)` 容易过分选择 CU8 的问题，保留 mode 9 作为历史基线，并新增两个可复现模式：

- mode 10：四个 CU16 区域分别累加其四个原始 `J8`，最终使用全部 16 个 CU8 的原始 cost；
- mode 11：以修正后的 sum-cost 为决策树强制根节点，再用纹理、分层 SAD 收益、MV 一致性、QP 和 `sqrt(lambda)` 修正边界。

最终推荐 `--hw-hme-inter-layers 11 --hw-hme-layer-cutoff 50`。在 Class A/B/C/E 共 17 个序列、每点 30 帧（1I+29P）、QP 22/27/32/37 下，相对完整三层 P 帧 anchor 的平均 Y-PSNR BD-rate 为 **+0.273%**。上一版 mode 8 为 **+0.966%**，改善 **0.693 个百分点**（相对降低约 71.7%）。高/低两层选择比例为 **56.542% / 43.458%**。

纯 sum-cost mode 10 在 Class B 平均为 **+3.133%**，证明只把 `4×min` 改成求和会从“过选 CU8”变成“漏选 CU8”；必须增加多尺度特征修正。

## Cost定义

对每个 8×8 子块：

```text
J8[i] = SAD8[i] + ((sqrtLambdaQ8 * MVD_bits8[i] + 128) >> 8)
```

旧 mode 9：

```text
J8_old = splitRate(5 bits) + Σ(g=0..3) 4 × min(J8[4g..4g+3])
```

新 mode 10/11：

```text
J8_sum = splitRate(5 bits) + Σ(i=0..15) J8[i]
J32    = SAD32 + rate(MVD_bits32) + splitRate(1 bit)
```

`sqrtLambdaQ8` 直接取 x265 当前运动估计 lambda，故 QP 对码率项的影响被显式包含；QP 本身也是树特征。所有运行时运算均为整数加法、绝对值、比较、移位和常数分支。

## mode 11特征与判断

决策树输入为原 29 个多尺度特征加 11 个 cost 特征，共 40 维：

- 原 29 维：QP；CU32/CU16/CU8 SAD统计和分层收益；activity纹理；CU16/CU8相对父块、根块的MV差异和span；搜索窗边界计数；
- 新 11 维：sum-cost初判、cost比例分箱、J32/J8_sum归一值与差值、四个CU16区域sum-cost均值/极差/MAD、旧min-cost及其乐观偏差、`sqrtLambdaQ8`。

树的第一个节点强制使用 `J8_sum <= J32`，子树再纠正纯cost估计。最终训练树最重要的特征包括：sum-cost比例、sum-cost初判、CU16→CU8最大SAD收益、QP、CU8 SAD极差、CU32 MV幅度、CU8 activity极差和CU8 MV span。

## 训练数据与准确率

Class B 5个序列、12帧、QP 22/27/32/37：

- `INTERLAYERMS` 与 `INTERLAYERCOSTSUM` 各448,800行；
- 有效完整CU32为435,600个，边缘无效样本13,200个；
- 字段错误和未配对记录均为0；
- CART使用确定性1/4抽样108,900个样本拟合，`--sample-stride 1`可执行全量训练；
- 深度6、最小叶128、LOW权重1.5、按序列留一验证；
- 纯sum-cost：准确率69.180%，LOW recall 28.165%，低层选择15.185%；
- mode 11树、cutoff50：准确率73.810%，平衡准确率75.724%，LOW recall82.468%，低层选择49.440%（Class B留一分类验证）。

真实编码而不是分类准确率用于选择最终cutoff。cutoff55的ABCE平均为+0.611%；cutoff50降为+0.273%。

## 逐序列BD-rate

| Class | 序列 | mode11 cutoff50 |
|---|---|---:|
| A | PeopleOnStreet | -0.679% |
| A | Traffic | +0.317% |
| B | BasketballDrive | +0.691% |
| B | BQTerrace | -1.119% |
| B | Cactus | +0.626% |
| B | Kimono1 | +1.609% |
| B | ParkScene | +0.964% |
| C | BasketballDrill | +0.380% |
| C | BQMall | +0.151% |
| C | PartyScene | +0.036% |
| C | RaceHorses | -0.208% |
| E | FourPeople | +0.631% |
| E | Johnny | -0.276% |
| E | KristenAndSara | +0.640% |
| E | vidyo1 | +0.191% |
| E | vidyo3 | +0.395% |
| E | vidyo4 | +0.298% |

类别平均：Class A -0.181%、Class B +0.554%、Class C +0.090%、Class E +0.313%；17序列算术平均 **+0.273%**。16/17个序列低于1%，Kimono1为唯一超过1%的序列，因此不能宣称逐序列全部小于1%。

## 复现命令

采集完整三层标签和新旧cost：

```powershell
python .\experiments\inter_hw_hme\run_classb.py `
  --encoder D:\path\to\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest.csv `
  --frames 12 --qps 22,27,32,37 --modes hw --layer-mode 7 `
  --output D:\work\classb_sumcost_collect
```

训练并导出C/C++头文件：

```powershell
python .\experiments\inter_hw_hme\train_inter_sum_cost_tree.py `
  D:\work\classb_sumcost_collect\runs.csv `
  --output D:\work\sum_cost_tree --max-depth 6 --min-leaf 128 `
  --low-weight 1.5 --sample-stride 4 --recommended-cutoff 50 `
  --cpp-header .\x265_overlay\source\encoder\inter_sum_cost_gate_model.h
```

最终编码：

```text
--hw-hme --hw-hme-inter-layers 11 --hw-hme-layer-cutoff 50
--hw-hme-pme-range 32,28 --hw-hme-ime-range 12,12
--hw-hme-pme-cost-mode 1 --hw-hme-pme-rate-scale 256
--hw-hme-pme-texture 8,24 --hw-hme-pme-attractor 1
```

I帧在代码中明确绕过P帧选层控制，intra32/intra16/intra8始终全开。

## 文件索引

- 运行时实现：`x265/source/encoder/inter_layer_selector.h`、`analysis.cpp`；
- 生成模型：`x265/source/encoder/inter_sum_cost_gate_model.h`；
- 训练脚本：`experiments/inter_hw_hme/train_inter_sum_cost_tree.py`；
- 训练结果：`results/inter/sum_cost_tree_classb/`；
- 纯cost实测：`results/inter/classb_sumcost_mode10_30f/`；
- 最终ABCE实测：`results/inter/abce_sumcost_adaptive_mode11_c50_30f/`。
