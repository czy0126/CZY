# 嘉立创 EDA Pro：从当前 WIP 到可制造的原生项目

**本项目特殊情况**：hardware/dcx_main/dcx_main_board.eprj2 是可编辑 EasyEDA Pro SQLite 工程，约 83 位号；已保存的原生网表可与 SPICE 金网表比对，但五磁件的引脚仍是逻辑端子名而非物理焊盘。主功率 PCB 尚未完成；main_board.svg 是历史导出图而非当前 83 位号审核证据。

## A. 每次变更按以下顺序操作

1. **冻结副本/版本**：复制 .eprj2，记录 SHA256、编辑器版本、BOM 版本；不要在无法回写本地 SQLite 时把 headless API 返回 true 当成已保存。打开 GUI 后保存、关闭、重开并再导出网表。
2. **解决五磁件**：按供应商图纸逐只核 T1-T4 的 PRI_A/PRI_B/SEC_A/CTAP/SEC_B 与 CT 的 PRI_A/PRI_B/SEC_A/SEC_B，附真实厂商引脚号+DOT+尺寸；注意当前 CT 的占位封装只有 2 焊盘但逻辑有 4 脚，不能用“金网表一致”掩盖。见 04 指南和 magnetic_terminal_map.csv。
3. **清理 61 占位位号**：逐位号归入真实 MPN/实物受控自定义件/不装件。现有 pin_footprint_review.csv 的 PLACEHOLDER 是事实，模板只能提供建议，不能把 PLACEHOLDER 改成 MAPPED 但实际器件还没变。
4. **真实封装映射**：对每只 IC、MOSFET、二极管、多脚接口按厂家 pin ↔ symbol pin ↔ physical pad ↔ net 验证，尤其 U2 裸焊盘 PGND、BAT54 非使用脚、SR Kelvin 信号与电力回流。
5. **原生 ERC**：在 GUI 中运行当前图页的完整 ERC，逐项关闭 error/warning；将报告、实际工程版本、例外原因纳入证据。仓库既有 headless sch_Drc.check() 的直方图曾不随图纸变化，**不作为正式 ERC 通过证据**。
6. **导入 PCB 并回读比较**：先从已保存的工程生成 PCB，再导出 PCB 焊盘→网络表，双向核对**全部 BOM 实装件**、非仅由 SPICE 产生的金网表子集。标记试验点/接头/安装孔等工程新增位号的例外。
7. **真实 routing/DRC**：优先把四组 SR 到四组 Cout 的高 di/dt 回路、100A 汇流铜/铜条、Kelvin 采样与绝缘边界布通；校核层数/铜厚/回流/热扩散、铜箔补强工艺。DRC 0 不足以单独证明 100 A 可持续承载。
8. **制造包版本绑定**：Gerber、钻孔、坐标、装配、3D Z 剖面、叠层、BOM 的源 EDA SHA + 图纸版次一致；双人审图后才可能通过 fabrication gate。

## B. 可使用的仓库命令（从 repo root）

    python tools/main_board_schematic.py --write
    python tools/check_main_board_netlist.py
    python tools/d1_bom_coverage.py
    python tools/d1_fabrication_gate.py
    python -m pytest tools/test_main_board_schematic.py tools/test_check_main_board_netlist.py tools/test_d1_fabrication_gate.py -q

前两行仅检查逻辑坐标/焊盘子集，**不**表示实体可制造；严格放行命令为：

    python tools/d1_fabrication_gate.py --require-release

本项目早前在 headless 模式中用内存注入磁件占位封装才能导出网表，但内存属性不会持久化到 .eprj2。终验应证明“保存→关闭→重开→导出→网表仍对”，禁止拿不落盘的临时导出代替原生文件。保留该方法仅用于诊断。

## C. 必须能交付、不能以截图替代的文件

| 交付 | 通过条件 |
|---|---|
| EDA 源工程（含 PCB） | 在另一台机器打开、保存、关闭重开，器件封装及网表一致 |
| pin-pad-net 审表 | 所有实装位号有真实 MPN/封装/资料修订，未知项为 0 |
| 真实 GUI ERC | 所有违规逐项处理并关联原文件 |
| PCB→SCH diff | 真实导出且双向覆盖，0 未解释的 pad/net 差异 |
| 有网 PCB DRC | 规则与厂家能力匹配，含高流铜/回流与间距复核 |
| 10mm Z 剖面 | 统一 Z=0，五磁件/接口/TIM/紧固件及制造公差列明 |
| DFM 回执 | 供应商对具体叠层、铜厚、沉槽、外形及高流连接确认 |
| 制造包+签核人 | 每个文件版本和 SHA256 与 EDA 绑定 |

## D. 现在最容易造成返工的五个错

- CT 两焊盘占位 ≠ 四个物理引脚已确认。
- ELP32 五只均要计入高度，只有 T1-T4 沉槽会留下 Lr 高度冲突。
- 原生网表子集通过 ≠ BOM 真实值、真实脚号、完整 PCB 通过。
- 靠铜箔宽度公式无法证明分流均匀；必须求每组实际 I²R 和接头电阻。
- 修改 Lr/Cout 实际结构后，仿真、BOM、磁件 RFQ、机械剖面、原生 CAD 都必须同步 ECO。
