# D1 V17 / V18 版本裁决与单主线决策（2026-11-15，NOT_FOR_FAB）

> **决定**：面向“先能够正常启动和变换，再提升至100A，最后3 LPM液冷”，只继续推进 **V17 KiCad 后续连接闭合版（PR #137 / commit `9c87bea`）的 PCB 布局/绕组集成**。**V18 嘉立创原生工程（PR #130）降级为电气/封装/布局事实核验的参照，不再平行投入106项原生飞线的无差别修复。** 正式的源原理图仍以已经真实读回的嘉立创 P1 为起点，但任何电气改动必须先对齐独立 SCH/ERC/netlist，不能仅凭相同网名假设等价。这是设计选型决策，不是认可V17发板或上电。

## 必须区分的三份版本

1. **V17 嘉立创原生 V17**：原生 `.eprj2` 历史版本，是 V18 克隆起点，源文件名 `dcx_main_board_g2_V17_REAL_NATIVE_JLC_CAP_AND_PGND_LAYOUT_WIP_NOT_FOR_FAB.eprj2`，原记录源文件 SHA256 `7c9fe44004b3490ddf7c599385d57a8471803a146cdf8c16cc36d544d33cb95a`。此源二进制未见于当前PR #130 head所追踪的文件列表；不可声称本次已重新打开核验其全部结构。
2. **V17 KiCad 重建工程**：沿 V15 的 149 器件对应关系做独立 KiCad 10 主板、T530 OEM封装、11铺铜区域、12层连接修复。实际选定的是 `hardware/dcx_main/g2/d1_lane_a_connectivity/six_net_trial_04_NOT_FOR_FAB.kicad_pcb`，SHA256 `85fff295c2c8bd594266881b711584be02b40b2158e266e8df4a2ba77d6bb76c`，commit `9c87bea`，PR #137。真实KiCad10.0.6重开与native DRC：**0启用规则违规/0未连接**，继承5项已有被忽略的检查；这只覆盖已经建模的PCB，不是完整五磁件样机。
3. **V18 嘉立创原生板**：直接从上述原生V17克隆并对Cin/T1同步整流/Lr实际改位，当前关联PR #130 head commit `06de46a`；保存文件 `hardware/dcx_main/g2/dcx_main_board_g2_V18_CIN_T1_LR_RELAYOUT_NATIVE_SAVED_NOT_FOR_FAB.eprj2`，二进制 SHA256 `b291faea3b46c1d7ec4e7b54d57dd78a20e70523a2a629760f49d5141f7c7739`。原生独立二次DRC **106 Connection Errors**，其中**PGND 38**，规则误设 `JLCPCB Capability(Two Layers Board)`；149器件、423焊盘、508线、106过孔。真实存在但不是可制造版。

## 两版具体几何、网表、铜层差异（已对工程物件核查）

| 核查点 | V17 KiCad 闭合版 | V18 原生 |
|---|---|---|
| 组件参考编号 | 149 | 149，**与V17完全同一组ref** |
| 已建模网络名称 | 62 | 62，**两边集合一致** |
| 实体焊盘 | 425 | 423；逐脚（ref/pin/net）多重集有**419个共同项**，不是425/423逐点全一致 |
| 72颗CHB T530 | CHB01…72皆有、两个OEM-B焊盘2.37×2.43 mm | 同样CHB01…72，焊盘也是2.37×2.43 mm，**不能说V18缺原厂焊盘尺寸** |
| 端子差异 | J_OUT两个网络各4个同编号重复大焊盘5.5×5.5mm（相对V18多6个焊盘） | J_OUT每个网络一个1.8×1.8mm焊盘；此外保留4个不属于已注册元件的CT原边/副边自由焊盘（PRI_A、PRI_B、SEC_A、SEC_B），它们**并非完成的磁件** |
| 实际层与铺铜 | 12铜层定义、11区域，出板前需检查区/内层承载电流及DFM | 现场只读原生线段 427条顶层/75条底层；后续移位版本508线/106过孔，仍采用两层板规则，未验收真实12层铜与大电流回流 |
| 连接检查 | 0规则违规、0未连接，5项既有ignored；磁件未纳入 | 106连接错、38 PGND错，未取得完整制造DRC |
| 关键位置（mm，主板坐标系并不相同） | Cr(40,7)、Lr(25,7)、QH(48,7)、QL(57,7)、Cin(51.5,13.5) | 保存后 Lr(26,79)、Cr(72,52)、QH(48,50)、QL(57,50)、Cin(43,44) |
| Cr–Lr中心直距 | **15.0 mm** | **53.3 mm**，不是完整寄生电感估算，但明显不利于短谐振环路 |
| 真实性范围 | 有真实KiCad实铜和DRC，但SCH/ERC未独立全量签署，缺五磁件24引脚 | 有真实可编辑EasyEDA全项目和原生PCB，优势是电路/库/PCB同生态；但长谐振路径、错误DRC阻断首件 |

**注意**：J_OUT差异意味着KiCad重建不是原生V18的逐pad位拷贝；既不能用`419`个相同ref/pin/net对就称“完整ERC一致”，也不能把V18的四个自由CT Pad视作已装CT。两边的T1–T4/CT真实PCB绕组和电气极性都**未完成**。

V18原生实做的有价值内容：Cin原从(92.4,43)改到(43,44)，缩短输入热环；SR1/T1整流单元上移后距离减少，局部走线随元件同步位移。**但不要将Lr移到(26,79)的几何和106连接错的铜线直接迁入V17**。V17原边靠近Cr/Lr/半桥的布局应作为保留区，持续做电流回流、铜截面和EMI验证，而不是仅追求DRC为零。

## 工作流冻结：只保留一个 PCB 集成主线

- **主版PCB唯一源**：GitHub PR #137 `feat/d1-v19-lane-a-primary-power-20261114` 的 `six_net_trial_04_NOT_FOR_FAB.kicad_pcb`（本页原始SHA锁定）。
- **原理图与引脚核验**：保留 EasyEDA P1以及PR #130的原生工程作受控只读电气依据，建立正式逐网/逐器件/逐pad/net对比和ERC签字；禁止单方面“自动补齐”没有真实绕组的网络。
- **A/B/C同步策略**：A继续做KiCad主板铜路及供电安全；B必须对该主板设计全套T1–T4、CT真实绕组、24端子及绝缘；C必须用同一版板的偏置/关断信号与测点验证保护。B、C当前已自有独立工作树，**不要强行reset/rebase正在改的分支**；输出CAD/证据经审查后在单独集成分支合并到这份KiCad PCB，重新运行SCH/ERC/DRC。禁止回头继续做第二份并行布局板。
- **V18状态**：保留独立可重开的原生快照与PR #130供几何回查/后续嘉立创移植；不继续为了让其106飞线归零而浪费主线人力。若最后必须交付嘉立创原生文件，以完成G0的KiCad PCB做单次受控导入，逐网/器件/焊盘/铜/层叠比对和嘉立创DRC再签核；不能假设导入天然可靠。
- **G1（首个可用样机）** 入口：先真实闭合CT/T1–T4与驱动和OC/D0保护，补齐完整原理图网表、制造间距、限流与失偏置默认关断，再受控轻载测出真实波形。**不能直接上48V/100A**。
- **后置G2/G3**：100A逐级电流、各层并联与过孔电热、EMI，最后3 LPM冷板/≤16mm/2Wcm³产品形态。这些不阻塞G0最小安全电气样机，但首试仍需要临时散热与安全急停。

## 证据清单（均为工程文件而非编造指标）

- [V17 KiCad 真正7→0原生铜路](D1_LANE_A_CONNECTION_REPAIR_20261115_NOT_FOR_FAB.md)，其原生保存板/原生DRC JSON均随PR #137提交。
- GitHub [PR #130](https://github.com/czy0126/CZY/pull/130)，原生V18二进制、历史源SHA和`g2_v18_independent_post_T1_Lr_relayout_real_native_DRC_AND_30primitive_readback_NOT_FOR_FAB.json`，及`g2_v18_actual_native_before_powercell_layout_149parts_READONLY_NOT_FOR_FAB.json`。
- GitHub [PR #137](https://github.com/czy0126/CZY/pull/137)，保存的V17 KiCad与源绑定检验。
- 主本机根目录的 `hardware/dcx_main/g1` 是**另一条正在修改的G1原生工程**：2026-11-15较新回执`g1_r8_1k_connected_drc.json`为130 Connection/1 Netlist，不等于PR #130的V18从106退化到130，也不得未经对源SHA核查就算到V17/V18指标中。G1相关在途脏文件保持原样，不覆盖。
