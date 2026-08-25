# 本仓库 x265 研究改动说明

`x265/` 是完整的 x265 源码快照，不是只包含补丁的目录。研究改动已经直接合入 `source/`，可以单独配置和构建；`../x265_overlay/` 保存同一组关键文件，便于向其他兼容 x265 代码树人工移植。

主要改动：

- P 帧 `PME → IME → FME` 硬件友好三级搜索，PME 使用 1/4 下采样图像，IME 使用重构参考，FME 结果继续进入 AMVP/Merge/RDO。
- 正方形 CU=PU=TU 的 32×32、16×16、8×8 三层探针与精度对齐。
- PME 自适应 rate 权重、纹理分档及零向量/AMVP attractor 控制。
- P 帧完整三层、强制高两层、强制低两层、CU32-only、多尺度 CART 和层次 cost-only 运行模式。
- mode 7 的 `INTERLAYERMS` 与 `INTERLAYERCOST` 训练日志。
- mode 8 的 29 维整数多尺度树；mode 9 的 `SAD + sqrt(lambda)×MVD_bits` 层次判据。
- I 帧保护：P 帧选层开启时，I_SLICE 仍开放 intra32/intra16/intra8。

构建示例：

```powershell
cmake -S .\x265\source -B .\x265\build\hw -G Ninja `
  -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=OFF -DENABLE_CLI=ON
cmake --build .\x265\build\hw
```

推荐的 P 帧两层配置是 `--hw-hme-inter-layers 8 --hw-hme-layer-cutoff 45`。mode 9 是用户指定公式的独立研究基线，不是当前推荐。详细参数、训练、测试和结果请返回仓库根目录查看 `README_zh.md`、`docs/REPRODUCE_zh.md` 和正式 DOCX 报告。

源码沿用 x265 的 GPL 条款，见本目录 `COPYING`。测试 YUV、码流、可执行文件、构建目录和逐 CTU 大日志不随仓库分发。
