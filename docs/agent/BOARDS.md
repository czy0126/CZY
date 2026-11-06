# 实验板（SR 验证板 / fast-OC / 制造视图）

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- 单对真实 SR 关断验证板（`pcb/sr_fault_validation`）
- 布局 pass 3：布线 + 铺铜（`tools/make_sr_fault_board_pcb.py` + `tools/sr_board_router.py`）
- TLV3501 快速过流 ECO 模块（`pcb/fast_oc`）
- 模块布线板（`pcb/fast_oc/fast_oc.kicad_pcb`，`tools/make_fast_oc_pcb.py`）
- 实验板制造目录与主板剩余依赖（两张视图）

## 单对真实 SR 关断验证板（`pcb/sr_fault_validation`）

`tools/make_sr_fault_board.py` 是 D0 之后的下一实物：**一对真实 UCC24624 + 两只
BSC010N04LS6 + 故障接口**，取代"UCC27524 推假门极电容"那种只能验逻辑的台架。
它只到原理图/网表/ERC/BOM + 争流算术，`hardware_built`/`fabrication_approved` 恒 false。

- **主关断是 REG 撬棒（Q41+R44 4.7 Ω），不是切 VDD、也不是门极钳位**：UCC24624 没有
  enable，只有 REG UVLO 或 standby 才会把 VG 拉低。2.3 µF×11 V=139 µJ，撬棒
  **12.11 µs** 到 VREGOFF（3.63 V 门限、4.748 Ω = 4.7 + AO3400A 的 0.048 Ω）；
  只切 VDD 要 **75.5 ms**（1.1 µF 级电容 ÷ 1.5 mA 运行电流）。
- **Q41 已选 AO3400A（`references/datasheets/ao3400a.txt`），但"选中"不是"合格"**：
  3.3 V 台架经 R40/R41 1k/10k 只给 **3.0 V** 栅压，落在数据手册 2.5 V 列（48 mΩ max）
  与 4.5 V 列（32 mΩ）之间，所以 `RDS_SELECTED = 0.048` 取慢的那一列，不做插值。
  `q41_selection.qualified` **恒 false**，open items 是开通过渡 SOA（仓库没有数字化 SOA 曲线）、
  自热与 Rds 温度系数、R44 重复脉冲。BOM 行写 `AO3400A` + `mpn_source`，
  `test_the_bom_carries_the_same_stress_the_report_computes` 锁住"3.0 V"与能量字样。
- **撬棒的 UVLO 时间必须按 3.63 V 算，且它只是估计值**（2026-11-05 审核 P1）：`VREGOFF`
  是 3.63/4.0/4.25 V，取 4.25 V 会凭空快 1.5 µs。`crowbar()` 报四个场景
  （0.0 Ω 理想钳位 11.98 µs / **AO3400A 0.048 Ω 12.11 µs** / 0.1 Ω BOM 目标 12.24 µs /
  1.5 Ω 旧占位 15.81 µs），`worst_case.is_worst_case` **恒 false** 并列出理由，另有恒流注入敏感性
  **17.55 µs**（`t=RC·ln[(V0−IR)/(Vth−IR)]`，95 mA 是 REG=8 V 条件，只在 IR<Vth 成立）。
  **不要把它写"快速硬关断"**——route 里"REG 撬棒=快"已被降级为实验选项。
- **R44/Q41 的脉冲表是筛选比，不是合格判据**：释放能量 124 µJ（11→3.63 V），
  R44 **122.7 µJ、峰 25.23 W** / 均 10.1 W（在 4.748 Ω 下，**不是** 1.5 Ω 占位的 14.8 W
  ——Rds 变小 R44 分到的更多，审核明确不许再引旧值）；`r44_equivalent_pulse_width_s`
  = E/P_peak = **4.87 µs**，供对厂家脉冲曲线查表。1206 单脉冲曲线与 Q41 热模型仓库里都没有，
  `r44_pulse_rating_j`/`q41_thermal` 恒 `null`，温度写 UNVERIFIED。
- **开通过渡只能报估计**：Ciss 630 pF / Qgd 1.8 nC / Rg 4.5 Ω 全是 typ，经 R43 100 Ω 得
  到阈值 **43.5 ns** + Miller 穿越 **235 ns**（假定平台 2.2 V），线性斜坡上界 **3.55 µJ**；
  `turn_on_estimate.status` 明写 ESTIMATE 且无 SOA 曲线。**这不是 SOA 签核**。
- **故障输入默认态是"不撬棒"（fail-open）**：R41 10k 下拉，故障源断开/失电时板子
  保持不关断；`input_default()` 把这个限制写进 JSON，不许当成"默认安全"。
  状态输出是开漏 + R42 100k 下拉，高电平是分压的**下拉端**（3.3 V×100k/110k=**3.0 V**），
  写成 10k/110k 就把分压算反了（这条真的写错过一次）。
- **BOM 的 MPN 只在仓库里有数据手册时写，其余一律 `TO_SELECT`**：`Part.mpn`/`Part.mpn_source`
  成对出现，`test_every_mpn_in_the_bom_is_traced_to_a_datasheet_in_the_repository` 拿
  `mpn_source` 指的文件去 `grep` 那个字符串——编一个型号会让测试红，而不是让它进采购单。
  当前只有 U1（`UCC24624DR`，`references/datasheets/ucc24624.txt` 的订货表）与 Q1/Q2
  （`BSC010N04LS6`）有名有姓，其余 68 行是 `TO_SELECT`。**空白格读起来像"待补"，编出来的
  型号读起来像"有这个货"**——后者的代价高一个量级。
- **门极钳位默认 DNP（R47/R48/Q42/Q43）**：能压住 VG 的钳位（≤0.2 Ω）要 UCC24624
  在输出级烧 **16–18 W**，因为 6.5 Ω 上拉与钳位分压后仍要求 1.5 A 源流；2N7002 级
  （1.5 Ω）只能压到 **2.06 V**，高于 SR 的 VGS(th) 下限 1.3 V。焊盘留着是为了**实测一次**。
- **`VG1` 网络成员恰好 4 个**（`U1.1`/`Rg1.1`/`TP5`/`R47.2`），测试锁死——不许把第二个
  推挽驱动硬并到 VG（路线 P1 明令）。
- **`VSS` 与 `PGND` 是两个网络**，只经 R1(0 Ω)→SR_SRC→Rsh1(1 mΩ) 相连；不然门极电流
  的返回路径不可测。改这两只件等于放弃这条测量。
- **SR 支路 15.8 µs > 参考原边支路 1.29 µs**（REG→UVLO 是主导项），所以
  `t_stop = t_common + max(t_primary, t_SR)` 在这里选 SR；两支路并联**不许相加**。
  `delay_budget` 只是**地板**（`is_worst_case=false`），不含 UVLO 后的 VG 动态。

生成器两个踩过的坑：
- SR 符号把 S1–S3、D5–D8 合并到同一个图形端点，所以"不同器件不许共用 pin tip"的校验
  必须放行**同一器件、同一网络**的重合，只拒绝跨器件重合。
- **跳线两侧要各放一个 `PWR_FLAG`**：U1 的 VDD 是 `power_in`，被 JP1（被动引脚）与
  `VDD_IN` 隔开，只在 `VDD_IN` 上放旗子会报 `power_pin_not_driven`。ERC 的 0 违规
  必须用 `--severity-all` 且报告不比原理图旧，否则"干净"没有意义。

### 布局 pass 3：布线 + 铺铜（`tools/make_sr_fault_board_pcb.py` + `tools/sr_board_router.py`）

原生 `.kicad_pcb`：71 只件各摆一次、每只焊盘带原理图网络、132×92 mm 外形、四个 M3 孔，
**两层全部布通**（121/121 连接、163 个过孔、2993 段），`drc.json` 的
`unconnected_items` 为 **0**、`schematic_parity` 为 0、`silk_overlap` 也为 **0**。
**最后四条丝印冲突是靠挪“实例的文字偏移”消掉的，不是改库封装**：`Rg1`/`Rg2` 的位号
带 `g` 的下沉笔画压到自己的丝印线，TP13/TP17 距配对探针 3.5 mm 而 1 mm 文字更宽，
`REFERENCE_TEXT_SHIFT_MM` 只改这四只实例的 `(property "Reference" … (at dx dy))`，
因此同库的其它 0805 一个字节不动；`fill.json` 的填充面积与改前逐位相同（铜没变）。
五个电源网各有 zone 外形（PGND/VOUT 在 B.Cu，
SEC_A/SEC_B/SR_SRC 在 F.Cu）。`routed` 因此是 true，但
`fabrication_approved`/`hardware_built` 仍 false：**铺铜保留外形面积的 75 %–98 %**（见下条）。
载流不再靠"铺得满"来声称：**填充根本不在板文件里**（只存外形），所以
`power_path.escape_rating` 只对**布出来的逃逸铜**报价，且两种口径分开——故障脉冲用绝热
`I²t`（无散热项，是下界），连续电流用 IPC-2221 外表走线图表，**两个数不混用**。
每半副边从 x 43 的铺铜边缘经**一条 0.8 mm 走线 + 两个 0.3 mm 钻孔过孔**串到 x 46.87 的
漏极焊盘；**两种铜厚下都是过孔筒壁绑住脉冲数**（0.3 mm 钻 / 0.020 mm 壁 = 0.0201 mm²，
小于 1 oz 的 0.0278 mm²，长度相同），所以**加宽走线没用，要加大钻孔**。
`--check` 现在同时导出 `fab/`（gerber 带 `--check-zones`、drill、position、装配图）与
`fab/manifest.json`（逐文件 sha256 + 板哈希 + 重复那份载流评级 + 两个 false 旗）；
`--fab` 在没有 kicad-cli 时直接失败。**这只是制造包，不是签核**：
`hardware_built`/`fabrication_approved` 不变，1 oz 是包的要求。
`--check` 会重生成 + 跑 `kicad-cli pcb drc` + 实测填充写 `fill.json` + 导出 `fab/`。
清单另有 `process_requirements`，字段按出处三分（`measured_here` 读布线 /
`design_rules` 路由器常量 / `our_choice_not_measured`），三组互斥且覆盖全部非列表字段，
测试锁住；阻焊与丝印颜色写"板厂默认"，不编颜色。

**装配/DNP 图不从 kicad-cli 出，从同一张 `Placed` 表生成**（`tools/assembly_drawing.py` →
`fab/assembly.svg`）：A4 1:1 俯视，每只件一个 courtyard 方框 + 编号气泡，十个 DNP 件
红底虚线框并在板上标 `DNP`，下方两栏表列位号/取值/封装/状态。选它是因为
`pcb export svg` 画的是丝印——位号位置由布图决定（本板尚有重叠）、且**丝印说不出"DNP"**，
空缺焊盘与漏订件在图上一样。图与铜同源，因此不会互相矛盾，也不需要 KiCad。
`export_fab()` 里是**惰性 import**（`assembly_drawing` 反过来 import 本模块取件表）。
清单的 `files` 必须覆盖 `fab/` 下每个文件，测试逐名比对——未列入即无人哈希过。
**复用这张图纸时要连 `<title>` 一起换**：`svg()` 的标题参数只管印在页上的那行，
`<title>` 元素（窗口标题、读屏、grep 都能看到）第一版是写死的 SR 板名，于是 fast-OC 的
`assembly.svg` 里同时出现两块的板名。现在有独立参数 `doc_title`，默认值仍是 SR 板的原字面量，
所以已提交的 `pcb/sr_fault_validation/fab/assembly.svg` **逐字节未变**（参数化时验证过）。

**kicad-cli 只绘板文件 `(layers)` 表里声明过的层，没声明的静默丢弃**（退出码 0、
无消息、无输出行），焊盘上写着 `(layers "F.Cu" "F.Mask" "F.Paste")` 也不算数。
第一版生成器的表只有 F.Cu/B.Cu/丝印/Edge.Cuts，于是"九层"的包实际是**五层、
无阻焊无钢网**，而清单照请求列表印了九层。两份板生成器（`make_sr_fault_board_pcb.py`
与 `main_board_mechanical.py`）现在都把 `B.Paste`/`F.Paste`/`B.Mask`/`F.Mask` 写进表里；
`check_plotted_layers()` 在导出后逐层核对、缺哪层点名失败，清单同时记 `layers`（请求）
与 `plotted_layers`（实得），测试要求两者相等。**空层也会生成文件**（B.Paste/B.Mask
各一个），所以"文件数等于层数"是可用信号。

**`--exclude-dnp` 读的是封装上的 `(attr ... dnp)`，不是件表里的 `dnp` 标记**：SR 板的
十个 DNP（门极钳位 Q42/Q43/R47/R48/CGL1/2/Csn1/2/Rsn1/2）只记在件表里，板文件里
一个封装都没这个属性，于是 `--exclude-dnp` 什么也没排除——**十只默认不贴的件全进了
贴片坐标**，而 `manifest.json` 的 `excluded_from_position` 照件表宣称"已排除"，两份
工件互相矛盾。现在 `_embed(..., dnp=part.dnp)` 写进封装属性，`export_fab` 导出后
用 `check_position_excludes_dnp()` **读回 CSV** 逐位核对（位置文件 51 → 41 行）。
同类教训：清单里"我说已排除"不构成证据，判据必须从交付文件读回来。**`dnp` 与
`exclude_from_pos_files` 是两个属性**：测试点（TP1–TP20）用的是后者，DNP 件仍要
有焊盘与坐标之外的"不上料"语义，不能拿一个冒充另一个。

**Q1/Q2 的封装现在是从数据手册量出来的，不是厂商 vendored 件**：
`tools/bsc010n04ls6_land.py` 数字化 `references/datasheets/bsc010n04ls6.pdf` 第 10 页的
Board Pads 图（rev 2.3，8 个印刷标注全部 ≤10 µm，实测最大残差 4.9 µm），写
`design/v3/pcb/bsc010n04ls6_land.json`；`make_sr_fault_board_pcb.bsc_source()` 读它生成
`dcx.pretty/BSC010N04LS6.kicad_mod`，任一项 `checks` 为 false 就 `SystemExit`。
**28 个焊盘分三类**：10 个带号铜焊盘（漏极基座 `5` + 四根指 `5/6/7/8`，源极条 `1` +
`1/2/3`，栅 `4`）、3 个 `F.Mask`、15 个 `F.Paste`。同名号多块铜只有在相接时才是同一块
焊盘，所以每根指压进基座 **0.125 mm**——图纸上边对边相接，CAD 里一个舍入就会把 6–8 脚
留成孤立铜。掩膜（并集外扩 0.05 mm）与钢网（面积比 0.6102）作为独立焊盘画出，
`sr_board_router._copper_layers()` 对无 `*.Cu` 的焊盘返回空元组，所以它们对布线不可见。
原来 vendor 件把五块漏极铜全编号 `"5"`、6–8 脚无焊盘的问题由此关闭
（`pad_pin_mapping.symbol_pins_without_a_pad` 变成 `{}`），**但这是照图重画，不是厂家
CAD、也没按 IPC-7351 校核——`remaining_work[0]` 就写着这条**。
封装测试 `tools/test_bsc010n04ls6_land.py`（9 项）在无 PyMuPDF 时跳过重生成，
只校验提交 JSON 的不变量，与 `vendor_soa.py` 同一个模式。

**铺铜的第一版被 `island_removal_mode 0` 吃掉了，原因是布线不是铺铜**：这个模式只保留
能碰到本网焊盘的铜，而信号一旦横穿走廊，一条 0.25 mm 的走线就把走廊切成两半，远端那半
够不到焊盘、整块被删。改法是在**布线**一侧加价，不是把外形画大：`keep_clear()` 把五个外形
交给路由器，`Router._zone_cost(net)` 对除本网外的每个网络在走廊内按格计 `ZONE_PRESSURE = 6`
（0.125 mm 一格，穿 12.5 mm 走廊要付 100 步，绕行更便宜），`route_net` 把它传给 `_search`。
实测保留比例因此从 36.2/12.2/10.7/2.5/65.2 % 变成 PGND **4519.5/5336.0（84.7 %）**、
VOUT **552.7/561.0（98.5 %）**、SEC_A **262.1/350.0（74.9 %）**、
SEC_B **336.5/360.0（93.5 %）**、SR_SRC **248.0/284.0（87.3 %）**，**五块各成一整块**；
121/121 连接、2993 段、163 过孔、`barrier_crossings` 空。
**这仍不是载流结论**：面积百分比与铜厚无关，没有铜厚就没有方阻；Q1/Q2 的逃逸口
（x 43–46.4 mm，外形到 43、漏极焊盘从 46.4 起）无论如何都要走 0.8 mm。IPC-2221 在 1 oz/10 °C
下给 10 A 约 7 mm——图表不是测量，但足以说明**铜厚定下来之前本板不能按 10 A 导体引用**。
`fill.json` 的"外形内的本网焊盘"按**焊盘中心**
判定（热焊盘中心天然不在铜上），连通性只看重新填充后的 DRC（`unconnected_items`=0、
`isolated_copper`=0），不要拿这个计数当连接判据，也不要拿面积当载流判据。
`fill.json` 是构建产物（kicad-cli 版本相关），提交但不逐字节比对。

**加价是"偏好"，保不住走廊；VOUT 带必须是"墙"**（2026-11-06 定）。先修的是优先级：
`keep_clear()` 原来只交 `(outline, net)`，VOUT 带（B.Cu 优先级 2）与 PGND 平面（优先级 0）
在 y 40–45.5 重叠，VOUT 却在替 PGND 的走廊付账，于是它绕开自己即将拥有的铜，VOUT 只剩 11.1 %。
`_zone_cost()` 改成按**每格最高优先级**的归属加价后 VOUT 恢复到 93.8 % **但问题没解决**：
另一次与布线无关的改动（D40 从 SOT-23 换 SOD-123）把一条 PGND 走线挪进带内，VOUT 又掉到
**11.3 %**，而 PGND 同时从 84.9 % 升到 94.0 %——**这是一个铺铜换另一个铺铜，靠运气**。
根因是**加价永远只是偏好**：穿 5.5 mm 带是 44 格、按 `ZONE_PRESSURE` 约 260 步，绕 100 mm 走廊的任何走法都更贵，
所以"加价更高"这条路上 A* 一定选择穿过去。常数调到 20 会让 A* 搜遍全板（15 min 未完，
6 时约 3 min），也不是解。
现在 `Pour.barrier=True`（只有 VOUT 带）把 **本层的**带内格子变成障碍：`Router._zone_barrier()`
用同一张 `_zone_owners()` 归属图生成墙，`route_net` **先带墙搜、搜不到再去掉墙重搜**，重搜成功
就把这条连接记进 `RouteResult.barrier_crossings`（同样是"(新焊盘, 已连焊盘)"序）并出现在
`routing.barrier_crossings` 里。**墙不是绝对的**：走廊里有焊盘的连接硬拦着会变成未布线，
而未布线比切开的铺铜更糟。墙只作用在本层，所以要穿过的网络可以打过孔走另一层。
判据仍是 `test_the_corridors_keep_their_copper` 的 70 %，**没有为变绿而放宽**；
两条新测试锁住"墙只在本层"与"非穿不可时会回退并如实上报"。

**`island_removal_mode 0` 只问"碰到本网焊盘"，所以一条走线也算**：VOUT 带的中段能活下来
不是因为它被本网焊盘碰到（`fill.json` 的"外形内的本网焊盘"读 **0**），而是因为 VOUT 有一条
B.Cu 走线伸进带内。**不要把"焊盘数 = 0"读成"这块铺铜是孤岛"**——连通性判据是重新填充后的
DRC（`unconnected_items`/`isolated_copper`），不是焊盘计数。
**这正是 VOUT 带要设成墙的原因**：带内没有本网焊盘做锚，任何一条外来走线切开后，
中段只能靠"恰好还有本网走线伸进去"活着——那是走线顺序的副产品，不是设计属性。

三条铺铜专属的坑（都在 `test_make_sr_fault_board_pcb.py` 里）：

- **`island_removal_mode` 只能写在 `(fill ...)` 里**。写到 zone 层 KiCad 10.0.6 拒绝加载
  （退出码 3）。旧 `check()` 用 `check=False` 吞掉，然后读到上一次的 `drc.json`，
  把"0 未连接、4 条 silk"当成刚测出来的——**stale report 比崩溃更危险**。
  `run_drc()` 现在先 `unlink` 报告再跑，非零退出或无报告一律 `SystemExit`。
- **`--save-board` 只在测填充时用，而且只对 `pcb/sr_fault_validation/` 里的临时副本用**：
  出了这个目录 `fp-lib-table` 找不到，填充为空（看起来像"铺铜没填上"）；
  写回真板会让文件从 2.5k 行变成 33.6k 行。
- **VOUT 带子必须避开 J3.4**：PGND 通孔 x 31.6–34.4、y 44.6–47.4，一条居中在 y=46 的带子
  会被剪成两条 1.4 mm 细条；现在放在 y 40–45.5。

另外：**热焊盘中心本来就不在铜上**（0.5 mm 热隔离 + 辐条），所以"焊盘中心落在填充上"
的计数低于外形内焊盘数**不代表没连上**；判连通用重新填充后的 DRC
（`unconnected_items`=0、`isolated_copper`=0），`isolated_copper` 已进 `POUR_ERRORS` 门槛。
`kicad-cli` 的 stdout 不是 GBK：`subprocess.run(..., text=True)` 会在读线程里抛
`UnicodeDecodeError`，把捕获的消息全变成 `None`——所有 kicad-cli 调用都加
`encoding="utf-8", errors="replace"`。

生成器的 `check()` 有两条**互相反向**的守卫，缺一条就会被净空表骗过：
router 说全连而 kicad-cli 还报未连接 ⇒ SystemExit（铜没落到网表点名的焊盘上）；
router 说没布通却 0 未连接 ⇒ SystemExit（网表根本没进板子）。当前走的是第一条的反面。

**栅格路由器有三个已经踩过的坑，都写在 `test_sr_board_router.py` 里**：

- **焊盘不是它的包围盒**：本板 114 个 `roundrect`、30 个 `circle`。1 mm 圆焊盘的
  bbox 角点离铜 **0.207 mm**，走线端点落在那儿，router 数的是"连上了"，kicad-cli
  报 `track_dangling`（第一版 94 条违规里 78 个是这类，另一批 22 个是圆焊盘）。
  `_pad_cells` 现在用 `_pad_distance()` 按 shape（circle/oval/roundrect+`rratio`）算到**铜**
  的距离，第一个候选层是"格心在铜内"，退路是"距铜 ≤ 半个线宽"。**半格步长的容差是错的**，
  它够得着线端帽盖不到的格子。
- **rip-up 的选择顺序 ≠ 重布顺序**：`_rip_victims()` 按距离挑（"谁的铜挡路"），但如果
  照这个顺序重布，主通路上排第一的 PGND 会被五个信号网挤掉一条连接 ⇒ 118/119，
  单调判据把整次修复回滚。改成按主通路 `order` 重布同一批受害者 ⇒ 119/119。
- **同网铜可以共用，同网钻孔不行**：`_blocked` 豁免本网铜，于是搜索能把过孔叠在自己的
  过孔上（`holes_co_located` 2 条）或放到 0.25 mm 外（`hole_to_hole` 2 条）。
  `_via_keepout()` 按 `drill + 0.25 mm` 圆心距封掉所有已有钻孔，且**不接受本网豁免**。
- **净空是按格心盖的，格与格之间可以低到半个步长**：到凸集的距离是 1-Lipschitz，
  一条线段在两端格心都合格，中段仍可能比规则低 `PITCH_MM/2`。第一版开走廊压制后立刻
  报出一条 0.152 mm 对 0.20 mm 的 SEC_B/SR_SRC 冲突，正是这个缝。修法是
  `CLEARANCE_MARGIN_MM = PITCH_MM/2` 加进障碍物边距——但**只对走线和过孔加，焊盘不加**：
  给焊盘也加会把两条网挤到布不通（119/121、rip-up 折腾 8 分半），只加走线/过孔时
  121/121、2944 段、169 过孔、3 分 06（那版读数；加了 VOUT 墙之后是 2993 段 / 163 过孔）。
  焊盘周围的半格缝由搜索的"距铜 ≤ 半个线宽"退路
  负责，不与净空混为一谈。

**间距常量的来历**：`GAP_MM = 1.25` 是量出来的，不是审美——SOIC-8 焊盘 1.95×0.6 / 1.27 间距
在相邻焊盘间只剩 0.67 mm 无铜，0.25 mm 走线加 0.2 mm 净空要 0.65 mm，剩下 0.02 mm
是栅格步长 0.125 的六分之一，**根本表示不出来**。同一路由器同一顺序实测：0.75 mm 停在
117/119（383 s），1.25 mm 65 s 到 119/119。

**三个默认关闭的结构性杠杆**（`sr_board_router`，为一块 176 器件的 D0 十路板加的；
那块板按 issue #36 的排序**延后**到 "真实驱动器决策" 之后，所以这三个杠杆目前**没有已提交的
消费者**——留着是因为测量过、默认关闭、且由测试锁住；SR 板与 fast-OC 板的已提交铜逐字节不变）：

- **`rip_corridor=True`：修复只看得见端点附近 1.5 mm 的障碍**。`_rip_victims` 原来按
  **两个焊盘之间**的距离给候选打分，所以走廊中段的挡路铜永远不进候选表，失败一次就永久。
  打开后按 `_element_line_distance` 量到"这条连接要沿的那条线"，再加一条**反向**分支
  优先**单个**网。实测 D0 板：只布 PGND（114/118）就把 40 个失败网里的 **8 个**关死
  （`GL1/HB/HO/LO/PERMIT_RAIL/SOB2/TG_HI/TG_LO`，六个是 U18 的信号脚），其余 32 个是被
  其它 94 条网的累计铜挡住的——**两个原因，不要用一个杠杆去解释全部 40 条**。
- **`dir_penalty>0`：两层原先完全等价**，于是一条要走 50 mm 东向的网会自己摊到两层上，
  谁也不给需要北向的网留车道。给 F.Cu 水平走向、B.Cu 垂直走向后，转弯只能走过孔——这才是
  手布线板的样子，也是 400+ 连接能塞进两层的条件。启发式仍然可采纳（每步至少代价 1）。
  **代价是搜索变慢**：D0 板基座（无粮、escape 0.40）40 个失败网要 601.3 s。
- **`t_junction=True`：`route_net` 只认目标焊盘**，于是 118 个焊盘的 PGND 会画 117 条
  各自回到焊盘的平行走线；打开后可以先接到**本网已有的铜**上，成为一条主干加短支。
  `_near_cells` 只把树里离目标 6 mm 以内那段当目标——把整条 110 mm 的树交给 A* 会让它
  退化成全板 Dijkstra。

三者都是**参数不是常量**：`route(...)` 与 `Router(...)` 的默认值分别是 `False/0.0/False`，
改默认值会让两块已提交的板重生成后不再逐字节相同（`test_..._is_off_unless_the_caller_asks_for_it`
三条锁住）。

- **courtyard 不一定关于原点对称，必须整框平移**：MX126 02P 是 **−3.5…+8**（中心 +2.25）、
  04P 是 **−3.5…+18**（中心 **+7.25**）。只存"宽×深"再按包围盒居中，会把 J1 往左挪 2.25 mm
  （真报过 `courtyards_overlap` 对 U1），04P 会挪 7.25 mm——比 0.75 mm 的间隙大一个量级。
  `Placed.bounds` 存本地整框、`Placed.rect` 做平移；`_first_fit` 扫的是**原点**，
  用 `origin + local box` 判定。
- **kicad-cli 10.0.6 把任何被旋转的封装报成 `lib_footprint_mismatch`**：把库里的封装
  逐字节复制、只加一行 `(at x y 90)` 也会报。所以摆放全部 0°，`placement()` 里
  非零角度直接 `SystemExit` 并写明原因——旋转一只件去"消警告"是拿真实布局换一条被压制的发现。
- **DRC JSON 有三个顶层项目数组**：`violations`、`unconnected_items`、`schematic_parity`。
  老鼠线在**第二个**里；只读 `violations` 会得到"未布线板子 0 个未连接"，于是
  "未连接为 0 ⇒ 网表没进板子"这条守卫正好反着触发。布线前是 **111** 条欠账、29 条 `silk_*`，
  布通后两项都是 0；`schematic_parity` 始终 0 条。真名是 `courtyards_overlap`（复数）。
  丝印按**欠账**报、不当门——永远绿不了的门没人看。
- **`missing_courtyard` 默认被忽略**（没 courtyard 的板子报"0 违规"），要靠
  `sr_fault_validation.kicad_pro` 的 `board.design_settings.rule_severities` 提到 error；
  该文件**只由 `python tools/make_sr_fault_board.py --check` 写**，改完 PCB 生成器不重跑它就不生效。
  生效的判据是 `drc.json:ignored_checks` 里不再有它。
- **vendor 的 TDSON-8 把五个漏极焊盘全编成 "5"**（`1,2,3,4` 之后 5 个 `"5"`），而符号按真实
  BSC010N04LS6 引脚把漏极拆成 5–8 ⇒ 6/7/8 脚没有自己的焊盘（`pad_pin_mapping.symbol_pins_without_a_pad`）。
  本板已由数据手册量出的 land pattern 关闭（见上），这条留在这里是因为它说明了
  **为什么不能靠改符号引脚号或改 vendor 封装去抹平**——那种改法会把缺件藏起来；
  器件专用 land pattern 才是正解。A5 主功率板也已换用同一份 land pattern（见"A5 带网摆放"），
  那边不再有 6/7/8 脚无焊盘的问题。
- **SOT-23 上放两脚稳压管（`D40`）不是"多一个空焊盘"，是钳位开路**（2026-11-06 修）：
  `Part.nets` 只映射**符号引脚**，而 `validate()` 要求它的键集合等于符号脚号——两脚齐纳
  永远只到得了封装的 1/2 号焊盘，而 **BZX84 的阴极在 3 号脚**。于是 `FAULT_G` 接在阳极上、
  `PGND` 接在空脚上，钳位在原理图/ERC/DRC 全绿的情况下**从来没导通**；旧的
  `test_a_pad_the_schematic_never_names_stays_netless` 还把这个空焊盘当成"闲置铜箔"的正面例子。
  现在 D40 是 `5V1` + `Diode_SMD:D_SOD-123`（两焊盘，极性由丝印带标），
  `test_the_shutdown_clamp_cathode_has_a_pad_and_lands_on_the_gate` 从 **vendored `.kicad_mod`
  里读丝印带**（最短的那条竖线）定位阴极焊盘，再要求它落在 `FAULT_G`——不靠生成器自证。
  **教训**：`symbol_pins_without_a_pad` 只查"脚有没有焊盘"，查不到"**电气极性与实装相反**"；
  两脚器件配三焊盘封装要当成拓扑问题，不是封装美学问题。空焊盘的那条测试改用晶体管举例，
  并保留"必须存在至少一个空焊盘、否则断言什么都没检查"的守卫。
- **装配审核是拿板子和 `BOM.csv` 对，不是拿板子和自己的件表对**：`assembly_review()` 从
  BOM 文件读回来比 Reference/Value/Footprint（**必须是文件**，读生成器自己的表等于自证），
  输出 `in_bom_but_not_on_the_board`/`on_the_board_but_not_in_the_bom`/
  `value_or_footprint_mismatch`/`duplicate_bom_rows`，并计入 `checks`。
  同时列出 7 只通孔件（J1–J4、JP1–JP3）与 10 只 DNP 件（DNP 是"不上料"，焊盘仍在）。
  **position 文件不导出**：未布线的板子旁边放一个贴片坐标文件，看起来就能下单了。

## TLV3501 快速过流 ECO 模块（`pcb/fast_oc`）

`tools/make_fast_oc_eco.py`：D0 的快速过流通道（U3B LM393）**不是比较器慢，是它前面
三级滤波慢**——1k/47nF、10k‖24k+10nF、10k/1nF 合计 **127.6 µs** 时间常数，再加快 1.3 µs
传播。所以"把 LM393 换成 4.5 ns 的 TLV3501"在系统上只值约 1.3 µs，属于路线点名的
"只换 BOM 名称"。本模块直接取 CT 负载节点 OCD，单极点 1 µs + 12 ns + 50 ns ≈ **1.06 µs**。

- **系统级 `t_stop` 由 SR 支路决定，不是比较器**：`system_delay()` 按路线 P1-b 的式子
  `t_stop = t_CT/整流/滤波 + t_cmp + t_common_logic + max(t_primary, t_SR)` 组装。
  SR 支路从单对 SR 板的 `delay_budget` **读出**（不重推，防止两份文档漂移）：撬棒 50 ns +
  REG→UVLO **12.107 µs**（3.63 V 门限、AO3400A 0.048 Ω）+ VG 拉低 16 ns = **12.173 µs**；
  那块板自己的 **10 µs 输入 RC 不计入**
  （它是验证板前端，不是主板的故障通路，`sr_branch_terms.excluded_input_rc_*` 显式记着）。
  原边参考支路 1.29 µs ⇒ 慢支路是 SR。公共项（D0 解码 + CD4013 锁存）从
  `design/v3/stage_f/d0_response_budget.json` **读出**，不在这里重推：
  快模块路径付 **external** 通道 1.11 µs、原滤波通路付 **fast** 通道 1.00 µs
  （差的就是 U11F 反相器），各加锁存 0.4 µs ⇒ **1.51 / 1.40 µs**，两条总数各加自己那一项
  （`common_logic_terms` / `existing_common_logic_terms`）。整机地板 **14.7 µs**，
  对原滤波通路 **142.5 µs** 是 **≈9.7×**，而模块自身的 **121×** 只是**检测段**比较。
  仍是**地板不是最坏值**：U6.4（CD4081B）没有 max，`common_logic_is_a_floor` 为 true。
  `test_each_path_pays_its_own_decode_not_the_other_one` 锁住两条路径不许共用一项
  （共用会凭空造出 0.11 µs 的差异），`test_a_moved_decode_chain_is_not_silently_repriced`
  锁住解码链一挪就 `SystemExit`；`test_the_system_stop_is_not_the_module_delay` 锁住
  9.7× 必须远小于 121×（<1/5），
  `test_the_shutdown_branch_comes_from_the_sr_board_report` 锁住 SR 板 `max_branch_s` 与
  这里之差**恰好**是那条被排除的 RC。

- **SHDN 接高电平会把比较器关掉**：SBOS321E 里 SHDN 距 V+ 不足 0.9 V 即关断（输出高阻），
  低于 V+ 超过 1.7 V 才使能。接 V+ 得到的是 ERC 干净、永不翻转的板子。R8 10k 拉到 PGND，
  `test_shutdown_is_pulled_low_because_high_disables_the_comparator` 锁死。
- **推挽输出不能直接并到 `FAST_TRIP`**：D0 那条网是 U3B 漏极开路 + R15 10k 上拉，本模块
  用 R5→Q1(2N7002)→漏极开路才合法。`U1.5` 不在 `FAST_TRIP` 网络里，测试锁死。
- **D1/D2 写的是 `BAT54W-E3-08`（Vishay，SOD-123），不是短名 "BAT54"**：同一个短名在
  Nexperia 是 SOT-23（`BAT54W` 那边反而是 SOT323），在 Vishay 是 SOD-123
  （Doc 86408 订货表），所以短名既不能下单也不能当封装依据。`d12_selection.land`
  拿仓库里的 `Diode_SMD:D_SOD-123` 与 Vishay 推荐焊盘逐项比：焊盘 0.9×1.2 对 0.85×0.85、
  中心距 3.30 对 3.35 mm（差 0.05 mm），verdict
  `COMPATIBLE_WITHIN_0P1_MM_NOT_THE_VENDOR_LAND`——**兼容但不是厂家 land**，首件要实测；
  `qualified` 恒 false，open items 里有反向馈电通路（D2 把 INP 抬回 V5 的工况没建模，
  只列台架计划）。
- **最坏值用 12 ns，不用 4.5 ns**：12 ns 是 5 mV 过驱、−40…+125 °C 的 max。典型值只配当注释。
- **门限 75.0 A 标称 / 76.6 A 跳闸 / 73.4 A 释放**（2.5 V × 3 / 0.1 V/A）。它**刻意高于**
  冻结短路 deck 的 73.68 A——那一档留给 UCC25600 自己的 1 V/24 A、2 V/48 A 两级；
  本模块指向 84.83 / 97.44 / 101.26 A 的严重故障。改分压就改这个次序，测试会红。
- 共模上限对应 **144 A**，绝对最大值对应 **159 A**；已发布的峰值全部在共模内。
- **5 V 丢失 = 失去快速保护，不是误跳闸**：R6 把 Q1 栅极拉到地，FAST_TRIP 释放。
  LM4040D25IDBZR 的最小工作电流本仓库没有，低压拐点标 UNVERIFIED，不许填数字。
- **本模块不锁存**，锁存在 D0 的 CD4013。单独使用时输出跟随电流。
- 生成器复用 `make_sr_fault_board` 的解析/校验helper（`Part`/`Pin`/`custom_symbol`/
  `extract_symbol`/`pin_tips`/`validate*`/`erc_violations`），UUID 命名空间与件表是本板自己的，
  两块板不会撞。改 helper 的签名要同时看两个测试。
- **U1 是 DBV 六脚封装，不能和两脚基准源共用 `SMD = SOT-23` 这个常量**：第一版就是六脚落在
  三个焊盘上，而 ERC 全绿——**ERC 不看封装**。已改成 `Package_TO_SOT_SMD:SOT-23-6`，
  `test_every_symbol_pin_has_a_pad_in_its_footprint` 逐件读库文件数焊盘（不是数符号脚）。

### 模块布线板（`pcb/fast_oc/fast_oc.kicad_pcb`，`tools/make_fast_oc_pcb.py`）

52 × 38 mm 双层，26 只件、9 条网、52 个焊盘、**42/42 连接**（504 段 0.25 mm、35 过孔），
`drc.json` 三个顶层数组全空。`--check` 在 DRC 有任何一条时就 `SystemExit`，
`hardware_built`/`fabrication_approved` 恒 false。三条操作事实：

- **`escape_mm = 0.0` 是实测选的**：路由器默认给"尚未布线的网"的焊盘留 0.40 mm 余量，
  防后续网把出口封死；U1 内侧焊盘到对面一排只有 1.375 mm，够 0.25 mm 走线（0.775 mm）
  不够两侧同时留（1.575 mm）。六种确定性顺序在默认值下停 40/42 或 41/42，归零后 42/42
  且无净空违规。参数默认值仍是 `ESCAPE_MM`（SR 板不变，`test_sr_board_router.py` 锁住），
  本板的选择写进 `fast_oc_pcb.json:escape_reserve_mm`——**不要只写在注释里**。
- **安装孔位号必须隐藏**：孔中心离边 5 mm、位号在孔上方 4.9 mm ⇒ 落在 38 mm 板外，
  DRC 报 `silk_edge_clearance`。`mounting_hole_source(hide_reference=False)` 默认不变
  （SR 板已提交文件的字节不能动），本板传 True。**两处都要传**：`write()` 写 `dcx.pretty`
  的文件、`board_file()` 内嵌的那份是**各自独立生成的文本**，只改一处板子照样带可见位号。
- **`dcx.pretty` 必须先写再生成板文件**：`board_file()` 经 `stock_text()` 从磁盘读封装，
  顺序反了会内嵌上一次的副本——全新 checkout 重生成与提交件不一致，而本机看起来没问题。
  同一个陷阱对任何"生成器先写库、再引库"的板子都成立。

**本机 `PostToolUse` 钩子会对编辑过的 `.py` 跑 `ruff check --fix`，它会删掉"暂时未使用"的 import**：
先加 `import x`、下一次编辑才写用法的分步做法会被吃掉（`make_fast_oc_eco.py` 与它的测试都撞过）。
要么一次写完 import + 用法，要么在用法落地后再补 import。`make_fast_oc_pcb.py` 加 `--fab` 时
**同一个坑又踩了一次**：`import subprocess` 与 `from pathlib import Path` 分两步加，写 `export_fab`
之前就被删掉，首跑 `NameError`。

## 实验板制造目录与主板剩余依赖（两张视图）

两张都是**视图，不是审核**——只搬用已提交工件的数字（哈希、文件数、旗标、阻塞项），
不做任何设计判断，也**不能**把任何一项变绿。48 小时路线第 5 项明确"不再新增综合审计框架"，
所以两者都只读上游、只在自己过期时失败。

- **`pcb/manufacturing/{index.json,README.md}`**（`tools/manufacturing_index.py`）：四块实验板的
  固定表（`sr_fault_validation` / `fast_oc` 有完整制造包，`d0_protection` / `control_validation`
  只有原理图）。**表是写死的，不靠遍历 `pcb/`**：新出现的目录不该自动获得"已知板"的地位，
  消失的板必须让 `--check` 变红。状态四选一：`SCHEMATIC_ONLY` / `NO_FAB_PACKAGE` /
  `FAB_PACKAGE_STALE` / `FAB_PACKAGE_PRESENT`，过期由三条判据得出：manifest 的 `board_sha256`
  与提交板不符、manifest 文件清单与实际目录不符、`plotted_layers != layers`。
  **manifest 缺 `flags` 时按 false 读**（`_flags()`）：缺席正是未批准的包混成已批准的路径。
- **`hardware/dcx_main/remaining_dependencies.{json,md}`**（`tools/remaining_dependencies.py`）：
  把 `d1_fabrication_gate.json` 的 6 个阻塞项逐一配上**实物/数据出口**（`VENDOR_DRAWING` /
  `PART_SELECTION` / `GUI_DEVICE_CHANGE` / `ROUTING` / `BENCH_MEASUREMENT` / `SIGNED_REVIEW`），
  数字全部从 gate 与 `placeholder_eco.json` 读，不重算。两个 12 是**不同的两组**：
  `NATIVE_DEVICE_CHANGE`（C5/CT/Cin/Cout/Cr/D_BT/Lr/R3/T1–T4，要 GUI 换器件）与
  `requirement is None` 的 12 行（C7–C10、R28–R35，先定义需求再选型）。证据文件名必须与
  `manual_evidence` 逐字相同——差一个字，读者就会去造一个 gate 永远不看的文件。
  `uncovered_blockers` 为空是**工具表**的不变量，不是设计结论。
- 两者都进了 `tools/ci_check.py` 的 `VIEWS`（`--skip-tests` 也查），因为它们只读提交文件、
  不需要 kicad-cli；过期的一页会让读者照着一个失效的哈希或命令去做事。
- **`counts` 里三个字段是"名字的列表"不是计数**：`magnetics_missing_physical_pads`、
  `refs_with_placeholders`、`bom_rows_not_selected` 都是 list。直接插进 f-string 会把 30 个
  字典印进化后的段落里（`remaining_dependencies` 第一版就这么印了），要 `len(...)`。

