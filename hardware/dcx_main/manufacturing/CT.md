# 加工输入 CT —— 串联在谐振腔里的电流互感器（4 个独立逻辑端子）

状态：**MANUFACTURING_INPUT_DRAFT_NOT_RELEASED**（加工输入草稿：未放行，不是采购结论）。数量：1 只。

本页只保留一个冻结候选。询价用的多候选表在 `hardware/dcx_main/rfq/`，两者不混用：询价问厂家能给什么，本页写我们要做什么、回来量什么。

CT 按带宽、负载与复位决定，与前两类都不同；二次负载 10 Ω 已冻结，不随 CT 改。现行 2 pad 封装是无效的：四个逻辑端子必须各有独立物理端子。

**注意**：本页的磁芯套件尚未选定，因此这一页还不是一份可下单的加工输入。

## 1. 冻结候选

| 项目 | 值 | 出处 |
|---|---|---|
| 磁芯套件 | 未选定：只有 Ae = 20.10 mm^2 与 Bsat = 0.34 T | ct_design.json:core_candidate（没有型号与机械尺寸） |
| 匝比 | 100:1 | ct_design.json:as_built |
| 二次负载 | 10.0 Ω（冻结，不随 CT 改） | ct_design.json:as_built |
| 分压增益 | 0.6857 | ct_design.json:as_built.divider_gain |
| 磁密峰值 @额定 | 2.448 mT = 0.72 % Bsat | ct_design.json:as_built |
| 合规电压 | 1.139 V | ct_design.json:as_built.compliance_v |

## 2. 绕组与叠层

| 项目 | 值 | 出处 |
|---|---|---|
| 一次 | 1 匝，串在谐振腔里（CR_CT → CT_LR） | vendor_terminal_request.json |
| 二次 | 100 匝，接 10 Ω 负载后整流 | ct_design.json:as_built |

## 3. 端子需求

| 逻辑端子 | 电路网络 | 设计 DOT | 物理端子 |
|---|---|---|---|
| PRI_A | CR_CT | UNVERIFIED_FROM_CT_VENDOR | 待商家提供 |
| PRI_B | CT_LR | UNVERIFIED_FROM_CT_VENDOR | 待商家提供 |
| SEC_A | CS1 | UNVERIFIED_FROM_CT_VENDOR | 待商家提供 |
| SEC_B | CS2 | UNVERIFIED_FROM_CT_VENDOR | 待商家提供 |

物理端子号必须来自厂家端子图；本仓库没有，所以写「待商家提供」，不编焊盘号。

## 4. 尺寸与限值

| 项目 | 值 | 出处 |
|---|---|---|
| 整机限值 D1 | 16.0 mm（要同时供 D3 则收紧到 10.0 mm） | d1_staged_target_policy.json |
| 完整高度 | 待厂家给出磁芯型号后填 | ct_design.json 只有 Ae 与 Bsat |
| 现行封装 | 2 pad —— 无效，必须换成 4 个独立端子 | vendor_terminal_request.json:requirements |

## 5. 首件试验条件

| 试验 | 条件 | 判据 | 出处 |
|---|---|---|---|
| 匝比与相位 | 一次注入 20 A / 200 kHz 方波，二次接 10 Ω | 匝比 100:1；相位误差待定义（本仓库没有要求来源） | ct_design.json |
| 传输比 | 一次 20 A，R_b = 10 Ω | 0.100 V/A ±5 %；实测中位 0.0997355 V/A，标称 0.1 | hotfault srprobe 标定 |
| 直流偏磁 | 故障脉冲下的一次电流波形 | 故障下 AC 自复位假设不成立，量测值只作记录 | ct_design.json:caveats |
| 耐压 / 爬电 | 待厂家给出绝缘等级后确定 | 待厂家（CT 串在 48 V 谐振腔里，原副边隔离等级未定义） | vendor_terminal_request.json |
| 外形高度 | 千分尺 | ≤ 10.0 mm 才能同时供 D3 | d1_staged_target_policy.json |
| 极性 | 按 4 个逻辑端子的 DOT 逐个通断 | 与 vendor_terminal_request.json 逐端一致 | tools/winding_polarity.py |

判据是首件的接受/拒收线；没有判据就没有拒收依据，所以不接受只写「按厂家标准」。

## 6. 实测回填

| 字段 | 回填值 |
|---|---|
| 件号 | — |
| 日期 | — |
| 仪器 / 夹具 | — |
| 匝比 | — |
| 传输比 (V/A) | — |
| 励磁电感 L (uH) | — |
| 二次 DCR (mΩ) | — |
| 外形高 (mm) | — |
| 耐压 | — |
| 结论 | — |

本栏由首件实测填写，草稿里一律为空。本页的磁密来自仿真波形积分或解析计算，气隙与 AL 是解析值——都不是这里的测量值。

## 7. 未决项

1. 四个独立物理端子的焊盘、坐标与极性的厂商图（现行封装只有 2 pad，是无效的）。
2. 原副边耐压、爬电距离与绝缘测试方法。
3. 磁芯型号与机械尺寸：现在只有 Ae 与 Bsat，完整高度无从判断。
4. 故障电流下的直流偏磁与剩磁：ct_design.json 的 caveats 假设 AC 自复位。

## 8. 出处

- `design/v3/bom/ct_design.json`
- `design/v3/pcb/board_netlist.csv`
- `hardware/dcx_main/vendor_terminal_request.json`

**跨件提醒**：变压器的磁通按各绕组实际电压积分核算；`L*I/(N*A)` 是 Lr 的电感筛查判据，不能拿来判断变压器励磁饱和。变压器在 ELP32、Lr 在 ELP38，这是分用途的两个决定。
