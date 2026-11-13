# V18 实际嘉立创PCB功率单元重布局交付回执（NOT_FOR_FAB）

## 真正完成的原生几何

本轮基于 V17 实存原生 `.eprj2` 另存 V18，**仅打开一个可见的嘉立创EDA窗口**，选择原生PCB `9b212da9a255a2af`，不覆盖V14、V15或V17。原生工程文件：[V18 合并真实功率重排PCB](../g2/dcx_main_board_g2_V18_CIN_T1_LR_RELAYOUT_NATIVE_SAVED_NOT_FOR_FAB.eprj2)，SHA256 `b291faea3b46c1d7ec4e7b54d57dd78a20e70523a2a629760f49d5141f7c7739`。SQLite最新项目结构ID=90，三张PCB原始UUID均保留，终版真实组件149个/Pad423个/走线508段/Via106个。

1. **输入高频旁路→半桥**：原Cin中心(92.4,43)mm，现(43,44)mm。Cin.VIN_P通过**3段真实顶层铜线**接QH `VIN_P` Pad8，绕开Cin自身PGND焊盘（首个直线尝试造成实际Clearance错误，已撤销）；Cin.PGND通过**2个0.4mm钻孔/0.8mm外径的实际镀通孔，1条底层与2段顶层铜线**接QL.PGND Pad1。共新建6段真实铜线+2个原生Via，所有Net与实际焊盘一致。源真实DRC **103→102**，未新增Clearance/Physical/Netlist。Cin.VIN_P→QH同网脚几何距离由约42.0mm缩至5.0mm；新PGND路线包含底层约15.9mm长的跨层连线，**这只是可追溯的旁路连通雏形，不是已经完成的高频最小环路/高电流PGND平面**。
2. **T1整流功率单元**：SR1A、SR1B、U3、底层REG电容C7、VCC12_S去耦C105与R20/R21/R28/R29共**9颗真实Native组件全部上移30mm**，对应**20条原生铜线、2个原生过孔**也以同样几何刚体平移，保留现有NET标签和图元UUID。SR1A中心(14,82)→(14,52)mm；相对于T1磁芯中心(20,20)mm，中心距离由62.29缩至32.56mm，减少约47.7%；T1槽下缘到SR副边端竖直距离由48.18缩至18.18mm。
3. **Lr磁芯安装位置置换**：Lr原中心(26,49)→(26,79)mm，以腾出T1至SR间的直下换流区域。基于ELP38的38.1×25.4mm占位，替换后磁芯外包络约x6.95–45.05、y66.3–91.7mm；对**静态焊盘和异网络已布铜**做几何检查，未发现碰撞；但实际夹具、磁芯高度、PCB凹槽、绝缘和水冷板间隙**仍需实物/3D验证**。

## 原生独立复核与真实不完整项

- [Cin首个错误及已撤销的原生DRC证据](../g2/g2_v18_Cin_power_loop_one_clearance_error_NATIVE_DIAGNOSTIC_NOT_FOR_FAB.json)；[修正后Cin双回路实线路由与原生DRC 102](../g2/g2_v18_true_native_Cin_relocated_both_loop_3VIN_3GND_tracks_2via_DRC_ONCE_NOT_FOR_FAB.json)。
- [T1+Lr 10器件移动回执](../g2/g2_v18_T1_Lr_10native_components_RELOCATED_ONCE_NOT_FOR_FAB.json)、[20段铜线+2Via移动回执](../g2/g2_v18_T1_Lr_20tracks_2vias_NATIVE_MOVE_ONCE_NOT_FOR_FAB.json)、[保存时DRC](../g2/g2_v18_T1_Lr_swap_actual_native_DRC_AND_SAVE_NOT_FOR_FAB.json)、[独立再次回读](../g2/g2_v18_independent_post_T1_Lr_relayout_real_native_DRC_AND_30primitive_readback_NOT_FOR_FAB.json)：**106 Connection Error、0新Physical或Clearance错误**；PCB仍149/423/508/106。
- **连接错误变化解释**：V17基线103，完成Cin输入+返回闭环后102；因为T1区组件、去耦与原有局部铜线整体上移并移动Lr，存在必须重新布通的接口，当前106。并非DRC改善项目，**优先完成真实功率几何**，后续才逐网修复外部接口。PGND当前38个开路，绝不把显示标签删除当作修复。
- **严重EMC尚未通过**：迁移Lr后，它与仍在原位的Cr的中心距从46.1增到53.3mm；这是合理的物理空间置换但**不是最终谐振布局**。下一阶段需将Cr/CT、QH/QL及T2/T3与T1/T4一起重排，以同时降低SW、CR_CT、CT_LR、PRI_T1、四个副边及100A VOUT/PGND完整正向/返回回路。不能依赖短路不同原副边网或假DOT来减少DRC。
- **制造未放行**：四只EI变压器3:1:1多层真实绕组尚缺，CT厂家针脚/DOT未签，厚铜12层实际叠层及绝缘未签，机械Lr夹持/液冷16mm包络未签；EDA原生DRC仍是 `JLCPCB Capability(Two Layers Board)`，不是12层厚铜厂商规则。完整EMI/寄生L提取、200W 100A直流压降与温升未测。**NOT_FOR_FAB，不要生产。**

## 后续布局优先顺序（尚未完成）

1. T2：受QH/QL及C5/C101等功率与去耦器件阻挡，不能像T1直接上移30mm。先设计半桥/Cin/Cr新整体落位与铜返回，再以成组元件/走线同时重排；不能把MOSFET和其去耦拆开。
2. T3：受实际CT四自由PAD、OCD/CS1/CS2线阻挡；CT本体/物理端子/DOT定稿后与第三组整流单元配对布置，并缩短二次侧换流路径。
3. 重新布局Lr–Cr–CT谐振电流回路、T1–T4四个1匝二次侧、对称100A输出汇流与低ESL回流平面；依据真实12层叠层与磁芯非金属孔厂商能力检查。

