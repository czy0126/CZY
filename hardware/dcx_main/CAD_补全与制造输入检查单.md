# D1 原理图补全与制造输入检查单

> 自动核对：`python tools/d1_bom_coverage.py`、`python tools/d1_fabrication_gate.py`  
> 当前工况：48 V→约 2 V、固定比 24:1、100 A 基准，111.16 A 仅为 LTspice 仿真工况。**非投板、非额定放行。**  
> 项目优先级：电气/可制造设计优先，冷板/详细热设计暂缓；安全的电应力、绝缘与保护验收不豁免。

## A. 已补画（仍缺 MPN/封装）：17 个黄金 SPICE 网表里没有的真实 BOM 位号

**2026-11-02 状态**：17 只已画进原生原理图并逐焊盘核对——
`netlist_compare.json` 的 `peripheral_pads_checked = 34`、`missing_or_wrong = 0`、`unexpected_nets = 0`，
`bom_coverage.json` 的 `required_bom_refs_missing_from_native_design` 已为 `[]`。
它们仍以 0603 通用符号 + `PLACEHOLDER` 注释存在，**值冻结、MPN 未定**，
所以制造门槛没有因此变绿（`d1_fabrication_gate.json` 仍 `NOT_FOR_FAB`）。

来源：`design/v3/bom/bom_draft.csv`，机器展开后列于 `bom_coverage.json`。这组缺口**不是**原先“五磁件尚未放置”的同一个问题：

| 位号 | 原 BOM 功能/参数候选 | 必须补齐的实际设计 |
|---|---|---|
| R7 | U2 EN 到 PGND，10 kΩ | EN 默认安全态、电平转换与上电顺序 |
| R8 | U2 RUN 跳线到 12V_P，1 kΩ | RUN 受控接入/禁用，不允许浮空 |
| R9 | U2 HI 到 PGND，10 kΩ | 驱动输入默认关闭，确认 UCC27282 引脚与逻辑极性 |
| R10 | U2 LI 到 PGND，10 kΩ | 驱动输入默认关闭，确认互锁与关断动作 |
| C13 | U2 EN 滤波，1 nF | 滤波节点/引脚与 R7、R8 连接一致 |
| C101–C112 | 六只控制 IC 的本地去耦，1 µF + 100 nF/IC | 每个控制器紧邻 VDD-GND 的两只电容、真实耐压、布局/回流；**不要简单把 12 只当作 12 个相同值** |
| PS1（外部接口） | 12V_P/12V_S 偏置 | 可为外置供电，不强制占一个 PCB 封装；但需明确接头、返回地、隔离约束、上电顺序、功率计量 |

**注意**：上表仅引用 BOM 现有候选值，不能替代厂商典型电路校核。若主板的控制接口与原 BOM 冲突，必须先形成 ECO，不能为满足行数而盲目接线。

## B. 五只磁件：符号已画，**实体端子仍未核实**

**2026-11-02 状态**：`DCX_XFMR_5P`（用于 T1–T4）与 `DCX_CT_4P` 两个项目库符号已建、已放置，
`.eprj2` 里共 **83 个位号**；原生导出网表已把 24 个逻辑端子全部连到正确网络
（`netlist_compare.json` 对 `T1`/`CT` 等逐 pad 比对，`missing_or_wrong = 0`）。
`magnetics_symbol_contract.json` 的五条 `native_symbol_present` 由 `project_symbols.json`
派生，**不是**手填的。

仍未做的是**物理**那一半：

- 引脚号是逻辑端子名（`PRI_A`…），不是厂商编号。`physical_pad` 全部 `null`，
  `physical_pad_map_verified` 全部 `false`——名字对不等于极性对。
- T1–T4：每只五逻辑端 `PRI_A,PRI_B,SEC_A,SEC_B,CTAP`。**CTAP = 副边 A 同名端 + 副边 B 非同名端**，不能将两组同名端直接相连。
- CT（过流互感器）：四逻辑端 `PRI_A,PRI_B,SEC_A,SEC_B`；其实际同名端与针号必须由绕组工艺/首件确认，目前不能推断。
- **物理 pad 编号必须来自确认的端子图**，不能用“1–5”假定序号填入正式符号。
- 封装仍是占位件：CT 的符号 4 端 vs `XFMR-TH_ZHT104A` 2 焊盘，只为让网表能导出。
- 拿到端子图后，从原生嘉立创 EDA 导出全部网表并逐 pad 比对；在此之前任何自制磁件
  都不得以“逻辑网名符合”为由放行。

## C. 61 个占位位号与正式 BOM

`pin_footprint_review.csv` 目前 **61** 个位号含 `PLACEHOLDER`：39 个原有占位件 +
17 个 BOM 外围 + 5 只磁件（磁件的符号已画，占位的是封装与物理端子，见 §B）。`bom_draft.csv` 中还有 `TO SELECT/TO BUILD/TO ASSIGN` 的器件条目，应通过 **ref→value→MPN→package→footprint pad→net→source→status** 逐行审查。

其中必须优先核实：Cr（不能以 100 nF/0603 代替 620 nF 谐振电容）、Cin（真实 48 V 输入电容组）、Cout（15×470 µF 的真实封装与有效耐压）、D_BT（反压和结电容）、Lr（三匝候选及实测漏感补偿），以及门极电阻、CT 限流网络。相关电容必须在正式 BOM 中体现**数量和并联构造**，不是只画一个通用 `Cout` 占位。

## D. 制造 Gate：七类检查，全真才允许考虑发布

检查入口 `hardware/dcx_main/d1_fabrication_gate.json`；它从当前真实文件再生成。目前预期仍为 **NOT_FOR_FAB**。完成后需归档：
1. 原生 `.eprj2` 可编辑并含完整真实器件。
2. 原生 EDA 导出的全量网表以及黄金/新增外围/实际 pad 对应。
3. T1–T4、CT 真实物理脚号、极性与工艺卡签核。
4. 原生编辑器 ERC 带逐项错误、警告、豁免理由及修正版本。
5. 真正带网、带走线和连续铜层的 PCB，而不是 35 个占位对象的机械摆件。
6. 真实制造封装、叠层/沉槽、Gerber、钻孔、装配图、坐标/BOM 和 PCB DRC。
7. 负责人审核与制造包版本号；`--require-release` 在此之前应保持**非零退出**。

可选的三个手工证据记录路径分别为 `native_erc_approved.json`、`pcb_to_schematic_verified.json`、`fabrication_approval.json`。**它们尚未创建**；不能仅填写 `approved=true` 就代表真实证明。放行应人工核对报告实际存在、版本及签名；本地 Gate 只检查最少必需字段，非实物核验的替代品。

## E. 提升输出的最近一批验证

- **已有证据：** 48 V、16.9 mΩ 负载的 LTspice 仿真给出 111.16 A、208.83 W；探针仿真端口效率 94.53%，账本 `NOT_CLOSED`，**不是硬件实测**。
- **下一步先做：** 48 V / 120 A 候选的真实模型运行，保留原 110 A 工况做对照；同时建立 110 A 的外部输出路径补偿、SR 各组实际分流的非对称电阻敏感性、OC/Cr/Cout/RMS 限值表。
- **不得忽略：** 100 A 133 周期 5/2/1 ns 对照中原边端口差与 SR 损耗分项仍明显不收敛。暂不发布百分位后的“效率提升”结论。
  - **已完成专项排查**（`tools/sr_loss_audit.py` → `design/v3/stage_f/sr_loss_audit.json`）：量纲/符号由三条恒等式验证；
    不收敛的**只有体二极管正向导通**（沟道跨三步只动 0.03 W）；闭合里的外部驱动功率 `drv`
    原本多算了 `Rg+Rgs+Cpin ≈ 0.217 W`，修正后 133 周期三段进入 0.2 W，但 **16 周期窗口仍不能用**，
    `closure_status` 一律保持 `NOT_CLOSED`，效率口径不变。详见基线 §2.7。
- **暂缓：** 详细 CFD/冷板/连续额定温升。本阶段优先设计测试点与限能保护，连续工作能力待后续验证。

**当前直接任务：五只磁件的厂商端子图（符号与逻辑端子已画入，缺的是物理脚号/DOT）、61 个占位料号、GUI ERC，然后把原生原理图导入带网络的主 PCB；17 个 BOM 外围已画入但在正式料号选定前仍按占位件计。继续扩展文字审核不会让板子更接近制造。**
