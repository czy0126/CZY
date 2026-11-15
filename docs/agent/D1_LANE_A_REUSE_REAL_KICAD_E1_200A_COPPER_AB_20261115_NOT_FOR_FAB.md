# D1 E1 / 对既有结果复用的实际进度：四单元双极输出铜试验板A/B（2026-11-15）

> **本轮不再只停留于路线设计。** 在Lane A独立干净worktree里，直接以已选定 V17 **真实KiCad10板上SR1A–SR4B的8个封装实例和10×8个物理pad-net**为输入，生成并**保存两份可重开的、带实铜与双极zone的真正KiCad试验PCB**。将输出端同时从侧边x95移动到中央x50，重新运行原生KiCad DRC，并根据真实4×50A注入位置计算铜损变化。源PCB与已有ELP38嵌铜Lr试件SHA全部固定。**两份都是局部无磁件、不包含全部驱动的铜路试验件，不是可上电的200A LLC-DCX或最终产品板！**

## 可直接继承 / 受限继承 / 必须重新设计

| 来源 | 已有真实成果 | 本次处理 | 不能偷换的资质 |
|---|---|---|---|
| **V17 KiCad 12Cu**，`d1_lane_a_connectivity/six_net_trial_04_NOT_FOR_FAB.kicad_pcb`，SHA `85fff295…e2b40b2158e266e8df4a2ba77d6bb76c` |149器件，0/0启用DRC，8真实SR pad实例，输入热环与相同net名 | **复用SR实际footprint对象和逐脚物理焊盘/网映射，重新放置到4×两SR单元**。原V17保持不动 | 真实pad在原板但**value=V15_PROVISIONAL_CAD_ONLY**；实际SR器件原厂封装/电流能力/驱动时序未签收；五磁件/完整ERC缺 |
| **ELP38三匝6Cu原生PCB** `hardware/dcx_main/pcb_winding/ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.kicad_pcb` | 已有圆角三孔开槽、每过渡4个PTH样件，源SHA `00f930a8…a3463e5bef9a2` | **保留其过孔CAD方法、圆角开槽和镀铜敏感性作为下一版矩阵磁件生成器的输入**；本次试验板不假装已有4单元磁芯 | 现有Lr额定约9.45A RMS，并非200A副边；OEM非线性/气隙损耗、量产DFM未签字 |
| **独立本机T1 Maxwell FEM** `D:\workshop\design_48v-2v\design\v3\maxwell\local_full_fem_20261115\T1_ALL_5_TERMINALS_CTAP_CONDUCTION_SOLVED_NOT_FOR_FAB.aedt` | 真实5端子/Ctap+并接原边3D磁件求解；只读回执SHA `9692cf53…d8fceb`，当地磁芯Bmax拒绝放行的证据SHA `a614dca7…917db` | **仅复用建模端口、网格工具链、3D导体构建方法；数据留原dirty工作树，未复制/覆盖。**下一步重新收紧引线、插板磁芯和实际厂商绝缘方案，再跑完整FEM | 100°C N97真实非线性、高频铜/芯损、网格独立性**未通过**，不能搬出局部L矩阵直接声称600A合格 |
| **CT 100匝本机Maxwell** `local_t1_fem_20261115/ct_true100turn_2port_actual_magnetostatic_matrix.json` | 实体100匝局部模型，SHA `abca0157…7ef0b3` | 复用真实端口/磁芯/保护极性研究与失偏置测试指导 | OEM/Ae/DOT、PS完整端口求解/材料没有签名 |
| **Lane C 保护支线** `feat/d1-v19-lane-c-output-protection-20261114` | 隔离48→12V辅助偏置、HS UVLO/紧急停止/失偏置默认OFF的候选设计与G0 witness脚本 | 作为下一版完整电路原理图及设计约束，按差分VGS/GND本地参考一项项集成，不重置工作树 | 当前模块本身**无电源驱动**，其它分支的模拟证据不可转成当前PCB的保护通过 |
| **旧V17两极输出与145/189过孔** | 可用于逐脚/zone关系、两极热态电阻估算边界 | 借鉴两极并置+层叠回流，**主动摆脱输出长而窄的PCB汇流** | 100A/200A/600A热态电流、端子、同回路几何未实证 |
| **旧800→12.5V液冷论文与冷板项目** | 提供局部热点、PCB埋线、层间/流体耦合的既有可参考方向 | 只作研究比较，不把800V/12.5V磁件变比和局部热试验直接映射为48V/2V/200-600A样机 | 原论文工作点、完整外形与水路压力需要同口径重新验证，BirEn冷板工程同样不能未经CFD再定型 |

## 实际生成了哪些本地真实KiCad原生文件

`hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon/` 下：

- **A / 边缘输出版本** `e1_4cell_200A_pair_collector_copper_coldplate_interface_NOT_FOR_FAB.kicad_pcb`：来自V17真实8个SR封装实例（4×2），另8个副边模拟测试输入焊盘、4个CTAP BCu模拟输入焊盘、2个前后独立输出SMD端子，**22 footprints**、12铜层定义、16条实际SR到铜zone导体线路、2个实际铺铜zone（顶层PGND/底层VOUT）、102×50mm诊断试验板，背面+正面靠近输出形成两个**不同电气网络**的面内collector，用户绘图层仅示意2.5mm薄冷板预留。
- **B / 中央输出版本** `e1_4cell_200A_center_output_pair_collector_NOT_FOR_FAB.kicad_pcb`：严格从A真实板复制，只把同处x95mm的正/负极表面输出焊盘**同时移动到x50mm**；其余8个SR及全部焊盘网络/两铜zone保留，反映一个可实测的单因素布局对照。A和B均通过**原生KiCad10 DRC 0启用规则违规/0未连接**（仍有KiCad默认5个ignored checks，包括无courtyard、封装过滤器等），**无完整原理图/ERC**，不准误报为可制造全板。
- **两个原生DRC JSON**、**两个真实PCB SHA绑定回执**以及`e1_200A_A_B_real_KiCad_collector_comparison_NOT_FOR_FAB.json`真实A/B几何铜损筛查。脚本直接重开KiCad板、检查所有封装/焊盘网名、F.Cu vs B.Cu而非使用无效的`GetLayerName()`默认名称进行判断。源码：`tools/d1_lane_a_reuse_200a_copper_coupon.py`、`tools/d1_lane_a_centered_200a_collector.py`、`tools/d1_lane_a_reuse_200a_copper_gate.py`、`tools/d1_lane_a_reuse_200a_ab_gate.py`。反复生板会导致KiCad UUID与源SHA变化，**不要在下游混用旧SHA回执**，每次重画须重新跑两个原生DRC和两个门禁。

## 用实铜几何反推出瓶颈：DRC 0不代表200A

假设每个单元正负极各**50 A直流**、x=20/40/60/80mm注入，两极各一层70µm的铜宽`43−29.3=13.7mm`，100°C铜，且**完全均流/同温/忽略pad扩散、过孔、接点、PCB ac损耗**；逐段按`I²ρL/A`积分（不是总电流乘全线长度，也不把两个极性的一极电阻漏掉）：

| 仅是直流示意模型 | A：最远x95输出 | B：x50居中输出 | B相对A改进 |
|---|---:|---:|---:|
| 实板两极各一层70µm | **61.436 W** | **14.177 W** | **−76.92%** |
| 假设两极各有0.8mm铜带（**未真正焊装**） | **5.376 W** | **1.241 W** | **−76.92%** |

200A/2V/95%总损耗预算仅`400×(1/0.95−1)=21.053W`，如果给两极输出铜留不超过20%的预算就是**4.211 W**。所以**A绝不能直接拿去做200A，B虽已大幅缩短电流路径，70µm实际铜本体仍不满足仅占总损耗20%的设计目标**；必须实际做厚铜/铜片、电流端子/焊点、冷却接触、连续热稳态验证。0.8mm铜带只是需要厂家验证的**假想加厚改进模型**，不是KiCad板实际已有0.8mm载流铜，也不能声称损耗实测减少76.92%！

**为什么中央更好**：两边50/100/150/200 A串接区域的`I²·L`总权重由A的1300 A²m降至B的300 A²m，当前PCB上同其他几何下近似降低76.92%。此对照仅比较一种同网同pad原理的电气几何移动；暂时无法排除其对真实磁件位置/冷板/EMI/功率输出接口的负面影响。

## 下一阶段向真正200A / 然后400A和600A集成

1. B的中央两极输出不宜保持普通单层长铜。**选择更短的单元级侧接出口、真实厚铜/侧壁镀铜或铜排与冷板绝缘组合**，用相同100°C和同一12/16层叠构做真实Rdc和Maxwell Rac/铜热。只有在10–50 A单元对等验证和制造商板厚/镀层/绝缘签认后，才把铜排画成原生可制造的PCB/机械联合实体。
2. **把现在真正8路SR每路SECn_A/SECn_B的虚拟接入点接到有DOT的矩阵绕组几何**，从已存在的T1五端子Maxwell模型继承端口/驱动对应关系，验证有效48→2V变比、磁通/磁芯及冷启动；运行最新版本独立ERC与DRC。
3. C偏置/HS参考/D0保护同步移植到统一电路，以本主板一项项检查，不在现有G1原生dirty分支上做破坏性编辑。G0完成功能样机保护后，在冷板接触面（隔离TIM/绝缘铜扩散）试可控200A。
4. 将200A/400W的完整热/泵耗和最高温度数据作为E2放大到400A，再用对照A/B/C/D评估600A的5.5mm电源级与2.5mm薄冷板是否是真实可装配，而不是设计外形想当然。

## 复测及正确结论

```powershell
$k='C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\'
& ($k+'python.exe') tools/d1_lane_a_reuse_200a_copper_coupon.py --check
& ($k+'python.exe') tools/d1_lane_a_centered_200a_collector.py --check
& ($k+'python.exe') tools/d1_lane_a_reuse_200a_copper_gate.py --check
& ($k+'kicad-cli.exe') pcb drc --severity-all --format json -o hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon/e1_A_fresh_native_drc.json hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon/e1_4cell_200A_pair_collector_copper_coldplate_interface_NOT_FOR_FAB.kicad_pcb
& ($k+'kicad-cli.exe') pcb drc --severity-all --format json -o hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon/e1_B_fresh_native_drc.json hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon/e1_4cell_200A_center_output_pair_collector_NOT_FOR_FAB.kicad_pcb
D:\anaconda3\python.exe tools/d1_lane_a_reuse_200a_ab_gate.py --check
D:\anaconda3\python.exe -m pytest tools/test_d1_lane_a_reuse_200a_ab_gate.py -q
```

**总状态：两块真实可编辑KiCad诊断试板、可重演几何铜损A/B比对、物理原始source SHA和原生DRC已形成；这不是 200A制造样品，更不是400–600A LLC-DCX已经投板/跑通。** 不允许在外部宣称电气性能比现有文献更好，缺的是有意义的短路径/双极实体铜排+液冷及真绕组/保护一体化。
