# D1 子 Agent 并行执行包（2026-11-14；实体 CAD WIP，NOT_FOR_FAB）

> **2026-11-14 用户优先级修订：先使48V→约2V LLC-DCX正常、安全、可重复地运行；3 LPM液冷冷板/≤16mm完整包络、极限功率密度和100A长期热稳态均后置。** 不允许把“冷板后置”理解成带故障风险的上电或取消必要散热；先有可靠的初始低功率功能验证，再扩大电流和热设计。本文优先于先前A/B/C交接文本中的同类排序。

## 实际完成路线（验收前不得宣称已运行）

| Gate | 必须真实完成的最低交付 | 必须保持的限制 |
|---|---|---|
| **G0 / 可上电准备（当前唯一P0）** | 真实可制造/可装配的完整工作电路，闭合关键主功率与驱动网；CT及所选变压器真实绕组和逐脚/DOT/极性核验；输入限流/软启动、驱动偏置、SR失偏置默认OFF、输出异常保护；明确器件BOM、ERC/DRC/原生网表和安全绝缘间距。低能量台架测试计划和观测点齐备。 | 目前五套磁件未实装，KiCad仍7未连接且D0关断仅有不完整证据，**G0未完成，不允许直接给原板48V/100A通电**；需要先修好板、磁件和保护。 |
| **G1 / 首次可靠运行** | 在**具备输入电流限制、独立保护/急停、适当临时散热和监测**的台架上，用设计允许的输入范围验证启动/关断、稳态功率变换、真实输出电压与电流、门极VGS、磁件极性、SR温度和异常关断；负载先从可控轻载开始。确认是固定比DCX、非稳压2V。 | 不擅自把48V额定输入降到LLC控制无法运行的电压；不用纯仿真结果假冒实测。“运行成功”需要原始波形与日志。 |
| **G2 / 提升输出能力** | G1过关后依次推进25/50/75/100A，核对热态VOUT/PGND损耗、SR均流、变压器/铜温、接点及保护SOA。每一级都需散热条件充分、稳态/故障判据满足；100A要求独立热管理验证。 | 功率/电流门槛未过不得直接跨级或全功率长时间试验。 |
| **G3 / 产品优化（明确后置）** | 3 LPM内嵌液冷冷板、完整≤16mm高度、≥2W/cm³功率密度、效率目标≥95%、长期热稳态与EMC/DFM制造验证。 | 此类产品化指标**不阻塞G0/G1功能验证**，也不能以功能验证代替G2/G3产品通过。 |

## 共同基线（已实际写入，不再退回摆放图）

- **工程对象**：48 V→约2 V 固定比 LLC-DCX；前级负责稳压；100 A验证平台与高密度产品开发分别验收。产品阶段目标：负载端≥180 W、完整体积≤90 cm³、≥2 W/cm³、≥95%目标效率、≤16 mm总高，均尚未实证。
- **共同只读设计输入**：`hardware/dcx_main/g2/dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb`，SHA256 `4bdb3492959aa08e70716a0f6ca020fe8cf98da66f08c795b72f8172b5ab50f9`。必须冻结源；**不等于原生嘉立创V18**，不得直接覆盖或二进制合并V18。
- **已完成实体**：V17完整149器件/425焊盘/12铜层/11铺铜区域；72颗T530 X-case原厂B级焊盘及9.12×5.10mm courtyard落到主板，左右镜像36件转180°，逐脚`VOUT/PGND`保留，母板源SHA可追溯。接着在独立候选新增3条1.8mm VIN_P（J_IN.1→QH.5）和2条SW（QH.1→Cr.1，1.8mm主段/0.8mm过渡段）实铜。第三版**真实KiCad DRC 0 rule violations / 7 unconnected**；5项原生DRC检查仍被忽略，**不能**写成“制造DRC全部通过”。所有DRC由相应同名`*_native_DRC_NOT_FOR_FAB.json`记录，三阶段9→8→7可复测。
- **未闭合**：VIN_P 1（Cin正极）、SW 2、GH 1、GH_DRV 1、HB 1、OC 1；五物理磁件CT/T1–T4、24端子与真实绕组不在本KiCad DRC的网络覆盖内。PGND/VOUT显示无未连接不等于其100A热态/EMC合格。材料ESR、启动、极性与厂家认证尚无签字。详见 [源绑定三阶段门禁](../../hardware/dcx_main/g2/g2_v17_OEM_T530_72_VIN_SW_consolidated_gate_NOT_FOR_FAB.json)。
- **环境**：`D:\workshop\design_48v-2v`有未提交的工作、嘉立创GUI运行状态不稳定；**禁止**重置/清理/覆盖；各自独立git worktree。KiCad 10路径`C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\`；仿真必须遵守`docs/agent/ENVIRONMENT.md`中的远端要求。零费用约束不强制，但量化设计优先于堆昂贵器件。

## 可交由子 Agent 并行执行的三个独立写入区

| Lane | 专属任务（最低实体成果） | 严格允许写入范围 | 交付与完成条件 |
|---|---|---|---|
| **A / 原边真实功率PCB（G0）** | 从共同源复制新命名KiCad候选，**优先闭合剩余VIN_P、SW、GH、GH_DRV、HB、OC等关键线路和输入主功率回路**；使整板原理图/原生网表、驱动偏置、功率铜路可靠。布局适当紧凑和控制回流检查同步做，但不追求G3极限EMC/功率密度。 | `hardware/dcx_main/g2/d1_lane_a_*/`、`tools/d1_lane_a_*.py` 和 `docs/agent/D1_LANE_A_*.md`；不修改本基线/其他lane文件 | 具备真实元件与电网关系的KiCad候选、原理图/ERC/真实DRC、逐脚pin-net复核；明确主电流铜颈/开路残项。目标是G0可装配，而不仅是减少飞线数。 |
| **B / 最小可工作磁件（G0）** | **先**确定Lr、CT及至少一套真实3:1:1变压器的可装配绕组/物理端子、DOT/匝比/绝缘/工作点；若单单元无法独立成完整电路，则同步补齐首轮实际电路所需磁件。**之后**扩为T1–T4的24端子整板和完整Maxwell多工况网格无关性。 | `hardware/dcx_main/g2/d1_lane_b_*/`、`design/v3/maxwell/d1_lane_b_*/`、`tools/d1_lane_b_*.py`、`docs/agent/D1_LANE_B_*.md`；不改A板 | 真实物理绕组CAD、各端子网络/极性、基础L/Lm/漏感/绕组直流电阻及饱和/绝缘风险，首轮电源运行的最低必需磁件完整；Maxwell进阶优化不阻塞已验证的低功率台架起步。 |
| **C / 供电与D0保护（G0/G1）** | **立即优先**驱动电源、自举/偏置、UVLO/过流/软启动、D0失偏置默认OFF、同步整流异常关断及首轮低功率台架观测设计；同步核对输出回路基本连通性/电流路径与临时散热。100A两极铜排、温升/3LPM液路**移至G2/G3**，不阻挡低功率功能验证。 | `hardware/dcx_main/g2/d1_lane_c_*/`、`design/v3/stage_f/d1_lane_c_*/`、`tools/d1_lane_c_*.py`、`docs/agent/D1_LANE_C_*.md`；不改A/B板 | 可重现启动/失偏置与保护仿真、实装与低能量验证步骤、可测VGS/输入/输出和应急关断方案，实际原始波形缺失标为`PENDING`；G0/G1通过后再100A/冷板专项。 |

**集成者的唯一写入权**：最终统一PCB位于**新的独立集成分支**，A/B/C只交不可变输入SHA + 独立输出/原始测量。先用G0完整运行电路所需的实体磁件/极性/安全保护和A原边线路建立**最小可用电气样机**，重新进行ERC、逐脚pin-net、独立DRC；G1低功率上电实证后才将100A铜件、3D液冷与完整电热/EMI制造要求纳入G2/G3。没有完整证据继续`NOT_FOR_FAB`。

## 子Agent领取工作包时必须执行

1. **每条Lane单独worktree**，以同一新基线commit为`base`。不得直接从已污染的用户主目录进行`reset --hard`/`git clean`；先`git status --short`和`git rev-parse HEAD`。
2. 用`tools/d1_v17_oem_copper_gate.py --check`及`python -m pytest tools/test_d1_v17_oem_copper_gate.py -q`确认锁定。KiCad本体仍需重新运行：`kicad-cli pcb drc --severity-all --format json -o <本lane输出> <本lane实际pcb>`。
3. 每个交付填写`base_commit`、`input_pcb_sha256`、`output_pcb_sha256`、`changed_nets`、`native_drc_before_after`、`copper_thickness_and_RMS_assumptions`、`unverified_fab_blockers`、`validation_commands`、`commit`；每个Lane独立PR。**不合并文件名相同但SHA不同的两份PCB或DRC**。
4. **严禁假阳性制造审批**：G0必须补齐可运行电路所需的全部磁件、完整原理图、关键线路、绝缘/限流/关断；G1有实际波形及温升后才称功能运行。完整100A、3 LPM冷板、12层厂商DFM和EMI验证是后续产品化关口；现阶段不得冒称完成，更不得提前100A高能量测试。

## 状态说明

这份文件是可供子Agent立即领取的执行合同；2026-11-14观察到本机WebCodex Runner `coding_agent_providers=[]`，**尚不能通过当前执行器自行启动三个真正的自主子Agent**。三个Lane仍是**待领取/待执行**，不能把已分工写成“已完成”。现有单会话完成的CAD改动与真实DRC结果仅属于共同基线。
