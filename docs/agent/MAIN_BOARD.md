# A5 摆放·布线·铺铜、A6 机械剖面

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- A5 带网摆放（`hardware/dcx_mech/`）
- A5 已经布出来的铜（`tools/main_board_power_copper.py`）
- A5 铺满两层的上限（`POUR_PATHS` / `pour_study()`）
- A6 机械剖面（Issue #12）

## A5 带网摆放（`hardware/dcx_mech/`）

`main_board_mechanical.py` 已从"无网摆件"改成**带网摆放**（网从
`hardware/dcx_main/pin_footprint_review.csv` 读，按**焊盘名**落户）。板仍然是**未布线**的。

- **三个数不是同一个量**：`pads_landed` **262**（带网的焊盘**名**）、`physical_pads_netted`
  **278**（实际铜焊盘）、`kicad-cli` 的 `unconnected_items` **150**（**不是** 262 − 64）。
  差额 16 = 8 只 SR × 2（漏极基座与一根指都叫 `5`，源极条与一根指都叫 `1`）。
  **KiCad 把同一封装里同号焊盘当一只连接实体**，所以老鼠线条数跟着焊盘**名**数走，
  不跟物理铜走——这正是厂家用同号漏极焊盘表达"这五个是一个引脚"的原因。两个数都报，
  报一个会让另一个看起来像丢了的连接。**150 比两个计数都短**，因为 KiCad 还会把**铜重叠的
  同网焊盘**并成一个节点（四根漏极指压进基座 0.125 mm），所以"老鼠线 = 焊盘名 − 网数"这个
  等式不成立，不要写死。**这三个数字随摆放改变，别当板子的属性**：144/160/74 是 35 件时的
  读数，66 是 QH/QL 换 comb land 后的读数，180/196/84 是放上 18 只门极/Kelvin 电阻后的读数，
  212/228/111 是放上 U3–U6 后的读数，242/258/134 是再放上撬棒后的读数，260/276/148
  是 2026-11-06 再放上 CT 过流链（D_CT1–4/R15–R17/C11–C12）后的读数，**262/278/150**
  是同一晚再放上 2512 的 `R3` 后的读数
  ——引用必须带"哪一版"，相减没有意义。
- **老鼠线与连接数都等于 Σ(每网焊盘数 − 1)，所以新冒出来的网只贡献 k−1 条**：U3–U6 那步
  的 +27 = 16（`VD*`/`VG*` 由一焊盘变两焊盘）+ 8（`PGND` 新增 8 个脚）+ **3**（`VCC12_S`
  是板上原先没有的**新网**，4 个脚给 3 条）。按焊盘数算会得到 28，差的那一条就是新网的第一只
  焊盘。同一笔账在网数上也对：48 → 53 = `VCC12_S` + `REG1`–`REG4`。撬棒那步的 **+23** 用同一本账
  （30 个新焊盘）：`FAULT_G` 5 脚 +4、`RC_G` 5 脚 +4、`REG_CROW1–4` 各 2 脚 +4、
  `REG1–4` 由一焊盘变两焊盘 +4、`PGND` 新增 7 脚 +7、`FAULT_IN` **只有 1 脚** +0；
  网数 53 → 60 = 四条 `REG_CROW` + `FAULT_G` + `RC_G` + `FAULT_IN`。CT 过流链那步的 **+14**
  用同一本账（18 个新焊盘）：`CS1`/`CS2` 由一焊盘变三焊盘各 +2、`OCD` 2→3 +2、`OCM` 1→5 +4、
  `OC1` 1→3 +2、`OC` 1→3 +2；网数 60 → 64 = `OCD` + `OCM` + `OC1` + `OC` 四条新网（三个单焊盘网
  各给 0 条）。`R3` 那步是 **+2**：`OCD` 3→4、`OCM` 5→6，**两条网都早已存在**，所以网数
  64 → 64 不变——"新网只贡献 k−1"的另一面是"给现成的网加焊盘，每一只都画一条线"，
  老鼠线 +2 与网数不变可以同时成立。**先算 134 再用 `--check` 的 DRC 读数核对**，两者一致
  ——这条算术可以当预测用，不要改成"跑完再说"。
- **撬棒（R50/D50/R51/C50/R52/Q51–Q54/R53–R56）是第三种网来源，不是审核表**：
  `pin_footprint_review.csv` 记的是**原生 LCEDA 原理图**的逐脚状态，而 `library_pins.json`
  的 14 个键里**没有 MOSFET、没有稳压管符号**——给撬棒写审核行等于断言一批不存在的原生引脚。
  所以连接声明是 `main_board_mechanical.crowbar_nets()`，`part_nets()` 当第三个分支读它，
  与 `main_board_schematic.py:PERIPHERALS`、`board_netlist.py:NOT_A_DECK_ELEMENT` 同类。
  `test_the_crowbar_refs_are_not_in_the_review_table` 要求两个集合**不相交**：`part_nets()`
  先读审核表，同一个位号两边都有，测试就变成拿表跟自己比，怎么改都绿。值/封装/逐脚角色
  由测试从 `pcb/sr_fault_validation/BOM.csv` 与 `sr_fault_validation.json:net_map` **读回来**比，
  生成器只留自己的字面量；证据等级是新加的 `validation-board`（既不来自数据手册、
  也不是本仓库推出来的）。`REG_CROW`/`REG` 四路是逐路核对，验证板只提供一个通道。
- **U3–U6（`UCC24624DR`，四只 SOIC-8）摆在 FET 行的上方（y = 72），不是按信号流放在下方**：
  一对里两片 land 铜之间只剩 **3.35 mm** 的竖缝（A 的漏极指到 `x_fet+3.325`，B 的源极从
  `x_fet+6.675` 起），`VG`/`VD` 只能从这条缝下去；FET 下方是横贯整片身体的漏极铜，且
  y = 88 那条电阻带已经在那儿。放置坐标是 `x0 + SR_PAIR_MM/2`（= 各对中缝 19/57/95/133），
  不是手打。**这一步不需要 ECO**（金网表、BOM 的 `U3-U6` 行、主题第 3 节都有它们，缺的只是
  焊盘），但 `VG`/`VD` 从一焊盘变成两焊盘、`REG1`–`REG4` 作为**新的一焊盘网**出现（撬棒还没放），
  单焊盘网因此从 20 条变成 8 条，`test_the_eight_single_pad_nets_are_the_off_board_ends_of_the_taps`
  锁的是**名字集合**——只断个数的话，网搬家看不出来。
  值是 BOM 的 MPN，**不过 `placeholder_value()`**（这四只在 `placeholder_eco.json` 里没有行，
  它们是已选型件，不是占位）；land 是 vendored `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`
  （`PROVENANCE.md` 有 sha256），**不是厂家图**。
- **A5 的 SR 已换成按数据手册量出的 land pattern**（`dcx:BSC010N04LS6`，来自
  `design/v3/pcb/bsc010n04ls6_land.json`，`make_sr_fault_board_pcb.bsc_source()` 生成），
  所以 `netlist_pins_without_a_physical_pad` 里不再有 SR 脚（旧 vendored TDSON-8 把五个漏极
  焊盘全编 `"5"`，6/7/8 脚没有焊盘）。A5 用**惰性 import** 调它，因为
  `make_sr_fault_board_pcb` 反向 import 本模块的 `find_kicad_cli()`。
  `land_pattern_provisional` 现在按**证据等级**判定（`datasheet` = 只有体尺寸），
  **不再按注释里出现"land pattern"**——换封装后那句注释把八只 SR 全误判成占位。
  `test_the_sr_drain_pins_now_have_pads_of_their_own` 与
  `test_the_sr_fet_land_is_generated_from_the_datasheet_measurement` 锁住。
- **QH/QL 的 land + stencil 由 `tools/csd19531q5a_land.py` 数字化**（2026-11-05），
  `design/v3/pcb/csd19531q5a_land.json` → `dcx:CSD19531Q5A`，占位 `Placeholder_SON_5x6`
  已删，`land_pattern_provisional` 因此**为空**。两页要分开拟合：
  **§7.2 第 10 页是 MIN/MAX 表**（F1–F11），**§7.3 第 11 页没有表、标注直接印在图上**
  （`(0.020) 8x` 这种，所以倍数是 `re.search(r"(\d+)x\s*$")` 才能抓到，`fullmatch` 抓不到）。
  比例尺取**图上/标注比值的中位数**，不是最小二乘——后者被最长跨度拖到 11.3 µm；
  残差按 **1 mil（0.0254 mm）** 判（制图取整的底噪），land 最大 21.1 µm、stencil 2.8 µm。
  **引脚号是量的**：左列 5–8、右列 4→1；**第 9 脚（散热焊盘）图上没有号**，是符号给的，
  0.05 mm 阻焊外扩与 0.25 mm courtyard 也不在图上，从另一份 land 借——三条都在
  `limitations` 里。**梳状漏极四指压进基座 0.125 mm**（图上边对边），否则导入器舍入会让
  5–8 脚落在只是相碰的铜上。**1 脚标记必须放在 courtyard 外**：第一版在 (3.12, −2.30)
  落在源极阻焊开窗里，DRC 报 20 µm `silk_over_copper`；不要靠缩阻焊去消它。
- **CT 过流链在 y = 62.40 的一行，是"能放下的唯一一条带"**（2026-11-06）：Lr 下沿到 64.70
  （x 4.12–35.88）、CT 下沿 59.50（x 82–102）、撬棒上沿 65.30，所以 59.50–65.30 是空隙；
  最深的件又是 **SOT-23 的 3.40 mm**，`CT_SENSE_ROW_Y = 62.4` 就是 max–min 中心（两侧各 1.20 mm，
  0603 余 **2.17 mm** = (5.80 − 1.46)/2），与撬棒行同一个论证。**这两个数由测试量，不由注释声明**：
  `test_the_ct_sense_chain_sits_in_the_band_between_the_ct_and_the_crowbar` 现在覆盖**九只**
  （第一版按 `D_CT*`/`R15` 过滤，五只通过、四只可以随便漂），并要求最深那件到两侧空隙**相等**。
  这一段曾写"0603 余 1.79 mm"——算术差了 0.38 mm，没有任何测试能抓它，因为它是注释。
  九只件横排在 x 108/114/120/126（D_CT1–4）、
  132/136/140（R15–R17）、144/148（C11/C12），行宽 44 mm 落在 155 mm 板内。
  **值只从能自证的地方来**：R15–R17/C11/C12 走 `placeholder_value()`（寄存器里的
  "1 kohm"/"10 kohm"/"24 kohm"）；D_CT1–D_CT4 的 BOM 是 `TO SELECT`、且 `D_CT1` **在
  `placeholder_eco.json` 里没有行**，所以值写**功能名** `dual Schottky` 并在注里说明
  原生原理图的 BAT54 是"它带着的"而不是"选定的"。land 是 vendored
  `Package_TO_SOT_SMD:SOT-23` 与 0603（证据等级 `kicad-library`），**不是**审查表里的
  原生 JLC 封装名，也不是厂家图。**`R3` 曾故意没放，现在放下了**（2026-11-06）：10 Ω 冻结、
  封装仍是 `TO SELECT`（实测 125.7 mW 是 0805 标称 0.125 W 的 100.6 %），但
  `r3_vendor_rating_screen.json` 给出了候选 `CRCW251210R0FKEHHP`（EIA 2512、1.5 W、
  高 0.70 mm max），`remaining_actions[0]` 正是"2512 footprint/placement in native CAD"。
  所以板上给的是**候选壳体 + vendored 的 KiCad IPC-7351 2512 land**（`R2512_FP`，
  **不是**厂家推荐 land），四道旗（`pcb_footprint_verified`/`verified_mpn`/`hardware_approved`/
  `fabrication_release_approved`）仍全 false，原生编辑器里仍是 0603。它落在
  `CT_BURDEN_X = 77.0`——那一段唯一跑得开的空隙是 x 35.88（Lr 右沿）到 82.00（CT 左沿），
  右半已被分压器占到 149.48，7.66 mm 的壳体最左只能到 78.17，取 77.0 就是**贴着 CT 的
  整流器**（OCD/OCM 走 30 mm，而不是放到那段空档的另一头走 45 mm）。
  **最深的那件因此从 SOT-23 的 3.40 mm 变成 2512 的 3.86 mm**，`CT_SENSE_ROW_Y = 62.4` 不动
  （它本来就是 max–min 中心），两侧余量 (5.80 − 3.86)/2 = **0.97 mm**，SOT-23 仍让 1.20 mm。
  `test_the_ct_overcurrent_chain_closes_the_secondary_from_end_to_end` 断言的是
  **每网焊盘数**（`CS1 3 / CS2 3 / OCD 4 / OCM 6 / OC1 3 / OC 3`），不是"≥2"——
  这些数就是审查表的 pad→net 行，哪天把 D_CT3 从 OCM 改到 OCD，焊盘数先红；
  `test_the_burden_is_a_2512_across_the_rectified_secondary` 另外把四道 false 旗、
  `footprint == R2512_FP`、`h_mm_worst == candidate_height_max_mm`、焊盘 x = ±2.9625
  与 `{"1": "OCD", "2": "OCM"}` 从屏幕 JSON / 审查表**读回来**比，生成器只留自己的字面量。
- **`not_placed_here_reasons` 是逐位号的表，不是一句话**（`NOT_PLACED_REASONS`）：31 个
  排除位号里**29 个**是控制/驱动/去耦，上一版那句「control, drive and decoupling parts
  have no position on this board」对另外两个是错的——`Cin` 是功率链上的件（doc 34 把它排在
  占位之前），`Cout` 根本没漏（集总元件，十五颗以 `Cout1..Cout15` 在板上）。`R3` 曾是第三个，
  已离开这张表去占那只 2512 候选壳体——**这是表必须失败的另一方向**。三类：`REPRESENTED_BY_OTHER_REFS` / `HELD_BACK` / `NOT_THIS_BOARD`（默认）。
  汇总句 `nets.not_placed_here_reason` **由表拼出来**（`29 control, … 2 more …: Cin: …; Cout: …`），
  摆上任何一个都会同时改计数与句子。守卫**双向**：`NOT_PLACED_REASONS` 里的位号上了板 ⇒
  `SystemExit`（和 `SINGLE_PAD_REASONS` 同一个病：CS1/CS2 就是这样在列表上多待了好几个提交）。
  **`Cin` 的理由带的是选型数**（20 µF 输入组、`TO SELECT`、`bridge_ac_rms_a` 5.3157 A），
  不是审查表里那只 100 nF 0603 的外形——没有要求就没有可核对的对象。
- **`unconnected_items` 是第二个顶层数组**，不在 `violations` 里。只读 `violations` 会在
  一块一条线都没画的板上读出"0 个未连接"。`check()` 现在打印两个数，并带一条**反向守卫**：
  声明了网却报 0 条老鼠线 ⇒ `SystemExit`（要么真布完了，要么 `(net …)` 没落到焊盘上）。
  **111 条是欠账，不是失败门**——`check()` 不为未连接失败。
- **焊盘名就是身份**：Lr 用审查表的 `1`/`2`，**不是**原理图的 `N1`/`N2`（第一版按 N1/N2 建
  封装，Lr 一条网都没落上）；U2 的占位外形**没有焊盘**，所以它的十一条网表行一条都不该上板
  ——`part_nets()` 必须先按 `_pad_positions()` 过滤，否则 U2 会出现在 `PGND` 里。
- **输出电容阵位号是 `Cout1`–`Cout15`，不是 `C100`–`C114`**：原理图把 `C101`–`C112` 用在
  十二只 IC 去耦电容上，同号会让 470 µF 落到 0603 位置上。
  `placement_report.json:cout_bank_refs` 显式列出这十五只，`tools/cout_bank_path.py` 的
  `units()` **读它而不是按 `C1xx` 猜**——改名后旧写法静默匹配空集，报的是
  "a bank row needs at least two units"，看不出是找不到电容。
- **原理图把整组输出电容画成一只集总 `Cout`**：十五颗物理电容没有自己的网表行，借那只符号的
  两条网。BOM 必须展开成十五行，`nets_report()` 的 `lumped_from_one_netlist_element` 明写。
- **现在只剩 3 条网只有一只焊盘**：`FAULT_IN`、`GH_DRV`、`GL_DRV`。
  **一焊盘的网画不出老鼠线**，所以欠账里看不见，必须单列（`single_pad_nets`），
  否则会被读成"已经连好了"。这组名字变过四次：原先 12 条含 `GA1`–`GB4`、`GH`/`GL`
  （FET 栅极就是终点）；电阻放上板后它们是**两焊盘网**，"另一端不在板上"跟着搬到电阻的
  驱动器侧；放 U3–U6 后 `VD*`/`VG*` 走，`REG1–4` 进；撬棒让 `REG1–4` 走、`FAULT_IN` 进；
  **CT 过流链（D_CT1–D_CT4/R15–R17/C11–C12）让 `CS1`/`CS2` 各得三个焊盘**（整流桥原先在
  没有焊盘的 U2 外形里，现在在板上）。测试比的是**名字集合**（`test_main_board_mechanical.py`
  与 `test_main_board_power_copper.py` 各一条）——只断个数的话，网搬家看不出来。
- `nets_report().nets[*].straight_line_mst_mm` 是**直线生成树下界**，不是走线上界；
  `PGND` 341.124 mm / `VOUT` 325.209 mm 这两个是要铺铜的面，别拿它当长度预算。
  四条 `SEC*_A`（6 焊盘各 **76.989 mm**，含 `R28`/`R30`/`R32`/`R34`）与四条 `SEC*_B`
  （**65.766 mm**）**逐位相同**，`test_the_four_secondary_groups_are_drawn_the_same_length`
  锁的是布线前那一半。加电阻前后这些长度不变——电阻压在自己那只 FET 的焊盘正下方。
- **`parts()` 必须不 import 任何交叉模块**（2026-11-06）：`python tools/main_board_mechanical.py`
  把本文件当 `__main__` 执行，而两个 land 生成器（`make_sr_fault_board_pcb` → `make_sr_fault_board`）
  会 `from main_board_mechanical import find_kicad_cli`，于是本文件**被再执行一次**成模块
  `main_board_mechanical`，拿到的是半初始化的 `make_sr_fault_board_pcb`——现象是
  模块底部 `PARTS = parts()` 抛 `AttributeError: module 'make_sr_fault_board_pcb' has no
  attribute 'bsc_source'`。所以 `parts()` 读**数据**：两只 FET 的 land 从
  `LAND`（`design/v3/pcb/*_land.json`，只看 `"F.Cu"` 那几项，矩形中心 = 封装里的 `(at x y)`，
  首次出现优先，与 `_pad_positions` 的 `setdefault` 同义）经 `_land_pads()` 取，
  0603 从 vendored 封装文本经 `_text_pad_positions()` 取；**不调 `_pad_positions()`**，
  因为它会建整个封装库。两个来源的一致性由测试比对，不靠"看起来一样"。
- **vendored KiCad 封装的焊盘可以完全没有 `(uuid …)`**（`R_0603_1608Metric` 就是）：
  `_inject_pad_nets` 原先在 `(uuid ` 前插网行，于是 18 只新电阻的焊盘一个 `(net …)` 都没落上
  （`208 − 48 = 160` 对断言 196 时才发现）。现在没有 uuid 时退回到**焊盘块最后一个 `)` 之前**插，
  且缩进必须是**比焊盘深一层**（取块里第一行内层的缩进），否则 `\t(net …)` 会被
  "板级网声明"计数器 `^\t\(net \d+ "` 数进去（84 = 48 + 36 那次就是这么来的）。
- **`sr_board_router.extract_pads` 不应用封装旋转**：所以 A5 所有件必须摆 **0°**，
  电阻靠"FET 焊盘 x − 电阻焊盘相对偏移"（`under()`）贴到栅极/漏极基座正下方，
  不靠转 90°。行位：SR 那批 y = **88.0**，QH/QL 那两只 y = **57.5**。
- **电阻带落在 SR→铜排的输出通道里**（y = 88 在 SR 行 y ≈ 82 与 Cout 行 y ≈ 98 之间），
  铺铜必须绕开它们。只放电阻时 `routed_copper.json:pours.series_mohm` 是 1 oz **3.1742** /
  2 oz **1.5871** / 4 oz **0.7937 mΩ**；再放上 U3–U6 后是
  **3.4741 / 1.7371 / 0.8688**；撬棒 + 两个走线宽度之后是 **3.7280 / 1.8640 / 0.9322**
  （VOUT 填充 90.8 → **91.1 %**、PGND 93.5 → **95.6 %**，
  方块 3.9891/0.8296 → 4.4526/0.9137 → **4.9045/0.8538**；铺满实验的 `solder_mask_bridge`
  也是 12 → 20 条）。**填充率上升而串联电阻也上升能同时成立**：铜的总量多了，但分组 3
  的 PGND 走廊被改道后的走线切窄了——VOUT 那侧 +0.45 方块、远超 PGND 那侧 −0.06。
  再放上 CT 过流链后是 **3.638 / 1.819 / 0.9097**（VOUT 填充 91.1 → **90.7 %**、方块
  4.9045 → **4.7655**，PGND 0.8538 **那一版逐位未动**）。这次是**填充率下降而方块数也下降**
  的反向配对，同样两个数分别报；VOUT 方块移动 2.8 %（2 oz 串联只动 2.4 %），而这份铺铜本来就
  12 倍于基准，不改变任何结论。
  **再放上 2512 的 `R3` 后是 3.6408 / 1.8204 / 0.9104，而"PGND 逐位未动"这条到此为止**：
  PGND 现在 **0.8538 → 0.8539 方块、95.2 → 95.0 %**，因为 `OCD`/`OCM` 两条走线要跨 B.Cu。
  移动量是 **0.0001 方块（0.012 %）**，比两档网格差（0.83 %）小两个数量级，但它**不再是零**，
  所以"三代逐位没变"不能再往下延续。VOUT 那侧是 **填充 90.7 → 90.6 %、方块 4.7655 → 4.7698
  （+0.09 %，粗网格 4.7925 不动）**——又是"填充率降、方块升"的反向配对，方向与上一代相反。
  派生布线板现在是 **61 条网、275 只焊盘、214/214 连接、1913 段、94 过孔、DRC 三个顶层
  数组全空**（275 = 278 物理焊盘 − 3 只单焊盘网;214 = 275 − 61；上一版是 273/212/1854/88），
  但最差一组 2 oz **142.284 mΩ** 对 0.15 mΩ 基准（分组 1/2/3/4 = 122.153 / 92.007 /
  142.284 / 95.446，四组与上一版**逐位相同**：`route_plan` 按 `(-count, name)` 排序，
  PGND/VOUT 先走，3–5 焊盘的新网排在后面，动不了它们的树）⇒ 状态串
  `ROUTED_DRAFT_CONNECTIVITY_ONLY_AMPACITY_NOT_MET` 说的是"走线扛不了 100 A"，
  不是布线没做完。**最差组从 122.153 一路涨到 142.284 的账不要算在同一个原因上**：
  122.153 → 136.518 是撬棒带来 7 个新 PGND 焊盘、树变长；136.518 → 142.284 是
  **修复轮不再运行**（`VOUT` 的树逐位没动，动的是 PGND 423.5 → 460.12 mm、0 → 16 过孔）——
  之前那次是"VCC12_S 失败触发 4 轮 rip-up、PGND 被当受害者重布过"的板子，
  那 4 % 是缺陷的副作用。摆放板一个字节没动。
- **提交的 `drc.json` 逐次重跑会大改**（带 `date`、每条未连接项带 uuid 与坐标），
  重跑后看到两千行 diff 是正常的；没有测试逐字节比对它，只比对**板子本身**
  （`test_the_committed_board_is_what_the_table_produces`）。
- **铜排中心是算出来的，不是 76.0 这个字面量**：`_sr_row_centre()` 取 `SR_X0` 的四个
  组中心均值。原先 J_OUT 在 x = 100（对 155 mm 板"居中"，对它服务的 19/57/95/133
  四组不是），第 1 组要横走 41 mm ⇒ 3.67 方块 / 1.188 mΩ，而第 3/4 组 0.94 方块。
  居中后两组外侧各 17 mm，最差 0.671 mΩ、spread 3.91 → 2.21（左右对称），
  2 oz 总路径 0.281 → 0.267 mΩ。**铜排尺寸没变**，所以 34.5 µΩ 与接点上限 57.8 µΩ 不动。
  `test_the_busbar_sits_on_the_centre_of_the_row_it_serves` 锁"移动任一组，铜排跟着动"。
- **`output_path_budget.remedy()` 曾给所有选项套同一个 80 mm 铜排电阻**，却给"加宽"
  选项 134 mm 的几何 ⇒ 4 oz 加宽显示 0.183 mΩ 的假最优。现在 `_busbar_ohm()` 读
  **摆放的 `w_mm`**（不读 `cb.BUS_LENGTH_M`），每个选项按自己的长度付账：最优变成
  **4 oz + 80 mm 居中 0.206 mΩ**，加宽 134 mm 是 **0.214 mΩ（更差）**。
  加宽真正买到的只有均流对称（2.20 → 1.00），代价 8 µΩ 总路径 +
  **接点上限 57.8 → 46.1 µΩ，低于 50 µΩ 占位值**。别再把"加宽"当无本万利的杠杆。
  两个温度基准不要混：`connector_budget.joint_limit()` 用 20 °C，本工具用 100 °C。

### A5 已经布出来的铜（`tools/main_board_power_copper.py`）

`hardware/dcx_mech/power_stage_routed.kicad_pcb` 是**从摆放板派生的布线草稿**：275 只参与
布线的焊盘（278 物理焊盘 − 3 只单焊盘网）、61 条可布网、**214/214 连接**、1913 段走线
（2 条 0.8 mm + 59 条 0.25 mm，见下条）、94 个过孔，kicad-cli DRC 三个顶层数组全空
（`violations` / `unconnected_items` / `schematic_parity` 都是 0，`counts.placement` 0）。
放 `R3` 之前是 **273 / 212 / 1854 / 88**，两次只差这只 2512 的两只焊盘与它那两条连接
（`OCD`、`OCM` 都已存在，没有新网；`route_plan` 按 `(-count, name)` 排序，两条网在
其后的位置，动不了 VOUT/PGND 的树）。
摆放板一个字节没动（本工具只读它），所以 A5 的逐字节测试不受影响。
`width_basis` 里那 **3 条**单焊盘网的**理由现在是一张按网名索引的表**
（`SINGLE_PAD_REASONS`），不是手写句子——手写句子四次落后于名单（"`VG*`/`VD*` 是单焊盘网"、
"`REG*` 也是、撬棒还没放"、以及 CT 整流器放上板后仍写着"the CT rectifier"）。
`single_pad_note()` **双向核对**：活着的单焊盘网没有理由、或理由的网已经不再单焊盘，
都直接 `SystemExit`；它在 `route_board()` 里**布线之前**调用（检查免费，布线 2.5 min）。
测试同时要求报告里那句逐字包含表里的每条理由，所以"文字与表是同一张表"是判据而不是承诺。

- **一个全局的 0.8 mm 走线宽度出不了 UCC24624 的引脚列，代价是整条 `VCC12_S`**（2026-11-06）：
  每只 UCC24624 的 5/6/7/8 脚是**一列**（同一个 x、1.27 mm 间距、焊盘 1.95×0.6 mm），
  边到边只剩 **0.67 mm**，而 0.8 mm 走线加 0.2 mm 净空要 **1.2 mm**。
  于是 `VCC12_S`（只有 4 个焊盘）在 `route_plan` 的 `(-count, name)` 序里排到十个更宽的网之后，
  三条连接**全部**失败（`unrouted_nets ['42']`、195/198、DRC 3 条 `unconnected_items`），
  而 `_rip_victims` 只量到两个端点的距离、选不出 38 mm 走廊中段的挡路铜，
  修复轮永远修不回来。现在按**预算量的是哪两条网**分两个宽度：`OUTPUT_NETS`（VOUT/PGND）
  保持 0.8 mm 让 `what_a_track_would_need` 的比较有意义，其余 53 条网是 0.25 mm 的**连通占位**——
  状态串本来就写着 `AMPACITY_NOT_MET`，宽占位买不到额定，只会在每次跨越时吃掉一条车道。
  `width_of()` 是唯一让宽度撞上网名的地方（`route_plan` 与 `report` 各写一遍时，
  报告整整一个阶段都在声称所有网同宽）。**失败的修复路径才是路由慢的原因**（4 轮 rip-up ×
  每次约 6 条重布 ⇒ 20 min 以上；现在 198/198 一次过，本机约 2.5 min）——`--check` 是
  `ci_check` 的一个 view，别再让它走那条路。
  **这次修复还让最差组从 136.518 变成 142.284 mΩ，原因不是宽度**：`VOUT` 的树逐位没动，
  动的是 `PGND`（423.5 → 460.12 mm、0 → 16 个过孔），而 PGND 焊盘最多、永远第一个布，
  只能是之前那 4 轮 rip-up 把它当受害者重布过——**那 4 % 是缺陷的副作用，不是设计**，
  别为了它去把 rip-up 打开当优化。

```bash
python tools/main_board_power_copper.py --json hardware/dcx_mech/routed_copper.json   # ~2.5 min，含 DRC 与铺铜重解
python tools/main_board_power_copper.py --check        # 重布 + 比对板子与报告（不需要 kicad-cli）
```

- **状态字符串是 `ROUTED_DRAFT_CONNECTIVITY_ONLY_AMPACITY_NOT_MET`，这不是保守话术**：
  按走线最短路量出来的单组串联路径在 2 oz 下最差 **142.284 mΩ**（g1 122.153 / g2 92.007 /
  g3 142.284 / g4 95.446），对 `output_path_budget.DESIGN_BASIS_OHM` 的 **0.15 mΩ** 是 ~950 倍。
  `what_a_track_would_need` 算出要满足 0.15 mΩ 的单条走线宽 **425.4 mm**（最长路径 197.12 mm），
  比 155 mm 的板还宽——
  这就是"功率路径必须铺铜"的算术版本，不是意见。**别为了让这条变绿去改 0.15**：
  它和公布的 92.33 % 效率是同一个基准。
- **布线拓扑量不出电阻，必须先做"焊盘收缩"**：连续几条连接从**同一焊盘的格子**出发，
  所以发出的线段之间**不共享栅格节点**——它们是被焊盘电气连起来的。第一版直接在
  `(layer,x,y)` 上建图，VOUT 裂成 8 个连通块（20/20/20/19/18×4），`path_squares` 全部返回 None。
  现在 `_pad_key` 把同一封装的同号焊盘并成一个节点，`_attach` 用 `router._pad_distance`
  按层判断"线段端帽是否压在铜上"。**不要把 `None` 读成"没连上"**，先看是不是没做收缩。
- **同号焊盘是一个电气节点（KiCad 语义）**：八只 SR 的漏极基座与一根指都叫 `5`，
  所以 `_pad_key` 用 `(ref, number)` 而不是物理铜块。层也要对：F.Cu 焊盘上的 B.Cu 走线
  不算相连，除非中间有过孔（`test_a_track_on_the_other_layer_does_not_reach_a_pad`）。
- **`checks` 里放的全是结构不变量，`results` 里才有物理结论**：`checks` 全绿的同时
  `results.power_path_meets_the_0p15_mohm_basis` 是 **false**，这是同一份报告要能同时说的两句话。
  `test_the_structural_gates_pass_while_the_power_target_fails` 锁住这个组合。
- **磁件的端子位置仍是 PROVISIONAL，铜因此是临时的**：`interfaces.provisional_land_patterns`
  从**封装自己的 `descr`** 读（不是摆放的 `evidence` 标签——ELP32 那里写的是
  `generated-json`，而封装文本仍写 "Terminal positions PROVISIONAL"）。T1–T4/Lr/Cr/CT/J_IN/U2/
  Cout 都在表里；拿到厂家端子图后焊盘会移动，**这份走线要重做**，本增量的永久部分是
  路由器与量出来的铜成本。
- **`--check` 有两个独立的过期信号**：板子字节（摆放改了没重布）与
  `routed_copper.json:board.board_sha256`（板子重布了但数字没重算，或有人手改 budget）。
  只比板子的话，手改过的预算能混过每一次 `--check`。它已进 `tools/ci_check.py` 的 `VIEWS`
  （`--skip-tests` 也会跑；加了铺铜重解之后约 3 min，是那里最慢的一项）。
- **kicad-cli 的坑照旧**：报告先 `unlink` 再跑（否则崩溃后读上一次的干净报告）、
  `tracks` 在 `unconnected_items` 这个**第二个顶层数组**里、退出码 0 不代表没违规、
  子进程必须 `encoding="utf-8", errors="replace"`。板子需要同名 `.kicad_pro`
  （`project_file()` 从摆放那份改名生成），否则 `dcx:` 封装解析不了，courtyard 检查静默失效。

### A5 铺满两层的上限（`POUR_PATHS` / `pour_study()`）

走线量出来的 142.284 mΩ 只说明"走线不行"，没回答**铺铜行不行**。这一层把两条输出网真的铺满整板
再解电阻网络，结论是**也不行**，而且差得不是一点：

| 网 / 层 | 填充率 | 方块数（0.25 / 0.35 mm） | 1 oz | 2 oz | 4 oz |
|---|---|---|---|---|---|
| VOUT / F.Cu（T1–T4 中心抽头 → J_OUT.1） | 90.6 % | 4.7698 / 4.7925 | 3.088 | 1.544 | 0.7722 |
| PGND / B.Cu（八只 SR 源极 → J_OUT.2） | 95.0 % | 0.8539 / 0.8468 | 0.5528 | 0.2764 | 0.1382 |
| **串联** | | | **3.6408** | **1.8204** | **0.9104** |

对 `DESIGN_BASIS_OHM` 0.15 mΩ 是 **2 oz 12.1 倍、4 oz 6.1 倍** ⇒ **铜排才是输出路径，
铺铜只是每组到铜排焊盘的过渡**。`verdict` 与 `not_a_layout` 都由实测值拼出，不写死。
这组数字随摆放变（放 U3–U6 前是 3.1196 / 1.5598 / 0.7801、放 U3–U6 后是
3.4741 / 1.7371 / 0.8688、撬棒 + 两个走线宽度之后是 3.7280 / 1.8640 / 0.9322、
CT 过流链之后是 3.638 / 1.819 / 0.9097、放上 `R3` 之后才是上表），引用必须带"哪一版"。
**"PGND 逐位没变"这条只说三代**（放 U3–U6 → 撬棒 → CT 过流链都是 0.8538）：放上 `R3` 之后
它变成 **0.8539 方块 / 95.0 %**，因为 `OCD`/`OCM` 有走线跨 B.Cu。移动 0.012 %，比网格差
（这一版 0.83 %）小两个数量级，但它是**从"零"变成"非零"**，所以这句话不能再当不变量用。
VOUT 那一代则从 4.9045 → 4.7655 → 4.7698——**填充率和方块数可以同向、也可以反向**：
CT 过流链那步是 91.1 → 90.7 % 与 4.9045 → 4.7655 **同向下降**（"铜更少、方块也更少"），
这个方向**没有已验证的机制**（同一个电阻网络去掉导体，等效电阻本不该变小），所以**只报数不解释**：
2.8 % 约为两档网格差（那一版 0.57 %）的五倍，不像栅格噪声，但也远小于 12 倍的判据余量；
`R3` 那步则是 90.7 → 90.6 % 而方块 **4.7655 → 4.7698 反向上升**（+0.09 %，粗网格不动），
与上一代方向相反、幅度小一个数量级。
放 `R3` 之前 B.Cu 那侧逐位不动，至少排掉了"整个求解器这次收敛得不一样"；现在这唯一的对照也没了
（PGND 0.8538 → 0.8539），所以两个方向的读数都只能各自成立、互相不能当证据。**填充率与串联电阻可以同向变**：撬棒之后
VOUT 90.8 → 91.1 %、PGND 93.5 → 95.6 % 都升了，串联电阻也从 1.7371 升到 1.8640 mΩ——铜的总量多了，
但分组 3 的 PGND 走廊被改道后的走线切窄了，VOUT 那侧 +0.45 方块盖过 PGND 那侧 −0.06。
所以"填充率更高"不等于"路径更短"，两者要分别报。

- **方法**：把重填后的铜栅格化（一格 = 一个方块），四邻边各一个单位电导，汇 1 V、源 0 V，
  五点拉普拉斯上跑 Jacobi 预条件 CG，`R = 1/I_total`，最后才乘方阻。
  **上机前先过两个夹具**：20×200 长条给 **199/20 = 9.95**（不是 10）、40×40 方板给
  **39/40 = 0.975**（不是 1）——电极只有一格宽，量到的跨距短一格。**这个 0.5 % 偏置是网格自己的，
  铺铜数字继承它**，不要再当成收敛证据。两个网格尺寸（0.25 / 0.35 mm）的差 ≤1.1 %，
  是"栅格化没漏轮廓、求解没早停"的**一致性**检查，不是收敛性证明。
- **汇电流求和必须只算留在铜里的边**：一块方板最初读出 **0.02 方块**，因为汇电极在铺铜边缘，
  朝外那条边 `1 − 0` 也计了 1 A，每开一面白送一安培。现在把 mask 补零一圈、用
  `linked = pad_m[...] > 0.5` 过滤。**只这一条就把方板从 0.02 拉回 0.975。**
- **KiCad 10 的填充格式是一整条带缝折线，不是轮廓+孔**：每层只有一个 `(filled_polygon)`，
  它的 `(pts ...)` 是**单条闭合折线**，避让孔靠**零宽切口**折进去，首点只出现一次，
  所以"按重复首点切轮廓"在这个版本**永远不触发**。matplotlib 的 `contains_points`
  对子路径是**并集**（两个绕向都返回 True），所以判据用**逐轮廓奇偶**
  （`depth % 2 == 1`），不用绕向。表里的填充率是**真的铜**，不是栅格化漏了孔：
  早一版铺满板上逐点核对过——238/238 个落在填充里的采样点都是本网自己的走线，
  528 个他网 F.Cu 走线中点**没有一个**落在里面。**这个核对没有在新版重跑**，
  别把它当成当前读数；缺的那几个百分点是避让通道。
- **临时板必须写在 `OUT` 里，不能放子目录**：`${KIPRJMOD}/dcx.pretty` 要靠板子旁边的
  `fp-lib-table` 解析，放进 `_pour/` 会让**全部封装丢失**（当时 35 只，现在 70 只），
  而 courtyard 检查随之**静默失效**——DRC 从 12 条变 47 条，其中 35 条是 `lib_footprint_issues`。
  `_poured_board()` 把 `_pour_stage.kicad_pcb/.kicad_pro` 写在 `OUT`，`finally` 里连同
  `_pour_stage_drc.json`/`.kicad_prl` 一起删，`git status` 保持干净。
- **铺满时那 `solder_mask_bridge` 不是缺陷，是这个实验的代价**：VOUT 铺满后每只 SR 的
  阻焊开窗下面都有铜。条数随摆放走（放 U3–U6 前 **12** 条、之后 **20** 条），
  引用要带"哪一版"，**不要**把它当成一个可以调平的指标。所以 `not_a_layout` 明写
  "这不是一个设计、它的 DRC 不是门"，
  **不要为此去印一条更小的 zone**——那会把"铺满能买到多少铜"这个问题悄悄改掉。
- **接触 ≠ 导通**：`pour_path()` 里每个电极先与填充求交（焊盘自己的铜本来就不在 zone fill 里，
  要求整个电极都是铜会**按构造失败**），逐焊盘判接触；但那只证明碰得到。
  `mesh_squares()` 返回 `None`（没有电流流过）时直接 `SystemExit`，因为热焊盘辐条与避让通道
  可以把一只焊盘留在孤岛上——那种情况下"每只焊盘都接触铜"照样是 true。
- **numpy 出不了 `json.dumps`**：`round(np.float64, n)` 返回的还是 `np.float64`，
  用它与阈值比较得到 `np.bool_`，`json.dumps` 直接
  `TypeError: Object of type bool is not JSON serializable`——而它炸在**最后一行写文件**上，
  前面所有测量都印出来了，看起来像跑完了。类型在 `mesh_squares()` 边界上就转成
  `float`/`int`/`bool`，不要留到序列化时。
- **`--check` 会重铺重解**（`_compare_pours`，每个权重相对误差 >1e-6 即 `SystemExit`），
  约 3 min，是 `ci_check` 的 `VIEWS` 里最慢的一项；没有 kicad-cli 时打一行说明并跳过。
  **只比板子字节不够**：手改预算能混过每一次 `--check`，所以报告自己的 `pours` 也必须重算比对。

## A6 机械剖面（Issue #12）

- **"≤10 mm" 没有规定量到哪**，而仓库里有三个不同的数。`mechanical_section()` 因此先定
  基准面：**PCB 顶面 Z = 0**，`PARTS` 的 `h_mm_worst` 本来就是这个口径。剖面表在
  `placement_report.json:section`，文档是 `design/v3/A6_机械剖面_2026-11-01.md`。
- **沉槽只是把压块买回来**：A 平面 9.94 mm，C（0.5 mm 沉槽 + 0.5 mm 压块）也是 9.94 mm，
  余量同为 +0.06 mm。不要写"开了沉槽就有余量"——`test_the_pocket_only_buys_back_the_clamp`
  锁住 C = A（1 µm 内）。
- **TIM / 冷板 / 紧固件 / 板弯在本仓库完全没有数据**，所以 `definitions` 里的 D 情形
  必须是 `null`，不许填。`gate` 字段写明"A6 未签核"。填一个想象出来的 D 会让
  "≤10 mm" 看起来签核过了——这正是 #12 要防的。
- **剖面表自己加一遍、再与 `magnetics_design.json` 的 `height` 比对**，不一致直接
  `SystemExit`。改 `GLUE_MAX_MM`/`LABEL_MAX_MM` 会立刻触发，这是有意的：两个独立的和
  必须相等，否则文档与 JSON 会悄悄分叉。
- **100 A 输出路径要用"方块数"看，不是微欧**：`output_path_budget.py` 读摆放坐标算
  `R = ρ/T × 方块数`（2 oz、100 °C 时 **0.324 mΩ/方块**），于是 0.15 mΩ 的预算
  **只有 0.46 个方块**。J_OUT 占 x = 60–140 mm 而 SR 行是 19–133 mm，**第 1 组头顶没有铜排**，
  要横向走 41 mm（2.73 个方块）⇒ 单组 1.188 mΩ。这不是损耗问题：它比整台变换器的
  `r_out_equiv_ohm`（1.135 mΩ）还大，四组之间差 3.91 倍，均流假设先崩。
  加宽铜排到 134 mm 是唯一不改叠层的杠杆（最坏组 1.188 → 0.304 mΩ，散布比 1.00），
  但 **4 oz + 加宽也只有 0.297 mΩ，仍然过不了 0.15**——瓶颈这时转到接点占位值。
  工具是**上界**（均匀电流密度、忽略转角扩散），但方向的正确性足够回答"要不要改摆放"。

## V9 本机原生铜排与 ≤16 mm 机械挡板（2026-11-12，仍非投板）

- [`tools/g2_v9_bipolar_mechanical_gate.py`](../../tools/g2_v9_bipolar_mechanical_gate.py) 读取真实保存的 V9 `.eprj2` SHA 与原生 API 149/443/407/93/65 图元回执，不再拿旧 G1 摆放猜焊盘。输出 [`g2_v9_100a_bipolar_physical_screen_NOT_FOR_FAB.json`](../../hardware/dcx_main/g2/g2_v9_100a_bipolar_physical_screen_NOT_FOR_FAB.json) 和 [`铜排覆叠图`](../../hardware/dcx_main/g2/g2_v9_bipolar_native_busbar_overlay_NOT_FOR_FAB.svg)。VOUT 源 CTAP 与电容已在一个真实铜岛；PGND 共39个**几何铜岛**，其中主功率岛已包含阵列/多组SR，另外38个不能都当成主功率断路。实际 native DRC 仍为168 Connection/1 Netlist。
- 旧 G1 双极底铜排外形套在 V9 时，VOUT 轮廓范围内有 **1** 个异网孔、PGND 内有 **25** 个异网孔需要绝缘/加工避让。四个 CTAP 和16个所筛选 SR.3 源焊盘都落于旧几何轮廓内，但这**不**意味着已经形成实际的板到铜排接触。旧 bar 并无孔、接点/锁紧设计，尚未放到 V9 原生 PCB，禁止将其生成制造文件。
- 三个实际 VOUT 源 0.4mm 钻孔/1.0mm 外径孔，按假设 **25µm 孔铜、1.6mm 板厚**及 20°C 铜电阻率的薄壁圆筒模型，三孔并联约 **292.675µΩ**，仅这一项如果全载100A均匀分担就消耗约2.927W；缺少电流扩散/其他通路等真实条件，不是测量值。1.6mm×74mm×70µm 的三条走线另有显著电阻，不能用现有窄馈线作为100A极柱。
- 旧 **1.2mm** 底铜排方案无TIM/压件时假定总高15.45mm；另假设TIM0.3mm、压紧0.4mm、累计公差0.3mm则 **16.45mm**，超16mm目标0.45mm。假定每极20/50µΩ接点的旧方案算术电阻分别121.511/181.511µΩ，后者超150µΩ预算；全部为条件模型，**不能**代替接触电阻、热稳态、绝缘、冷板/磁件结构实测和制造商DFM。下一轮要首先确定足够的实接点截面、绝缘槽/隔离层、真实螺栓与CTAP/SR引出结构，再做原生V10铜排CAD、3D配合和额定电流分布计算。`NOT_FOR_FAB`。
- **V9 原生铜的过孔扩容不够替代功率接点**：[`tools/g2_v9_100a_copper_pillar_screen.py`](../../tools/g2_v9_100a_copper_pillar_screen.py) 从同一保存的V9原生图元，按实有四个CTAP与八个SR源极位置，在各源5mm范围用1.6mm孔中心间距、1.0mm孔外径、0.4mm钻孔、异网0.3mm名义间隙，检索与现有**上层同网络铜相接**且避开两层所有已知异网图元、旧版底部铜排轮廓内的可能过孔点； VOUT仅10处、PGND39处。为避免任意拍一个“需要多少孔”阈值，另采用**显式假定**每一极100A在100°C时仅允许过孔桶壁损耗0.2W、四/八个源均流且平均分配损耗：理想数学需要VOUT每组15、总60处，PGND每组8、总64处——均远超现有可检索接点。这不是IPC额定值或温升实测，甚至连旧铜排本身的真实电连接都还未建立；完整原生坐标/计算假设在[`实际接点可行性数据`](../../hardware/dcx_main/g2/g2_v9_100a_native_contact_via_feasibility_NOT_FOR_FAB.json)里。下一阶段必须**改功率端子机械形式**，考虑厂家签认的铜柱/嵌铜/贯穿铜块，将CTAP/SR原生封装、双极母排、绝缘和机械冷板一体布局；不得直接在V9堆小孔、出制造文件。
## V11 原生八路SR门极局部铜线与剩余D1硬阻塞（2026-11-13）

- 真实 [V11 原生二进制](../../hardware/dcx_main/g2/dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2) 完成8段PGND纵线重构与24段顶层GA/GB门极补线，信号线宽0.15mm、名义异网间距0.18mm。独立保存新会话PCB→DRC→SCH完整验收**149器件/443焊盘/465铜线/93孔/65网**，Drc Connection **165→149**（原V10对照）、Netlist仍1，八条门极网各2→1铜岛且PGND37→37，T530第二页72器件/144线保持。[原生独立验收回执](../../hardware/dcx_main/g2/g2_v11_independent_native_reopen_verified_NOT_FOR_FAB.json)。所有用户GUI保留；非改V10原文件。
- **其余不是靠门极布线就能解决**：全板还149 Connection /1 Netlist。PGND37个几何岛并非全部100A主载流分割，必须逐条按真实网络闭合，不能依靠缺厂商封装的磁件裸焊盘伪装完整。四变压器与CT的24脚真实原生封装/DOT、R6原生DNP、100A CTAP→两极铜柱/嵌铜/端子、底层绝缘与16mm完整机械/冷板、100°C N97的L(I)及D0十路实体故障停机必须联合验证；厂家蚀刻和阻焊间距也未签。阶段性CAD进步**不能**宣称可下单。`NOT_FOR_FAB`。


## V14 穿板磁芯与双面主板几何制造门禁（2026-11-13）

- 依照[TDK EILP32/N97三磁柱厂家图](https://www.tdk-electronics.tdk.com/inf/80/db/fer/elp_32_6_20.pdf)与实际保存的G2 V11 155×131mm原生板，开发[`12槽几何+铜阻源锁定脚本`](../../tools/g2_v14_through_board_magnetics.py)：T1–T4四只各3条NPTH槽，总12条；左右宽5.50mm、中央宽7.80mm、长22.00mm、R0.6mm、距铜0.50mm；真实旧铜冲突**20个裸磁件焊盘+7段VOUT线+3个VOUT过孔**，不能先于PCB绕组/铜排重构直接刻槽。[详细工程CAD/完整验收约束](../../hardware/dcx_main/manufacturing/V14_THROUGH_BOARD_ELP32_DFM_RFE_NOT_FOR_FAB.md)、[NPTH槽DXF草案](../../hardware/dcx_main/g2/g2_v14_ELP32_four_core_12_NPTH_slot_toolpaths_NOT_FOR_FAB.dxf)、[预览](../../hardware/dcx_main/g2/g2_v14_double_sided_slot_winding_overlay_NOT_FOR_FAB.svg)。**DXF轮廓尚不是已放置在新原生PCB中的开槽，更不是刀补刀路或Gerber。**
- **已实做原生库CAD而非仅构想**：在唯一存活的V13嘉立创GUI新建库件 UUID `d5e95cf104ff4eb082a0566ebcc7d830`，通过真实`pcb_PrimitivePolyline.create`创建三条Board Outline layer11圆角闭合槽，保存后在**同一GUI**重新打开读回3个原生UUID与尺寸，V13/V11主板原文件SHA均未变化。[原生三槽库验收回执](../../hardware/dcx_main/g2/g2_v14_native_three_slot_saved_reopened_NOT_FOR_FAB.json)。**库件尚未加入实际PCB，实板不因此获得绕组、器件或开槽资格**。
- 100A四变压器原边三匝串联、两路中心抽头副边各1匝的初步5mm U型多层绕组，中心铜线长69.8mm、侧向可用铜宽6.64mm。8L/70µm铜100°C纯DC四磁件铜损约10.49W；12L/70µm约7.67W；12L/140µm约3.83W但**厚铜12层板厚最坏约2.97mm，不能满足ELP32最小3.05mm磁窗减去装配间隙与0.10mm预算后的2.45mm限制**。[磁窗高度联合门禁](../../hardware/dcx_main/g2/g2_v14_ELP32_PCB_window_stackup_16mm_fit_GATE_NOT_FOR_FAB.json)。12L/105µm+0.09mm介质计算最坏2.44mm仅余0.01mm，厂家内铜与压合能力未证、AC铜损/过孔/绝缘均未证实，**不得当做已完成的PCB磁件**。
- V13原生读回所有149个器件均为顶层，**尚无真正背面器件**。V14需先新建真实母板多层结构、真实底层部件再实测门极回路与完整16mm冷板/扣件/100A双极铜排结构。旧V11 DRC仍149 Connection/1 Netlist，V12尚有1 Physical，T1–T4真实极性/DOT须由PCB绕组绘制与首件测试共同确认；CT独立四端厂家PIN/DOT仍须签字。全部`NOT_FOR_FAB`。


### V14 实存PCB复制图纸 + 12内部NPTH真实轮廓 + 12层初稿（2026-11-13）

- 在**现有V13唯一活GUI**内从原PCB1 UUID `2f6fa2d508d3f9a8`复制完整真实149/443/465/93图纸至独立 PCB UUID `8c496410b2877d3c`，复制品实际移除与三磁柱NPTH槽冲突的**20个T1–T4旧裸PAD、7条VOUT铜线、3个VOUT过孔**，编辑器所有删除均返回`true`，再真实创建12个 layer11 Board Outline 圆角闭合槽，每条有真实primitive UUID；原生PCB启用铜层**12**（1/2/15–24），保存后原生可读 **149组件/423PAD/458Line/90Via、BoardOutline 13**。真实DRC目前 **149 Connection/1 Netlist**，并未新增物理错误。见[`原生V14 12槽创建原始回执`](../../hardware/dcx_main/g2/g2_v14_real_native_12_NPTH_outline_CREATED_NOT_FOR_FAB.json)、[`12层源回读`](../../hardware/dcx_main/g2/g2_v14_native_PCB_12copperlayers_12cutouts_saved_NOT_FOR_FAB.json)、[`保存后的V14原生`.eprj2`二进制项目`](../../hardware/dcx_main/g2/dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_12L_STACK_WIP_NOT_FOR_FAB.eprj2)、[`实际原生DRC`](../../hardware/dcx_main/g2/g2_v14_native_PCB_after_12slots_real_DRC_raw_NOT_FOR_FAB.json)。原PCB1仍在同一容器；用户不希望新开软件窗口，所以该保存文件尚无独立重开证明，仅同GUI原生保存与SQLite项目结构双PCB回读。
- **区分机械图元、叠层和真实功能**：本轮确实已在**PCB主板**放置12个槽并启用12铜层，绝非仅库件；但**没有真正制造验证的NPTH开槽输出/Gerber，不存在多层3:1:1原副边铜绕组、贯孔/埋孔和首件DOT，也未布背面器件**。现实供应商尚未签内铜3oz/0.09mm介质多层板与ELP32磁窗实际配合，100A真实铜嵌件以及D0没有验收，V14继续`NOT_FOR_FAB`。原V11验证源SHA仍不变；V13临时容器现在含原PCB1+V14复制PCB，文件SHA因新增PCB实际改变，不应再重复旧阶段“V13整个容器未修改”的说法。


### V14 真正降低原生DRC并首次实现四路背面元件（2026-11-13）

- 连续实操嘉立创 **同一可见V13 GUI** 中的 **V14复制板 UUID `8c496410b2877d3c`**，逐次插入 `OC`、`OCM`、`OCD` 三条独立低电流比较器/CT检测信号的真实顶/底铜与PTH：2Via+3Track、2Via+3Track、2Via+4Track；每次均做真实焊盘网络/物理间距检查、原生`pcb_Drc.check`、`pcb_Document.save`，并**待SQLite容器写入刷盘之后**分开留存带SHA的`.eprj2`快照。
- 第二阶段将 `C7–C10` 四颗原来与SR驱动器 `U3–U6` 相隔数十毫米的REG稳压去耦电容，真实翻面至驱动器背后：所有**4个器件原生 `layer=2,rotation=180°`**，每颗两个引脚分别REG1–4/PGND，PCB底层焊盘放在y≈75mm，8个0.4mm drill/0.8mm外径PTH分布在y≈76mm；16段顶/底铜线各0.2mm，防止误用镜像/穿焊盘过孔，实存回读验证。见[底层四元件+铜线布局](../../hardware/dcx_main/g2/g2_v14_after_REG4_native_full_copper_readback_NOT_FOR_FAB.json)与[原生真实DRC回执](../../hardware/dcx_main/g2/g2_v14_after_REG4_independent_second_native_DRC_bottom_four_NOT_FOR_FAB.json)。
- 实际DRC连续实测：**149 Connection/1 Netlist → 124/0 → 122/0 → 120/0 → 111/0**，Physical=0；最终实际保存的[原生 V14 双面PCB快照](../../hardware/dcx_main/g2/dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_REG4_BOTTOM_WIP_NOT_FOR_FAB.eprj2) SHA256 `7dd77910bcf7ff3fd0e2be1e4194439a22189aaf353f105bbe1280c104e4f6fc`，保持参考PCB1不修改。**首个149→124的25项含去除旧20磁件PAD后原生DRC重算，不是单OC线路修好了25个问题**；随后124→111的改善与OCM/OCD/底层REG实际操作对应。**仍有111项真实未连通，不能发板。**
- **严重待修制造门禁**：当前规则配置显示`JLCPCB Capability(Two Layers Board)`，是12层工作PCB的错误审核标准，不能把目前Physical=0视为12层正确DFM。T1–T4完整3:1:1 PCB原副边实际绕组、P-S绝缘、内部盲/埋孔、磁芯首件DOT、100A主输出VOUT/PGND铜排、CT物理针脚、16mm液冷与电磁温升尚未完成。不能为DRC清零短接原副边或忽略缺失元件。所有成果`NOT_FOR_FAB`。
