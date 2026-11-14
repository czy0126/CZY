# Issue #133 / Lane C — HS 引脚、自举与双路 12V UVLO 候选（2026-11-14，NOT_FOR_FAB）

## 实际修复范围与保留边界

本文配套 **可打开的独立原生 KiCad 工程**：
`hardware/dcx_main/g2/d1_lane_c_hs_reference_NOT_FOR_FAB/d0_lane_c_hs_reference_NOT_FOR_FAB.kicad_sch`。在不修改共享 D0 源文件、不修改 V17 原边 PCB、不覆盖 Lane A/B 的前提下，由 `tools/d1_lane_c_hs_candidate.py --write` 从已提交 D0 原理图器件表复制并施行以下电气修正。报告为 `hs_interface_contract_NOT_FOR_FAB.json`，KiCad 原生导出的 `.net` 和 `*_erc.json` 属于独立证据。**这是实验室非隔离台架接口的工程候选，并不是完整48V LLC主板，也不是可直接制板与上电的交付。**

### 1. 主驱动/高侧真实管脚

- 原 D0 台架 `U18`（UCC27282DRCR）把 DRC 的 **5 = HS** 绑 `PGND`，本候选改为 `SW`。管脚 9 = VSS 与 11 = 散热焊盘仍归 `PGND`；3 = HB、4 = HO、6 = EN、10 = LO 不变。这一修改与主板黄金网表 U2.5=SW 一致。
- `C29` 的负端从 `PGND` 改为 `SW`，形成 **HB–SW** 自举电容；暂定 220 nF / 25 V 与主板文献基线 C5=220nF 对齐，但真实 MLCC 直流偏置、封装、ESR、驱动峰值、充电路径均未验证。器件内部自举二极管由 UCC27282 本身提供，**不得重复把文献 D_BT 的耐压或电路直接套入本台架**。
- `R64` 高侧栅源泄放电阻及 `C40` 4 nF 等效栅极电容均改为 `GH1–SW`。正确的测量是 **VGS_H=V(GH1)−V(SW)**，自举是 **VBOOT=V(HB)−V(SW)**。已新增 SW、GH1、HB 差分探头焊盘 TP20–TP22。
- 原本的 **D17 + R74** 把高侧的 GH1 绝对电压送入 `GSMAX`（相对地检测）。当 SW 升至约48V时，不可能等同于VGS；已将这两只标成 **DNP** 并强制 BOM 与脚本校核。**硬件高侧VGS检测仍缺失，这是明确的G0阻塞，不允许把只剩9条的GSMAX当成10条合格检测。**

### 2. 12V 失电检测与短暂关断能量

- 保留外部 12V 台架输入、保险丝 F1/F2 与二极管 D1/D2。将 UVLO 的 R20.1 从下游 `V12P` 改到上游 `V12P_F`、R22.1 从 `V12S` 改到 `V12S_F`，以便先感知外部电源掉电，而不被下游持压电容掩盖。**该候选仍使用共用 PGND，不满足隔离 DCX 的真实一次/二次供电隔离证明。**
- 将 R21/R23 从14.7k改为10k，R20/R22保持100k、比较器参考1.000V；增加 R110/R111=1M 从 `V12P_OK/V12S_OK` 正反馈到各自 `SNS`，在理想5V高/0V低输出下得到**典型名义** 上升11.1V、下降10.6V（0.5V迟滞）。输出高电平由10k上拉提供，真实电平偏差、1%/温漂容差与LM393速度需单独实测。
- C14/C15从100nF缩小至1nF，按100k∥10k∥1M得到约9.01us输入滤波常数；新增 D1/D2 后端的 C114/C115=22uF/25V 保持电容，旨在前端欠压检测后给驱动一个**候选**有源下拉窗口。但有效容量可能被直流偏置/温升降低；实物供电电流与硬短路故障尚未上界化，不能据此宣称关断电源合格。
- `R45` 强制 **DNP**，避免用 1k 将 PERMIT_RAIL 无条件拉高。故障锁存、EN默认下拉及原芯片数据手册时序依然要接受物理故障注入。暂不将 UCC24624 的模拟同步整流算法替换成 UCC27524A TTL 作为主板设计签核。

### 3. 独立外部急停/高侧监测的最终许可门（本轮补齐原生连接）

本候选新增 `U20`（CD4081BE），不再把原 `U8.10` 的 `PERMIT` 直接送往 Q1。该引脚改为 `PERMIT_INTERNAL`，经过两级硬件与门才获得最终 `PERMIT = PERMIT_INTERNAL AND ESTOP_OK AND HS_MON_OK`；下游 `R33→Q1→Q2→PERMIT_RAIL` 保持不变。KiCad 的 **U20A 3 脚为输出**，**U20B 4 脚为输出、5/6 脚为输入**，禁用的 U20C/D 输入接地、输出 NC；这些都按实体引脚在原生网表和 ERC 中核对。

- `J11`：外部 **常闭急停串联回路**由 V5 经触点送入 `ESTOP_OK`，触点断开/线缆脱落由 `R112=10k` 拉低；`J12`：合格的**隔离高侧门极状态监测模块**通过触点从 V5 向 `HS_MON_OK` 发出许可，缺监测器由 `R113=10k` 拉低。J12 不是已有的浮地 VGS 传感器，只是**必须连接未来真实监测器**的默认禁止接口。
- `R114=10k` 让最终 `PERMIT` 在 U20 无电/高阻时回到 PGND；`TP23/TP24` 为两项外部许可测点，原 TP15/TP16 仍可分别验证 `PERMIT/PERMIT_RAIL`。任何外部许可为低时都不得有驱动使能。**逻辑真值表与 KiCad 接线已检查，门传播时间、欠压瞬态以及实际 EN/VGS 关闭时间未测试。**
- 必须实际安装**独立物理切断 48 V 输入**的安全急停硬件（接触器或适当等级的断能电路），并验证触点熔焊、线路短接、V5 塌缩及上电复位行为。此处 J11 只是控制许可链，绝不能冒充断能/电气安全等级证明。J12 实际浮地门极监测必须通过隔离与动态门极命令对应性试验，不能由简单手动跳线永久置高。**无外部监测器与 E-stop 时此候选按照设计保持不可启动。**

本轮再次实际执行 KiCad 10 的 `sch export netlist` 和 `sch erc --severity-all`，**565 个声明引脚与原生导出网表逐项一致、ERC 0 违规（保留 4 类原工程忽略项）**。新增对 U20 输入/输出脚错连、U8 绕过最终门、J11/J12 断线、R112–R114 缺失/错误返回的回归测试。整组 Lane C 检查共 43 项通过（仅软件/电路图级别），**G0/G1 仍未获得硬件签核**。

### 4. 仿真证据与新版 KiCad 工程不得混用

上一版 `d1_lane_c_uvlo_holdup_illustrative_NOT_FOR_FAB` 的 LTspice deck、原日志和 .raw.gz **保持原封不动**，它在新增 U20/J11/J12 前运行，没有模拟外部急停/高侧监测的两级与门。因此原收据中 `native_candidate_schematic_sha256` 和 `native_candidate_bom_sha256` 是**当时实际采用的工程 SHA**，不允许悄悄改成当前新 CAD 的哈希。已在收据中分别记录 `current_candidate_schematic_sha256`、`current_candidate_bom_sha256`，并标识 `candidate_matches_original_simulation_snapshot=false`、`model_includes_new_external_estop_and_hs_monitor_gate=false`，保持 G0 拒绝放行。重算 `d1_lane_c_uvlo_evidence.py --check` 只证明**历史原始模型文件与证据一致**，不是新 U20 或真实MOS延迟的仿真证明。

### 5. 已完成的真实工具验证及边界

- 在本机 KiCad 10.0 执行 `sch export netlist` 与 `sch erc --severity-all --format json`，得到**565个源器件表/真实导出网表引脚对应，ERC违规0**。图仍有 ERC 项目忽略项且不是制造DRC。新增生成器可复现工程本身、BOM与DNP，并能拒绝重新接回PGND、移除失偏置监测/保险丝、错误焊接高侧检测和无条件RUN等回归。
- 在远端 `winsrv` 使用固定版本 LTspice 26.0.2 对**初始化后稳态失电故障**跑了一次理想一阶模型 `d1_lane_c_uvlo_holdup_illustrative_NOT_FOR_FAB.cir`，保留源 `.cir`、原始 `.log`、压缩 `.raw.gz`、SHA证据 JSON。100us 令输入由12V快速跌落至0后，理想电路的 UVLO 翻转于 **101.119us**，栅极下降至1.3V 于 **101.134us**（仅理想3.1Ω输出开关，差约14.8ns）；保持电容电压在130us约11.682V、200us约11.619V。**模型的理想比较器、理想开关和随意设定的20mA负载不能推导真实最坏时延**。1.3V只是器件阈值参考，不能视为安全OFF限值。
- 复核命令：`python tools/d1_lane_c_hs_candidate.py --check`；`python tools/d1_lane_c_uvlo_evidence.py --check`；`python -m pytest tools/d1_lane_c_test_hs_candidate.py tools/d1_lane_c_test_uvlo_evidence.py -q`。原 Lane C 17项既有回归与源码哈希检查仍必须通过。

### 6. 下一步交给集成者的硬件阻塞（不可虚报）

1. **负责人：Lane C**。对 LM393 实际上升/下降波形、比较器失电状态、5V基准及软启动/ACK是否触发正确锁存做独立台架验证；给出阈值离散与最坏传播延迟范围。对 C114/C115 的厂家有效容量、ESR、漏电、失电初始电流及断供端短路做实测，计算 `Ceff >= (Iquiescent*Tshutdown + Qg_total)/(Vinitial_min−VDD_min)`，并用真实MOSFET逐路VGS完成失偏置关断。
2. **负责人：Lane C / 电气集成者**。选定可用的48V→12V偏置电源与一次/二次隔离方案、回路保护和硬件独立急停，重画实际主板带网的 V12P/V12S/5V/UVLO/EN，禁止双供电共地台架被误认隔离型主板；校核无偏置、开路、短路下默认OFF。
3. **负责人：电气集成者**。把本独立候选的 UCC27282 HS=SW、HB–SW、GH1–SW 连接原则与主板 U2/C5/QH/D_BT逐脚比较，不直接替换原板；主板的源网表、制造BOM与DRC都必须分别重新生成。D17/R74不只是“忘装的可选件”，需要**新的浮地VGS检测与故障释放逻辑**，还要保留原UCC24624真实同步整流控制和第三象限测试。
4. **负责人：Lane A/B及电气集成者**。闭合原边7处未连、磁件24端子真实绕组/DOT、输出铜与各部件间实际隔离，原始汇总的旧DRC SHA需要在公共写权限下复核再生成。
5. **负责人：G1硬件台架操作人员**。只有各项G0通过后才能做标称输入附近的限流轻载上电；逐一保存 U18差分VGS、高侧bootstrap、电源欠压、8路SR VGS、VIN/IIN/VOUT/IOUT、温度、故障急停的原始记录与仪器标识。**G0、G1以及制造审批均保持PENDING**；G2 25/50/75/100A 和 G3 3 LPM冷板后置。
