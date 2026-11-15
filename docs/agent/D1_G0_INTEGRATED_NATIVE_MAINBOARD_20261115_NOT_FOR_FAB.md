# D1 / 48V→约2V LLC-DCX — G0 154 器件整合主板 KiCad 工程（2026-11-15，NOT_FOR_FAB）

## 交付与使用

本阶段交付 **可编辑的 KiCad 10 原生 PCB+原生原理图校对视图**，以及 BOM、每个封装针脚的网表证据和原生 EDA 报告。工作树：`feat/d1-g0-integrated-mainboard-20261115`。**不是已经完成物理安全验证的可制板产品，不允许直接上 48 V 或送厂**。

请进入 `hardware/dcx_main/g2/d1_g0_integrated_mainboard_NOT_FOR_FAB`，打开同名前缀 `d1_g0_integrated_mainboard_ELECTRICAL_NOT_FOR_FAB` 的 `.kicad_pro`，并检查同名 `.kicad_pcb`、`.kicad_sch`。该目录同时含本地 `G0LogicalMainboard.kicad_sym`、`sym-lib-table`、`.net`、`_native_drc.json`、`_native_erc.json`、`d1_g0_integrated_trial_bom_UNQUALIFIED.csv` 和 `d1_g0_integrated_trial_package_NOT_FOR_FAB.json`。

## 已在实际 KiCad 10 中确认

- 在源 SHA 锁定的 V17 OEM-72 原生 KiCad PCB 上新增五个真实 PCB footprint 对象：T1–T4 和 CT；以已审查原生 P1 逻辑网表为准定义 **24 个逻辑焊盘**，并补充缺失的串联初级网 `PRI_12/PRI_23/PRI_34`。最终共 **154 个 PCB 封装对象**；原 149 个器件及 72 只 T530 OEM 电容阵列仍保留。
- 一轮原生试装曾造成 63 项 DRC 问题：实际板材 Edge.Cuts 在 y22–44 具有 12 个磁件开槽，原始逻辑焊盘坐标与板边、控制器等冲突。重新规划磁件逻辑落点后，独立布局候选 DRC = 0，但新增磁件使未连接合计 27 项。
- 从实际的 27 项 ratsnest 逐个补入 KiCad `PCB_TRACK`、`PCB_VIA` 内层走线，规避磁件槽、控制器、端子及细间距器件。最终试验 PCB 独立导出 `pcb drc --severity-all --format json`：**DRC 规则违规 0，未连接 0**。这只是**连接和几何 DRC**；铜载流量、走线发热、层压过孔、EMC、SI、绝缘不因 DRC=0 自动合格。
- 原始主板没有可直接关联的完整 KiCad 原理图；因此通过 `tools/d1_g0_native_schematic_projection.py` 由 **154 个封装对象的当前物理 Pad→Net** 生成了一个真实、可编辑的原生 `.kicad_sch` 网络映射，维持 **427 个不同的 Ref/Pin/Net**，不是只把文字表导成图。对该校对视图真实运行 `sch erc --severity-all`：**ERC 0**；同时由 `sch export netlist` 导出原始网表并逐节点核对 427 个封装引脚一致。**此图是 PCB 来源的网络反投影，不构成独立设计者原理图签核，符号为未取得厂家图纸的简化校对符号，原理图内不含真正量产封装对应**。
- 保留之前 Lane C 的双路 12 V 隔离域候选与 U20/J11/J12 外部失能互锁接口，但是这些 **未并入这一块真实产品 PCB**，因此不能宣称“完整功率级保护/偏置”已具备。

## 未完成的硬阻塞，不得签 G0

1. **磁件与真实功能电路**：目前五磁件封装只有逻辑焊盘；厂家实体外形、端子编号、DOT、匝比和真实绕组/PCB 装配尚未签核。首个真实 3:1:1 电路的磁饱和、绝缘、漏感、CT极性和连接需闭合，不可用逻辑 24 引脚对应冒充实体可制造磁件。
2. **独立电路审查**：需要以 UCC25600/UCC27282/UCC24624 真实器件和主板零件值、供电/保护/软启动功能重新创建并签署原理图；不能仅凭本项目提供的 PCB→SCH 投影，宣称主板功能完备。当前多数符号/封装/BOM 仍处于设计占位或 MPN 未核验状态。
3. **供电/故障安全**：两路隔离偏置 (V12P/V12S)、UVLO 保持关断、独立物理切断 48V 急停、真正浮地高侧 VGS 检测和 10 路 SR/原边门极全故障关断都没有整合进产品 PCB。Lane C 独立台架原理图不能替代这些实体主板电路。
4. **工艺和电磁/热**：12 层堆叠、部分焊盘/过孔位置、埋入磁件槽、铜截面和输出接点都需要厂家 DFM、真实电流损耗/温升和电磁兼容审查。**KiCad 原工程仍有五种被忽略的 DRC 检查**；本次未修改这些规则来取得虚假放行。
5. **实物台架 G0/G1**：没有制作装配，也没有原始示波器 60 组故障捕获、隔离耐压、冷启动、负载阶跃或首次限流运行签核。请依照 `docs/agent/D1_LANE_C_G0_ACCEPTANCE_20261115_NOT_FOR_FAB.md` 逐项检查；G0 BLOCKED，G1 PENDING，`energization_allowed=false`。

## 可复现命令

使用本机 KiCad 10 bundled Python，例如
`C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe`：

```powershell
& "C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe" tools/d1_g0_integrated_native_board.py --check
& "C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe" tools/d1_g0_router_trial.py --check
& "C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe" tools/d1_g0_native_schematic_projection.py --check
& "C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe" tools/d1_g0_package_native_mainboard.py --check
python -m pytest tools/d1_g0_test_integrated_project.py -q
```

从原始 V17 源版本再现整套工程的 `--write` 顺序依次为 `d1_g0_integrated_native_board.py`、`d1_g0_router_trial.py`、`d1_g0_package_native_mainboard.py`；最后一个工具同时重新生成原生 SCH、导出网表、原生 ERC/DRC、BOM 和文件 SHA。**禁止为完成 G0 而删除实物测试缺失标识或修改旧源 PCB。**
