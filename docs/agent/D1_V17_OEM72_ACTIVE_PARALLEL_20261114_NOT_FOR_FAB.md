# D1 子 Agent 并行执行包（2026-11-14；实体 CAD WIP，NOT_FOR_FAB）

## 共同基线（已实际写入，不再退回摆放图）

- **工程对象**：48 V→约2 V 固定比 LLC-DCX；前级负责稳压；100 A验证平台与高密度产品开发分别验收。产品阶段目标：负载端≥180 W、完整体积≤90 cm³、≥2 W/cm³、≥95%目标效率、≤16 mm总高，均尚未实证。
- **共同只读设计输入**：`hardware/dcx_main/g2/dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb`，SHA256 `4bdb3492959aa08e70716a0f6ca020fe8cf98da66f08c795b72f8172b5ab50f9`。必须冻结源；**不等于原生嘉立创V18**，不得直接覆盖或二进制合并V18。
- **已完成实体**：V17完整149器件/425焊盘/12铜层/11铺铜区域；72颗T530 X-case原厂B级焊盘及9.12×5.10mm courtyard落到主板，左右镜像36件转180°，逐脚`VOUT/PGND`保留，母板源SHA可追溯。接着在独立候选新增3条1.8mm VIN_P（J_IN.1→QH.5）和2条SW（QH.1→Cr.1，1.8mm主段/0.8mm过渡段）实铜。第三版**真实KiCad DRC 0 rule violations / 7 unconnected**；5项原生DRC检查仍被忽略，**不能**写成“制造DRC全部通过”。所有DRC由相应同名`*_native_DRC_NOT_FOR_FAB.json`记录，三阶段9→8→7可复测。
- **未闭合**：VIN_P 1（Cin正极）、SW 2、GH 1、GH_DRV 1、HB 1、OC 1；五物理磁件CT/T1–T4、24端子与真实绕组不在本KiCad DRC的网络覆盖内。PGND/VOUT显示无未连接不等于其100A热态/EMC合格。材料ESR、启动、极性与厂家认证尚无签字。详见 [源绑定三阶段门禁](../../hardware/dcx_main/g2/g2_v17_OEM_T530_72_VIN_SW_consolidated_gate_NOT_FOR_FAB.json)。
- **环境**：`D:\workshop\design_48v-2v`有未提交的工作、嘉立创GUI运行状态不稳定；**禁止**重置/清理/覆盖；各自独立git worktree。KiCad 10路径`C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\`；仿真必须遵守`docs/agent/ENVIRONMENT.md`中的远端要求。零费用约束不强制，但量化设计优先于堆昂贵器件。

## 可交由子 Agent 并行执行的三个独立写入区

| Lane | 专属任务（最低实体成果） | 严格允许写入范围 | 交付与完成条件 |
|---|---|---|---|
| **A / 原边真实功率PCB** | 从共同源拷贝**新命名**原生KiCad候选；重排Cin、QH、QL、Cr、CT、Lr；闭合剩余VIN_P/SW并优化真正的输入往返热环与GH/HB门驱Kelvin，不能以0.2mm线代替功率路径。对比V18的Cin近旁摆放并移植有用的几何子集 | `hardware/dcx_main/g2/d1_lane_a_*/`、`tools/d1_lane_a_*.py` 和 `docs/agent/D1_LANE_A_*.md`；不修改本基线/其他lane文件 | 新KiCad可重开、完整DRC JSON、与输入基线SHA一一对应的pin/net校验、功率铜宽与局部L/R/热态损耗评估、危险铜颈/开路明细。禁止只报“减少几项飞线” |
| **B / 实体磁件及制造层叠** | 设计并画出真实CT、T1–T4 PCB绕组，24 pin与DOT逐端映射，重评3:1:1的铜厚、槽孔、磁件窗口、层间绝缘；执行Maxwell实际激励、网格收敛与热态L(I)/B/Pcu/Pcore验证 | `hardware/dcx_main/g2/d1_lane_b_*/`、`design/v3/maxwell/d1_lane_b_*/`、`tools/d1_lane_b_*.py`、`docs/agent/D1_LANE_B_*.md`；不改A板 | 真正可读的绕组/机械CAD，端子层叠表、OEM/厂家待确认字段、Maxwell原始文件与数值收敛报告；必须说明与PGND/VOUT六层复用/冲突 |
| **C / 100A输出功率完整性、热和D0保护** | 以SR—Cout—负载侧置短路径为起点给出输出正负两极实体铜/端子/冷板联合布置；按15mm有效路径、≤150µΩ两极热态预算评估；实证低电压掉电默认关断、10路SR保护，核对3LPM和≤16mm总高；72颗Cout启动与动态 | `hardware/dcx_main/g2/d1_lane_c_*/`、`design/v3/stage_f/d1_lane_c_*/`、`tools/d1_lane_c_*.py`、`docs/agent/D1_LANE_C_*.md`；不改A/B板 | 可装配3D/铜路与冷板接口、Rloss/热网络、台架分级25/50/75/100A证据；无实测须明确`PENDING`，不写“热态已过” |

**集成者的唯一写入权**：最终统一PCB位于**新的独立集成分支**，A/B/C只交不可变输入SHA + 独立输出/原始测量。先对齐磁件24端子与多层使用，再移植A原边和C次级输出，重新运行原理图ERC、逐脚pin/net、独立DRC，最后3D冷板和完整电热/EMI验证。没有完整证据继续`NOT_FOR_FAB`。

## 子Agent领取工作包时必须执行

1. **每条Lane单独worktree**，以同一新基线commit为`base`。不得直接从已污染的用户主目录进行`reset --hard`/`git clean`；先`git status --short`和`git rev-parse HEAD`。
2. 用`tools/d1_v17_oem_copper_gate.py --check`及`python -m pytest tools/test_d1_v17_oem_copper_gate.py -q`确认锁定。KiCad本体仍需重新运行：`kicad-cli pcb drc --severity-all --format json -o <本lane输出> <本lane实际pcb>`。
3. 每个交付填写`base_commit`、`input_pcb_sha256`、`output_pcb_sha256`、`changed_nets`、`native_drc_before_after`、`copper_thickness_and_RMS_assumptions`、`unverified_fab_blockers`、`validation_commands`、`commit`；每个Lane独立PR。**不合并文件名相同但SHA不同的两份PCB或DRC**。
4. **严禁假阳性制造审批**：新阶段也要实际补齐5磁件、完整原理图、接点/铜路热态、12层厂商DFM、保护实测和EMI实测，禁止提前出Gerber或100A带电验证。

## 状态说明

这份文件是可供子Agent立即领取的执行合同；2026-11-14观察到本机WebCodex Runner `coding_agent_providers=[]`，**尚不能通过当前执行器自行启动三个真正的自主子Agent**。三个Lane仍是**待领取/待执行**，不能把已分工写成“已完成”。现有单会话完成的CAD改动与真实DRC结果仅属于共同基线。
