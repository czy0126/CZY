# D1 / V17 集成版：原生 KiCad PCB 与 PGND/VOUT 制造门禁（2026-11-14）

**结论：已生成可重复的 KiCad 10.0.6 PCB 与真实连接/铜层，仍为 \`NOT_FOR_FAB\`。** 
本分支从 Agent-A 已通过 KiCad DRC 的 \`46844814e2eb473d2b69570b00a59c636cf60a13\` 开始，绝不覆盖用户原目录及 Agent B/C/D 并行成果。独立重新生成与DRC不再被 Windows CRLF/Git LF 转换阻断。

## 1. 当前被独立验证的实际板

- 源自 V15 唯一真实 PCB \`02d59c63c747678849466cc62565c1522bc50586a7dadc06b0829016ab601e75\` 的149器件 / 原关联419焊盘；新 \`J_OUT\` 一极四孔，现真实 **149 footprints / 425 pads**。与原V15相比，148个未替换器件的每个 \`ref + pin + net\` 多重集**完全相同**；仅 J_OUT 由 \`1=VOUT\`、\`2=PGND\` 各一个电连接焊盘变为各四个同编号焊盘。证据：[逐脚原生重开审计](../../hardware/dcx_main/g2/g2_v17_integrated_native_pin_parity_NOT_FOR_FAB.json)。
- **真实12铜层、11个已填充铜区、359个PCB通孔、165条走线、12条磁芯 NPTH槽、155×113mm板框**。VOUT/PGND 3组独立铜平面：\`In2.Cu VOUT / In1.Cu PGND\`、\`In5.Cu VOUT / In6.Cu PGND\`、\`In7.Cu VOUT / In8.Cu PGND\`；辅助12V另占In3/In4。**不能把剩余In9/In10视为未来可任意使用的铜层，12L磁件绕组还未完成。**
- **KiCad10.0.6原生DRC: 0 violations, 9 unconnected**，PGND和VOUT均为0连接错误。U2 原导出0.49784 mm最坏间距修复为数据手册标称0.5 mm引脚节距、移动不超过5 µm，仍保留0.20 mm真实净空限制，没有禁用DRC或缩小真实焊盘。其封装中心散热焊盘为源矩形边界近似，后续必须用 OEM 实际多边形代替。
- 9个未连接不是全部电气故障：\`SW:3\`、\`VIN_P:2\`、\`GH:1\`、\`GH_DRV:1\`、\`HB:1\`、\`OC:1\`。电气上真正缺失的 **T1/T2/T3/T4+CT五套物理磁件和原边/副边24端子绕组**未计入该DRC；不得将 \`9\` 误读为“离交付只剩9根线”。
- 输出端子采用**临时4孔/极PTH**: VOUT \`(70,78/87/96/105) mm\`、PGND \`(82,78/87/96/105) mm\`，孔径3.2mm，铜环5.5mm。装配外框试验为 \`(66.65,74.5)-(85.35,108.5)mm\`；通过 KiCad 实际 DRC零元件courtyard重叠。**螺栓/焊接、铜排接口、触点电阻、孔铜厚度、冷板总高和4×25A均流未有厂家签核**，不能按每孔25A“默认合格”。

## 2. 已纠正的跨工作区缺陷

此前多个 Agent 的 \`g2_v17_*json\` 使用 Windows CRLF 写出并将原始 SHA 嵌入后继数据，Git默认以LF保留，导致换到新的干净worktree后 \`g2_v17_generate_kicad.py\` 误报布线数据篡改。现在使用 [V17跨平台源锁定Digest](../../tools/g2_v17_source_digest.py) **仅针对7个明确列出的历史文件恢复原 CRLF hash**，对其余 JSON 和所有 \`.eprj2/.kicad_pcb\` 坚持原始逐字节 SHA。通过 [回归测试](../../tools/test_g2_v17_source_digest.py) 确认LF/CRLF等价，任何实际数据变更仍拒绝。源锁定链已经在全新隔离工作树重放成功，非仅复用现成旧PCB。

## 3. 与四Agent成果的批判性集成

- Agent A信号分支原生9开路/2项U2几何错误，是本次主板最合适的连线基线。它关闭了部分SW指间、SR焊盘邻近的低电流Kelvin、驱动供电与GPIO，**但剩余SW主功率回路未建**。
- Agent B原边重排试验的0项DRC、21项开路比A网络覆盖差，且 QH→QL SW存在 **3.517mm×0.45mm铜颈**，按假设35 µm/100℃会产生5.06mΩ局部DC电阻（不能推断实际RMS）；**不能直接用B完整PCB覆盖A**。B的U2正确节距规则已独立落实至本集成脚本。
- Agent D六电源内层+8输出接点的几何数据已在本工作树**按最新A信号板重建**，不是覆盖旧D的板文件；源D旧接点位于y76/86/96/106，新的触点y78/87/96/105用于避免主板Cout和电容组件courtyard。**原D电阻网络的数值因此不得直接等同于此版。** D旧假设下，35 µm铜/50 µΩ单接点模型双极R≈0.259mΩ，70 µm/50 µΩ≈0.173mΩ，105 µm/50 µΩ≈0.143mΩ，均非实测，且后者对0.15mΩ目标没有工艺容差余量。
- Agent C的SR和磁件分支尚有未合并修改，必须以**真实绕组、端子、磁芯空腔与DOT**逐项校验，不以D0/D1图纸排版或PPT代替实体电路。

## 4. 严格的制造/EMC后续优先序

**P0：原边真实功率单元。** 规划整流前的输入48V/PFC接口、原边\`Cin–QH–QL\`正反路径、\`QH/QL-SW–Cr–CT–Lr–T1...T4\`功率铜；建议重新研究上下FET旋转/相对朝向，以同时缩小SW与输入供回环路。对纯网络补细线的“DRC从9到0”不算成功。优化后以等效环路寄生L、寄生C、I_RMS铜损和温升进行比较；独立重建 \`GH/GH_DRV/HB\` 短门驱回路，所有高dv/dt SW sense只能Kelvin抓取。\`OC\` 是横贯全板约58mm的保护信号，需通过局部保护器件重新布置或安全信号链方案，不能用超长普通trace掩盖。
**P0：磁件与12L制造。** 为CT与四只T1–T4提供真实的3:1:1绕组设计、24逻辑引脚到铜层/端子对应、DOT相位、层间耦合和磁芯实际干涉。预定的六层整流用铜必须和PCB内嵌磁件竞争层数；任何冲突以几何与热态电性能协同重新设计，不能让高流铺铜覆盖绕组铜线。
**P0：100A VOUT/PGND双极汇流。** 新8孔多触点需要铜排、孔铜厚度、温度、螺栓/焊接阻抗和接触均流的R网络重新拟合，留出对0.15mΩ目标的真实裕量；真实输出接触/过孔25A均流尚未验证，不能仅凭zone连通判断。
**P1：真实器件与EMI/热测试。** 72颗Cout、原边63/100V真实旁路、Cr RMS、Lr、U2封装、SR器件与门驱器件的厂家MPN和OEM pad/3D Courtyard，一同落实12L板厂可行工艺与16mm总高/3LPM冷板。实物验证先降压/限流，再EMC传导及辐射，严禁现版直接100A通电。

## 5. 可复现命令（现有Windows KiCad 10.0.6）

\`\`\`powershell
C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe tools/g2_v17_generate_kicad.py
C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe pcb drc --format json -o hardware/dcx_main/g2/g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json hardware/dcx_main/g2/dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb
C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\python.exe tools/g2_v17_integrated_pin_parity.py
python tools/g2_v17_remaining_powercell_handoff.py
python -m pytest tools/test_g2_v17*.py tools/test_g2_v16_floorplan_screen.py -q
\`\`\`

**唯一可发板定义：** 与真实P1完整原理图的每一 pin/net/OEM封装吻合；实际PCB（含全部实体磁件）0未连接、0DRC、制造DFM通过、100A DC/AC+接点热态、EMI/EMC与冷板/故障试验全部验证。当前均不满足，不出Gerber。
