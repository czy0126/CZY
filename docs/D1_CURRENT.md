# D1 当前交接面板（唯一日常入口）

> 状态基准：2026-11-10；研发主线 `feat/d1-fab-package`，本轮检出 `feat/g1-live-schematic-netlist`。本页是操作入口，不是第二份任务总表，也不批准制造。实际结论以最新**同一 CAD 修订版**的原生证据和 [D1 制造门禁](../hardware/dcx_main/d1_fabrication_gate.json)为准。总进展只回填 [Issue #4](https://github.com/czy0126/CZY/issues/4)。

## 目标与固定范围

**D1**：48 V → 约 2 V、固定约 24:1、目标 100 A、完整装配高度目标 ≤16 mm；成本暂不设上限，但安全、热、机械和制造验证不能省。D2 120 A 与 D3 ≤10 mm 均不占本轮 G1–G3 的资源。上位设计合同是 [第 49 章](D1_EXECUTION_KIT/49_D1主功率板PCB唯一执行计划_2026-11-09.md)，旧版本路线仅为历史证据。

**目前真实状态：`NOT_FOR_FAB`。** 现有 G1 可编辑原生 PCB，但尚未完成 G1 布线、G2 实体封装/100 A 铜路及 G3 原生 ERC/DRC、保护与制造审查。每次回报只引用当前实际产物，不再汇总旧日期的“最新”。

## 唯一可继续编辑的基线

| 对象 | 当前有效源 / 含义 |
| --- | --- |
| G1 **父版** | [`g1/dcx_main_board_g1_lr_repack.eprj2`](../hardware/dcx_main/g1/dcx_main_board_g1_lr_repack.eprj2)，sha256 `552628f0ef68fddca1411b808990274505a1d6a219038829c89261bd73abf87e`；只在**副本**上操作，不回写父版 |
| **信号增量已验收，待随本轮提交提升基线** | [`dcx_main_board_g1_signal_stubs.eprj2`](../hardware/dcx_main/g1/dcx_main_board_g1_signal_stubs.eprj2)，SHA256 `17fbae57bebdab6e0e18b6e4ddd177da98e25ca646bcb71d5e482a3b8db7b37e`；[本轮同会话重开/DRC审核](../hardware/dcx_main/g1/lr_signal_review_report.json)：77件/299焊盘/65网/107线/18过孔，未连接206→199，Physical 0，Netlist仍1；仅接受增量，不是整板通过 |
| 原生重开读回 | [`lr_repack_readback.json`](../hardware/dcx_main/g1/lr_repack_readback.json)、[`lr_repack_drc_raw.json`](../hardware/dcx_main/g1/lr_repack_drc_raw.json)：77 个 PCB 位号、299 焊盘、65 网络、98 铜线、18 过孔；206 条 Connection、1 条 Netlist、0 条 Physical 错误 |
| 实际 G1 原理图清册 | [`g1_native_inventory_raw.json`](../hardware/dcx_main/g1/g1_native_inventory_raw.json) / [审计](../hardware/dcx_main/g1/g1_native_inventory_bom_gate.json)：83 个原理图元件、38 项 MPN/目标值冲突，原 R8 被排除并在清册中重编号为 R6（BOM/PCB 双 false） |
| 当前 原理图↔PCB 逐脚差异 | [`g1_import_changes_diff.json`](../hardware/dcx_main/g1/g1_import_changes_diff.json)（2026-11-10 实测）：原理图 65 网/278 脚 vs PCB 62 网/254 脚；**不配对 24 脚全部是 CT(4)+T1–T4(各5) 的逻辑端**，PCB 侧不配对脚 0，`PRI_12/23/34` 只见于原理图，47 个共有网逐脚相同，两侧未分配的 5 脚一致。编辑器对比器 `netlistComparison` 的 PCB 列恒空，差异取自 `pcb_Net.getNetlist('JLCEDA')`；1 条原生 Netlist Error 与之**相容**，但 DRC 只报条数、逐项映射仍是推断。旧 [`g1_schematic_pcb_alignment.json`](../hardware/dcx_main/g1/g1_schematic_pcb_alignment.json) 是 Nov 6 网表口径的 83−77 计数，不再作当前差异 |
| G1 **活网表**（原理图侧） | [`g1_live_netlist.json`](../hardware/dcx_main/g1/g1_live_netlist.json)：83 位号的 `{位号:{脚:网}}` 由编辑器图元重建（`--path` 打开时**所有**制造导出都是 `null`），先在参考板逐脚复现 Nov 6 导出才采信；与旧导出只差 `R8→R6`。是读数，**不是** Netlist Error 的根因结论，也不是 ERC/DRC |
| 100 A 铜路 | [`g1_100a_copper_neck_screen.json`](../hardware/dcx_main/g1/g1_100a_copper_neck_screen.json)：4 条 VOUT + 8 条 PGND 的 1 mm 旧窄颈，不满足既定两极 150 µΩ 内部预算；必须改实体铜路，不得只改报告 |

> **切忌混用两套审计：** 根目录 `hardware/dcx_main/d1_fabrication_gate.json` 当前仍从**旧版主板**相关清册/网表重建，因此其中原 R8、39 条厂商冲突不是当前 G1 实际清册的逐项读数；不要用旧门禁的元件字段推翻 G1 的 R6 双 DNP 实际读回，也不能用 G1 的读回直接把旧门禁置绿。安全总状态始终保持 `NOT_FOR_FAB`，直到同一 CAD 修订版完成全链审核。

## 接下来仅允许 A/B/C 三个工作包

| 工作包 | **下一个有意义的交付** | 完成标准 | 未满足时 |
| --- | --- | --- | --- |
| **A · #9**（最高优先） | Import Changes **逐脚差异已实测**（24 脚仅 CT/T1–T4 逻辑端，PCB 侧不配对脚 0）；下一步落实**实体 Cout** 与 **100 A VOUT/PGND 短宽铜路**，待 B 给出可制造端子后再做原生 ECO | 差异原文（已有）、原生CAD、保存重开、实际ERC/DRC；不得仅靠R6改名或匿名磁件猜测Netlist错误根因；新铜路需真实几何与双极电阻预算 | 不继续第十条低电流线的预检；涉及实体端子/工艺缺口则转B/C的具体交付 |
| **B · #12/#1** | 用现有 [Maxwell 概念入口](../tools/maxwell_diy_run.py)先求解 Lr 3 匝/0.92 µH，并构建可制造的 CT/T1–T4 实绕组与 **24 个正式 PAD/DOT**；2 匝及更大磁芯作为物理备选 | 实际 AEDT 求解/收敛/局部 B/L(I) 原始文件，实体绕组/绝缘/出线/极性/尺寸与 EDA 封装一一对应；合成 B–H 不能当厂家认证 | Maxwell 无授权时不再重复生成概念 STEP；只完成独立真实绕组与端子工程输入 |
| **C · #36** | 原边与单对 SR 的**低能量**真实关断验证，然后覆盖全部十路 VGS、掉电、故障锁存、复位 | 原始示波器/同步测量与接线、条件、SOA；必须有真实关断默认状态 | 无实验台时仅保留现有接口和待采记录，不用理想 LTspice 再“证明”关断安全 |

严格 **WIP≤3**，A 高于 B/C。除真实 P0 安全故障外，A 未形成下一张原生板前，不再为 A 增加纯分析/检查 PR。

## 本轮信号增量验收与下一操作

9条原生连接已经落板，**不要再次运行`--apply`覆盖或重画**。原先C103.1–C104.1报覆盖失败，是已有0.25/0.30mm同网铜线与新0.20mm线合并后，旧检查器仍要求全程等宽。现检查器同网同层投影裁剪、连续区间合并，signal显式允许更宽铜，保持原坐标容差；异网不能提供覆盖，真实缺口仍失败。原失败回执保留。

本轮只读重新打开该CAD、读取全部图元并运行原生DRC，前后SHA一致；未重画已经覆盖的线段。原生证据：[读回](../hardware/dcx_main/g1/lr_signal_review_readback.json)、[DRC原文](../hardware/dcx_main/g1/lr_signal_review_drc_raw.json)、[绑定SHA的审核结果](../hardware/dcx_main/g1/lr_signal_review_report.json)。

可重复的离线检查：

```powershell
python -m pytest tools/test_g1_copper_coverage.py tools/test_g1_driver_route_plan.py tools/test_deepseek_settings.py tools/test_d1_fabrication_gate.py -q
```

本轮57项相关检查通过，不能替代原生DRC。`review_signal_stubs.py --capture`是本轮原生回执的生成器，存在回执即拒绝覆盖；不为刷新日期重复执行。

DeepSeek已通过用户指定的Claude设置恢复连接，配置只提供连接字段，不发送配置内容。已完成[具体修复审核](../deepseek/20261110_signal_review/reply.md)及[下一步任务](../deepseek/20261110_signal_review/next_step_reply.md)。保留异网过滤/原容差等独立复核，未照搬“任意异网线即否决整个列表”的表述。下一步回复中的端子映射不能代替真实绕组/磁场求解；DRC不新增错误也不能代替十路VGS、失电行为和SOA的实测证据，B/C仍按上表验收。运行器支持`--claude-settings`，密钥未进入仓库。

**本轮 Import Changes 差异（2026-11-10）：** 在候选的**副本**上只读完成四步（对比器读数 → PCB 网表模型探针 → PCB 网表导出 → 离线配对），前后 SHA 一致，证据 [`lr_signal_import_changes.json`](../hardware/dcx_main/g1/lr_signal_import_changes.json) · [`lr_signal_pcb_netlist_model.json`](../hardware/dcx_main/g1/lr_signal_pcb_netlist_model.json) · [`lr_repack_pcb_netlist_jlc.json`](../hardware/dcx_main/g1/lr_repack_pcb_netlist_jlc.json) · [`g1_import_changes_diff.json`](../hardware/dcx_main/g1/g1_import_changes_diff.json)。`sys_Tool.netlistComparison` 可调用但 PCB 列对本板恒空（65 网全 `[]`，含逐脚完全相同的 47 个），**不能当差异清单**；逐脚比对改用 PCB 自己的 `pcb_Net.getNetlist('JLCEDA')`（165 556 字符 / 77 器件 / 62 网 / 254 脚）。这只是**配平**证据，不等于实体端子/DOT（D-07），也不把 1 条 Netlist Error 说成已定位根因。操作陷阱已记 [EDA.md](agent/EDA.md)。

**后续路线：** 信号增量归档 → Import Changes 逐脚差异实测（已完成）→ 实体 Cout 与双极 100 A 铜路/端子/磁件剖面 → 原生 ECO、同修订 ERC/DRC 及 DFM → 真实低能量关断与分级25/50/100 A验证。B线的自研Maxwell/绕组与C线的台架关断继续并行，120 A和≤10mm仍后置。当前199条未连接与1条网表不一致必须逐步消除；绝不把本轮增量验收表述为可投板。

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
