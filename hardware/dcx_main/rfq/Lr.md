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
| 气隙口径 | 上面这个气隙来自 TDK EILP32 N97 B66287G0000X197 + B66287K0000X197 的 AL_ungapped = 6300 nH、le = 35.10 mm；换套件就作废 | magnetics_design.json:core.AL_ungapped_nH / core.le_m |
| 首选套件气隙 | UNKNOWN（目录摘录没有 ELP38 的 AL_ungapped 与 le） | lr_tdk_catalog_core_source.json 只有 Amin/Ae/高度 |
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
| 整机限值（D1_100A） | 16.0 mm | d1_staged_target_policy.json:stages[D1_100A].height_limit_mm |
| 整机限值（D3_THIN） | 10.0 mm | d1_staged_target_policy.json:stages[D3_THIN].height_limit_mm |
| 现行首选套件 | ELP38_I38 | d1_staged_target_policy.json:stages[D1_100A].preferred_magnetic_core |
| 首选套件全叠层最坏高 | 12.49 mm | magnetics_design.json:catalogue_core_stack（含胶/标签/沉槽，不含夹子） |
| 留给 TIM / 冷板 / 紧固件 | 3.51 mm | magnetics_design.json:catalogue_core_stack |
| 高度结论 | ELP38_I38 在 D1 内余 3.51 mm，高于 policy 的 2.0 mm 非磁芯预留；但 TIM、冷板与紧固件厚度本仓库没有数据，所以这是预算不是签核高度 | 由上三行算出，不是引文 |
| 旧筛选表的口径 | 2026-11-03 按 10 mm 判定，ELP38 的 REJECT 理由是高度；policy 2026-11-04 把 D1 改为 16 mm 后该条不再适用，当时同时通过的磁通筛选（0.23206 T < 0.248 T）仍然成立 | lr_tdk_catalog_core_screen.json:requirements |
| 首选询价结构 | 整机叠层（含板、绕组、胶、沉槽）按 policy 限值核算；裸芯 <= 8-9 mm 作为谈判起点 | 第20章（谈判起点，不是设计结论） |


**磁芯套件候选（D1_100A，限值 16 mm，磁密判据 0.248 T）：**

| 套件 | 订货前缀 | Amin mm^2 | 3 匝磁密 T | 面积 | 裸芯最坏 mm | 全叠层最坏 mm | 余量 mm | 高度 | 2026-11-03 结论 |
|---|---|---|---|---|---|---|---|---|---|
| ELP 32/6/20 + I 32/3/20 | B66457G0000X | 128 | 0.34809 | 不过 | 9.80 | 9.94 | 6.06 | 过 | REJECT_FOR_THREE_AND_FOUR_TURN_FLUX_AT_RFQ_CURRENT |
| ELP 38/8/25 + I 38/4/25 **首选** | B66459G0000X | 192 | 0.23206 | 过 | 12.35 | 12.49 | 3.51 | 过 | REJECT_STANDARD_UNMODIFIED_AS_HEIGHT_EXCEEDS_TOTAL_LIMIT |
| ELP 43/10/28 + I 43/4/28 | B66461G0000X | 217 | 0.20533 | 过 | 13.90 | 14.04 | 1.96 | 不过 | REJECT_STANDARD_UNMODIFIED_AS_HEIGHT_EXCEEDS_TOTAL_LIMIT |
| ELP 58/11/38 + I 58/4/38 | B66293G0000X | 308 | 0.14466 | 过 | 14.90 | 15.04 | 0.96 | 不过 | REJECT_STANDARD_UNMODIFIED_AS_HEIGHT_EXCEEDS_TOTAL_LIMIT |
| ELP 64/10/50 + I 64/5/50 | B66295G0000X | 518 | 0.08601 | 过 | 15.60 | 15.74 | 0.26 | 不过 | REJECT_STANDARD_UNMODIFIED_AS_HEIGHT_EXCEEDS_TOTAL_LIMIT |

在 D1_100A 的 16 mm 下，同时通过高度余量与三匝面积筛选的目录套件只有 ELP38_I38；旧筛选表按 10 mm 判定，所以它给 ELP38_I38 的 REJECT 理由是高度，不是磁通。

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

1. ELP38 的 AL_ungapped、le、Ve 与窗口净高：目录摘录只有 Amin/Ae/高度，所以目标 AL 对应的中柱气隙现在算不出来——现有气隙是在 ELP32 的 AL 上算的，换套件即作废。
2. ELP38 + I 片在目标气隙下、0 - >=121.52 A、100 °C 的增量电感 L(I)；验收窗口沿用 1.0 uH ±10 %，即该电流范围内不得跌破 0.9 uH。
3. 外置件与变压器漏感的分配：外置 = 目标总电感 - 实测漏感，首件实测后才定。
4. 独立 Lr 的物理端子、焊盘与机械定义（器件定义目前只有电感/匝数/气隙）。
5. 气隙公差与 AL 验收窗口。
6. 止损路径：若 ELP38 的气隙窗口或 100 °C L(I) 不成立，才回到定制低矮磁路（三匝 Amin >= 200 mm^2）——标准 ELP32 在 121.52 A 下不满足磁通筛选，不能作为退路。

## 12. 出处

- `design/v3/bom/lr_design.json`
- `design/v3/power_priority/lr_tdk_catalog_core_screen.json`
- `design/v3/power_priority/lr_tdk_catalog_core_source.json`
- `design/v3/power_priority/d1_staged_target_policy.json`
- `design/v3/magnetics/magnetics_design.json (catalogue_core_stack)`
- `docs/D1_EXECUTION_KIT/20_低矮磁件Lr原厂尺寸磁通双约束审核.md`
- `design/v3/pcb/board_netlist.csv`

**跨件提醒**：变压器的磁通按各绕组实际电压积分核算；`L*I/(N*A)` 是 Lr 的电感筛查判据，不能拿来判断变压器励磁饱和。系统 24:1 是「半桥 + 四原边串联」与「3:1:1」共同形成的，单件匝比是 3:1:1。
