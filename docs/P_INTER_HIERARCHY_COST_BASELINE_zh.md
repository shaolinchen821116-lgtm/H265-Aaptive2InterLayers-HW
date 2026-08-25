# P 帧层次 IME Cost-only 两层判决报告

## 1. 目的与状态

本报告只评估用户指定的层次代价规则，不混入纹理、SAD 离散度、MV 一致性或训练树修正。它是后续“cost 为主、其他特征为辅”模型的独立基线，对应 `--hw-hme-inter-layers 9`。

结论：规则能够较好避免漏选 CU8，但明显偏向低两层；Class B 真实 30 帧平均 BD-rate 为 **+1.659%**，尚不能替代 mode 8 的多尺度 CART（Class B +1.050%）。

## 2. 精确定义

x265 运动估计使用的 `x265_lambda_tab[QP]` 是 sqrt(lambda)。实现把它量化成 Q8：

```text
sqrt_lambda_q8 = round(x265_lambda_tab[QP] * 256)
rate(bits)      = (sqrt_lambda_q8 * bits + 128) >> 8
```

CU32 代价：

```text
J32 = SAD32 + rate(MVD_bits32) + rate(split_bits32)
split_bits32 = 1
```

每个 CU8：

```text
J8[k] = SAD8[k] + rate(MVD_bits8[k])
```

对每个 CU16 所覆盖的四个 CU8，取最小值并乘 4；四个 CU16 区域求和，再加入层次 split bits：

```text
group16[g] = 4 * min(J8[4*g + 0 ... 4*g + 3])
J8_to_32   = group16[0] + group16[1] + group16[2] + group16[3]
              + rate(split_bits8_to_32)
split_bits8_to_32 = 1 + 4 = 5
```

判决严格遵循：

```text
if J32 < J8_to_32: HIGH2(CU32/CU16)
else:              LOW2(CU16/CU8)
```

三个尺度使用同一参考索引和 CU32 AMVP；PME 仍在 1/4 分辨率图上搜索，乘 4 对齐到 IME 全像素起点。子块探测只执行 PME/IME，不执行 FME。

## 3. 日志格式

mode 7 完整三层标签采集新增一行：

```text
INTERLAYERCOST,
ctu,x,y,valid,qp,sqrt_lambda_q8,
sad32,mvd_bits32,J32,split_bits32,
group16_0,group16_1,group16_2,group16_3,
split_bits8_to_32,J8_to_32,selected,
leaf32,leaf16,leaf8,oracle
```

`oracle=low` 表示完整 32/16/8 RDO 最终出现 CU8 叶节点，否则为 `high`。边缘不完整 CTU 的 `valid=0`，不进入统计。

QP32 的一个实际样本：

```text
sqrt_lambda_q8 = 2580
SAD32 = 2901
MVD_bits32 = 26
J32 = 2901 + round(2580*26/256) + round(2580*1/256) = 3173
group16 = 900, 912, 960, 1048
J8_to_32 = 900+912+960+1048+round(2580*5/256) = 3870
result = HIGH2
```

## 4. 分类仿真

Class B 5 个序列、12 帧、QP22/27/32/37：

| 指标 | 结果 |
|---|---:|
| 原始记录 | 448,800 |
| 有效完整 CTU | 435,600 |
| 边缘无效 CTU | 13,200 |
| 字段错误 | 0 |
| oracle LOW | 35.894% |
| 规则选择 LOW | 58.073% |
| 正确率 | 67.794% |
| 平衡正确率 | 71.808% |
| LOW recall | 86.034% |
| 误删 CU8（oracle LOW→HIGH） | 13.966% |
| 误选低层（oracle HIGH→LOW） | 42.418% |
| 平均 `J8_to_32/J32` | 0.9945 |

逐序列正确率：BQTerrace 77.132%、BasketballDrive 74.603%、Cactus 49.721%、Kimono1 59.413%、ParkScene 78.103%。Cactus 的低层选择达到 78.267%，是最明显的过度 LOW 偏置。

## 5. 真实 RD 结果

条件：Class B、1I+29P、QP22/27/32/37、medium、zerolatency、定 QP、单参考、CTU32、正方形 PU、I 帧三层全部开放；anchor 为相同硬件 HME 的完整三层。

| 序列 | Y-PSNR BD-rate |
|---|---:|
| BQTerrace | +0.956% |
| BasketballDrive | +1.849% |
| Cactus | +1.438% |
| Kimono1 | +2.837% |
| ParkScene | +1.216% |
| Class B 平均 | **+1.659%** |

## 6. 原因分析

`4 * min(J8)` 是一个有意的低复杂度估计，但它假设一个 CU16 内四个 8×8 都可以复用“最好那个 8×8”的代价。当四个子块的纹理、遮挡或 MV 不一致时，该估计会系统性低估低层路径：

- 一个非常容易预测的 CU8 会掩盖另外三个高代价 CU8；
- MVD bits 也随最小值一起被复制，无法体现四个独立 MV 的总代价；
- 5 个 split bits 相对像素 SAD/MVD 总成本较小，无法抵消这种低估；
- `J32` 与 `J8_to_32` 平均比值接近 1，轻微估计误差即可翻转大量 CTU。

因此它适合作为主判据/根分支，但不适合作为唯一判据。

## 7. 下一阶段训练设计

`train_inter_hybrid_cost_tree.py` 强制把 `J8_to_32 <= J32` 作为决策树根节点，再在两侧分别训练整数子树。新增 cost 特征包括：

- cost 基础方向；
- 无除法的 cost 比值档位（3/4、7/8、1、9/8、5/4、3/2）；
- J32、J8_to_32、绝对差，统一为 Q8 每像素；
- 四个 group16 的均值、极差、MAD；
- 根 MVD bits 与 sqrt(lambda)_Q8。

子树再使用已有的 CU8 activity/SAD 极差、16→8 SAD gain、MV parent/root 一致性等整数特征学习是否推翻 cost-only 结论。模型仍限制为比较、分支、加法、绝对值和移位。

## 8. 复现命令

标签采集：

```powershell
python .\experiments\inter_hw_hme\run_classb.py `
  --encoder .\x265\build\hw\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest.csv `
  --frames 12 --qps 22,27,32,37 --modes hw `
  --layer-mode 7 --output D:\work\classb_cost_collect
```

cost-only 分类统计：

```powershell
python .\experiments\inter_hw_hme\analyze_inter_hierarchy_cost.py `
  D:\work\classb_cost_collect\runs.csv `
  --output D:\work\classb_cost_collect\cost_accuracy.csv
```

cost-rooted 混合树训练：

```powershell
python .\experiments\inter_hw_hme\train_inter_hybrid_cost_tree.py `
  D:\work\classb_cost_collect\runs.csv --output D:\work\hybrid_model `
  --max-depth 7 --min-leaf 256 --low-weight 1.5 `
  --recommended-cutoff 45
```
