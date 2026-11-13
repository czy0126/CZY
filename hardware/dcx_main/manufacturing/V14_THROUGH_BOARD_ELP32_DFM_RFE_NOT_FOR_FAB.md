# D1 G2 V14 双面PCB与穿板式平面变压器：制造可行性询证（NOT_FOR_FAB）

状态：三槽CAD、原生库件、**真实复制PCB主板的12条内部BoardOutline槽及12铜层候选已落盘**；但真正的多层3:1:1原副边绕组、层间连接、绝缘及背面器件尚未绘制。**禁止直接发板。**

## 原始磁芯与开槽

采用 TDK ELP32/6/20 N97 E磁芯与 I32/3/20 N97磁板，料号 B66287G0000X197、B66287K0000X197。厂家 E芯外形31.75±0.65 ×20.35±0.4 mm，E高6.35±0.15mm，I磁板高3.15±0.15mm，绕组窗口3.20±0.15mm。厂家尺寸：[TDK 2022 数据表](https://www.tdk-electronics.tdk.com/inf/80/db/fer/elp_32_6_20.pdf)第4页。

对应保存的 V11 主板155×131mm，四磁芯中心为 (20,20)、(58,20)、(96,20)、(134,20) mm。不能把整个外廓挖成大洞：每只 E 芯需三条非金属化槽。预设计的左/右槽分别宽5.50mm，中槽宽7.80mm，全部长22.00mm，角半径0.60mm，所有槽外再留至少0.50mm铜箔禁布。四芯共12槽。设计数据：[12槽源锁定几何及所有冲突](../g2/g2_v14_through_board_three_leg_slot_DFM_screen_NOT_FOR_FAB.json)、[12槽坐标CSV](../g2/g2_v14_ELP32_12_NPTH_slot_coordinates_NOT_FOR_FAB.csv)、[DXF几何边界草案](../g2/g2_v14_ELP32_four_core_12_NPTH_slot_toolpaths_NOT_FOR_FAB.dxf)、[SVG示意](../g2/g2_v14_double_sided_slot_winding_overlay_NOT_FOR_FAB.svg)。DXF是轮廓，尚不是带刀补的机床刀路，更不是Gerber。

JLCPCB公布普通NPTH铣槽最小宽1mm、公差±0.2mm、槽边铜距至少0.2mm；我们选择更保守的孔宽和0.5mm预留，需要厂商明确加工可行性、R角残余、三槽之间PCB板条强度、铁氧体进板裕量。[JLCPCB工艺能力](https://jlcpcb.com/capabilities/pcb-capabilities)。

## 原板冲突与必须真正重构的网络

实存V11原生PCB 149器件/443焊盘/465走线/93过孔；应用12槽与0.5mm铜禁布后共与**20个旧T1–T4裸PAD、7段VOUT真实铜线、3个VOUT过孔**碰撞。因此不能将槽直接刻进当前原生板。必须先删除/重建20处旧Pad为多层PCB铜绕组，绕过12处槽重新实现四路原边串联与中心抽头副边，并在外部把四路2V/25A源接入单独100A双极嵌铜/铜排，重审SR源极、散热及绝缘。

**已经在原先存在的V13嘉立创GUI中完成原生库机械封装**：名称 CZY_G2_V14_ELP32_THREE_NPTH_SLOT_BOARDOUTLINE_TRIAL_NOT_FOR_FAB，库 G1_R34_REC10K_v3_TEST，UUID d5e95cf104ff4eb082a0566ebcc7d830。三个真实 Board Outline layer11圆角闭合图元已建立且保存后重新打开，图元UUID/位置保持。见[原生保存重开回执](../g2/g2_v14_native_three_slot_saved_reopened_NOT_FOR_FAB.json)。没有新开软件窗口，原V11 SHA不变；V13原PCB1仍存在，但V13工作容器由于复制了V14 PCB，其二进制哈希已变化。**该句为库封装历史；现已有真正V14复制PCB上12条原生Board Outline槽，仍待制造文件/DFM验证**。

## 电磁与窗口叠层联立筛查

PCB中心槽与外侧槽之间每边有效几何铜道约7.6375mm，考虑两侧各0.5mm禁布后约6.6375mm。已建立5mm宽、69.8mm中心线长度的一匝U型绕组概念，并建立3个串联原边匝、两个各1匝的中心抽头副边及并层分配表；实际原副边跨层连接与盲/埋孔避让尚未实体绘制。9.45014A原边RMS、每变压器25A输出、每半副边假设17.68A RMS，在100°C纯DC铜阻估算：8层70µm铜约10.49W、12层70µm约7.67W、12层140µm约3.83W（四磁件合计）。这些是**低估值**，没有200kHz趋肤/邻近损耗、连线过孔损耗与温度非均匀，不能作为最终效率。

**更关键的磁芯窗口约束**：3.2±0.15mm窗口最坏值3.05mm，留每侧0.25mm装配间隙和额外0.10mm余量，PCB最坏厚度仅允许2.45mm。若12层140µm铜+11层各0.10mm介质+上下阻焊总0.04mm+PCB正公差0.15mm，最坏PCB厚度**2.97mm，无法塞进现有磁窗**。12层105µm铜+每层0.09mm定制介质所得最坏厚度2.44mm，只剩0.01mm预算，**不是可批量制造的稳健设计**。详见[窗口厚度门禁](../g2/g2_v14_ELP32_PCB_window_stackup_16mm_fit_GATE_NOT_FOR_FAB.json)。需要PCB厂提供真12层3oz内铜及≤90µm绝缘叠层能力、制造公差、绝缘试验、铜填充和每层实际厚度，或转向定制较深窗口/独立绕组子板。

## 双面组装与冷板

读取目前复用中的V13原生组件图元，**149个真实PCB元件全部位于顶层，底层为0**。因此现有主板并非已经双面布置。QH/QL和8路SR及100A输出互连应优先留在有冷板的主散热侧，U1/U2以及保护控制信号可作为背面整组迁移候选，但不能不计PCB层间过孔和栅极环路就直接翻面。名义E+I磁芯9.5mm、名义2mmPCB居中后磁芯两面各伸出约3.75mm，仅是芯体几何，16mm整机必须包括冷板/TIM/夹具/接头/公差完整叠层核算。

CT仍为待厂家确认的1:100四脚独立检测磁件，不随四只变压器改PCB绕组而自动消失。Lr还需单独解决 N97@100°C 121.515A 偏磁饱和；不能照搬ELP32开槽。

## DFM必须收回的验收资料

1. TDK/磁芯加工商提供最终E/I实测三维、中心柱/外柱偏移、铁氧体定位夹具受力、接触气隙、热裂纹风险与首件尺寸。
2. PCB制造厂签12条22mm长NPTH槽的刀具、R角、板条刚度及开槽铜边距；签12层厚铜实际逐层构造、盲/埋孔反焊盘、绝缘耐压和最坏板厚，**不能以0.01mm计算裕量视为量产可行**。
3. 实际V14 PCB建立12槽、四变压器3:1:1 PCB绕组与每只明确的DOT规则；恢复全部SR/VOUT网络；规划真正底层组件并保持短低阻驱动环路。独立重开原生工程，Physical/Connection/Netlist DRC全0。
4. 首件必须实测变比、绕组极性/DOT、Lm/Llk、200kHz Rac、100°C损耗、耐压、100A电流/热分布、D0故障快速停机、3LPM冷板与完整高度≤16mm。

**当前文件只授权继续CAD和厂商询证，不授权发Gerber/下单；NOT_FOR_FAB。**


## 最新实存V14原生主板/DRC（2026-11-13更新）

在现有V13唯一GUI中将PCB1完整复制为独立UUID `8c496410b2877d3c`，原PCB1 `2f6fa2d508d3f9a8`保留。经原生API真实删除 **20旧磁件PAD、7条VOUT铜线、3Via** 并创建12条layer11 Board Outline内部闭合槽，真12铜层已启用（1,2,15..24）；原生PCB保存后组件149/Pad423/Track458/Via90，外板框+内部槽13。实际原生DRC **149 Connection/1 Netlist/未新增Physical**。原生项目二进制 [`V14_EILP32_TWELVE_NPTH_12L_STACK_WIP_NOT_FOR_FAB.eprj2`](../g2/dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_12L_STACK_WIP_NOT_FOR_FAB.eprj2) SHA256 `1e76e6865a746a49bea8a9fb87037b0301213faa386f5fdd2d6bdf5550ffbac6`；[操作回执](../g2/g2_v14_native_PCB_12copperlayers_12cutouts_saved_NOT_FOR_FAB.json)。保存文件中有原PCB1和新V14复制品两份PCB，尚未从独立新GUI磁盘重开（避免增开窗口）。用户要的真实多层3:1:1电气绕组与厂家批准仍未完成；仅属于**机械完整、电子不完整的WIP**。

## EI 与 UT型磁芯的选型决定

在目前四变压器原边串联、每只3:1:1、200kHz/约50V输入的**均压方波示例**下，TDK ELP32 + I32 N97的有效磁截面积Ae=130mm²、le=35.1mm；ACME UT20的Ae=13mm²、le=53mm，UT30的Ae=27mm²、le=77mm。若均压每变压器原边约12.5V，方波估算 `Bpk≈(50/4)/(4×200000×3×Ae)`：EI约0.040T，UT30约0.193T，UT20约0.401T。不同厂家的UT材料和气隙/损耗不能直接用N97的Bs代替；但这表明标准UT20/30若保持3匝将大幅增磁通。UT减少单磁件穿板孔（三腿→常见两腿）有吸引力，却可能需要提高匝数（UT30接近15匝原边才达到EI同等通量水平），使 PCB 层数/绕组铜损和100A低压副边接线更复杂。**V14四只主变压器保持EI ELP32+I32，UT仅保留对照，不直接替换。**来源：[TDK EILP32/I32 Ae=130](https://jm.pl/gfx-base/s_1/orgs/18/B66287G400X187.pdf)（EILP32数据页）与[ACME UT型Ae与尺寸](https://www.acme-ferrite.com.tw/img/MnCorePDF/ut.pdf)。实际激励/磁通均需Maxwell/示波验真。

## 实际信号DRC清除与四路背面REG去耦（2026-11-13完成）

现有V14复制板上真实完成**OC、OCM、OCD低电流故障检测网络**布线，分别新增2/2/2个PTH与3/3/4段铜线。四路REG1–4在原布板中C7–C10与U3–U6位于不同区域且大幅拉长，已通过原生API实际移动到驱动器背面 **layer2/180°**（每颗2个过孔+4段铜线，总8Via/16Track），电容焊盘在下层，两个PCB网络经由顶底线/过孔独立相连。结果[真实原生V14双面工程](../g2/dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_REG4_BOTTOM_WIP_NOT_FOR_FAB.eprj2) SHA256 `7dd77910bcf7ff3fd0e2be1e4194439a22189aaf353f105bbe1280c104e4f6fc`，149组件/423Pad/484Track/104Via。原生DRC真实回执[独立第二次复查](../g2/g2_v14_after_REG4_independent_second_native_DRC_bottom_four_NOT_FOR_FAB.json) **111 Connection/0 Netlist/0 Physical**；首个149→124同时包含删除旧磁件焊盘后的重算，不能伪称单OC线路修好了25个错误。V14尚有111开路和四只PCB绕组欠缺。**原生DRC使用的仍是两层板规则，而本主板启用了12铜层，需12层板厂真实叠层/设计规则与DFM签核。当前NOT_FOR_FAB。**
