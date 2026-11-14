# Issue #133 — Lane C G0/G1 电源偏置与 D0 安全关断交接（NOT_FOR_FAB）

当前唯一优先级是先得到**可安全启动和关断的48 V→约2 V LLC-DCX 低功率实物功能验证**，而不是先做100 A/3 LPM/16 mm。此文档是**已核对源文件的工程交接与拒绝放行记录**，不是宣布已制作硬件或已实测成功。

## 已直接核查的工程事实

- 共同只读输入PCB为 `hardware/dcx_main/g2/dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb`；其锁定 SHA256 由本 Lane 工具复验。现有V17汇总报告中的部分原生DRC文件SHA与实际原生报告不同，因此上游 `d1_v17_oem_copper_gate.py --check` 会提示汇总过期；本Lane只报告该证据不一致，不越权改写公共汇总。**不覆盖原板或A/B Lane**。源报告仍为0规则违规、7处未连接、5类检查被忽略；不得将其转写为制造通过。
- 独立的 `pcb/d0_protection` 是**台架D0十路门极检测/驱动替代验证板**，并非实际主板的原生完整电路；按其器件表审查共有**8条SR门极 GA1–GA8 + 2条原边 GH1/GL1**，不是10条SR驱动。对应实际原理图引脚/实体封装及主板整合还未完成。
- U14–U17为4片UCC27524ADR，每片两路，两个EN都挂`PERMIT_RAIL`，由R36–R43八只4.7k下拉对抗各EN内部上拉；U18 UCC27282 EN也接`PERMIT_RAIL`，其EN自身下拉。R45 (V12P→PERMIT_RAIL 1k) **必须 DNP**，否则可能破坏默认关断。
- 每个门极有2.2Ω串阻、10k下拉、1k检测支路、独立BAT54ZFILM检测二极管，经`GSMAX`感知残余电压；但**检测不等于主动拉低**。`R64/R65`给原边，`R56–R63`给SR。
- `C29` 在现有**台架**D0表内连接HB→PGND，不能当作实际半桥HB→HS自举电容设计直接合并。真实U18高侧与主板的SW/HS/BOOT逐脚对应、驱动供电、启停时序均待封闭。
- `tools/d0_response_budget.py`揭示LM393只有typ传播延迟，CD4081B不具备完整最大延迟；UCC27524A 失去V12S时10k被动放电仍可能持续百微秒级。**不能写成“D0安全关断已验证”**。
- D0 bench改用UCC27524ADR的数字TTL门极路径，对既有UCC24624同步整流控制**不等效**；若决定采用该替代方案，必须重新实测第三象限反向导通/电流均流和故障保护，不能只做引脚替换。

## 已交付的可执行核查

`python tools/d1_lane_c_g0_gate.py --write` 生成 `design/v3/stage_f/d1_lane_c_g0/g0_wiring_and_fault_gate_NOT_FOR_FAB.json`，将输入PCB和D0 schematic/netlist哈希与10条门极逐路的驱动、串阻、下拉、检测二极管、对应电源引脚绑定。每次读源重算，错误/缺失件会直接失败；`--check` 检测过期报告；`--require-g0` 在没有真实制造和测量条件时明确拒绝放行。回归测试专门插入虚假门极、EN和DNP错误，验证能否被拒绝。

**请勿以“十路检测逻辑正确”“ERP/ERC通过”“保护延时理论值”为上电许可。** 输出JSON对所有缺失测试都写`PENDING`，`gate_0_approved`/`gate_1_measured_success`/`energization_allowed`始终为false。

## 必需的实际硬件修复顺序（P0）

1. 原理图层面明确12V原边/副边供电来源、不同参考地/隔离要求、电源ORing、UVLO迟滞、软启动、过流检测、先关原边后关SR的故障时序。**不得用原边V12P仅有电压就推断隔离副边V12S已经健康**。供电缺失/欠压/急停均必须独立拒绝`PERMIT`；硬件保护应不依赖固件。
2. 合并前对U18的`HB/HS/HO/LO/EN`逐脚核对真实开关节点和高侧驱动自举；给出`VB−VS`、`VGS_H`、`VGS_L`和SR每一路的差分测量点。D0台架版C29不能照抄到真实板。
3. 对SR1–SR8逐路进行`V12S`突失、上电欠压、故障关断、器件离散、死区及反向电流验证；若V12S突失后只有10k泄放，先做最坏失偏置门极放电与交叉导通SOA验证，必要时设计保持供电的独立关断/主动钳位方案。**不得一边用强推挽驱动输出高电平，一边直接硬钳门极**。
4. 原边失偏置时验证UCC27282驱动逻辑与MOS实测残余VGS，不得拿控制器停振替代功率管关断。故障发生后必须锁存禁止自动重启，操作者独立撤能、复位确认才允许下一轮。
5. A/B Lane闭合主功率与CT/T1–T4真实绕组后由集成者提交新的真实原理图、统一网表、ERC、原生DRC、pin-net映射及制造条件。Lane C没有权限修改这些公共输入，不能自行声称集成完成。

## 限流低能量台架步骤（G1；尚未执行）

**先G0签核，否则不接48V到主板**。准备有独立硬件切断/急停、隔离防护、供电限流和电压/电流记录的台架；临时风冷/散热器必须覆盖SR、磁件和功率管，温度探头位于高风险节点。上电前断电检查输入短路、输出极性、CT/DOT、栅源短路/极性和所有驱动偏置保险丝。先在隔离、限能的偏置台架上做不接主功率的EN、POR、ACK与门极放电验证，故障保持锁存且所有10路VGS真实触发测量，先原边停止、再确认SR没有异常导通。

只有硬件签核后，按控制器允许的实际Vin范围以**输入电流受限、负载受控、具备急停和适度临时散热**进行首次轻载运行；记录V12P/V12S/V5、PERMIT、VIN/IIN、VOUT/IOUT、HO/LO和SR1–SR8的差分VGS，测量电流与温度及软启动、关断、过流/急停事件时序。48V是标称条件，不擅自将输入电压降到控制器不能振荡的区域。任何异常立即急停并断能，数据以示波器原始文件和仪器/板号作证；无文件则`PENDING`。当且仅当G1合格才开始G2 25/50/75/100A。3LPM完整冷板是G3，不能反过来阻挡G0/G1，但临时散热不可取消。

## 验收状态与集成者签收

- **已完成**：十路保护接线表源代码绑定校验、锁定源SHA审计、故障清单/失偏置安全边界和禁止放行逻辑、自动回归测试。
- **尚未完成**：真实12V供电/UVLO/软启动和独立急停的实装闭环、U18高侧自举重画、真实A/B磁件和原边线路集成、原始示波器实测波形、10路故障硬件测试与真实低功率运行。
- `output_pcb_sha256=null`，`changed_nets=[]`，`native_drc_after=null`：本 Lane未私自提交一块未经集成验证的PCB；铜厚、损耗和SOA仍UNKNOWN。提交给集成者时以工具报告中的源SHA和commit作基准。

验证：`python tools/d1_lane_c_g0_gate.py --check`; `python tools/d1_lane_c_sim_evidence.py --check`; `python -m pytest tools/d1_lane_c_test_g0_gate.py tools/d1_lane_c_test_sim_evidence.py -q`。原生 `kicad-cli sch erc --severity-all` 对 D0 台架原理图重新运行报告 **0 条违规，但保留 4 类忽略检查**（见 `d0_bench_erc_readback_NOT_FOR_FAB.json`）；这是台架原理图 ERC 而非真实主板 DRC。上游 `python tools/d1_v17_oem_copper_gate.py --check` 与配套 1 项测试因现有汇总证据 stale 而失败，需集成者在公共范围按实际 DRC 重生成并复核。软件审查和台架原理图 ERC 不能证明 G0/G1 实物通过。

## 新增高侧参考电位硬缺陷（必须在主板集成时修复）

已逐项对照 TI [UCC27282 数据手册 SNVSAQ5B，Fig. 5-1 / Table 5-1](https://www.ti.com/lit/ds/symlink/ucc27282.pdf)：**DRC VSON-10 的 U18 引脚 5 是 HS，9 是 VSS**；HS 必须到实际高侧 MOSFET 的源极（半桥开关节点），C29 自举电容负极必须返回 HS。当前 D0 台架网表把 U18.5 和 U18.9 都接 **PGND**，并把 C29 负极、R64 高侧门极泄放返回 PGND；所以即便 KiCad ERC 为 0，也**不具备真实浮地高侧驱动的电气连法**。此外 D17→GSMAX 仅为地参考的门极指示，不能替代实际差分 V(GH1)-V(HS) 测量。

`python tools/d1_lane_c_g0_gate.py --check` 现在输出 `physical_high_side_reference_audit`，逐项拒绝上述错误作为 G0 成功证据。集成方需在实际主板闭合 HS/SW Kelvin、HB-HS 电容及高侧 G-S 泄放路径，重导原理图网表和 PCB DRC，针对真实实装型号核对封装与失偏置状态，并以安全差分探头记录高侧 VGS 波形。**本 Lane 只有报告/防误放行，不曾越过路径权限更改源 D0 台架或实际 PCB，更未给出实体安全放行。**

## 远端实际模型运行结果（独立可重放，不能替代实测）

已将`d1_lane_c_sr_gate_loss_illustrative_NOT_FOR_FAB.cir`传到`winsrv`，按项目规定的`D:\ADI\LTspice-26.0.2\LTspice.exe`仿真并取回原始`.log`和压缩原始`.raw.gz`。模型只对比**驱动仍有偏置的理想下拉**与**驱动完全高阻时靠10k泄放**，不是原理图连接的完整动态模型，不会自动证明SR关断。

在12 V初始门极、6.7 nF台架假负载、10k泄放下，门极下降至用于演算的1.3 V点为 **148.910 µs**；理想化3.1Ω驱动下拉为 **46.010 ns**。`1.3 V`是SR器件的VGS(th)最小参考值，**不是可保证的功率开关安全关断判据**。真实高频切换的Miller注入、驱动失电状态与MOSFET温度离散均未覆盖。

使用`python tools/d1_lane_c_sim_evidence.py --write`及`--check`可重新核对`.cir`、`.log`与归档`.raw.gz`的SHA、LTspice结束标识、两条波形阈值时刻及一阶RC计算一致性。此项仅状态`VALID_MODEL_RECEIPT_NOT_HARDWARE_PROOF`，不解锁G0。
