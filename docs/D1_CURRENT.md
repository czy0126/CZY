# D1 当前交接面板（唯一日常入口）

> 状态基准：2026-11-10；**工作分支** `feat/d1-fab-package`，而非默认 `main`。本页是操作入口，不是第二份任务总表，也不批准制造。实际结论以最新**同一 CAD 修订版**的原生证据和 [D1 制造门禁](../hardware/dcx_main/d1_fabrication_gate.json)为准。总进展只回填 [Issue #4](https://github.com/czy0126/CZY/issues/4)。

## 目标与固定范围

**D1**：48 V → 约 2 V、固定约 24:1、目标 100 A、完整装配高度目标 ≤16 mm；成本暂不设上限，但安全、热、机械和制造验证不能省。D2 120 A 与 D3 ≤10 mm 均不占本轮 G1–G3 的资源。上位设计合同是 [第 49 章](D1_EXECUTION_KIT/49_D1主功率板PCB唯一执行计划_2026-11-09.md)，旧版本路线仅为历史证据。

**目前真实状态：`NOT_FOR_FAB`。** 现有 G1 可编辑原生 PCB，但尚未完成 G1 布线、G2 实体封装/100 A 铜路及 G3 原生 ERC/DRC、保护与制造审查。每次回报只引用当前实际产物，不再汇总旧日期的“最新”。

## 唯一可继续编辑的基线

| 对象 | 当前有效源 / 含义 |
| --- | --- |
| G1 **父版** | [`g1/dcx_main_board_g1_lr_repack.eprj2`](../hardware/dcx_main/g1/dcx_main_board_g1_lr_repack.eprj2)，sha256 `552628f0ef68fddca1411b808990274505a1d6a219038829c89261bd73abf87e`；只在**副本**上操作，不回写父版 |
| 原生重开读回 | [`lr_repack_readback.json`](../hardware/dcx_main/g1/lr_repack_readback.json)、[`lr_repack_drc_raw.json`](../hardware/dcx_main/g1/lr_repack_drc_raw.json)：77 个 PCB 位号、299 焊盘、65 网络、98 铜线、18 过孔；206 条 Connection、1 条 Netlist、0 条 Physical 错误 |
| 实际 G1 原理图清册 | [`g1_native_inventory_raw.json`](../hardware/dcx_main/g1/g1_native_inventory_raw.json) / [审计](../hardware/dcx_main/g1/g1_native_inventory_bom_gate.json)：83 个原理图元件、38 项 MPN/目标值冲突，原 R8 被排除并在清册中重编号为 R6（BOM/PCB 双 false） |
| 当前 原理图↔PCB 差异 | [`g1_schematic_pcb_alignment.json`](../hardware/dcx_main/g1/g1_schematic_pcb_alignment.json)：83−77 对应 CT/T1–T4 的 24 个**匿名临时 PAD**及不应装配的 R6；275 个在板 PAD 与**旧版**网表一致，但**当前** 1 条原生 Netlist Error 的根因未确定 |
| 100 A 铜路 | [`g1_100a_copper_neck_screen.json`](../hardware/dcx_main/g1/g1_100a_copper_neck_screen.json)：4 条 VOUT + 8 条 PGND 的 1 mm 旧窄颈，不满足既定两极 150 µΩ 内部预算；必须改实体铜路，不得只改报告 |

> **切忌混用两套审计：** 根目录 `hardware/dcx_main/d1_fabrication_gate.json` 当前仍从**旧版主板**相关清册/网表重建，因此其中原 R8、39 条厂商冲突不是当前 G1 实际清册的逐项读数；不要用旧门禁的元件字段推翻 G1 的 R6 双 DNP 实际读回，也不能用 G1 的读回直接把旧门禁置绿。安全总状态始终保持 `NOT_FOR_FAB`，直到同一 CAD 修订版完成全链审核。

## 接下来仅允许 A/B/C 三个工作包

| 工作包 | **下一个有意义的交付** | 完成标准 | 未满足时 |
| --- | --- | --- | --- |
| **A · #9**（最高优先） | 在 Windows EasyEDA Pro **实际**将已预检的 **9 条** VCC12/VCC12_S/RUN/OC1/OC 低电流线布到**新副本**；随后在编辑器里检查 Import Changes 的 1 条真实网表差异，处理实体 Cout 和 100 A 两极铜路 | 新 `.eprj2`、实际保存/关闭/重开读回、原生 DRC：206 条 Connection 必须下降，0 新 Physical，Netlist 不上升；不能把预检算完成 | 无可用 EasyEDA 时**停止增加**第十条小信号线的脚本，登记一次工作站条件，切换到 B 或 C |
| **B · #12/#1** | 用现有 [Maxwell 概念入口](../tools/maxwell_diy_run.py)先求解 Lr 3 匝/0.92 µH，并构建可制造的 CT/T1–T4 实绕组与 **24 个正式 PAD/DOT**；2 匝及更大磁芯作为物理备选 | 实际 AEDT 求解/收敛/局部 B/L(I) 原始文件，实体绕组/绝缘/出线/极性/尺寸与 EDA 封装一一对应；合成 B–H 不能当厂家认证 | Maxwell 无授权时不再重复生成概念 STEP；只完成独立真实绕组与端子工程输入 |
| **C · #36** | 原边与单对 SR 的**低能量**真实关断验证，然后覆盖全部十路 VGS、掉电、故障锁存、复位 | 原始示波器/同步测量与接线、条件、SOA；必须有真实关断默认状态 | 无实验台时仅保留现有接口和待采记录，不用理想 LTspice 再“证明”关断安全 |

严格 **WIP≤3**，A 高于 B/C。除真实 P0 安全故障外，A 未形成下一张原生板前，不再为 A 增加纯分析/检查 PR。

## A 线唯一立即执行命令（需有 EasyEDA Pro 的 Windows 工作站）

在仓库根目录执行；应用前关闭占用目标工程的编辑器，确认工作区无未保存修改：

```powershell
python hardware/dcx_main/g1/apply_lr_signal_stubs.py --check
python hardware/dcx_main/g1/apply_lr_signal_stubs.py --apply
```

`--check` 只做源板/几何预检。**`--apply` 才写入** `hardware/dcx_main/g1/dcx_main_board_g1_signal_stubs.eprj2` 新副本；存在同名目标即拒绝覆盖。将新 `.eprj2`、`lr_signal_readback.json`、`lr_signal_drc_raw.json`、`lr_signal_drc_delta.json` 及回执提交到 **同一个 A 交付 PR**。若执行失败，保留原始失败文件，**不要**手调报告数值。A 线不要把临时 CTAP/变压器 PAD、原生 2 mm 连通线称为 100 A 可制造结构。

## 一轮交付只回答四件事

1. **改变了哪份真实产物？** 给新旧 CAD SHA、磁件实测/AEDT、BOM GUI 导出或台架原始数据路径；若没有，写“未推进实体交付”，不可改写成“完成”。
2. **关掉了哪一个可复核的阻塞？** 同一来源版本的原生 DRC/脚号/实测数据前后值；无变化则不再重复开同类 PR。
3. **哪一项依赖工作站或实体输入？** 只登记一次：所需工具、当前不可得的输入与恢复条件。
4. **下一次只做什么？** A 的下一份真实 PCB、B 的下一组实体磁件或 C 的下一次真机测试三选其一。

## 永久入口（不要建立第二张状态表）

- 任务与责任：[#4 全局](https://github.com/czy0126/CZY/issues/4) · [#9 主板](https://github.com/czy0126/CZY/issues/9) · [#12/#1 磁件](https://github.com/czy0126/CZY/issues/12) · [#36 保护](https://github.com/czy0126/CZY/issues/36)
- 已决定 / 何时可重新讨论：[D1 决策与停止重复登记](D1_DECISIONS.md)
- 原厂来源、历史路线及工具：[参考资料与历史索引](D1_REFERENCE_INDEX.md) · [EDA 操作环境](agent/EDA.md) · [完整命令表](agent/COMMANDS.md)
- **唯一制造判定：** [`d1_fabrication_gate.json`](../hardware/dcx_main/d1_fabrication_gate.json) 的独立原生证据、审核签字；CI 绿色/PR 合并本身**不能**许可投板或高能量上电。
