# D1 当前交接面板（唯一日常入口）

> 状态基准：2026-11-11；研发主线 `feat/d1-fab-package`，[PR #87](https://github.com/czy0126/CZY/pull/87) 已合并实际原生增量。本页是操作入口，不是第二份任务总表，也不批准制造。实际结论以最新**同一 CAD 修订版**的原生证据和 [D1 制造门禁](../hardware/dcx_main/d1_fabrication_gate.json)为准。总进展只回填 [Issue #4](https://github.com/czy0126/CZY/issues/4)。

## 目标与固定范围

**D1**：48 V → 约 2 V、固定约 24:1、目标 100 A、完整装配高度目标 ≤16 mm；成本暂不设上限，但安全、热、机械和制造验证不能省。D2 120 A 与 D3 ≤10 mm 均不占本轮 G1–G3 的资源。上位设计合同是 [第 49 章](D1_EXECUTION_KIT/49_D1主功率板PCB唯一执行计划_2026-11-09.md)，旧版本路线仅为历史证据。

**目前真实状态：`NOT_FOR_FAB`。** 现有 G1 可编辑原生 PCB，但尚未完成 G1 布线、G2 实体封装/100 A 铜路及 G3 原生 ERC/DRC、保护与制造审查。每次回报只引用当前实际产物，不再汇总旧日期的“最新”。

**当前唯一 Windows 原生布线执行入口（PR #94 已合并）：** 基于同一活板，从仓库根目录执行 `python hardware/dcx_main/g1/apply_g1_control_autoroute.py --check` 后执行 `python hardware/dcx_main/g1/apply_g1_control_autoroute.py --apply`。一次性运行先前12个已验证焊盘连接、保存重开及**实测 DRC 下降**；再利用官方 EasyEDA `RoutingNets` 只在 RUN/SS/DT/RT/OC1/OC/OCM/OCD 八个低电流网上执行原生自动布线，**其它57网全部明示排除**，只有不动功率铜/原网且原生DRC继续下降才接受另一份副本。**本机本轮已完成第一阶段，真实原生DRC为183/1/0；第二阶段结果另列。CI绿灯不代表原生布线完成。**

**不计成本 Cout 备选（PR #93 已合并）：** 已以既有确切原厂资料 KEMET `T530X477M006ATE004`（6.3V、470µF、4mΩ@100kHz/25°C）生成 **72颗（18×4）实际G1板源SHA绑定的XY/现有铜线干涉筛查**，代码 `tools/cout_t530_72.py`、[输入候选](../hardware/dcx_main/g2/cout_oem_candidate.json)。33.84mF、理想ESR 0.0556mΩ（25°C）仅是参考，**原107线板的VOUT/PGND铜区存在65处穿越关系，须重做功率层**；100°C/200kHz、启动与电流均分、厂家封装和全装配16mm均未核实。15颗A720仍只是2.5V基准模型，不能直接替代高耐压方案。

## 唯一可继续编辑的基线

| 对象 | 当前有效源 / 含义 |
| --- | --- |
| **本机最新已验收增量** | [`dcx_main_board_g1_open_batch.eprj2`](../hardware/dcx_main/g1/dcx_main_board_g1_open_batch.eprj2)，SHA256 `59ec7ab3f8dd17ba76b465e9686bce58647db66b76770a4762c0b7e33e33afb0`；77件/299焊盘/65网/132线/18过孔，[原生DRC回执](../hardware/dcx_main/g1/g1_open_batch_drc_delta.json)为Connection 183、Netlist 1、Physical 0。12组连接已执行，禁止再次apply覆盖。原生文件与 DRC 回执已随本次提交入库，可从干净克隆复核。 |
| G1 **历史冻结父版（只用于追溯）** | [`g1/dcx_main_board_g1_lr_repack.eprj2`](../hardware/dcx_main/g1/dcx_main_board_g1_lr_repack.eprj2)，sha256 `552628f0ef68fddca1411b808990274505a1d6a219038829c89261bd73abf87e`；只在**副本**上操作，不回写父版 |
| **本轮增量的冻结父版** | [`dcx_main_board_g1_signal_stubs.eprj2`](../hardware/dcx_main/g1/dcx_main_board_g1_signal_stubs.eprj2)，SHA256 `17fbae57bebdab6e0e18b6e4ddd177da98e25ca646bcb71d5e482a3b8db7b37e`；[本轮同会话重开/DRC审核](../hardware/dcx_main/g1/lr_signal_review_report.json)：77件/299焊盘/65网/107线/18过孔，未连接206→199，Physical 0，Netlist仍1；仅接受增量，不是整板通过 |
| 原生重开读回 | [`lr_repack_readback.json`](../hardware/dcx_main/g1/lr_repack_readback.json)、[`lr_repack_drc_raw.json`](../hardware/dcx_main/g1/lr_repack_drc_raw.json)：77 个 PCB 位号、299 焊盘、65 网络、98 铜线、18 过孔；206 条 Connection、1 条 Netlist、0 条 Physical 错误 |
| 实际 G1 原理图清册 | [`g1_native_inventory_raw.json`](../hardware/dcx_main/g1/g1_native_inventory_raw.json) / [审计](../hardware/dcx_main/g1/g1_native_inventory_bom_gate.json)：83 个原理图元件、38 项 MPN/目标值冲突，原 R8 被排除并在清册中重编号为 R6（BOM/PCB 双 false） |
| 当前 原理图↔PCB 逐脚差异 | [`g1_import_changes_diff.json`](../hardware/dcx_main/g1/g1_import_changes_diff.json)（2026-11-10 实测）：原理图 65 网/278 脚 vs PCB 62 网/254 脚；**不配对 24 脚全部是 CT(4)+T1–T4(各5) 的逻辑端**，PCB 侧不配对脚 0，`PRI_12/23/34` 只见于原理图，47 个共有网逐脚相同，两侧未分配的 5 脚一致。编辑器对比器 `netlistComparison` 的 PCB 列恒空，差异取自 `pcb_Net.getNetlist('JLCEDA')`；1 条原生 Netlist Error 与之**相容**，但 DRC 只报条数、逐项映射仍是推断。旧 [`g1_schematic_pcb_alignment.json`](../hardware/dcx_main/g1/g1_schematic_pcb_alignment.json) 是 Nov 6 网表口径的 83−77 计数，不再作当前差异 |
| G1 **活网表**（原理图侧） | [`g1_live_netlist.json`](../hardware/dcx_main/g1/g1_live_netlist.json)：83 位号的 `{位号:{脚:网}}` 由编辑器图元重建（`--path` 打开时**所有**制造导出都是 `null`），先在参考板逐脚复现 Nov 6 导出才采信；与旧导出只差 `R8→R6`。是读数，**不是** Netlist Error 的根因结论，也不是 ERC/DRC |
| 100 A 铜路 | [`g1_100a_copper_neck_screen.json`](../hardware/dcx_main/g1/g1_100a_copper_neck_screen.json)：4 条 VOUT + 8 条 PGND 的 1 mm 旧窄颈，不满足既定两极 150 µΩ 内部预算；[`g1_100a_output_interface.json`](../hardware/dcx_main/g1/g1_100a_output_interface.json)：底面双极铜排 + 两源排之间出端子，在 **39×5 mm、等损耗最宽极距 51.6001 mm、舌宽 39 mm** 下进预算（**147.529 µΩ**，余量 2.471，每极接点上限 51.235）；横向路径计入后 **4 mm 在 50 µΩ 接点场景下任何舌宽都不过**（最好 150.212；20 µΩ 场景则通过），**中线馈电 5 mm 也失败**（151.523，舌宽须 ≥21.26 mm）；终止于 J_OUT 不过（154.944 µΩ 且 VOUT 段穿过 PGND 排，按图不可实现，只能当下界）；**已核对高度冲突**：按TDK ELP38/I38最大12.35mm + 假定PCB1.6mm/绝缘0.3mm，5mm底面铜排总高**19.25mm（超16mm 3.25mm）**；[G2可编辑铜排CAD生成器](../tools/g2_busbar_cad.py) 对1.2mm底排/20µΩ每极接点给出15.45mm、121.511µΩ的**未实测**场景（50µΩ接点则181.511µΩ失败），仅留0.55mm给TIM/压件/公差。**不得根据5mm的电阻算术通过冻结装配**。[G2 原生铜避让](../tools/g2_board_keepout.py) 已发现 #88 中假定的 VOUT Ø3.4mm 试验孔落在 J_IN 的 PGND 焊盘上，PGND 试孔也低于筛查净距；现 STEP/DXF **已移除全部试钻孔并重建底面绝缘代理**，新孔位需实际端子/内层/Courtyard验证。结论见 D-12，铜路仍不在原生 CAD |

> **切忌混用两套审计：** 根目录 `hardware/dcx_main/d1_fabrication_gate.json` 当前仍从**旧版主板**相关清册/网表重建，因此其中原 R8、39 条厂商冲突不是当前 G1 实际清册的逐项读数；不要用旧门禁的元件字段推翻 G1 的 R6 双 DNP 实际读回，也不能用 G1 的读回直接把旧门禁置绿。安全总状态始终保持 `NOT_FOR_FAB`，直到同一 CAD 修订版完成全链审核。

## 接下来仅允许 A/B/C 三个工作包

**当前 CAD 继承规则**：后续原生布线/磁件/输出铜路 ECO 必须从上表最新已验收候选复制成**新的非覆盖候选**；signal_stubs只作本轮父版追溯；旧 Lr-repack 仅是冻结父版。不得重新运行 `apply_lr_signal_stubs.py --apply`，也不得把新的原生99条以上布线与旧98条基线混作同一张板。

| 工作包 | **下一个有意义的交付** | 完成标准 | 未满足时 |
| --- | --- | --- | --- |
| **A · #9**（最高优先） | Import Changes **逐脚差异已实测**（24 脚仅 CT/T1–T4 逻辑端，PCB 侧不配对脚 0）；**100 A 铜路拓扑已预筛**（D-12：中央双端子需 39×5 mm 且舌宽 ≥21.26 mm；4 mm 在 50 µΩ 接点下全面失败，20 µΩ 场景可通过；J_OUT 按图不可实现）。下一步落实**实体 Cout** 与**真实铜排/端子几何**，待 B 给出可制造端子后再做原生 ECO；**Cout主电容已有原厂实号候选**（[`g2/cout_oem_candidate.json`](../hardware/dcx_main/g2/cout_oem_candidate.json)：15×KEMET `A720V477M2R5APE003`，标称7.05mF/理想ESR0.2mΩ；**原厂规格页已于2026-11-11归档并核验** 470µF/2.5V/3mΩ@100kHz·25°C/11.69A rms@ΔT=+20°C/Hmax 2.1mm/F 2.4mm/无正向电压降额，[来源与哈希](../references/datasheets/a720v477m2r5ape003.provenance.json)；100°C/200kHz 温升、2.5V 超调与**原厂实装焊盘仍未核实**；Murata 100µF只作可选高频旁路，不能代替4mF主Cout） | 差异原文（已有）、原生CAD、保存重开、实际ERC/DRC；不得仅靠R6改名或匿名磁件猜测Netlist错误根因；新铜路需真实几何与双极电阻预算（已有离线预算，未进 CAD）；Cout 需同修订 BOM/几何读回/原生 DRC/CAD 哈希 | 不继续第十条低电流线的预检；涉及实体端子/工艺缺口则转B/C的具体交付 |
| **B · #12/#1** | 用现有 [Maxwell 概念入口](../tools/maxwell_diy_run.py)先求解 Lr 3 匝/0.92 µH，并构建可制造的 CT/T1–T4 实绕组与 **24 个正式 PAD/DOT**；2 匝及更大磁芯作为物理备选 | 实际 AEDT 求解/收敛/局部 B/L(I) 原始文件，实体绕组/绝缘/出线/极性/尺寸与 EDA 封装一一对应；合成 B–H 不能当厂家认证 | Maxwell 无授权时不再重复生成概念 STEP；只完成独立真实绕组与端子工程输入 |
| **C · #36** | 原边与单对 SR 的**低能量**真实关断验证，然后覆盖全部十路 VGS、掉电、故障锁存、复位 | 原始示波器/同步测量与接线、条件、SOA；必须有真实关断默认状态 | 无实验台时仅保留现有接口和待采记录，不用理想 LTspice 再“证明”关断安全 |

严格 **WIP≤3**，A 高于 B/C。除真实 P0 安全故障外，A 未形成下一张原生板前，不再为 A 增加纯分析/检查 PR。

## 已合并的 G1 信号增量与下一操作

9条原生连接已经落板，**不要再次运行`--apply`覆盖或重画**。原先C103.1–C104.1报覆盖失败，是已有0.25/0.30mm同网铜线与新0.20mm线合并后，旧检查器仍要求全程等宽。现检查器同网同层投影裁剪、连续区间合并，signal显式允许更宽铜，保持原坐标容差；异网不能提供覆盖，真实缺口仍失败。原失败回执保留。

PR #87 已合并；验收期间只读重新打开该CAD、读取全部图元并运行原生DRC，前后SHA一致；未重画已经覆盖的线段。原生证据：[读回](../hardware/dcx_main/g1/lr_signal_review_readback.json)、[DRC原文](../hardware/dcx_main/g1/lr_signal_review_drc_raw.json)、[绑定SHA的审核结果](../hardware/dcx_main/g1/lr_signal_review_report.json)。

可重复的离线检查：

```powershell
python -m pytest tools/test_g1_copper_coverage.py tools/test_g1_driver_route_plan.py tools/test_deepseek_settings.py tools/test_d1_fabrication_gate.py -q
```

本轮57项相关检查通过，不能替代原生DRC。`review_signal_stubs.py --capture`是本轮原生回执的生成器，存在回执即拒绝覆盖；不为刷新日期重复执行。

DeepSeek已通过用户指定的Claude设置恢复连接，配置只提供连接字段，不发送配置内容。已完成[具体修复审核](../deepseek/20261110_signal_review/reply.md)及[下一步任务](../deepseek/20261110_signal_review/next_step_reply.md)。保留异网过滤/原容差等独立复核，未照搬“任意异网线即否决整个列表”的表述。下一步回复中的端子映射不能代替真实绕组/磁场求解；DRC不新增错误也不能代替十路VGS、失电行为和SOA的实测证据，B/C仍按上表验收。运行器支持`--claude-settings`，密钥未进入仓库。

**本轮 Import Changes 差异（2026-11-10）：** 在候选的**副本**上只读完成四步（对比器读数 → PCB 网表模型探针 → PCB 网表导出 → 离线配对），前后 SHA 一致，证据 [`lr_signal_import_changes.json`](../hardware/dcx_main/g1/lr_signal_import_changes.json) · [`lr_signal_pcb_netlist_model.json`](../hardware/dcx_main/g1/lr_signal_pcb_netlist_model.json) · [`lr_repack_pcb_netlist_jlc.json`](../hardware/dcx_main/g1/lr_repack_pcb_netlist_jlc.json) · [`g1_import_changes_diff.json`](../hardware/dcx_main/g1/g1_import_changes_diff.json)。`sys_Tool.netlistComparison` 可调用但 PCB 列对本板恒空（65 网全 `[]`，含逐脚完全相同的 47 个），**不能当差异清单**；逐脚比对改用 PCB 自己的 `pcb_Net.getNetlist('JLCEDA')`（165 556 字符 / 77 器件 / 62 网 / 254 脚）。这只是**配平**证据，不等于实体端子/DOT（D-07），也不把 1 条 Netlist Error 说成已定位根因。操作陷阱已记 [EDA.md](agent/EDA.md)。

**后续路线：** 信号增量归档 → Import Changes 逐脚差异实测（已完成）→ 100 A 铜路拓扑预筛（已完成，D-12）→ 实体 Cout 与真实铜排/端子/磁件剖面 → 原生 ECO、同修订 ERC/DRC 及 DFM → 真实低能量关断与分级25/50/100 A验证。B线的自研Maxwell/绕组与C线的台架关断继续并行，120 A和≤10mm仍后置。当前183条未连接与1条网表不一致必须逐步消除；绝不把本轮增量验收表述为可投板。

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

## 2026-11-11 Cout 原厂数据核验与 DRC 旁路修复

**PR #92 官方 Cout 验证与真实交付的边界（2026-11-11）：**

- A720 的 **2.5 V / 470 µF / 3 mΩ** 单件参数有厂家原文，但与现有 [P0 高耐压 RFQ](../hardware/dcx_main/performance_first_component_rfq.csv) 的 **≥4 V（优选 6.3 V）、整组热态 ESR ≤0.07 mΩ** 不一致。**最终采购/装配 MPN 不放行**；15×A720 仅为现有 2.5 V 模型候选，见 [Cout 决策登记](../hardware/dcx_main/component_decision_register.json)。厂商 F=2.4 mm 属端子尺寸，不是获批的焊盘间距。
- 已提供 [15 颗 Cout 的原生 ECO 输入](../hardware/dcx_main/g2/cout_a720_15part_eda_input.json)：Cout1～Cout15、既有机械方案中的初步 XY 外形和极性网络；**0.6 mm 最大外形间隔不是批准的 courtyard**。重新排布后要重算 Cout 铜扩散阻抗。
- DeepSeek 评审对话中出现“132 线／183 Connection”数字，但 **PR #92 尚未提交绑定它的新原生 .eprj2、重开读回和原生 DRC**；不能将讨论数字提升为活板基线。该句为PR #92历史状态；本轮已在本机重新执行并取得132线/183 Connection的真实CAD与绑定回执，见上表，禁止再次执行旧12组批次。

- `tools/cout_bank.py` 现在从归档的 YAGEO 单件规格页读取选型值，并用 KEMET T2078 A720 系列节选交叉核对泄漏/ESR/纹波，产品简介确认 "No voltage derating"；`spec_facts()` 在缺行或数值不一致时拒绝。归档、URL 与逐文件 SHA256 见 [`references/datasheets/`](../references/datasheets/a720v477m2r5ape003.provenance.json)；选型行 `verified: true`，A798/Chemi-Con 两行仍标 `verified: false`（网络摘要）。
- 这关掉的是“Cout 无原厂手册、无法选型”的桌面阻塞，**不关落板**：现有单个 `Cout` 焊盘 F≈1.4 mm 与 A720 的 F=2.4 mm 不兼容，15 只阵列仍是本地原生 ECO。`NOT_FOR_FAB` 不变。
- `apply_g1_open_batch.py` 追加两条 DRC 旁路防护：`after` 缺失任何基线非零类别按截断拒绝；类别比较取 `before`/`after` 并集，新增类别不再被忽略。`route_open_connections.categories` 拒绝 `ok:false`、空 `raw`、坏嵌套与类别数不一致。相关离线测试通过；原生回执不放宽，也不把离线测试当成同修订 DRC。

**PR #92 遗留检查项（2026-11-11 后续）：**

- **寄存器可复现**：合并后的 `component_decision_register.json` 曾是手改，与生成器不一致。`tools/d1_sourcing_register.py` 现在从 G2 候选档案派生 Cout 的已验证身份与全部未决项，`test_checked_in_supplier_requests_are_current` 重新成立；RFQ 仍空白/`PENDING_*`，封装仍未放行。
- **支路铜阻 ↔ 阵列间距**：`tools/cout_bank_path.py` 的 lane 直接取机械摆放的实测中心距（15 只同为 x=14+8.2i、y=98）。新增测试把 15 颗 ECO 输入与铜模型逐位钉住（ref、x、y、pitch）；任一侧重排而未同步即红。该模型仍是“独立支路”示意，不是 PCB 阻抗上界。
- **原厂 ESR 曲线**：已归档 KEMET T2078_A720 日文版全 15 页 PDF，并手抄页级摘要。系列只在 p.3 给 ESR 限值：105 °C/额定电压 2,000 h 耐久与 105 °C/0 V 存放后 **ESR ≤2.0× 初值**。p.4 的 ESR-频率图只画 A720V477M002（2 V）与 A720V226M035（35 V），**没有 2.5 V 470 µF 的曲线，也没有表列数值**；全文无 ESR-温度、ESR-偏置曲线。故 200 kHz、2.5 V 偏置、100 °C 保持 `UNKNOWN`；寿命只有“×2 上限”，不是曲线。另：p.7 表 2 实际发布了 case V/7343-21 的推荐焊盘尺寸（A/B/C 三档），此前“系列无焊盘表”的说法过强——但尚未映射进 EDA，`actual_oem_land_pattern_and_signoff` 仍为 false。
- **生成视图**：v3 manifest 与 3 个生成视图未受 BOM 变化影响（`ci_check --skip-tests` 绿）；RFQ 视图仍由 `performance_first_design.py` 唯一生成，寄存器由 `d1_sourcing_register.py` 唯一生成，两者都不接受手改。

### Cout后续独立审核（2026-11-11，本轮）

已调用DeepSeek完成[针对当前代码的审核](../deepseek/20261111_cout_followup/reply.md)，实际修复 `_verified_cout`：室温100 kHz的ESR/N仅输出 `nominal_100khz_25c_esr_screen_met`；实际工况证据尚未接入生成器，`supplier_rfq_low_esr_target_met`保持false并标NOT_VERIFIED。新增100颗并联负例，确保室温筛选通过也不能误签热态目标；已重生成决策登记。候选档案删除“任意替代型号仍装15颗”的指令，改为按容量容差、实际频温ESR、纹波裕量和均流重新计算数量。

DeepSeek建议的“hot ESR直接乘2寿命系数”未直接采用：当前原厂耐久条款的测试条件不等于任意热态频率的通用乘数。额定电压筛选仍只是单体>=4V筛选，并不表示过冲合格；本方案并联，不额外引入串联均压任务。

下一份实体交付仍是Cout原生阵列，但先冻结满足>=4V（优选6.3V）的具体型号与数量。原厂新检索入口：[YAGEO T2091 A700/A720，2026-04-01](https://www.yageogroup.com/content/datasheet/asset/file/KEM_T2091_A700-A720)；这是另一版系列资料，不自动覆盖已归档的T2078或将其焊盘表套给不同case。只对逐型号核对的额定值、land图及页码建选型记录，未知的200kHz/热态数据仍未知，不把搜索摘要当型号认证。

执行顺序：①精确MPN及N、原厂land/极性与阵列布局；②基于当前可核验父板的新副本，原理图/BOM/PCB同步，保存重开与DRC；③两极铜排/接点/高度预算及真实磁件端子；④低能量控制/SR换流、掉电与故障恢复实测；⑤同修订制造检查及25/50/100A分级热验证。缺失的132线候选应恢复CAD与绑定回执后复核，不能仅恢复一个数字，也不重跑旧批次。

本轮改动为选型逻辑、候选执行要求及登记修复；未新增原生PCB铜线、未完成Cout实体阵列或控制/SR实测，NOT_FOR_FAB不变。

### 主线与本地整合（2026-11-11）

已核对并引入远端 `033b348` 的PR #93/#94：72颗T530布局工具、受限8网布线入口及对应测试，保留本地原厂资料、可复现登记与热态ESR修复。没有覆盖未提交的在途工作，未执行远端提交/推送。

本轮第一阶段已真实执行：26个生成线段经编辑器合并后铜线107→132，DRC199→183，父版未改、布局无漂移。原先缺失的历史132线副本不再作为证据，本轮新副本有独立SHA与原生回执。自动布线入口修复CLI超时超过60000ms及缺少显式打开PCB文档的问题；超时仍判失败，不接受中间结果。

已导出[72颗T530坐标与干涉清单](../hardware/dcx_main/g2/cout_t530_72_layout.json)，它仍绑定107线父版，不能伪称对132线或后续板已完成布局净距检查。下一次Cout与功率铜共同ECO必须重新绑定最新读回并重算65处穿越，而不是复制旧统计。72颗只是试排，不冻结制造数量；热态200kHz、厂家land和均流未通过。

[DeepSeek综合建议](../deepseek/20261111_integrated/reply.md)已取得。其“现有样机抽查”没有本地实物证据支持，不作为已完成或立即可执行的台架步骤。33.84mF相对7.05mF为4.8倍，理想2V储能从14.1mJ增至67.68mJ；这是电容能量计算，不是输入损耗或充电峰值。先用新容量及实际阻抗验证启动/限流/磁通，再低能量实测；不能沿用旧模型的启动结论。

统一下一路线：T530实际land/极性及72颗阵列与两极铜路联合ECO → 重新核对≤16mm装配、接点电阻和磁件真实端子 → 同修订原生网表/BOM/DRC → 控制/SR低能量关断和换流 → 25/50/100A热验证。5mm底排19.25mm方案淘汰；1.2mm底排的20µΩ接点场景仍待实测。NOT_FOR_FAB不变。
