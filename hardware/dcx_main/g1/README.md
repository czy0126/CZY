# G1 原生带网 PCB（非投板）— 2026-11-09

2026-11-10增量见 [驱动布局复审](driver_eco_review.md)：基线报告已修复写死的网络检查；7件移动的原生候选已重开读回验收（77件/299焊盘/65网/38折线，`driver_eco_report.json`）。同日的独立副本 `dcx_main_board_g1_driver_route.eprj2` 已建 25 条第 1 层铜线（GH_DRV/GH/GL_DRV/GL/HB），重开后 `driver_route_report.json` 覆盖校验通过、其余计数与摆放不变。
第二增量是**已落到 `dcx_main_board_g1_driver_route.eprj2` 并经原生 DRC 验收**的两层方案：HB 的 D_BT.1→C5.1、VCC12 的 D_BT.2/U2.1/C103/C104、PGND 的 U2.9/R19.2/C103/C104、SW 的 U2.5/C5.2/R18.2 通过 13 个 **0.3/0.505 mm** 过孔（读回 11.8/19.8 mil，环约 0.10 mm；外径取 0.505 是因为编辑器把 mil 截断到 0.1，0.5 mm 会落成 19.6 mil、低于规则 19.685 mil 的下限）转到第 2 层（13 段第 1 层短引线 + 11 段第 2 层走线）。重开读回 50 条线（47 段计划 + 3 处 T 型拆分）、逐网长度与计划完全一致、覆盖/过孔/摆放检查全空（`driver_route_report.json`）；新网最紧净距 0.156 mm（板规则 0.152，`CLEARANCE` 已对齐到规则值）。原生 DRC 原始结果在 `driver_drc_raw.json`（`pcb_Drc.check(true, false, true)`，规则配置 `JLCPCB Capability(Two Layers Board)`）：**Physical Error 组不存在**（0 条），剩 Connection Error 224、Netlist Error 1，因此 `native_drc_passed` 仍为 false；ERC 未跑，未取代本文基线的投板门禁。钻孔原为 0.2 mm，被 DRC 判了 13 条 `Via Size`（7.9 < 11.8 mil），规则值见 `driver_rules_raw.json`。

> **G1 非锁版审查件。** 这是原生 EasyEDA 工程里**长出来的 PCB**，不是
> `hardware/dcx_mech` 的 KiCad 概念板，也不是投板包。板厂门禁仍是
> `hardware/dcx_main/d1_fabrication_gate.json` 的 **NOT_FOR_FAB**。
> 本文件不改变任何证据意义。

## 1. CAD 文件

| 项 | 值 |
|---|---|
| 路径 | `hardware/dcx_main/g1/dcx_main_board_g1.eprj2` |
| 大小 / md5 | **2,535,424 B** / **`0d516efecae4c95b9baf2648b14c0a4f`** |
| 打开方式 | `lceda-pro open --path <上面这个路径> [--headless true]`；**不要**用 `openProject(uuid)` |
| 保存/关闭/重开 | 已做：headless 打开 → 改 → `pcb_Document.save()` → 关会话 → 重新打开逐项读回，77 器件 / 65 网 / **299 焊盘** / **38 折线**一致，md5 不变 |
| 源原理图 | 与仓库里那份 `dcx_main_board.eprj2` 同源，另加了 R8 双字段 DNP；**仓库里那份真文件没有被本工作流打开过**（md5 仍为 `01be95f71959ade99401e9f8d7a821af`） |

图：`g1_layout.png` / `g1_layout.svg` —— 由 `g1_pads.json`（从保存后的板子读回的 299 个焊盘
几何，含每只焊盘的旋转）重绘的平面图，**不是编辑器截图**。**这块基板**没有铜、没有走线；图上只有
焊盘、位号、板框、五个待锁区（紫框）、二十四个临时焊盘标记（黄框，板上 @第 13 层）和八个
DOT 标记（青色方框）。生成器：`make_g1_layout_svg.py`。

图下方的说明文字写着 `dcx_main_board_g1.eprj2`：现在同目录还有 `..._driver_eco` /
`..._driver_route` / `..._power_rails` / `..._kelvin` 四个候选（`_driver_route` 读回 50 条铜线、
13 个过孔，另有原生 DRC raw；`_power_rails` 在它基础上再加两极，读回 84 条线、15 个过孔；
`_kelvin` 再加两条 CT 检测网，读回 98 条线、18 个过孔），
一句不带文件名的 "无铜、无走线、无 DRC" 会被读成对整块板说的。提交里的 SVG 必须等于由提交里的
`g1_pads.json` 现渲染的结果，`tools/test_g1_layout_svg.py` 逐字节锁住；五个待锁区
就是 CT+T1–T4 五个磁芯本体，**Lr 是真放上去的器件、没有待锁区**。

**只有 SVG 是可复现的**：`.png` 是 11-10 早先的栅格快照，仓库里没有生成它的工具
（本机也没有能用的 SVG 栅格化器），所以它不参与测试、图上也没有后来加的文件名；
以 SVG 为准，需要图时直接用浏览器打开 SVG。

## 2. 改动前后网络 / 封装 diff

| 量 | 改动前 | 改动后 |
|---|---|---|
| PCB 器件 | **0**（工程里只有原理图，无 PCB 文档内容） | **77** |
| PCB 网 | **0** | **65** |
| PCB 焊盘 | **0** | **299**（275 封装焊盘 + 24 设计自有临时焊盘） |
| PCB 折线 | **0** | **38**（1 条板框 @第 11 层 + 37 条 @第 13 层：5 个待锁区 + 8 个 DOT 标记 + 24 个临时焊盘标记框） |
| 原理图器件 | 83 | 83（未增删）；R8 `addIntoBom=false` / `addIntoPcb=false` |

- **封装**：77 个器件全部用原生 `lib_Device.searchByProperties({supplierId})` 命中的真实封装
  uuid 放置，不是占位框；逐器件 uuid 见 `g1_native_pcb_report.json` 的 `placements[*].footprint_uuid`。
- **原理图 → PCB 的差集**（`netlist_export_raw.json` 的 refs vs 板上器件）：
  - 原理图有、板上有：**77**
  - 原理图有、板上没有：**6** —— `T1 T2 T3 T4 CT`（没有厂商封装，只有 §3 的临时焊盘）与
    `R8`（双字段 DNP，**故意**不用，不是漏放）
  - 板上有、原理图没有：**0**（没有凭空造件）
- **逐焊盘网络**：275 个封装焊盘与编辑器网表逐条比对，**不符 0 条**（`pad_net_mismatch_count: 0`）。
- **每只网都有焊盘**：`nets_without_pads: []`（上一版还留着 `PRI_12/PRI_23/PRI_34` 三个空网）。

## 3. 24 个设计自有临时焊盘（`DESIGN_OWNED_G1_CONCEPT_NOT_PHYSICAL_PAD`）

这 24 个是**自由焊盘**（第 1 层，2 mm 圆，带真网络名），来自
`design/v3/maxwell/generated_concept/design_owned_G1_pads_24plus2.csv`，位置 = A5 器件中心 +
包内偏移。它们标出磁件端子**将来要落在哪、接什么网**，但**不是实体 PAD**：后面没有器件、
没有丝印、没有 courtyard，也没有厂商给的焊盘几何。

**板上的"禁布标记"就是这 24 个黄框**：每只临时焊盘在**第 13 层（文档层）各套一个 6 mm 方框**
（`provisional_marks`，24 条折线）。这是 G1 要的"遗留禁布 PAD 标记"——在编辑器里看到黄框就知道
那里是占位、不是可布的实体端子。headless 画不出文字（`pcb_PrimitiveString.create` 全部失败），
所以标记只有方框，说明文字在本文件和 `g1_native_pcb_report.json` 里。

| 器件 | 端子 | 网络 | 板上位置 (mm, Y 向下) | DOT 期望 |
|---|---|---|---|---|
| T1 | `PRI_A` | `PRI_T1` | 3.000, 28.001 | DOT |
| T1 | `PRI_B` | `PRI_12` | 3.000, 11.999 | NON_DOT |
| T1 | `SEC_A` | `SEC1_A` | 37.000, 27.000 | NON_DOT |
| T1 | `SEC_B` | `SEC1_B` | 37.000, 13.000 | DOT |
| T1 | `CTAP` | `VOUT` | 37.000, 20.000 | S_A_DOT_AND_S_B_NON_DOT |
| T2 | `PRI_A` | `PRI_12` | 41.001, 28.001 | DOT |
| T2 | `PRI_B` | `PRI_23` | 41.001, 11.999 | NON_DOT |
| T2 | `SEC_A` | `SEC2_A` | 75.001, 27.000 | NON_DOT |
| T2 | `SEC_B` | `SEC2_B` | 75.001, 13.000 | DOT |
| T2 | `CTAP` | `VOUT` | 75.001, 20.000 | S_A_DOT_AND_S_B_NON_DOT |
| T3 | `PRI_A` | `PRI_23` | 78.999, 28.001 | DOT |
| T3 | `PRI_B` | `PRI_34` | 78.999, 11.999 | NON_DOT |
| T3 | `SEC_A` | `SEC3_A` | 113.000, 27.000 | NON_DOT |
| T3 | `SEC_B` | `SEC3_B` | 113.000, 13.000 | DOT |
| T3 | `CTAP` | `VOUT` | 113.000, 20.000 | S_A_DOT_AND_S_B_NON_DOT |
| T4 | `PRI_A` | `PRI_34` | 117.000, 28.001 | DOT |
| T4 | `PRI_B` | `PGND` | 117.000, 11.999 | NON_DOT |
| T4 | `SEC_A` | `SEC4_A` | 151.000, 27.000 | NON_DOT |
| T4 | `SEC_B` | `SEC4_B` | 151.000, 13.000 | DOT |
| T4 | `CTAP` | `VOUT` | 151.000, 20.000 | S_A_DOT_AND_S_B_NON_DOT |
| CT | `PRI_A` | `CR_CT` | 80.000, 55.999 | UNVERIFIED_FROM_CT_VENDOR |
| CT | `PRI_B` | `CT_LR` | 80.000, 48.001 | UNVERIFIED_FROM_CT_VENDOR |
| CT | `SEC_A` | `CS1` | 104.000, 55.999 | UNVERIFIED_FROM_CT_VENDOR |
| CT | `SEC_B` | `CS2` | 104.000, 48.001 | UNVERIFIED_FROM_CT_VENDOR |

包里的 **+2（`Lr_N1` / `Lr_N2`）没有单独放焊盘**：Lr 用的是原生封装，`CT_LR` / `PRI_T1`
已经各有一只封装焊盘。包现在的 Lr 端距是 **9.0 mm**，与原生封装一致（焊盘中心 610.2 → 964.6 mil）；
以前写的 40 mm 是没有任何 CAD 落过的概念跨度，已撤回。两套都放会把这两个网双计。

**包与 A5 TBD 矩形的关系（已按数据重算）**：包的 x 跨度是 34.0 mm（T1–T4）与 24.0 mm（CT），
而板上 TBD 矩形宽 31.75 mm / 20.0 mm——**矩形是磁芯本体（也是 A6 沉槽轮廓），不是器件包络**，
绕组端子本来就该出芯；真正的检查是端子不能碰到别的东西。读回实测最小边缘距离：
不同磁件的两只临时端子之间 **1.999 mm**（`PRI_23` / `SEC2_A`），临时端子到任一器件焊盘
**1.650 mm**（`CS2` / `D_BT.1`），相对板规则 0.152 mm 有一个数量级的余量。
这些是旋转后轴对齐包围盒距离，是筛查不是 DRC；明细在 `g1_native_pcb_report.json`
的 `provisional_pad_gaps`。

## 4. 仍然阻塞的实体 PAD 清单

**24 个**（T1–T4 各 5 + CT 4）。阻塞原因只有一条：**没有厂商封装**。项目库里唯一的磁件封装是
`XFMR-TH_ZHT104A`，与 D1 选型无关；`pcb_PrimitiveComponent.create` 也要求
`{libraryUuid, uuid}` 形状，不能"直接传封装 item"。所以这 5 个器件**不是 PCB 器件**，
只有 §3 的临时焊盘替它们占位。

| 器件 | 实体焊盘（`逻辑端子 → 网络`） |
|---|---|
| T1 | `PRI_A`→`PRI_T1`，`PRI_B`→`PRI_12`，`SEC_A`→`SEC1_A`，`CTAP`→`VOUT`，`SEC_B`→`SEC1_B` |
| T2 | `PRI_A`→`PRI_12`，`PRI_B`→`PRI_23`，`SEC_A`→`SEC2_A`，`CTAP`→`VOUT`，`SEC_B`→`SEC2_B` |
| T3 | `PRI_A`→`PRI_23`，`PRI_B`→`PRI_34`，`SEC_A`→`SEC3_A`，`CTAP`→`VOUT`，`SEC_B`→`SEC3_B` |
| T4 | `PRI_A`→`PRI_34`，`PRI_B`→`PGND`，`SEC_A`→`SEC4_A`，`CTAP`→`VOUT`，`SEC_B`→`SEC4_B` |
| CT | `PRI_A`→`CR_CT`，`PRI_B`→`CT_LR`，`SEC_A`→`CS1`，`SEC_B`→`CS2` |

**另一个未落地的实体 PAD**：`R8` 的两个焊盘——它不是"阻塞"，是双字段 DNP 的
`addIntoPcb=false` 落地结果（与"排除装配"一致）。

## 5. 两极电流路与 Kelvin 清单（基板未布线；两极与两条 CT 检测网已在候选上落地）

基板 `dcx_main_board_g1.eprj2` **没有铜、没有走线、没有过孔**——只有网络赋值和位置
（`_driver_route` 副本多了顶部那段原边驱动增量；`_power_rails` 副本再加下面的两极；
`_kelvin` 副本再加 CS1/CS2 两条检测网，仍远未布通）。其余各网下面列出的是"要连的端点"，不是"已连的路径"；100 A 铜排/铺铜
不在本文件里，也不该被读成本文件已解决。

坐标单位 mm，A5 坐标（Y 向下）。

**正向（VIN_P → 开关 → 原边 → 副边 → VOUT）**

| 网 | 板上焊盘端点 |
|---|---|
| `VIN_P` | 7 个：J_IN p1 (109.5, 52.0)、Cin p1 (91.7, 43.0)、QH p5–p8 (46.1…49.9, 47.2)、QH p9 大焊盘 (48.0, 49.4) |
| `SW` | 12 个：QH p1–p3 (46.1…48.6, 52.8)、QL p5–p9 (55.1…58.9, 47.2/49.4)、Cr p1 (71.3, 52.0)、C5 p2、R18 p2、U2 p5 |
| `PRI_T1` | Lr p2 (24.5, 52.0) ↔ T1 `PRI_A` 临时焊盘 (3.0, 28.0) |
| `CT_LR` / `CR_CT` | Lr p1 (15.5, 52.0) ↔ CT `PRI_B` (80.0, 48.0)；Cr p2 (72.7, 52.0) ↔ CT `PRI_A` (80.0, 56.0) |
| `PRI_12` / `PRI_23` / `PRI_34` | 各 2 个临时焊盘（T1→T2 / T2→T3 / T3→T4 的原边串联），**板上其余焊盘 0 个** |
| `SEC1_A/B` … `SEC4_A/B` | 每网 7 个：SR 的 p5–p8 + 大焊盘 p8 (81.5) + 门极电阻 p1 + 对应变压器临时焊盘 |
| `VOUT` | 6 个：Cout p1 (4.3, 47.0)、J_OUT p1 (73.5, 116.0)、T1–T4 的 `CTAP` 临时焊盘 4 个（37/75/113/151, 20.0） |

**返回（PGND）**：**75 个焊盘**——Cout/Cin 地、QL p1–p3、SR 的 p1–p3 + 大焊盘、U1–U6 地、
J_IN p2 (114.5, 52.0)、J_OUT p2 (78.5, 116.0)、T4 `PRI_B` 临时焊盘 (117.0, 12.0)。

**两极（`route_power_rails.py`，已应用到 `dcx_main_board_g1_power_rails.eprj2`）**

`output_joint_reduction_cases.json` 的 `next_eda_action` 要求把 VOUT 与 PGND 从 SR–Cout
焊盘到外部负载画成两条显式物理电流路、逐个列出接口。路径按**板上读回的焊盘**
（`driver_route_readback.json`）画出，用 `route_driver_eco` 同一套净距/端点/过孔检查，
并且把**已在那块候选上的原边驱动铜**一起放进检查（单独查两极会漏掉跨线），
`--check` 报 0 条问题：

| 量 | VOUT | PGND |
|---|---|---|
| 端点 | `Cout.1`、`J_OUT.1`、4 个 CTAP 临时焊盘 (37/75/113/151, 20.0) | `Cout.2`、`J_OUT.2`、8 个 SR 源极大焊盘 `SR1A.3`…`SR4B.3` (y 84.47) |
| 段数 / 长度 | 13 段 / 322.200 mm | 11 段 / 292.941 mm |
| 层 | 第 1 层 + 第 2 层干线（2 过孔：(4.3,49)、(73.5,110)） | 第 1 层 |
| 宽度 | 1.0（引线）/ 2.0（y=35.5 母线、第 2 层干线） | 1.0（引线）/ 2.0（y=96 母线） |

- 四个 CTAP 焊盘正下方 7 mm 就是同组 `SEC_B` 焊盘，**竖直落下会穿焊盘**，所以每条先横移
  2 mm 到间隙 (39/77/115/153) 再下行。
- 焊盘引线是 **1.0 mm**：2.0 mm 在源极大焊盘与相邻 SEC/漏极焊盘（最小 0.856 mm）之间过不了
  净距，`tools/test_g1_power_rails.py` 有一个用例专门证明这个门不是空转。
- VOUT 干线必须跨过 y=96 的 PGND 母线，所以经两过孔下到第 2 层；其余全在第 1 层。
- **这不是安培数结论**：2 mm 只是形状，100 A 的界面仍是 G2 的铜排/嵌铜；
  `power_rail_plan.json` 的 `status` 是 `DRAFT_TWO_RAILS_NOT_AMPACITY_QUALIFIED`。
  Cout 仍是一个占位件，不是 15×470 µF 的本地电容组；没有任何螺栓/铜排/可拆接头被建模。

**落地回执**（`apply_power_rails.py`，2026-11-10 第一次 invoke 即成功）：从 `_driver_route`
复制出 `_power_rails`，headless 打开 → 20 s settle → `return 1;` ping → invoke
`--emit-js` 的正文 → `created: 24`、`viasCreated: 2`、`failed: []`、`saved: true` → 等 30 s
越过保存防抖 → `--destroy` 关闭 → 重开读回：**84 条线 / 15 个过孔**，器件 77 / 焊盘 299 /
网 65 / 折线 38 不变。84 = 原 50 + 34：编辑器在保存时把 T 型节点拆开（8 条源极引线接进
y=96 母线那几处），所以按「同网、同层、同宽、共线覆盖」判，`power_rails_report.json` 的
`coverage_problems` / `vias.problems` / `placement_drift` **全空**。原始读数在
`power_rails_readback.json`，开/关/应用回执是 `power_rails_apply_*` / `power_rails_reopen_*`。
**原生 DRC 没有在这个新候选上重跑**（`driver_drc_raw.json` 是加两极之前那块板的读数，
且本身是 0 物理错误 / 224 连接错误，不是通过）；`_driver_route` 的 md5 在复制前后一致。

**Kelvin / 检测对**（各 3 个焊盘，含 CT 临时焊盘）

| 网 | 端点 | 已落地的路径（`route_kelvin.py`） |
|---|---|---|
| `CS1` | D_CT1 p1 (109.0, 70.9) ↔ D_CT3 p3 (119.0, 70.0) ↔ CT `SEC_A` (104.0, 56.0) | 7 段 / 34.550 mm；第 1 层 + 第 2 层（3 过孔：(106.2,56)、(110.1,66.5)、(119,69)） |
| `CS2` | D_CT2 p1 (115.0, 70.9) ↔ D_CT4 p3 (125.0, 70.0) ↔ CT `SEC_B` (104.0, 48.0) | 6 段 / 54.150 mm；全第 1 层 |

- 两条网都在 `_power_rails` 候选上再落地：检查用同一套净距/端点/过孔，且把**已有的驱动铜与
  两极**一起放进计划（`kelvin_plan.json` 的 `problems: []`，`tools/test_g1_kelvin.py` 10 个用例）。
- CS1 要横穿 CS2 的 y=65 走廊，所以它经三只 **0.3/0.505 mm** 过孔绕到第 2 层；CS2 留在第 1 层。
  第 2 层那条 y=66.5 的长横穿**直接穿过 (110.1, 66.5) 那只过孔**——不另画一小段支线：
  编辑器保存时会把共线重叠的线合并，支线回来是一条更长的线，覆盖检查判「没有这一段的读回线」。
- **D_CT1–4 的 p2 没有网络，但它们是铜**。第一版在 x=109 / x=115 直接竖下到 p1，正好从
  D_CT1.2 / D_CT2.2 中间穿过；原生 DRC 报了两条 `SMD Pad to Track`（0 mil，规则 ≥ 6 mil）。
  离线检查器当时**看不见无网焊盘**（`load_pads` 把它们跳过了），所以第一版 `--check` 是绿的。
  现在 `load_pads` 把无网焊盘按 `net=""` 保留，两条网各自先下到焊盘**右侧**再横一步进 p1 中心；
  `tools/test_g1_driver_route_plan.py` 用一条穿 D_CT1.2 的假线段锁住这个盲点。
- **0.3 mm 是检测线宽，不是电流额定**；SR 门极/漏极的 Kelvin 对（`GA*`/`GB*`）**仍未布**，
  CT 端仍是设计自有临时焊盘，磁件端子上板后这两条网会整体移动。

**落地回执**（`apply_kelvin.py`，2026-11-10；共两次，第二次是 DRC 之后改的绕行版）：从
`_power_rails` 复制出 `_kelvin`，同样的 settle/ping/invoke/防抖/关闭/重开协议，`created: 13`、
`viasCreated: 3`、`failed: []`、`saved: true` → 重开读回 **98 条线 / 18 个过孔**（第 1 层 81 /
第 2 层 17），器件 77 / 焊盘 299 / 网 65 / 折线 38 不变；`kelvin_report.json` 的
`coverage_problems` / `vias.problems` / `placement_drift` 全空，13 段计划长度 88.7 mm。
第一次落地（12 段 / 96 条线）几何上穿过了 D_CT1.2 / D_CT2.2，DRC 判 2 条净距错误；
改后的收据覆盖了它，历史在提交 `3a7f9e9` 里。原始读数在 `kelvin_readback.json`，
开/关/应用回执是 `kelvin_apply_*` / `kelvin_reopen_*`。`_power_rails` 的 md5 在复制前后一致。

**原生 DRC（2026-11-10，`run_driver_drc.py --board ..._kelvin.eprj2`）**：`unchanged: true`，
规则配置 `JLCPCB Capability(Two Layers Board)`。结果只剩 **Connection Error 206** 与
**Netlist Error 1**、**没有 Clearance 组**——即两极与两条检测网加进来后**物理错误仍是 0**
（`_driver_route` 时也是 0；连接错误从 224 降到 206，是这两次增量接通的鼠线）。那条网表错误
是原理图↔PCB 的既有不符（§2 的 6 个位号 + A5 表），不是走线造成的。原始读数
`kelvin_drc_raw.json`，开/关/ping 回执 `kelvin_drc_*.json`。

**驱动对**（各 2 个焊盘）：`GH_DRV` R4 p1 (49.2, 57.5) ↔ U2 p4 (130.5, 52.5)；
`GL_DRV` R5 p1 (58.2, 57.5) ↔ U2 p10 (133.5, 51.0)；`GA1–GA4` / `GB1–GB4` 各
门极电阻 p2 ↔ SR 的 p4。

## 6. 几何核对（真实读数，不是估计）

| 检查 | 结果 |
|---|---|
| 待锁区 vs 器件 | T1 (4.125, 7.3) / T2 (42.125, 7.3) / T3 (80.125, 7.3) / T4 (118.125, 7.3) 各 **31.75×25.4**，CT (82, 44.5) **20×15**（A5 实测包络）；按旋转后的焊盘包围盒比对，**0 个器件落进任何待锁区** |
| 跨器件焊盘重叠 | **0** |
| 封装内部焊盘重叠 | 64 处，全部是厂商封装自己的几何（SR1A–SR4B 的大焊盘压在 p3/p8 上，QH/QL 的 p9 热焊盘压在 p5–p8 上），不是摆件错误 |
| 重复焊盘号 | 8 个 SR 封装各有 p3、p8 各两只（同网，不冲突） |
| 焊盘总包络 | x 2.0–152.0 mm，y 11.0–116.9 mm，全在 155×131 板内 |
| 没有网的焊盘 | **5**：`D_CT1–D_CT4` 的 p2、`U2` 的 p2 —— 原理图里就没有网络名，**没有补**，如实记 |

## 7. 这份文件**不能**当作什么

- **不是**可制造件：没有铜厚/层叠/板厂 DFM、没有 ERC、没有 Gerber/钻孔/坐标/装配 BOM。
  本文件对应的基板 `dcx_main_board_g1.eprj2` **没有铜、没有走线、没有过孔**；原生 DRC 只在
  `_driver_route` 与 `_kelvin` 副本上跑过（后者 0 物理错误 / 206 连接错误 / 1 条网表错误，
  `_power_rails` 未单独重跑）。`d1_fabrication_gate.json` 仍是 `NOT_FOR_FAB`。
- **不是**布局完成件：器件按功能分行摆在该去的位置；基板**没有一条走线**，`_driver_route`
  副本只有原边驱动/自举那一小块（47 段 + 13 过孔），`_power_rails` 再加两极（24 段 + 2 过孔），
  `_kelvin` 再加 CS1/CS2（13 段 + 3 过孔），整板仍远未布通。
- **不是**磁件已锁版：T1–T4/CT 只有临时焊盘，没有实体封装；Lr 有原生封装但端子间距与
  concept 包对不上（§3）。
- **不是**原理图已同步的板：A5 机械表里有 28 个位号原生原理图里没有 —— 撬棒组
  `R50–R56`、`D50`、`Q51–Q54`、`C50` 与 `Cout1–Cout15`（原生只有一个集总 `Cout`）。
  这部分需要一次真实原理图 ECO 才能上板，本次**没有**做，也不假装做了。
- **R8 ECO 的落点**：只落在原生原理图和本 PCB 上；A5 表、`bom_draft.csv` 等派生文件未同步。

## 8. 复现

```bash
python hardware/dcx_main/g1/build_g1_board.py --check  # 摆放文件 vs 读回 + 网表（离线）
python hardware/dcx_main/g1/build_g1_board.py --slices DIR  # 生成重建这块板的 JS body
python hardware/dcx_main/g1/make_g1_report.py        # 从 g1_pads.json + 原理图 refs 重建报告
python hardware/dcx_main/g1/make_g1_layout_svg.py    # 从 g1_pads.json 重画平面图
python hardware/dcx_main/g1/route_power_rails.py --check  # 两极离线检查（净距/端点/过孔，含已有铜）
python hardware/dcx_main/g1/route_power_rails.py --emit-js  # 打印两极的 LCEDA body
python hardware/dcx_main/g1/route_power_rails.py --verify  # 从 power_rails_readback.json 重建报告
python hardware/dcx_main/g1/apply_power_rails.py           # 复制→应用→重开读回→出报告（改板，仅副本）
python hardware/dcx_main/g1/route_kelvin.py --check        # CS1/CS2 离线检查（含已有驱动铜 + 两极）
python hardware/dcx_main/g1/route_kelvin.py --emit-js      # 打印 CS1/CS2 的 LCEDA body
python hardware/dcx_main/g1/route_kelvin.py --verify       # 从 kelvin_readback.json 重建报告
python hardware/dcx_main/g1/apply_kelvin.py                # 复制→应用→重开读回→出报告（改板，仅副本）
python hardware/dcx_main/g1/route_driver_eco.py --check   # 离线检查走线计划（净距/端点/过孔）
python hardware/dcx_main/g1/route_driver_eco.py --verify  # 从重开读回重建 driver_route_report.json
python hardware/dcx_main/g1/run_driver_drc.py             # 只读原生 DRC → driver_drc_raw.json
python hardware/dcx_main/g1/run_driver_drc.py --rules     # 只读规则配置 → driver_rules_raw.json
python -m pytest tools -q                            # 离线测试
```

`driver_route.js` 由 `route_driver_eco.py --emit-js` 生成，内容就是当前计划；第一增量是一次
invoke 应用（回执 `driver_route_apply.json`），第二增量按网络逐次 invoke（回执
`driver_route_apply_chunks.json`）——一次卡死会让整段 body 的结果作废，分网能把损失限制在一网。
两次应用都必须重开读回验收（`--verify`），不能只信 `save()` 返回 true。

**这块板的生成器现在在仓库里**：原先建板的 `tmp_g1_probe/g1_build.py` 是未跟踪的临时目录，
30 个控制区器件的摆放（A5 机械表只摆功率级）和生成它们的 slice 正文都只存在于那份临时脚本和
板上。`build_g1_board.py` 取代它：`g1_placement.json` 是**唯一的一处**摆放（77 行，
mm / Y 向下、左上角原点，每行带位号、LCSC、器件 uuid、旋转与逐脚网络），slice 正文只由它
生成，再叠上已提交的 `native_inventory_raw.json` 与 `netlist_export_raw.json`。
`--from-board` 从板的原生读回生成这份摆放（它是设计决定，之后按 diff 评审）；`--check`
把摆放与读回、网表逐件比对（位置容差 0.25 mil，与 `audit_driver_eco.py` 同口径）。
`tools/test_g1_build_board.py` 锁住"提交的摆放 = 提交的读回所推出的摆放"以及 slice 的
mil / Y 取负换算。24 个自由端子焊盘也在覆盖内：它们不是手写坐标，而是由已提交的
`design/v3/maxwell/generated_concept/design_owned_G1_pads_24plus2.csv`（每个端子的相对
偏移与网络）加上板自身的 5 个待锁核体矩形（`g1_pads.json` 的 `tbd_zones`）算出来的，
`--check` 按**位置**（不是脚号——`PRI_A` 在 T1–T4 上各有一个）逐一对回板上的自由焊盘。
**尚未覆盖**：板框/待锁区/DOT 折线（`frame_js()` 已能生成，但没有对着活板跑过的回执）、
以及走线——它们仍由各自的增量脚本负责。

`g1_pads.json` 是 `pcb_PrimitivePad.getAll()` / `pcb_PrimitiveComponent.getAll()` /
`pcb_PrimitivePolyline.getAll()` 的原始读数（焊盘 X/Y 单位 mil、PCB 笛卡尔 Y 向上，
存储值为负；焊盘带 `getState_Rotation()`），保留它就是为了让平面图和报告可核对而不是"画的"。
`make_g1_report.py` 对每条 carry 过来的摆放做位置比对、对每个概念焊盘做"中心 + 偏移"比对，
断言不过就直接报错，不会写出自相矛盾的报告。
