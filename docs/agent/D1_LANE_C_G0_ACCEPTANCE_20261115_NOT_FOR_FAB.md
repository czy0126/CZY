# D1 / Issue #133 — G0 集成验收与硬件交接（2026-11-15，NOT_FOR_FAB）

本文件是 **G0 可执行交接入口**，不是硬件合格证或允许上电声明。与 [Issue #133](https://github.com/czy0126/CZY/issues/133) 保持 G0→G1→G2→G3 的顺序，3 LPM 冷板属于 G3。

## 真实工程输出

**G0 门禁：** `tools/d1_lane_c_g0_acceptance.py` 复核已提交 D0 候选、KiCad ERC、565 个网表引脚、BOM/DNP、远端 LTspice 原始模型证据，并对下面九项实物验收保持默认禁止。报告为 `design/v3/stage_f/d1_lane_c_g0/g0_integration_acceptance_NOT_FOR_FAB.json`。该工具不能自己签发物理上电许可。

**两路独立 12 V 供电工程候选：** `hardware/dcx_main/g2/d1_lane_c_dual_bias_NOT_FOR_FAB/g0_dual_domain_48v_12v_bias_NOT_FOR_FAB.kicad_sch`。由 `tools/d1_lane_c_bias_supply_candidate.py` 生成并用 KiCad 原生网表/ERC 检查。候选采用两只 [Traco Power THN 30-4812](https://www.tracopower.com/overview/thn30)（注意不等于 THN 30WIR）：36–75 V 输入、每只 12 V/2.5 A（标称 30 W），厂家单路引脚为 1 +VIN、2 −VIN、3 +VOUT、4 TRIM、5 −VOUT、6 REMOTE。

两只模块输入同接经独立保险丝候选的 48 V 母线。**原边模块输出负端接 PGND，副边模块输出负端独立保持为 SR_SOURCE_RETURN，严禁接 PGND**；不能把这一路输出直接插到当前共地的 D0 台架 J2。该候选确认了原理图地网分离，但**没有合格的 THN 30 实体封装**，保险丝、模块远端引脚、输出容量、绝缘间隙、36 V 以下启动、EMC、额定驱动功率、实物隔离等均未验证；尚不是可生产 PCB，也不是已经完成的 48 V→12 V 偏置系统。

## G0 剩余实施责任与验收条件

| 条目 | 负责环节 | 必须提供的验收证据 |
|---|---|---|
| G0-01 | Lane A / 电气集成 | 半桥 U2–QH/QL、Cin、Lr/Cr、SW/Kelvin 在**同一产品板**闭合；原生网表、ERC/DRC、Pin-Net |
| G0-02 | Lane B / 磁件集成 | T1–T4 与 CT 的真实 24 端子、DOT、绕组/PCB 对应，绝缘、连续性、磁参数实测 |
| G0-03 | Lane C / 电气集成 | 两路 12 V 偏置实际隔离、UVLO、启动及断供下保持电源实测 |
| G0-04 | Lane C / 硬件集成 | 常闭急停、外部物理断开 48 V、断线/触点失效的断能实测 |
| G0-05 | Lane C / 硬件集成 | 浮地 V(GH1)−V(SW) 真实隔离监测、HB−SW 有效，监测失电禁止启动 |
| G0-06 | Lane C / 台架测试 | 6 种故障×10 路源参考 VGS 原始波形（共 60 组），实际关断与重叠时序 |
| G0-07 | Lane C / 电气集成 | 最坏关断延迟、保持电容有效值、门极电荷/驱动功率、MOSFET SOA |
| G0-08 | A/B/C 集成 | 独立限流、临时散热、极性/短路/绝缘检查、仪器及板序列号 |
| G0-09 | A/B 集成 | 最终产品 PCB 未连接清零，并清除安全相关 ERC/DRC 忽略项 |

**注意：** 上面列的是工作环节而非已指派的具体人员。源 PR 的 Lane A/B 分支尚未提供可用于本轮集成的新增验证证据，不能把概念图或本 Lane 的台架 ERC 视作 G0-01/G0-02/G0-09 已通过。

## 实物采集与证据入库

生成的 `g0_gate_fault_capture_matrix_NOT_FOR_FAB.csv` 给出 10 路门极×6 类故障的独立原始波形采集要求。**高侧用 GH1−SW；原边低侧用 GL1−PGND；8 路 SR 必须分别接自身 MOSFET Source，不能把 PGND 当成最终副边参考地。** 同时记录 V12P/V12S、HB−SW、PERMIT、主功率急停断能、Vin/Iin、器件温度及死区。

`g0_witness_template_NOT_FOR_FAB.json` 是九项占位模板，并非通过证书。实际测试后才可复制成 `g0_external_witnesses.json` 并提供原始波形文件 SHA256、板号、程序、操作者与独立复核人员。工具校验记录可追溯性并拒绝文件缺失、错误哈希、路径逃逸或直接自填 `PASS`；即使证据齐全，最终仍需**独立人工硬件签核**，本工具固定不给 `energization_allowed=true`。

## 重现命令

```powershell
python tools/d1_lane_c_bias_supply_candidate.py --check
python tools/d1_lane_c_g0_acceptance.py --write
python tools/d1_lane_c_g0_acceptance.py --check
python -m pytest tools/d1_lane_c_test_bias_supply_candidate.py tools/d1_lane_c_test_g0_acceptance.py -q
```

`python tools/d1_lane_c_g0_acceptance.py --require-g0` 在当前状态必须非零退出。原独立 D0 项目及示意 LTspice 证据参见 `docs/agent/D1_LANE_C_HS_UVLO_CANDIDATE_20261114_NOT_FOR_FAB.md`。**只有 G0 完整硬件审查通过之后，才能进入 G1 标称输入附近的限流轻载实测。**
