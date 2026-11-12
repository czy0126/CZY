# 磁件询价、加工输入、61 占位清单

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- 磁件询价单（`hardware/dcx_main/rfq/`）
- 磁件加工输入页（`hardware/dcx_main/manufacturing/`）
- 61 占位责任清单（`hardware/dcx_main/placeholder_eco.{json,csv}`）

## G2 V9 24 个磁件裸焊盘与 6 件原生缺件（2026-11-13）

- [源锁定逐端子审核](../../hardware/dcx_main/g2/g2_v9_p1_magnetic_terminal_gap_NOT_FOR_FAB.json)由 [可复算脚本](../../hardware/dcx_main/g2/audit_v9_p1_terminal_parity.py) 产生：以真实已保存/独立重开 V9 PCB（149件/443 pad/407 line/93 via）对照源校准的旧 G1 P1 83件/280导线原生原理图；**77个已落板 P1 器件的259个带网脚没有发现网络不一致**，但还有6个原理图位号没有原生 PCB 元器件：**T1–T4、CT、R6**。V9 PCB 上磁件的 **24个裸焊盘**（T1–T4各5脚，CT4脚）按当初原始顺序、脚号、网络逐一匹配，因此线路定义不缺，但这24个焊盘至今**不属于真实的原生器件封装**。R6 两脚在 P1 是1=VCC12、2=RUN，PCB没有该实体；**另有原始R8在独立保存副本上经过原生DNP验证（`addIntoPcb=false`、`addIntoBom=false`），旧G1源连线回执明确证明R8→R6的位号更替和同网连线**。因此R6很可能是应不装的同一上拉功能；必须重新从V9/V10原生P1核对R6的实际DNP字段，避免误装。
- **P1证据的版本边界**：原理图侧来自旧G1的原生连接性文件，尚未再次在 V9 的第一页逐脚导出；V9 Cout 第二页72件/144线已经独立重开验过。故这是一份从真实封装推出的缺件清单，而不是已经通过的最新 V9 **全** SCH/PCB网表等价证据。Native DRC仍有 1 项聚合的Netlist Error、168项Connection Error。不可通过删除/豁免磁件、改成无网自由焊盘或硬改网表解决；必须取得厂商实际端子尺寸/DOT与脚号，再建5个关联符号与真实PCB封装；对R6先核实历史R8 DNP在当前位号下是否仍生效：如果已禁PCB装配，则保留DNP而不创建假器件；若已启用，则同步原理图、真实BOM/封装并做原生ERC/DRC。`NOT_FOR_FAB`。

## 磁件询价单（`hardware/dcx_main/rfq/`）

`tools/magnetics_rfq_package.py` 生成 6 张独立询价单（T1–T4、Lr、CT），**放在
`hardware/dcx_main/rfq/` 而不是 `design/v3/magnetics/`**：那个目录由
`make_magnetics_manifest.py` 逐文件散列，加文件就要重跑 manifest，而询价单是
对外工件、不是设计包的一部分。

- **没有数据的字段写 `UNKNOWN` 并在该单第 11 节重列，不许填一个看起来合理的值**；
  处数由工具自己数（`main()` 扫全部 section 的 `value`，`--write` 末尾印出来；现在 **50 处**），
  **不要手抄成一个常量**——本文件曾写"37 处"，那 13 处差额全是后来加的 UNKNOWN 行。
  其中 CT 的完整高度、三件的环境温度、全部物理端子图与焊盘号都是它。
- **高度限值从 `d1_staged_target_policy.json` 读，不许再写死**：本工具原先把
  `HEIGHT_LIMIT_MM = 10.0` 印在每张单上，而 policy（2026-11-04）把 D1 定为 16 mm、
  D2 16 mm、D3 10 mm，并把 D1 的首选磁芯直接写成 `ELP38_I38`。T1–T4 与 Lr 现在同时
  列 D1/D3 两个限值与各自的余量（`height_limit_mm(D1)`/`height_limit_mm(D3)`），
  CT 只列 D1 并注明要供 D3 得收紧。改 policy 后必须 `--write` 重生成，测试
  `test_the_height_limits_come_from_the_policy_and_not_from_a_literal` 锁住。
- **Lr 单里的 ELP38 候选表是"旧结论为什么过期"的证据，不是新结论**：五个目录套件
  按当前 D1 16 mm 重算后，同时过"高度余量"与"三匝面积"的只有 ELP38_I38，但
  `lr_tdk_catalog_core_screen.json` 是按 10 mm 判的，它给 ELP38 的
  `REJECT_STANDARD_UNMODIFIED_AS_HEIGHT_EXCEEDS_TOTAL_LIMIT` 必须原样保留并注明失效原因
  ——删掉它等于抹掉基准变过这件事。ELP43 在旧表里 `preliminary_combined_16mm_candidate`
  为 true（剩 2.1 mm），补上胶/标签后只有 1.96 mm，所以新表里它是"不过"。
- **ELP38 的原厂数据在 `references/datasheets/elp38.pdf`（2026-11-05 取得）**：
  TDK "ELP 38/8/25 with I 38/4/25"，B66459 无夹子槽版本，N97；**第 7 页**是 EILP 图 + 磁性表
  （第 4 页是 E910 EELP 表、第 6 页是 EELP 图，取数别拿错页）。这些值进了
  `lr_tdk_catalog_core_source.json`（AL_ungapped 8400 nH ±25 %、le 43.6 mm、Ve 8440 mm³、
  窗口净高 4.45 ± 0.15 mm），所以 ELP38 的气隙是**按它自己的 AL 重算的**，不是 ELP32 的 1.4443 mm。
- **窗口净高 = 半芯总高 − I 片厚**（ELP38 8.25 − 3.8 = 4.45；ELP32 6.35 − 3.15 = 3.2），
  数据手册不给单列的窗口尺寸。`magnetics_design.catalogue_core_stack()` 现在有一条守卫：
  目录里 ELP32 的窗口必须逐位等于 `CORE["window_height_m"]`，改任一侧立刻 `SystemExit`。
- **气隙有效性范围是每个套件各自的，而且 N97 的气隙常数 TDK 没公布**：ELP32 是
  `0.10 < s < 1.50 mm`、ELP38 是 `0.10 < s < 2.00 mm`；K1/K2 只对 N87 印。
  所以"落在范围内"仍是**解析值**，是询价目标不是签核值。实测后果：ELP38 上 3 匝 1.0 µH 要
  **2.1651 mm**（出界），2 匝要 **0.9461 mm**（在界内、最坏配对磁密 0.2349 T），
  Lr 单因此按 2 匝报价——`test_the_elp38_gap_is_recomputed_from_its_own_al_not_carried_over` 锁住。
- **`lr_design.catalogue_core_design()` 是第二条算气隙的路径**：它读
  `lr_tdk_catalog_core_source.json` 逐套件重算，`candidate()` 仍固定 ELP32 常量；
  测试要求 ELP32 行与 `candidate()` 的 3 匝气隙相等（容差按报告 4 位小数的半个末位，
  `abs=5e-5`，不是 `rel=1e-9`）。往 source JSON 加字段会经 `{**c}` 流进
  `lr_tdk_catalog_core_screen.json`，那是**要重生成**的产物，不是手改。
- **气隙只给"按目标 AL 的工艺窗口"，不给固定值**：T 是 0.1211 mm（AL ±25 % →
  0.112–0.126），Lr 在 ELP32 上是 1.4443 mm（1.0 µH / 3²，**换套件即作废**）。
  路线明确禁止填未经计算的气隙。
- **变压器的磁通不许用 `L·I/(N·Ae)`**：那是 Lr 的电感筛查。本包在每张 T 单的
  波形表里写死"按各绕组实际电压积分"。
- 询价单与 `vendor_terminal_request.json` 的 24 个逻辑端子**必须逐项相同**
  （测试比对 `(terminal, net, dot)` 三元组），否则会出现第七个端子。
- **24+2 包（`tools/maxwell_diy_pcb_envelope.py`）只描述已经在板上的接口**：Lr 的 +2 行
  端距取原生封装的 **9.0 mm**（`hardware/dcx_main/g1/g1_pads.json` 焊盘中心 610.2 → 964.6 mil），
  不是早期概念写的 40 mm——那个跨度没有任何 CAD 落过，已撤回；要改 Lr 端距先改封装。
  T/CT 的 TBD 矩形是**磁芯本体**（也是 A6 沉槽轮廓），不是器件包络：绕组端子出芯是设计意图，
  不是"越界"。真正要查的是端子别碰到别的东西——`g1_native_pcb_report.json` 的
  `provisional_pad_gaps` 记读回实测最小边缘距离（2026-11-10：临时间 1.999 mm、临时到器件焊盘
  1.650 mm，相对板规则 0.152 mm），改焊盘前先看它；那是包围盒筛查，不是 DRC。
- **`templates/staged_magnetics_16mm_rfq.csv` 的 3.65 mm 与设计包的 3.51 mm 是两个口径**：
  前者 `source_status=MANUFACTURER_CATALOG_CORE_ONLY`，只减裸芯+I 片；后者补上胶/标签/压块/沉槽
  （净 +0.14 mm）才是全叠层。两个数都对，**不许互改**——模板是"目录件本身还剩多少"，
  `d1_staged_target_screen.json:elp38_full_stack_budget` 是"已知层都算上还剩多少"。
  `d1_staged_rebaseline.elp38_stack_budget()` 同时校验两者的裸芯高度一致（差 1e-9 即 `ValueError`），
  但有意不校验余量——它们的定义不同。

- **变压器磁通已由副边实测电压积分，不再只引方波公式**：`tools/transformer_flux.py` 读
  `..._100a.raw` 的 `V(a1)/V(b1)/V(a4)/V(b4)−V(out)`，按 `B=∫v/(N_sec·Ae)` 积分（N_sec=1）。
  **一个半周期跨完整个峰峰**，所以正、负半摆幅是同一个摆幅的两次测量，**不能相加**（第一版
  相加，`measured/analytic` 读出 2.04）；周期净伏秒必须**隔一个取一对**（`range(0, n−1, 2)`），
  重叠配对会把累计偏磁翻倍。实测：**ΔB_pp 39.16 mT、B_ac 19.58 mT（6.3 % Bsat）、
  对方波式 38.34 mT 高 2.1 %**；单周期不平衡最大 **0.481 mT**（峰峰的 1.2 %），
  整窗累计 **−2.10 mT**、三角上界 **5.04 mT = 1.63 % Bsat**；T1/T4 以及 A/B 两半的摆幅
  一致到 **0.08 mT**。漏感界 0.48 mT（k=0.999，`L_leak·i_pair/Ae`）。
  **`cumulative_net_t` 是相对本 120 µs 窗口起点的漂移，不是绝对磁通偏置**（raw 不存激磁电流）；
  deck 的磁芯是线性的，这对"会不会饱和"不构成证据。T2/T3 不存副边电压，只能"代表"、
  不可写成实测——RFQ 的 T2/T3 单因此写 UNKNOWN。见
  `design/v3/magnetics/transformer_flux_100a.json` 与 `tools/test_transformer_flux.py`。
- **故障窗的磁通只能报"故障前摆幅 + 跳闸后伏秒上界"，跳闸后的积分不是磁通**：48 V/120 A
  hotfault raw（1.05 GB）上，故障由 `Vfltctl_hot` 的 0→5 V 斜坡在 **2175.0 µs** 穿过
  `HOTFLT` 的 `Vt=2.5` 触发，保存轴上 **175.00 µs**（`.tran` Tstart=2000 µs）——
  `fault_instant()` 从 PWL 与 Vt 的交点算，**不要用 PWL 起点 2170 µs**。
  故障前 **38.56 mT pp = 12.4 % Bsat pp**（半摆幅 6.2 %），与 100 A 窗口一致；
  跳闸后主桥停振、两个副边半绕组各被自己那只 SR 钳住，A/B 两条积分**不再一致**
  （3.09 对 9.83 mT），所以只报较大者 **9.83 mT = 3.17 % Bsat**，并写成上界。
  **`|v|` 的积分在跳闸后在零附近振铃，会读出约 620 mT（200 % Bsat），已刻意不报**——
  它量的是振铃，不是磁通。只有 48 V 基座跑满声明的 320 µs（50 V 在 296.9 µs 塌缩），
  所以这条只建立在 48 V 上。故障 deck 只存 T1 副边电压 ⇒ RFQ 只有 T1 引这组数。
  见 `design/v3/magnetics/transformer_flux_fault_48v.json`。

## 磁件加工输入页（`hardware/dcx_main/manufacturing/`）

`tools/magnetics_manufacturing_input.py` 生成 6 张加工输入页（T1–T4、Lr、CT）+ `index.json`。
它**不是询价单的副本**：询价单问厂家能给什么（多候选），加工输入页写我们要做什么、回来量什么
（一个冻结候选 + 首件判据 + 空白回填表）。两套工件都留着，混用会让"候选"读成"决定"。

- **变压器与 Lr 分用途冻结**：T1–T4 在 ELP32（`EILP32`，磁通按副边电压积分定），Lr 在 ELP38
  （按电感保持率、气隙工艺范围与 0.9·Bsat 选）。`test_the_transformer_and_the_inductor_do_not_share_a_core`
  锁住两边不互相串。
- **气隙窗口必须按电感排序**：气隙越大电感越小，所以 L_min 对应最宽气隙。第一版直接按
  L±10 % 的顺序返回，页面印成 `0.1374 - 0.1077 mm`（窗口倒过来，磨不出来）——文字级测试全绿。
  `gap_window_mm()` 现在返回 `(narrow, wide)`，`test_the_gap_window_is_ordered_by_inductance`
  要求 `low < 标称 < high`。**这个数从 `core_gap_m()` 反算，不抄询价单里的字面值。**
- **Lr 页只写 `L_external = L_tank_target − L_leak_measured`（0.920 µH 是模型漏感的预估），
  1.000 µH 是筛选上限**，不是要绕的值；页面同时写出对 D3 的余量是 **−2.49 mm**（ELP38 只能用在
  D1 的 16 mm，D3 的 10 mm 需要更矮的套件）。
- **物理端子一律写「待商家提供」**：T1–T4/CT 来自 `vendor_terminal_request.json` 的 null 物理号，
  Lr 来自 `board_netlist.csv` 的两个端子（该文件里没有 Lr，因为它只有两端）。**不编焊盘号**，
  `test_every_logical_terminal_has_a_requirement_row` 逐端比对且禁止出现 `physical_pad`。
- **磁密只能写「仿真波形积分」或解析值**：`test_the_flux_figures_are_labelled_simulation_not_measurement`
  禁止 `实测磁密`，回填栏的值必须全是 `—`（表头单独一行、分隔行以 `|-` 开头所以不在表体里）。
- **CT 的磁芯还没选**（只有 Ae 20.1 mm² 与 Bsat 0.34 T），所以 `frozen: False` 会在页头加一条
  「尚未选定，不是可下单的加工输入」；`test_a_page_that_has_not_frozen_a_core_says_so` 锁住
  「没说未选定的页面不许出现这四个字」。现行 2 pad 封装是无效的，四端必须各自独立。

## 61 占位责任清单（`hardware/dcx_main/placeholder_eco.{json,csv}`）

`tools/placeholder_eco.py` 是**连表工具，不是新审核**：把已经存在的四份工件按位号连起来
（`component_decision_register.json` 的 61 行、`board_netlist.csv` 的派生网表、
`main_board_schematic.py:PERIPHERALS` 的 17 个外围、`pin_footprint_review.csv` 的逐脚状态），
为每一行给出"谁定连接、谁定取值、原生设计实测到哪一步、还差哪一件事"。
它**不产生 MPN**：本仓库没有厂家证据，`verified_mpn` 恒为 null，61 行的 `decision_owner`
也全部为空——"0 个负责人 / 0 个已核实 MPN"是清单要报告的事实，不是缺陷。

- **61 = 44 金网表 + 17 外围，互相不交**：17 个外围正是 `PERIPHERALS` 的键
  （12 只 VDD 去耦、`C13` EN 滤波、`R7`–`R10` 控制下拉与 RUN 跳线）。新加占位若两边都不在，
  `netlist_governance` 会变成 `UNGOVERNED` 而 `checks` 变红——那是唯一会让一行悄悄
  进制造的口子。
- **49 行有可复算的需求出处，12 行没有**：没有的是 4 只 REG 电容（2.2 µF 来自
  UCC24624 数据手册建议，仓库里没有算出它的工件）与 8 只 SR 漏极开尔文链（要求是拓扑的：
  VD1/VD2 必须在漏极取样，不是数值）。这 12 行的 `next_action` 写"先定义需求再选型"，
  **不能写成"选一个满足要求的件"**——没有要求就没有可核对的对象。
- **Lr 的 `native_pin_review` 是 MAPPED，但那只是逻辑端子名**：`native_pin_review_scope`
  为 `LOGICAL_TERMINAL_NAME_ONLY` 的六行（T1–T4/Lr/CT）仍然 `blocked_on` =
  `MAGNETIC_PHYSICAL_TERMINAL_DRAWING`。把 MAPPED 读成"物理引脚已核实"正是这条路线上
  要防的事。
- **deck 出处按元件名引用，第四列不一定是数**：`Dbt aux hb DBOOT` 的值是模型名，
  `element()` 的 `_si()` 解析失败时记 `null` 而不是抛错。`Cf`/`Rf` 的 τ 由两侧
  `_si()` 相乘得到（47 µs），不手抄。
- **`energy_mj` 已经是毫焦**：再乘 1e3 会把 R3 的故障脉冲印成 122.6 mJ（真值 0.123 mJ）。
  测试 `test_the_burden_resistor_is_traced_to_both_its_value_and_its_power` 锁住这个量纲。

