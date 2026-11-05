# 加工输入 Lr —— 谐振电感 Lr（独立件，不是变压器的漏感）

状态：**MANUFACTURING_INPUT_DRAFT_NOT_RELEASED**（加工输入草稿：未放行，不是采购结论）。数量：1 只。

本页只保留一个冻结候选。询价用的多候选表在 `hardware/dcx_main/rfq/`，两者不混用：询价问厂家能给什么，本页写我们要做什么、回来量什么。

Lr 与变压器是两个决定：Lr 按电感保持率、气隙与故障电流选套件，变压器按电压积分选。本页冻结 Lr 的一个候选，变压器的候选见 T1-T4 各页。

## 1. 冻结候选

| 项目 | 值 | 出处 |
|---|---|---|
| 磁芯套件 | TDK ELP 38/8/25 + I 38/4/25（B66459G0000X，N97） | references/datasheets/elp38.pdf |
| 匝数 | 2 匝 | lr_design.json:catalogue_cores（气隙工艺范围与 0.9*Bsat 同时卡出） |
| 目标电感（外置件） | L_external = L_tank_target − L_leak_measured = 1.000 − 实测漏感（模型值 0.080 ⇒ 0.920 uH） | lr_design.json:tank |
| 筛选上限 | 1.000 uH——这是筛选上限，不是要绕的值 | lr_design.json:tank.note |
| 目标 AL | 250.0 nH/T^2 | = 1.000 uH / 2^2 |
| 气隙（按 AL 算） | 0.9461 mm | lr_design.json:catalogue_cores（ELP38 自己的 AL，不是 ELP32 的 1.4443 mm） |
| 气隙窗口 | 0.9346 - 1.1487 mm | 由外置件 ±10 % 用 core_gap_m() 反算 |
| 厂家气隙有效区间 | 0.10 - 2.00 mm | elp38.pdf；N97 的气隙常数 TDK 未公布，所以落区间仍是解析值 |
| 饱和电流（Amin） | 119.0 A | isat_a_amin = Bs·N·Amin/L |
| 最坏配对磁密 | 0.2349 T = 75.8 % Bsat | 每个实测峰值用自己的电感，不是把电流套到目标 L 上 |

## 2. 绕组与叠层

| 项目 | 值 | 出处 |
|---|---|---|
| 匝数 / 层数 | 2 匝，单层 | 本页冻结候选 |
| 端子 | 2 个：N1 = CT_LR，N2 = PRI_T1 | design/v3/pcb/board_netlist.csv |
| 绕向 | 无极性要求；两端做标记以便首件复现 | 磁件设计包 |

## 3. 端子需求

| 逻辑端子 | 电路网络 | 设计 DOT | 物理端子 |
|---|---|---|---|
| N1 | CT_LR | 无极性要求（两端可互换） | 待商家提供 |
| N2 | PRI_T1 | 无极性要求（两端可互换） | 待商家提供 |

物理端子号必须来自厂家端子图；本仓库没有，所以写「待商家提供」，不编焊盘号。

## 4. 尺寸与限值

| 项目 | 值 | 出处 |
|---|---|---|
| 整机限值 D1 / D3 | 16.0 / 10.0 mm | d1_staged_target_policy.json |
| 首选套件全叠层最坏高 | 12.49 mm | magnetics_design.json:catalogue_core_stack（含胶/标签/沉槽，不含夹子） |
| 留给 TIM / 冷板 / 紧固件 | 3.51 mm | magnetics_design.json:catalogue_core_stack |
| 窗口净高 / 单侧宽 | 4.45 ±0.15 mm / 6.35 mm | references/datasheets/elp38.pdf 第 7 页 |
| 对 D3 的余量 | -2.49 mm（负值 = 本候选只能用 D1；D3 需换更矮的套件） | = D3 限值 − 本套件全叠层最坏高 |

## 5. 首件试验条件

| 试验 | 条件 | 判据 | 出处 |
|---|---|---|---|
| 电感（小信号） | 100 kHz，0.1 V，25 °C | 0.920 uH ±10 % | 由 L_external 与自选验收窗口 |
| L 随直流偏磁 | 0 - 121.5 A，100 °C，按厂家 L(I, T) 曲线 | 不得跌破 0.828 uH（外置件的 0.9 倍） | 第 20 章询价假设 |
| 气隙 / AL | 按 AL 磨；实测 AL 反算气隙 | 落在厂家公布的有效区间内；N97 常数未公布，验收按 AL 而不是按气隙 | lr_tdk_catalog_core_screen.json |
| 直流电阻 | 20 °C，四线法 | 待厂家给出绕组尺寸后由铜损预算反算（本仓库只算了 Irms²·R_ac 的铜损） | lr_design.json:candidates |
| 全叠层高度 | 千分尺，最大处 | ≤ 12.49 mm | magnetics_design.json |
| 耐压 | 单绕组件，不做原副边耐压；绕组对磁芯按整机绝缘要求另定 | 待整机绝缘等级确定 | 磁件设计包 §4.1 |
| 温升 | 满 100 A 连续 30 min；环境温度待定 | 绕组热点 ≤ 100 °C 设计点 | 第 20 章 |

判据是首件的接受/拒收线；没有判据就没有拒收依据，所以不接受只写「按厂家标准」。

## 6. 实测回填

| 字段 | 回填值 |
|---|---|
| 件号 | — |
| 日期 | — |
| 仪器 / 夹具 | — |
| L 小信号 (uH) | — |
| L @121.5 A (uH) | — |
| AL (nH/T^2) | — |
| DCR (mΩ) | — |
| 全叠层高 (mm) | — |
| 温升 (K) | — |
| 结论 | — |

本栏由首件实测填写，草稿里一律为空。本页的磁密来自仿真波形积分或解析计算，气隙与 AL 是解析值——都不是这里的测量值。

## 7. 未决项

1. ELP38 上 N97 的气隙计算常数 TDK 未公布，所以气隙仍是解析值，需厂家按 AL 公差确认。
2. 0 - 121.5 A、100 °C 的增量电感 L(I)：验收窗口沿用外置件 ±10 %。
3. 外置件与变压器漏感的分配：首件实测漏感后才定，0.920 uH 只是按模型漏感的预估值。
4. 独立 Lr 的物理端子、焊盘与机械定义：现在只有电感、匝数与气隙。

## 8. 出处

- `design/v3/bom/lr_design.json`
- `references/datasheets/elp38.pdf`
- `design/v3/magnetics/magnetics_design.json (catalogue_core_stack)`
- `design/v3/power_priority/lr_tdk_catalog_core_screen.json`
- `hardware/dcx_main/vendor_terminal_request.json`

**跨件提醒**：变压器的磁通按各绕组实际电压积分核算；`L*I/(N*A)` 是 Lr 的电感筛查判据，不能拿来判断变压器励磁饱和。变压器在 ELP32、Lr 在 ELP38，这是分用途的两个决定。
