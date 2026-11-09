# G1 原生带网 PCB（非投板）— 2026-11-09

2026-11-10增量见 [驱动布局复审](driver_eco_review.md)：基线报告已修复写死的网络检查；7件移动的原生候选已重开读回验收（77件/299焊盘/65网/38折线，`driver_eco_report.json`），但仍无走线/DRC，未取代本文基线的投板门禁。

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
几何，含每只焊盘的旋转）重绘的平面图，**不是编辑器截图**。板上没有铜、没有走线；图上只有
焊盘、位号、板框、五个待锁区（紫框）、二十四个临时焊盘标记（黄框，板上 @第 13 层）和八个
DOT 标记（青色方框）。生成器：`make_g1_layout_svg.py`。

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
已经各有一只封装焊盘。包给的 Lr 端子相距 40 mm，原生封装两脚只相距 9 mm（15.5 ↔ 24.5），
两套都放会把这两个网双计。**这是有意不做的选择，不是遗漏。**

**包与 A5 包络的偏差（如实记，未修）**：包的 x 偏移是 ±17.0 mm（T1–T4）与 ±12.0 mm（CT），
而 A5 包络宽 31.75 mm / 20.0 mm（半宽 15.875 / 10.0）⇒ 临时焊盘比自己的待锁区**探出
1.125 mm / 2.0 mm**。图上能直接看到焊盘压在紫框边上。要收进包络得改 `design/v3/maxwell`
的 concept 生成器并重跑 `maxwell_diy_pcb_envelope.py`，本轮没做。

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

## 5. 两极电流路与 Kelvin 清单（**均未布线**）

这块板**没有铜、没有走线、没有过孔**——只有网络赋值和位置。所以下面是"要连的端点"，
不是"已连的路径"；100 A 铜排/铺铜不在本文件里，也不该被读成本文件已解决。

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

**Kelvin / 检测对**（各 3 个焊盘，含 CT 临时焊盘）

| 网 | 端点 |
|---|---|
| `CS1` | D_CT1 p1 (109.0, 70.9) ↔ D_CT3 p3 (119.0, 70.0) ↔ CT `SEC_A` (104.0, 56.0) |
| `CS2` | D_CT2 p1 (115.0, 70.9) ↔ D_CT4 p3 (125.0, 70.0) ↔ CT `SEC_B` (104.0, 48.0) |

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

- **不是**可制造件：没有铜厚/线宽/间距、没有 DRC、没有 ERC、没有 Gerber/钻孔/坐标/装配 BOM，
  没有板厂 DFM。`d1_fabrication_gate.json` 仍是 `NOT_FOR_FAB`。
- **不是**布局完成件：器件按功能分行摆在该去的位置，但**没有一条走线**；
  "自动布通 / 0 DRC"本来就"不算 G1"，这里连布通都没有。
- **不是**磁件已锁版：T1–T4/CT 只有临时焊盘，没有实体封装；Lr 有原生封装但端子间距与
  concept 包对不上（§3）。
- **不是**原理图已同步的板：A5 机械表里有 28 个位号原生原理图里没有 —— 撬棒组
  `R50–R56`、`D50`、`Q51–Q54`、`C50` 与 `Cout1–Cout15`（原生只有一个集总 `Cout`）。
  这部分需要一次真实原理图 ECO 才能上板，本次**没有**做，也不假装做了。
- **R8 ECO 的落点**：只落在原生原理图和本 PCB 上；A5 表、`bom_draft.csv` 等派生文件未同步。

## 8. 复现

```bash
python hardware/dcx_main/g1/make_g1_report.py        # 从 g1_pads.json + 原理图 refs 重建报告
python hardware/dcx_main/g1/make_g1_layout_svg.py    # 从 g1_pads.json 重画平面图
python -m pytest tools -q                            # 离线测试
```

`g1_pads.json` 是 `pcb_PrimitivePad.getAll()` / `pcb_PrimitiveComponent.getAll()` /
`pcb_PrimitivePolyline.getAll()` 的原始读数（焊盘 X/Y 单位 mil、PCB 笛卡尔 Y 向上，
存储值为负；焊盘带 `getState_Rotation()`），保留它就是为了让平面图和报告可核对而不是"画的"。
`make_g1_report.py` 对每条 carry 过来的摆放做位置比对、对每个概念焊盘做"中心 + 偏移"比对，
断言不过就直接报错，不会写出自相矛盾的报告。
