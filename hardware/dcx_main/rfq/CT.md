# RFQ CT —— 串联在谐振腔里的电流互感器（4 个独立逻辑端子）

状态：**REQUEST_FOR_QUOTE_NOT_VERIFIED**（询价单，不是制造图，不是签核）。数量：1 只。

每个数字都注明出处；本仓库没有数据的项写 UNKNOWN 并汇总在第 11 节，不省略、不填看起来合理的值。

## 1. 绕组极性与逻辑端子

| 逻辑端子 | 电路网络 | 设计 DOT | 出处 |
|---|---|---|---|
| PRI_A | CR_CT | UNVERIFIED_FROM_CT_VENDOR | hardware/dcx_main/vendor_terminal_request.json |
| PRI_B | CT_LR | UNVERIFIED_FROM_CT_VENDOR | hardware/dcx_main/vendor_terminal_request.json |
| SEC_A | CS1 | UNVERIFIED_FROM_CT_VENDOR | hardware/dcx_main/vendor_terminal_request.json |
| SEC_B | CS2 | UNVERIFIED_FROM_CT_VENDOR | hardware/dcx_main/vendor_terminal_request.json |

## 2. 电感、匝比与气隙

| 项目 | 值 | 出处 |
|---|---|---|
| 匝比 | 100:1 | ct_design.json:as_built（100:1） |
| 二次负载电阻 | 10.0 Ω | 冻结值，不随 CT 改 |
| 磁芯截面积 Ae | 20.10 mm^2 | ct_design.json:core_candidate（候选，未选定件） |
| 磁芯饱和磁密 | 0.34 T | ct_design.json:core_candidate |
| 励磁电感（模型） | 20.0 mH | deck 里的 20 mH 支路；额定下约 0.04 % 二次电流，故障时不成立 |

## 3. 工作波形

| 项目 | 值 | 出处 |
|---|---|---|
| 频率 | 200.62 kHz | = 1 / ct_design.json:measured.period_s |
| 一次电流峰值 / 平均 | 1.661 | ct_design.json:measured.peak_to_average（实测） |
| 半周电荷 | 20.824 uC | ct_design.json:measured.q_half_c |
| 磁密峰值 @额定 | 0.002448 T | ct_design.json:as_built.flux_peak_t |
| 磁密占 Bsat | 0.72 % | 由上两行相除 |
| 合规电压 | 1.139 V | ct_design.json:as_built.compliance_v |

## 4. 额定电流与故障电流

| 项目 | 值 | 出处 |
|---|---|---|
| 一次 RMS | 9.4502 A | ct_design.json:measured |
| 一次峰值 | 13.8814 A | ct_design.json:measured |
| 一次平均 | 8.3557 A | ct_design.json:measured |
| 故障峰值（50 V hotfault 前缀） | 101.26 A | 50 V 诊断前缀 |
| 二次 RMS = 一次 / 匝比 | 0.09450 A | 由上两行相除 |

## 5. 温度

| 项目 | 值 | 出处 |
|---|---|---|
| 设计点 | 100 °C | 与整机磁件同口径 |
| 环境温度 | UNKNOWN | 仓库没有整机环境温度要求 |

## 6. 允许损耗

| 项目 | 值 | 出处 |
|---|---|---|
| 二次负载功耗 | 0.0893 W | ct_design.json:as_built.burden_power_w |
| 口径提醒 | 这 89 mW 耗在 R3 上，不在 CT 本体；48 V/120 A 实测是 125.7 mW | CLAUDE.md 测量口径 |
| CT 本体铁损 / 铜损 | UNKNOWN | 未建模 |

## 7. 绝缘

| 项目 | 值 | 出处 |
|---|---|---|
| 原副边绝缘 | UNKNOWN | vendor_terminal_request.json：Confirm primary-secondary insulation and test method with vendor |
| 测试方法 | UNKNOWN | 同上 |
| 结论 | CT 串在 48 V 谐振腔里，原副边隔离等级未定义 | 路线 §P1 磁件 |

## 8. 完整高度

| 项目 | 值 | 出处 |
|---|---|---|
| 高度 | UNKNOWN | ct_design.json 只有 Ae 与 Bsat，没有磁芯型号与机械尺寸 |
| 整机限值（D1_100A） | 16.0 mm | d1_staged_target_policy.json:stages[D1_100A].height_limit_mm；要同时供 D3 则收紧到 10 mm |
| 现行封装 | 2 pad —— 无效，必须换成 4 个独立端子 | vendor_terminal_request.json:requirements |

## 9. 公差

| 项目 | 值 | 出处 |
|---|---|---|
| 匝比公差 | UNKNOWN | 无要求来源 |
| 相位误差 | UNKNOWN | 无要求来源 |
| 端子位置公差 | UNKNOWN | 无物理端子图 |

## 10. 物理端子图

| 项目 | 值 | 出处 |
|---|---|---|
| 逻辑端子 | 4 个：PRI_A = CR_CT，PRI_B = CT_LR，SEC_A = CS1，SEC_B = CS2 | hardware/dcx_main/vendor_terminal_request.json |
| 物理端子图 / 焊盘号 | NOT AVAILABLE —— 需要厂家给出 4 个独立端子的图与极性 | vendor_terminal_request.json |

## 11. 未决项（本仓库没有数据，或需要决定）

1. 四个独立物理端子的焊盘、坐标与极性的厂商图（现行封装只有 2 pad，是无效的）。
2. 原副边耐压、爬电距离与绝缘测试方法。
3. 磁芯型号与机械尺寸：现在只有 Ae 与 Bsat，完整高度无从判断。
4. 故障电流下的直流偏磁与剩磁：ct_design.json 的 caveats 假设 AC 自复位，带直流偏置的故障不覆盖。

## 12. 出处

- `design/v3/bom/ct_design.json`
- `design/v3/pcb/board_netlist.csv`
- `hardware/dcx_main/vendor_terminal_request.json`

**跨件提醒**：变压器的磁通按各绕组实际电压积分核算；`L*I/(N*A)` 是 Lr 的电感筛查判据，不能拿来判断变压器励磁饱和。系统 24:1 是「半桥 + 四原边串联」与「3:1:1」共同形成的，单件匝比是 3:1:1。
