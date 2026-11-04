# RFQ Lr —— 谐振电感 Lr（独立件，不是变压器的漏感）

状态：**REQUEST_FOR_QUOTE_NOT_VERIFIED**（询价单，不是制造图，不是签核）。数量：1 只。

每个数字都注明出处；本仓库没有数据的项写 UNKNOWN 并汇总在第 11 节，不省略、不填看起来合理的值。

## 1. 绕组极性与逻辑端子

| 逻辑端子 | 电路网络 | 设计 DOT | 出处 |
|---|---|---|---|
| N1 | CT_LR | 绕线起点建议标记；电感无极性要求 | design/v3/pcb/board_netlist.csv |
| N2 | PRI_T1 | 绕线终点建议标记；电感无极性要求 | design/v3/pcb/board_netlist.csv |

## 2. 电感、匝比与气隙

| 项目 | 值 | 出处 |
|---|---|---|
| 谐振腔目标总电感 | 1.000 uH | lr_design.json:tank.total_target_h |
| 外置件目标 | 0.920 uH | lr_design.json:tank.external_target_h |
| 首件修法 | 外置件 = 目标总电感 - 实测漏感；1.0 uH 是筛选上限，不是要绕的值 | lr_design.json:tank.note |
| 匝数 | 3 | lr_design.json:physical_peaks.min_turns_all |
| 目标 AL | 111.11 nH/T^2 | = 1.0 uH / 3^2 |
| 气隙（由目标 AL 算） | 1.4443 mm | lr_design.json:candidates[3 匝].gap_mm |
| 饱和电流 Isat | 120.9 A | lr_design.json:candidates[3 匝].isat_a |
| 气隙公差窗口 | UNKNOWN | 需要厂家的 L(I, T) 曲线才能定验收窗口 |

## 3. 工作波形

| 项目 | 值 | 出处 |
|---|---|---|
| 开关频率 | 200.62 kHz | lr_design.json:tank.clock_khz |
| 谐振频率 | 202.13 kHz | lr_design.json:tank.resonant_khz |
| 磁密设计上限 | 0.248 T | 第20章：B <= 0.248 T 的筛选线（不是签核值） |
| 3 匝最小截面积需求 | 179.66 mm^2 | 第20章：121.52 A 下 Amin >= 179.66 mm^2（推荐 >= 200） |
| 原厂标准件结论 | 五组未改造标准 ELP + I 组合无一同时满足磁通与完整高度 | 第20章筛选表 |

## 4. 额定电流与故障电流

| 项目 | 值 | 出处 |
|---|---|---|
| 稳态峰值 @100 A | 13.881 A | lr_design.json:peaks_a.steady |
| 冷启动峰值 | 22.53 A | lr_design.json:physical_peaks.startup_phys |
| 故障峰值（物理 deck） | 84.02 A | lr_design.json:physical_peaks.fault_phys_ride_through |
| 故障峰值（外置件取下限） | 104.17 A | lr_design.json:physical_peaks.fault_lrmin_ride_through |
| 故障峰值（50 V hotfault 前缀） | 101.26 A | 50 V 诊断前缀 |
| 询价设计电流 | 121.52 A | 第20章：101.26 A x 1.20 的 RFQ 假设 |

## 5. 温度

| 项目 | 值 | 出处 |
|---|---|---|
| 设计点 | 100 °C | 第20章：100 °C 的 L(I) 曲线是询价要求 |
| 环境温度 | UNKNOWN | 仓库没有整机环境温度要求 |
| 铜箔温升 | UNKNOWN | 无热模型 |

## 6. 允许损耗

| 项目 | 值 | 出处 |
|---|---|---|
| 铜损（3 匝） | 0.2234 W | lr_design.json:candidates[3 匝].loss_w = Irms^2 * R_ac |
| 磁芯损耗 | UNKNOWN | lr_design.json 只算铜损；Lr 的磁芯损耗未建模 |
| 口径 | Dowell 一维模型，含邻近效应；不是量热值 | lr_design.json |

## 7. 绝缘

| 项目 | 值 | 出处 |
|---|---|---|
| 绕组对磁芯 | UNKNOWN | 本仓库没有 Lr 绝缘要求 |
| 匝间 | UNKNOWN | 单层绕组，未定义 |
| 无原副边隔离 | Lr 是单绕组件，不承担隔离 | 磁件设计包 |

## 8. 完整高度

| 项目 | 值 | 出处 |
|---|---|---|
| 标准 ELP32 裸芯高度 | 9.20 - 9.80 mm（不含 PCB / 焊料 / 铜箔 / 引出端） | 第20章 TDK 原厂尺寸 |
| 整机限值 | 10.00 mm | D1 首样目标 16 mm；严格 10 mm 是 D3 目标 |
| 结论 | 标准 ELP32 装进整机必超 10 mm | 第20章 |
| 首选询价结构 | 整机叠层（含板、绕组、胶、沉槽）计入 10 mm；裸芯 <= 8-9 mm 作为谈判起点 | 第20章（谈判起点，不是设计结论） |

## 9. 公差

| 项目 | 值 | 出处 |
|---|---|---|
| 气隙 / AL 公差 | UNKNOWN | 须由厂家给出 L(I, T) 后定义 |
| 电感验收窗口 | UNKNOWN | 同上 |
| 端子位置公差 | UNKNOWN | 无物理端子图 |

## 10. 物理端子图

| 项目 | 值 | 出处 |
|---|---|---|
| 逻辑端子 | 2 个：N1 = CT_LR，N2 = PRI_T1 | board_netlist.csv |
| 物理端子图 / 焊盘号 | NOT AVAILABLE —— 独立 Lr 的器件、引脚与机械定义尚未取得 | 路线 §P1 磁件 |

## 11. 未决项（本仓库没有数据，或需要决定）

1. 三匝 Amin >= 200 mm^2 的定制低矮磁路；标准 ELP32 在 121.52 A 下不满足磁通筛选。
2. 0 - >=121.52 A、100 °C 的增量电感 L(I) 与直流偏磁曲线。
3. 外置件与变压器漏感的分配：外置 = 目标总电感 - 实测漏感，首件实测后才定。
4. 独立 Lr 的物理端子、焊盘与机械定义（器件定义目前只有电感/匝数/气隙）。
5. 气隙公差与 AL 验收窗口。

## 12. 出处

- `design/v3/bom/lr_design.json`
- `design/v3/power_priority/lr_tdk_catalog_core_screen.json`
- `docs/D1_EXECUTION_KIT/20_低矮磁件Lr原厂尺寸磁通双约束审核.md`
- `design/v3/pcb/board_netlist.csv`

**跨件提醒**：变压器的磁通按各绕组实际电压积分核算；`L*I/(N*A)` 是 Lr 的电感筛查判据，不能拿来判断变压器励磁饱和。系统 24:1 是「半桥 + 四原边串联」与「3:1:1」共同形成的，单件匝比是 3:1:1。
