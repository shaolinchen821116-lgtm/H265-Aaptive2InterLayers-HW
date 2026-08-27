# 构建、实验与训练复现说明

## 1. 准备环境

需要：兼容的 x265 源码、CMake、C/C++ 编译器、Ninja（可替换为其他 CMake 生成器）、Python 3.9+，以及合法获得的 8-bit I420/YUV420 测试序列。仓库不分发测试媒体。

覆盖文件对应的本地基线压缩包 SHA-256 记录在 `BASELINE.md`。若使用不同 x265 版本，应把 `x265_overlay/` 当作移植参考，逐文件三方合并，不应直接假定 ABI 和内部类结构一致。

## 2. 应用 x265 覆盖文件

建议从干净源码树开始：

```powershell
git clone https://bitbucket.org/multicoreware/x265_git.git D:\work\x265
.\tools\apply_overlay.ps1 -X265Root D:\work\x265
```

脚本验证目标包含 `source/x265.h`，并在覆盖前将已有文件备份到目标根目录的 `.hw-hme-backup-时间戳`。新增和修改文件清单可直接通过 `x265_overlay/` 查看。

若本机 PowerShell 执行策略阻止 `.ps1`，可使用：`powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\apply_overlay.ps1 -X265Root D:\work\x265`。

## 3. 构建

Windows 下先打开 Visual Studio Developer Command Prompt：

```bat
experiments\inter_hw_hme\build_hw_hme.bat D:\work\x265
```

等效 CMake 命令：

```powershell
cmake -S D:\work\x265\source -B D:\work\x265\build\inter-hw-ninja -G Ninja `
  -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=OFF -DENABLE_CLI=ON
cmake --build D:\work\x265\build\inter-hw-ninja -j 8
```

构建后先检查帮助中是否出现 `--hw-hme`、`--hw-hme-pme-cost-mode` 和 `--hw-hme-inter-layers`。

## 4. 快速冒烟测试

```bat
experiments\inter_hw_hme\run_smoke.bat ^
  D:\work\x265\build\inter-hw-ninja\x265.exe ^
  D:\yuv_data\yuv_hevc\ClassB\BasketballDrive_1920x1080_50.yuv ^
  D:\work\smoke
```

日志末尾应出现 `HW-HME summary`。启用自适应选层时还应出现 `HW-inter-layer summary`。冒烟测试只验证控制流和候选计数，不用于 BD-rate 结论。

## 5. 序列清单格式

Inter 脚本输入 CSV：

```text
class,name,path,width,height,fps
ClassB,BasketballDrive,D:/data/ClassB/BasketballDrive_1920x1080_50.yuv,1920,1080,50
```

仓库提供 `experiments/inter_hw_hme/sequence_manifest.csv` 和 `sequence_manifest_abce.csv` 示例。修改 `path` 列即可；文件路径可以是绝对路径，Windows 上建议在 CSV 中使用 `/`。

## 6. 复现原生 anchor 与最终 PME

```powershell
python .\experiments\inter_hw_hme\run_classb.py `
  --encoder D:\work\x265\build\inter-hw-ninja\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest_abce.csv `
  --frames 30 --qps 22,27,32,37 `
  --modes baseline,hw `
  --pme-cost-mode 1 --pme-rate-scale 256 `
  --pme-texture 8,24 --pme-attractor 1 `
  --layer-mode 0 `
  --output D:\work\results\abce_adaptive_30f

python .\experiments\inter_hw_hme\analyze_results.py `
  D:\work\results\abce_adaptive_30f\runs.csv
```

每个编码点生成 `.hevc`、x265 `.csv`、合并日志和 `.json` 元数据；目录总表为 `runs.csv`。分析阶段输出：

- `per_qp_comparison.csv`：匹配 QP 的码率、Y-PSNR、速度和模式统计。
- `bd_rate_summary.csv`：逐序列四点 BD-rate。
- `class_bd_rate_summary.csv`：逐 Class 算术平均和最差序列。
- `report.md`：简短文本摘要。

重新运行默认复用已有 JSON；改变参数后应换输出目录或加 `--force`。

## 7. PME 参数扫描

先有一份包含原生 `baseline` 行的 anchor `runs.csv`，再运行：

```powershell
python .\experiments\inter_hw_hme\run_pme_sweep.py `
  --encoder D:\work\x265\build\inter-hw-ninja\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest_abce.csv `
  --anchor-runs D:\work\results\anchor\runs.csv `
  --sequences BasketballDrive,Kimono1,RaceHorses,Traffic `
  --frames 30 --qps 22,27,32,37 `
  --variants 1:0:1,1:64:1,1:128:1,1:256:1,1:128:2 `
  --output D:\work\results\pme_sweep
```

`variants` 的三元组为 `cost_mode:rate_scale_q8:attractor`。关键输出为 `pme_sweep_summary.csv` 和 `pme_sweep_detail.csv`。扫描集必须包含明显运动、复杂纹理和平坦区域，不能只在静态序列上选参数。

## 8. P 帧决策树的完整训练过程

### 8.1 数据采集

模式 4 运行完整三层 RDO，同时输出每个 CU32 的 `INTERLAYERSTAT`：

```powershell
python .\experiments\inter_hw_hme\run_classb.py `
  --encoder D:\work\x265\build\inter-hw-ninja\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest.csv `
  --frames 12 --qps 22,27,32,37 --modes hw `
  --pme-cost-mode 1 --pme-rate-scale 256 `
  --pme-texture 8,24 --pme-attractor 1 `
  --layer-mode 4 `
  --output D:\work\results\classb_layer_collect
```

每条训练记录至少包含：序列、帧号、CTU 坐标、QP、PME MV、IME 中心和 MV、IME SAD、AMVP、纹理等级、边界标志以及完整 RDO 标签。训练脚本从 `runs.csv` 指向的日志抽取记录，因此移动目录后要保持日志路径有效，或在移动前完成训练。

### 8.2 训练与留一序列验证

```powershell
python .\experiments\inter_hw_hme\train_inter_layer_tree.py `
  D:\work\results\classb_layer_collect\runs.csv `
  --max-depth 4 --min-leaf 512 --low-weight 2 --cutoff 0.50 `
  --output D:\work\results\classb_layer_tree
```

训练/验证按“序列”划分，不能把同一序列 CTU 随机分散到训练和验证中。脚本逐次留出一个序列，输出 `inter_layer_cv.csv`；随后使用全部样本训练最终树，输出 `inter_layer_tree.json` 和便于移植的 `inter_layer_tree.txt`。

关键检查项：样本总数、每序列样本数、RDO 高/低标签率、预测高/低率、总体准确率、低→高和高→低两种错误率。阈值选择必须再经真实码流 BD-rate 验证，不能只看分类准确率。

### 8.3 高两层、低两层、自适应对比

```powershell
python .\experiments\inter_hw_hme\run_inter_layer_sweep.py `
  --encoder D:\work\x265\build\inter-hw-ninja\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest_abce.csv `
  --anchor-runs D:\work\results\abce_adaptive_30f\runs.csv `
  --anchor-mode hw --frames 30 --qps 22,27,32,37 `
  --variants 1:50:92,2:50:92,3:50:92 `
  --output D:\work\results\abce_inter_layer_sweep
```

`variants` 为 `layer_mode:two_layer_cutoff:only32_cutoff`。前 0..3 模式不使用第三项，但仍保留该字段以统一批量命令。输出 `inter_layer_sweep_summary.csv` 和 `inter_layer_sweep_detail.csv`，同时每个子目录保留完整逐序列 BD-rate。

### 8.4 CU32-only 高一层门控

mode 4 的同一份完整 RDO 日志也可用于 CU32-only 训练，正标签定义为 `leaf32>0`：

```powershell
python .\experiments\inter_hw_hme\train_inter_only32_gate.py `
  D:\work\results\classb_layer_collect\runs.csv `
  --output .\results\inter\only32_classb_train `
  --max-depth 6 --min-leaf 512 --recommended-cutoff 92 `
  --cpp-header .\x265_overlay\source\encoder\inter_only32_gate_model.h `
  --portable-header .\experiments\inter_hw_hme\portable_c\inter_only32_gate_model.h
```

固定模型的独立验证使用 `evaluate_inter_only32_gate.py`。正式编码使用 `--hw-hme-inter-layers 6 --hw-hme-layer-cutoff 50 --hw-hme-only32-cutoff 92`。完整字段定义、阈值选择原则和 ABCE 结果见 `P_INTER_ONLY32_TRAINING_RESULTS_zh.md`。

## 9. 便携 C 验证

```powershell
cmake -S .\experiments\inter_hw_hme\portable_c `
  -B .\build\portable-c
cmake --build .\build\portable-c --config Release
ctest --test-dir .\build\portable-c -C Release --output-on-failure
```

参考模型的 `hw_hme_config_default()` 与最终 x265 参数一致。平台必须实现三个回调：准确的 MVD bit 估计、QP 加权 MVD cost、qpel 插值 SAD。默认 Exp-Golomb bits 只适合早期原型，不替代目标编码器真实 CABAC 上下文模型。

## 10. Intra 复现入口

Intra 决策树跨平台训练流程在 `experiments/intra_2layer/training/README_zh.md`。最短流程为：完整三层 anchor 采集 → 数据集校验/按序列分割 → 深度受限 CART → 导出整数 C → 真实编码 BD-rate 复核。公开仓库不含 49–76 MB 的训练 CSV，但保留模型、指标、采集脚本和数据格式。

单帧 ABCE 回归脚本已改为显式路径：

```powershell
python .\experiments\intra_2layer\run_experiments.py `
  --encoder D:\work\x265\build\intra2-ninja\x265.exe `
  --yuv-root D:\yuv_data\yuv_hevc `
  --output D:\work\results\intra `
  --qps 10 16 20 24 28 32 36 40 44 48 `
  --modes all low adaptive40 --jobs 4
```

## 11. 复现记录建议

每次实验固定记录：x265 基线提交或归档 SHA-256、覆盖代码提交、编译器和构建选项、位深、序列文件 SHA-256、帧数、QP、命令行、决策树 JSON、原始 `runs.csv` 与最终汇总。BD-rate 比较双方必须使用完全相同的输入帧和编码约束。

## 12. 完整源码直接构建

本仓库的 `x265/` 已是合入研究改动的完整源码，不必先准备外部源码树：

```powershell
cmake -S .\x265\source -B .\x265\build\hw -G Ninja `
  -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=OFF -DENABLE_CLI=ON
cmake --build .\x265\build\hw
```

`x265_overlay/` 与完整源码保持同一实现，供已有平台按文件覆盖或人工移植。不要提交 `x265/build/`、YUV、码流、逐 CTU 日志。

## 13. 多尺度两层与层次 cost 复现

### 13.1 完整三层采集

mode 7 不裁剪 P 帧，输出 29 维 `INTERLAYERMS` 和层次代价 `INTERLAYERCOST`：

```powershell
python .\experiments\inter_hw_hme\run_classb.py `
  --encoder .\x265\build\hw\x265.exe `
  --manifest .\experiments\inter_hw_hme\sequence_manifest.csv `
  --frames 12 --qps 22,27,32,37 --modes hw `
  --pme-cost-mode 1 --pme-rate-scale 256 `
  --pme-texture 8,24 --pme-attractor 1 `
  --layer-mode 7 --output D:\work\classb_multiscale_collect
```

### 13.2 多尺度 CART

```powershell
python .\experiments\inter_hw_hme\train_inter_multiscale_tree.py `
  D:\work\classb_multiscale_collect\runs.csv `
  --output D:\work\multiscale_model `
  --max-depth 7 --min-leaf 256 --low-weight 1.5 `
  --recommended-cutoff 45 `
  --cpp-header .\x265_overlay\source\encoder\inter_multiscale_gate_model.h
```

正式编码使用 `--hw-hme-inter-layers 8 --hw-hme-layer-cutoff 45`。I 帧由代码强制保持 intra32/intra16/intra8 三层开放。

### 13.3 层次 cost-only

```powershell
python .\experiments\inter_hw_hme\analyze_inter_hierarchy_cost.py `
  D:\work\classb_multiscale_collect\runs.csv `
  --output D:\work\classb_multiscale_collect\cost_accuracy.csv
```

正式 cost-only 编码使用 `--hw-hme-inter-layers 9`。该模式严格比较 `J32` 与四组 `4×min(J8)` 之和并计入 1/5 个 split bits；它是研究基线，当前 Class B 平均 +1.659%，不作为最终推荐。

### 13.4 cost-rooted 混合训练

```powershell
python .\experiments\inter_hw_hme\train_inter_hybrid_cost_tree.py `
  D:\work\classb_multiscale_collect\runs.csv `
  --output D:\work\hybrid_model `
  --max-depth 7 --min-leaf 256 --low-weight 1.5 `
  --recommended-cutoff 45
```

该脚本强制 cost-only 判决为根节点，再用 cost 裕量、四组 cost 一致性、纹理、SAD 与 MV 一致性训练两侧修正子树。模型导出后仍须进行逐序列留一验证和真实 30 帧 BD-rate 测试，不能只按分类正确率发布。

仓库已保存一次 Class B 候选训练到 `results/inter/hybrid_cost_tree_classb/`。cutoff 45 的留一正确率为 76.294%，低于 mode 8 的 77.731%；尚未集成为新的运行模式，也没有真实 BD-rate，目录中的头文件仅供继续实验。

## 9. 最终mode 11复现

mode 7新版日志额外输出`INTERLAYERCOSTSUM`，保存四个CU16区域的原始J8和、16个J8总和、旧`4×min`总和及完整RDO标签。训练命令：

```powershell
python .\experiments\inter_hw_hme\train_inter_sum_cost_tree.py `
  D:\work\classb_sumcost_collect\runs.csv `
  --output D:\work\sum_cost_tree --max-depth 6 --min-leaf 128 `
  --low-weight 1.5 --sample-stride 4 --recommended-cutoff 50 `
  --cpp-header .\x265_overlay\source\encoder\inter_sum_cost_gate_model.h
```

正式编码使用`--hw-hme-inter-layers 11 --hw-hme-layer-cutoff 50`。相同30帧ABCE测试的平均BD-rate为+0.273%；完整逐序列结果位于`results/inter/abce_sumcost_adaptive_mode11_c50_30f/`。I帧仍由代码强制保持intra32/intra16/intra8三层开放。
