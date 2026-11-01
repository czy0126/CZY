# 唯一基线清单（2026-10-31 审核后）

本文件与 `design/baseline/baseline_manifest.json` 一起构成本项目在 2026-10-31 审核之后的**唯一基线**。
`design/review_20261031/manifest.json`（13 个文件，09:24–11:50 的快照）是审核当时的冻结版本，保留用于追溯，
但**不再作为当前版本的依据**；两者关系见 §1。

本基线只证明“参数、日志、报告三者对得上”，**不证明硬件行为**。所有台架均为行为模型/理想替身，
见 §3 每一行的“不能支持的主张”。

## 1. 版本关系与本次变更

| 变更 | 范围 | 对数值的影响 | 证据 |
|---|---|---|---|
| off-blank 起点注释更正 | `models/sr_timing_v3.lib` 仅注释 | 无，网表行逐行相同 | 与冻结副本 `design/review_20261031/sr_timing_v3.lib`（`28202ae20e8815aa`）diff，只有注释差异；现值 `5099df9183b0e060` <!-- hash-owner: design/review_20261031/sr_timing_v3.lib, models/sr_timing_v3.lib --> |
| 积分器符号统一 | 47 个 `sim/v2/comm_v3/*.cir`（`B… I=-∫…`） | 无；`.meas` 日志中的 QREV/EBD/ECH/EGE 由负变正，报告改为直接引用 | 36 个换流台重跑全部干净，量级与报告一致（`deck_runs_comm.json`） |
| 报告哈希刷新 | `design/v2/*.md` 中 60 个 16 位前缀 | 无 | `tools/refresh_doc_hashes.py` 机械替换，二次运行 0 行变化 |
| 栅极负载参数化（步骤 2） | 新增 `models/sr_timing_v3_1.lib`；`sr_timing_v3.lib` **未改动** | 默认值等价于 v3，旧台架不传参时逐位不变 | `sr_gate_load_test` 的 6.7n/CPIN=0 档与旧头条相差 <0.4 %；见 `design/v2/gate_load_calibration.md` |
| 修正栅极负载台架（步骤 2） | 新增 `comm_v3/sr_commutation_v3_g0.cir`（`CGATE=0 CPIN=100p`）；旧 headline 原样保留 | 40 A 主档 EBD 5.851 → 6.788 µJ、QREV 69.06 → 95.16 nC、Etot 9.362 → 9.897 µJ | `design/v2/sr_commutation_v3_g0_results.md` 八档全表 |
| 参数角台架（步骤 2） | 新增 `sim/v2/verify_param_bounds.cir`（BON×BOFF 12 档） | 无（新证据，不改变旧数字） | §4.2 |
| ARM 角台架（步骤 2） | 新增 `sim/v2/verify_arm_bounds.cir`（ARM 1.0–2.5 V × 4 个重触发时刻 = 16 档） | 无（新证据）；锚点与阈值 1:1，`off−arm` 恒 650.72 ns | `design/v2/sr_arm_interlock_results.md` §3 |
| 双路互锁复核（步骤 2） | 五个既有仲裁台架各跑两遍（v3 与 `*_g0.cir`），共 10 个新日志 | 无数值改变；v3→g0 仅“栅极穿 2 V”早 11.63 ns | 同上 §5 |
| `meas_table.py` 静默解析修复 | `tools/meas_table.py` + 新 `tools/test_meas_table.py`（5 例） | 仅影响单档日志的 `WHEN`/`FIND` 行；已发布表格取自扫描块，不受影响 | §5 第 5 条 |
| 时序模型关断比较器修正（步骤 3） | 新增 `models/sr_timing_v3_3.lib`（= v3_2 只改一行）；v3/v3_1/v3_2 未改动 | 旧台架不引用它，数字不变；真实谐振腔台上 EBD 10.31 → 1.29 µJ、沟道占比 5.2% → 44.8% | `design/v2/sr_tank_dual_results.md` §4 |
| 真实谐振腔双 SR 台架（步骤 3） | 新增 `sim/v2/sr_tank_dual_v33.cir`（主）、`sr_tank_dual_v32.cir`（v3_2 对照）、`sr_tank_dual_v2timing.cir`（v2 单变量 A/B）、`models/sr_timing_v2_pin100p.lib`（A/B 件） | 无（新证据，不改变旧数字） | 同上 §5；v32 与 v33 的非注释行只差一行 `.include`；v2 与 v3_3 各量差 ≤0.4%，缺陷归属关断比较器 |
| 电荷/能量/di/dt 积分工具 | 新增 `tools/tank_metrics.py` + `tools/test_tank_metrics.py`（10 例） | 无（离线分析新台架） | 同上 §5；`python -m pytest tools/test_tank_metrics.py -q` |
| **第三轮**：`tank_metrics` 口径修正 | `tools/tank_metrics.py` + `tools/test_tank_metrics.py`（13 例）：A/B 各按**自身**门极分类、时间加权平均、窗口真实极值 | 旧“A 通道”把 B 导通时刻记到 A 名下；`Vout` 由采样均值改为梯形时间平均；峰值由“8 周期峰值均值”改为整窗最大值 | `design/v2/第三轮_测量口径与能量账本_2026-10-31.md` §3 |
| **第三轮**：内部支路账本 | 新增 `tools/sr_energy_ledger.py` + `tools/test_sr_energy_ledger.py`（4 例）、`sim/v2/sr_tank_dual_v33_internal.cir` | 首次把沟道/体二极管/Rg/储能分开；残差 0.048 %（快照）/ 0.026 %（工作点） | 同上 §4；`design/v2/round3_energy_ledger_284k.json`、`_ss.json` |
| **第三轮**：工作点台架 | 新增 `sim/v2/sr_tank_dual_v33_ss.cir`（200.6 kHz 初始化）、`_ss_fine.cir`（5 ns，60 µs）与 `_ss_1ms.cir`（1 ms，取 887.6–997.3 µs / 22 周期） | 纠正“284.4 kHz 即稳态”：284.4 kHz 是 SS≈1.41 V 的软启动快照，工作点是 200.6 kHz；工作点 SR 耗散 855 mW/器件（6.84 W、3.82 %） | 同上 §2、§3.4；`_probe/ss_ic_a/b.cir` 证明 `.ic V(ss)=4` 必须配 VCC 常开 |
| **第三轮**：收敛与汇总工具 | 新增 `tools/steady_state_check.py`（4 例）、`tools/round3_summary.py` + `tools/test_round3_summary.py`（5 例） | 无（报告层）；汇总表由 raw 自动生成，缺 raw 时拒绝补数；主频从 `V(sw)` 取中位数，不取门极周期 | 同上 §1、§3.4；`design/v2/round3_summary.json` |

约定：报告里的哈希是 **SHA-256 的前 16 位小写十六进制**；完整值只在 `baseline_manifest.json`。
两者可用 §6 的命令互相核对。

## 2. 类别词表

| 类别 | 含义 | 可以支撑的结论 |
|---|---|---|
| `official_vendor_model` | 厂商提供的加密/公开模型 | **设计台架不使用**此类模型；只有 `design/v2/official_model_report.md` 记录的独立可行性探针（必须加 `-alt`），不在本基线台架内 |
| `calibrated_behavioural_model` | 按数据手册曲线拟合的行为模型 | 拟合区间内的趋势与量级；不得当作器件级验证 |
| `sequencing_surrogate_model` | 数字时序逻辑的替身（比较器、消隐、互锁） | 时序关系与逻辑正确性；门极边沿、PGD 定律未经标定 |
| `uncalibrated_behavioural_model` | 只按手册条目搭的控制/驱动行为 | 功能顺序；不含电荷、损耗、温度与寄生 |
| `simulation_deck` | LTspice 批处理网表 | 无（只按 §4 的运行结果说话） |
| `numeric_artifact` | 某次运行的 `.log` / `.json` | 该次运行发生了什么的记录，不是物理验证 |
| `report` / `analysis_tool` | 报告与脚本 | 便于复现与核对，不增加物理置信度 |

## 3. 模型分类与边界

| 模型 | 前缀 | 类别 | 用途 | 不能支持的主张 |
|---|---|---|---|---|
| `models/sr_device_v3.lib` | `5224e94703cc2a6e` | calibrated | BSC010N04LS6 替身，按手册曲线拟合 | 封装 Ld/Ls 为估计值；PGD 定律与温度未标定；非厂商签名 |
| `models/sr_timing_v3.lib` | `5099df9183b0e060` | sequencing surrogate | UCC24624 数字时序替身（SLUSD48C 7.5/7.6、8.3.4、8.4） | 仅 typ 门槛；PGD 未标定；128/46 ns 边沿 vs 手册 23/35 ns；待机、VSS 偏置电流、155/275 ns 自适应延迟未实现；**6.7 nF 门极替身是已知驱动模型缺陷**（审核 P1 后续项） |
| `models/sr_timing_v3_1.lib` | `32a5041bfac52b1e` | sequencing surrogate | v3 的严格超集：`Cgate` 参数化（默认 6.7n），新增 `Cpin`（默认 0） | 同 v3。`CGATE=0 CPIN=100p` **只在配 `SR_DEVICE` 时**使用：6.7 nF 是理想开关台的栅荷替身，与器件自带的 Cgs/Cgd 并联即重复计入；`CPIN=100p` 是数值正则化，不是封装/走线实测值 |
| `models/sr_timing_v3_roff.lib` | `f2c4180e44897c18` | sequencing surrogate | v3 + 行为化 330 µA VSS 偏置等效 | 偏置网络是等效，不是 VSS 引脚模型；门极回路仍回 S |
| `models/sr_timing_v3_2.lib` | `33bb9b0db38bf881` | sequencing surrogate | v3_1 + 关断消隐积分器软限幅，数值鲁棒性 | **缺陷快照**：关断比较器在真实谐振腔上锁存一次漏极振铃峰，导通 492–528 ns 后即关断 SR；**不得从中取 SR 导通数字** |
| `models/sr_timing_v3_3.lib` | `f03b6e179736916d` | sequencing surrogate | v3_2 删除上述锁存，恢复 v2 关断语义 | 与 v2 在真实谐振腔台上逐量一致；OFFTH 关断需 TOFF 持续反偏，仍非厂商签名 |
| `models/sr_timing_v2_pin100p.lib` | `2013de373fc5d7d4` | sequencing surrogate | v2 逐字复制，仅 `Cgate 6.7n` → `100p` | **A/B 件，不是模型修订**：用在真实器件台上只为了隔离状态机这一个变量；冻结 v2 未改动 |
| `models/sr_timing_v2.lib` | `412e07a9256576d0` | sequencing surrogate | 冷启动台（`startup_ct*`）使用的旧时序 | 已被 v3 取代用于 SR 判决；**v2 与 v3 的数字不得混用** |
| `models/ucc25600_legacy_behaviour.lib` | `b49c5dc13a44b383` | uncalibrated | UCC25600 振荡、软启动、OC 比较器、双门极 | 偏置/自举为行为级；**没有真实偏置/使能时序电路** |
| `models/ucc27282_behaviour.lib` | `fff5966a5e764ac2` | uncalibrated | UCC27282 驱动：UVLO、EN 时序、16 ns TPD、3 A/4 Ω | 无栅电荷/Qg 模型（负载是时序模型的集总 CGATE，即 6.7 nF 项）；延迟匹配、最小脉宽、自举反向恢复未建模 |

**模型族不统一（审核 P1，尚未整改）**：`startup_ct*` 台包含 `sr_timing_v2.lib` + `ucc25600_legacy_behaviour.lib`；
`comm_v3` 台包含 `sr_timing_v3.lib` + `sr_device_v3.lib`。两组数字不得合并成“整机已验证”。整台同模型属于后续步骤 4。

## 4. 运行登记：失败与超时

`baseline_manifest.json` 中每个台架可通过 `status`/`status_note` 标明特殊状态；运行结果另存为 JSON：

| 汇总文件 | 覆盖 | 结果 |
|---|---|---|
| `design/baseline/deck_runs_comm.json` | 36 个 `sim/v2/comm_v3/*.cir`（含 6 角 + 负载/门槛/瞬态扫描） | 36 个全部完成、无错误标记，见 §4.2 |
| `design/baseline/deck_runs_extra.json` | 此前从未跑过的 5 个 comm 台 | 3 个 ok、**2 个 TIMEOUT**，见 §4.2/§4.3 |
| `design/baseline/deck_runs_startup.json` | 启动台 + 诊断台 | 见 §4.2 |

### 4.2 运行结果明细

启动台（`deck_runs_startup.json`，8 个有效台全部完成；超时列在 §4.3）：

| 台架 | 状态 | 关键证据（直接从新 `.log` 的 `.meas` 读取） |
|---|---|---|
| `startup_ct.cir` | ok, 18.1 s | `ipri_pk` 36.0671844482 A、`ict_pk` 0.360634893179 A、`ocd_max` 3.57188892365 V |
| `startup_ct_02.cir` | ok, 1.8 s | 同上三项逐位相同；`vout_200u` 1.71819257736 V、`oc_at_200u` 0.410367995501 V |
| `startup_ct_long.cir` | ok, 76.1 s | `vout_avg` 1.91113883461 V、`vout_max` 1.92622435093 V、`oc_max` 0.556017756462 V、`ipri_pk` 36.0671844482 A、`sr_reverse` 12.3310022354 A |
| `startup_ct_long_f10.cir` | ok, 77.7 s | `vout_avg` 1.9112075341 V、`ipri_pk` 36.1723976135 A、`sr_gate_max` 8.297996521 V |
| `startup_ct_long_f10_c1.cir` | ok, 78.3 s | `vout`/`pre` 轨迹与 f10 同量级；见日志 |
| `startup_ct_fault_f10.cir` | ok, 59.9 s | `oc_trip` 3.98019814919 ms（延迟 30.20 µs），`ipri_after` 73.18 A（3.95–5 ms 窗），I²t 55.64 mA²s |
| `startup_ct_fault_f10_c1.cir` | ok, 63.3 s | `oc_trip` 3.96304769133 ms（延迟 13.05 µs），`ipri_after` 64.98 A，I²t 12.20 mA²s |
| `startup_ct_restart.cir` | ok, 92.7 s | `vout_avg_tail` 1.85052675606 V、`ipri_pk_restart` 14.0538311005 A、`oc_max_restart` 0.539260685444 V、`pre_at_9m` 0.99117732048 |

上表 12 个台架于 2026-10-31 12:29–12:31 整批重跑（`deck_runs_startup.json`），重跑后全部关键 `.meas`
与上一轮逐位相同——固定时间步长 + 同一求解器下结果可复现，因此上表数字可视为当前网表/模型哈希的结果。
两个 f10 台架的 `IPRI_AFTER` 窗口已从 4 ms 改为实际触发时刻 3.95 ms（另保留 `IPRI_AFTER_4M` 作旧窗口对照）：
峰值 73.18/64.98 A 取自 3.95 ms 起算，与 `fault_metrics_*.json` 的 `peak_primary_A` 一致。

已有的 `startup_ct_fault` / `startup_ct_fault_10m` 未重跑（日志晚于网表），但已用 `tools/fault_metrics.py`
从 raw 重新生成 `design/v2/fault_metrics_*.json`：51.25 µs/73.68 A/105.23 mA²s 与 283.31 µs/52.35 A/73.01 mA²s，
与报告一致；四个故障台（含两个 f10 变体）现在都有机器可读的 JSON。

换流台（`deck_runs_comm.json`）：36 个台架全部 `ok`，无错误标记，单台 0.56–4.30 s。
其中 5 类：器件台/理想对照/Roffset 台、6 个解析角、5 个负载点、11 个轻载门槛、5 个 di/dt 探针。
关键量复核：`sr_commutation_v3.log` 的 `qrev_c`/`ebd_c` 与报告一致（符号修正后为正值）。

此前从未跑过的 5 个换流台（`deck_runs_extra.json`，2026-10-31 12:37–12:47 整批）：

| 台架 | 状态 | 关键证据（`_cyc` 窗口，17–22 µs） |
|---|---|---|
| `comm_v3/sr_corner_25_0_2m.cir` | ok, 0.74 s | `irev_cyc` 1.5866 A、`qrev_cyc` 56.34 nC、`ebd_cyc` 4.795 µJ、`ech_cyc` 1.363 µJ、`ege_cyc` 0.617 µJ、`vds_max_cyc` 4.700 V |
| `comm_v3/sr_corner_probe_10_105m.cir` | ok, 0.69 s | `irev_cyc` 0.9211 A、`qrev_cyc` 42.51 nC、`ebd_cyc` 0.357 µJ、`ech_cyc` 0.214 µJ、`ege_cyc` 0.617 µJ、`vds_max_cyc` 4.400 V |
| `comm_v3/sr_corner_probe_40_0_18m.cir` | ok, 0.70 s | `irev_cyc` 2.1965 A、`qrev_cyc` 69.32 nC、`ebd_cyc` 4.306 µJ、`ech_cyc` 2.793 µJ、`ege_cyc` 0.618 µJ、`vds_max_cyc` 5.000 V |
| `comm_v3/sr_commutation_v3_roff_load.cir` | **TIMEOUT, 600.02 s** | 6 档扫描在 ILOAD=25 A / ROFF=120 Ω 档不收敛（已知，§4.3） |
| `comm_v3/sr_load_25_120.cir` | **TIMEOUT, 600.03 s** | 同上，单档版本；`raw` 增长到 ~100 MB 后超时 |

三个 ok 的角点均为**旧 6.7 nF 栅极口径**（见 §7 的作废声明）；它们的价值是“能跑通、量级合理”，
不能与 `sr_commutation_v3_g0_results.md` 的新数字混用。

时序参数角（`sim/v2/verify_param_bounds.cir`，ok 2.3 s，BON×BOFF 共 12 档）：

| 参数 | 预测 | 实测 | 差 |
|---|---|---|---|
| BON | 关断时刻 = max(VD 触发 4.62565 µs, Q 断言 4.164852 µs + BON) + TOFF | BON=400n → 4.645165 µs；475n → 4.663454 µs；700n → 4.888454 µs | <1 ns |
| BOFF | 重触发门极 = max(请求 5.21 µs, Q 下降 + BOFF) + TON | 550n/650n/750n → 5.3767/5.4815/5.5815 µs（BON=475n） | <1 ns |
| BOFF 上界 | 封锁条件：Q 下降 + BOFF + TON > 请求结束（5.71 µs） | BOFF=1 µs 三档全部 `g1r2` 无解（门极最高 3.3 mV）；BON=700n/BOFF=750n 亦被封锁 | 与预测一致 |

注意 typ 档的 BON 裕量很薄：VD 触发时 on-blank 年龄只有 465.1 ns，距 475 ns 只差 9.9 ns。

ARM 角与双路互锁（`sim/v2/verify_arm_bounds.cir` + 五个仲裁台架的 `_g0` 版本，共 11 个台架）：

| 台架 | 状态 | 关键证据 |
|---|---|---|
| `verify_arm_bounds.cir` | ok 0.6 s，16 档 | ARM 1.0/1.5/2.0/2.5 V 的 VD 穿越 4.97407/5.02807/5.08253/5.13707 µs，与 9.2 V/µs 斜坡的预测差 ≤0.35 ns；`off_t065−arm_t` 恒 650.71–650.72 ns（BOFF 650 + 步长）；`vd_at_g1` 16 档全为 −0.600 V；`ok_min` 全为 1 |
| `verify_t3_{interlock,simultaneous,skew,tie_exact,interlock_queue}.cir` | ok，各 0.2–1.0 s | 精确 tie 三次均判 CH1；50/5 ns 偏移均判先到者；被否决脉冲不入队；`overlap` 全 0；详见 `design/v2/sr_arm_interlock_results.md` §5 |
| 同上 `_g0` 版本（`sr_timing_v3_1.lib` + `CGATE=0 CPIN=100p`） | ok，各 0.2–1.0 s | 十条结论逐条保持；唯一变化是“栅极穿 2 V”统一早 11.63 ns（tie 台架 `g1_dly` 167.26 → 155.63 ns） |

真实谐振腔联合台（步骤 3，`design/v2/sr_tank_dual_results.md`）：

| 台架 | 状态 | 关键证据（450–500 µs，`tank_metrics.py` 8 周期平均） |
|---|---|---|
| `sim/v2/sr_tank_dual_v33.cir` | ok，97.7 s（与 v32 并发；单独运行约 85 s） | 周期 3.5156 µs（284.4 kHz）、Vout 1.6644 V、纹波 28.8 mV；QREV 316.5 nC、IREV_PK 5.135 A、QFWD 37.0 µC；EBD 1.289 µJ、ECH 1.045 µJ；QOVL 合计 446 nC 中 **ON 0**、OFF 112.5、MIXED 333.8；pair 4 与 pair 1 逐位相同 |
| `sim/v2/sr_tank_dual_v32.cir` | ok，99.2 s | 只换 `.include` 的对照：Vout 1.4752 V、EBD 10.860 µJ、ECH 0.786 µJ（沟道占 6.7%）、单管损耗 3.32 W（v33 为 0.664 W）、QREV 367 nC（194–832） |
| `sim/v2/sr_tank_dual_v2timing.cir` | ok，85.2 s | 与 v33 各量差 ≤0.4%（Vout 1.66437 vs 1.66436 V、QREV 317.7 vs 316.5 nC、QOVL_ON 0）；栅极导通时长稳定 1455 ns |
| `sim/v2/sr_tank_dual.cir` | ok，336.1 s（1.5 ms，v3_2） | **缺陷证据，不作稳态引用**：EBD 10.31 µJ、ECH 0.571 µJ（沟道占 5.2%）、周期 3.602–3.914 µs 拍频、QOVL_ON 0 |

### 4.3 诊断/失败/超时登记

| 文件 | 状态 | 原因 |
|---|---|---|
| `comm_v3/sr_commutation_v3_debug.cir` | ERROR（0.36 s） | `.include ../../../models/sr_timing_v3_bench.lib` 文件不存在；历史调试副本，PASS/FAIL 均无意义 |
| `comm_v3/sr_commutation_v3_debug1n.cir` | ERROR（0.36 s） | 同上 |
| `comm_v3/sr_commutation_v3_debug_orig.cir` | ok（0.74 s），DIAGNOSTIC | 修复前对照副本，不作证据 |
| `sr_commutation.cir`（v2 旧台） | ok（0.50 s），DIAGNOSTIC | 已被 comm_v3 取代 |
| `comm_v3/sr_commutation_v3_win15-20.log` | ORPHAN | 无同名 `.cir`（网表已删）；不作证据 |
| `comm_v3/sr_corner_10_0_18m.cir` | NOT_RUN | 解析角不收敛，见 §4.1 |
| `sr_timing_v3_checks_v2qrace_diag.cir` | NOT_RUN | 负对照，见 §4.1 |
| `comm_v3/sr_commutation_v3_roff_load.cir` | **TIMEOUT（600.02 s）** | 6 档 `ILOAD`/`ROFF` 扫描，第 5 档（25 A / 120 Ω）不收敛；前四档已完成。`run_decks.py` 以 600 s 上限截断并记为 TIMEOUT，不是静默失败 |
| `comm_v3/sr_load_25_120.cir` | **TIMEOUT（600.03 s）** | 上一条的单档版本，同一点不收敛；`.raw` 已增长到约 100 MB。属于已知的“轻载 + 大 Roffset”数值困难，不是台架判据失败 |

启动台无 TIMEOUT：最长 92.7 s，远低于 600 s 上限；`deck_runs_startup.json` 中 `timed_out` 全为 `false`。
两个换流台 TIMEOUT 由 `deck_runs_extra.json` 的 `timed_out: true` 显式记录。

### 4.1 明确不运行

| 台架 | 状态 | 原因 |
|---|---|---|
| `sim/v2/comm_v3/sr_corner_10_0_18m.cir` | NOT_RUN | 解析角，记录在案：120 s、67 MB raw 后不收敛；不要实跑 |
| `sim/v2/sr_timing_v3_checks_v2qrace_diag.cir` | NOT_RUN | 负对照，出现收敛失败才是预期结果（v2 缺陷演示） |

### 4.2 预期内的 `.meas` 失败

`sim/v2/verify_offblank_boundary.cir` 的 `g1r2`/`g1f2` 在 TD=4.7/4.8/4.9 µs 三档**必然**报
`Measurement failed`：这三档的再触发低电平在封锁到期前结束，门极本就不该再次上升。该失败是判据的一部分，
不是台架错误；有效档（TD=5.0/5.2/5.4 µs）必须测到门极上升。

## 5. 报告与清单的一致性

一致性核对不是“看起来一致”，而是逐项可执行：

1. 报告中的每个 16 位前缀都由 `tools/refresh_doc_hashes.py` 从磁盘现算，二次运行 0 行变化；
   2026-10-31 修复该脚本的一个绑定错误（哈希原先绑定“行内第一个可解析所有者”而不是**最近的前一个**，
   会把 `sr_timing_v3.lib` 的哈希改写成同行前面 `baseline_manifest.json` 的哈希）。修复后对
   `sr_commutation_v3_results.md`(82)、`sr_timing_v3_results.md`(17)、`task1_verification.md`(5)、
   `器件模型复核_电感默认电阻.md`(1) 共 105 个前缀复核，**0 行变化**——现有文档中的哈希与磁盘一致，
   该缺陷未在文档里留下错误值（只影响今后的自动刷新）；
2. 前缀与 `baseline_manifest.json` 的完整 SHA-256 前 16 位相同（§6 第 3 条）；
3. 启动台的报告数字逐一对应 `.log` 中的 `.meas` 名称（如 `ipri_pk`、`ict_pk`、`ocd_max`），
   不是人工抄录的中间量；
4. 跨台架“逐位一致”类主张必须由 `sim/v2/startup_ct_02` 与 `startup_ct` 的 raw 同窗口比对复核，
   不以两段日志各自的汇总值代替；
5. `tools/meas_table.py`（`ef71d7c0f7978d16`）修掉一个**静默**解析缺陷：单档日志的
   `tc1: V(d1)=-0.265  AT 4.009e-06` 与 `V(c2f) =0 at 5.9e-06` 两种行型里，“=”后是比较电平
   或采样时刻，旧实现把 −0.265、5.9 µs 当成了结果，且不报错。现在按四种行型分开取值，
   由 `tools/test_meas_table.py`（`4502b8f2c5366cbb`，5 例，`python -m pytest tools/test_meas_table.py -q`）
   锁住。扫描类日志走 `Measurement:` 块，不受影响——已发布的八档/12 档表格均取自该格式，
   未含此缺陷；受影响的只有本轮新读的五个仲裁台架，其数值已在修复后重读。

本次刷新涉及：`sr_commutation_v3_results.md` 33 行/82 个前缀，`sr_timing_v3_results.md` 17 个，
`task1_verification.md` 5 个。历史哈希（“当时为 …”“audit hash”）用不可见标记
`<!-- hash-owner: … -->` / `<!-- historical-hash -->` 固定，刷新脚本跳过它们并在有主时校验。

## 6. 复现命令

```bash
cd /d/workshop/design_48v-2v
python tools/run_decks.py --stale --timeout 600              # 只跑日志比网表旧的台架
python tools/make_baseline.py                                # 重新生成唯一基线清单
python tools/refresh_doc_hashes.py --dry-run design/v2/sr_commutation_v3_results.md

# 步骤 3 谐振腔台（各约 85 s，500 us 全瞬态）
cd sim/v2 && "D:/ADI/LTspice/LTspice.exe" -b sr_tank_dual_v33.cir && cd ../..
cd sim/v2 && "D:/ADI/LTspice/LTspice.exe" -b sr_tank_dual_v2timing.cir && cd ../..
python tools/tank_metrics.py sim/v2/sr_tank_dual_v33.raw --pair 1 --periods 8
python -m pytest tools/test_tank_metrics.py -q                # 13 例，离线积分口径

# 第三轮：支路账本 + 工作点（约 85 s / 90 s / 2-3 min；fine 台约 25 MB，1 ms 台约 105 MB）
cd sim/v2 && "D:/ADI/LTspice/LTspice.exe" -b sr_tank_dual_v33_internal.cir && cd ../..
cd sim/v2 && "D:/ADI/LTspice/LTspice.exe" -b sr_tank_dual_v33_ss_fine.cir && cd ../..
cd sim/v2 && "D:/ADI/LTspice/LTspice.exe" -b sr_tank_dual_v33_ss_1ms.cir && cd ../..
python tools/sr_energy_ledger.py sim/v2/sr_tank_dual_v33_internal.raw --periods 8 --json design/v2/round3_energy_ledger_284k.json
python tools/sr_energy_ledger.py sim/v2/sr_tank_dual_v33_ss_1ms.raw --periods 22 --t-offset-us 880 --json design/v2/round3_energy_ledger_ss.json
python tools/steady_state_check.py sim/v2/sr_tank_dual_v33_ss_1ms.raw --windows 6 --t-offset-us 880
python tools/round3_summary.py --snapshot sim/v2/sr_tank_dual_v33_internal.raw \
    --design sim/v2/sr_tank_dual_v33_ss_1ms.raw --design-deck sr_tank_dual_v33_ss_1ms.cir \
    --design-periods 22 --json design/v2/round3_summary.json
python -m pytest tools -q                                     # 31 例
python - <<'EOF'                                             # 报告前缀 vs 清单
import json
m = {e["path"]: e["sha256"][:16] for e in json.load(open("design/baseline/baseline_manifest.json"))["entries"]}
print(m["models/sr_timing_v3.lib"])
EOF
```

`run_decks.py` 先删除旧 `.log`/`.raw`，再在超时上限内运行；输出逐台 `ok`/`ERROR`/`TIMEOUT`，
任何“日志不存在 / 无 `Total elapsed time` / 有错误标记 / 超时”都会显式列出，不会被静默忽略。

## 7. 未闭环项（指回审核步骤 2 及以后）

步骤 2 已完成并归档的部分（证据在 `design/v2/gate_load_calibration.md` 与
`design/v2/sr_commutation_v3_g0_results.md`）：

- **6.7 nF 来历已结案**：它是理想开关台的栅荷替身；与 `SR_DEVICE` 配对时是重复计入。
  已参数化为 `sr_timing_v3_1.lib`，并在 `sr_commutation_v3_g0.cir` 以 `CGATE=0 CPIN=100p` 出八档基线。
- **1/2 ns 步长**：PGD=0 的两档延迟全部 ≤1.2 %；PGD=1 + 200 ns 延迟角的 QREV 达 3.05 %，已报告原因。
- **延迟增大负对照可检出**：EBD/IREV/QREV/门极重叠均有显著变化。
- **BON/BOFF 参数角**：`verify_param_bounds.cir` 12 档，关断时刻 = max(VD 触发, Q 断言+BON)+TOFF，
  重触发门极 = max(请求, Q 下降+BOFF)+TON，实测与预测差 <1 ns；BOFF=1 µs 时重触发被正确封锁。
- **ARM 阈值角**：`verify_arm_bounds.cir` 16 档（ARM 1.0–2.5 V × 4 个重触发时刻），阈值只平移
  消隐窗口（`off−arm` 恒 650.72 ns），16 档全部在 VDS=−0.6 V 时开栅、`ok` 全为 1；见
  `design/v2/sr_arm_interlock_results.md` §3。
- **双路互锁**：五个仲裁台架 × 两版模型共 10 个日志，精确 tie 恒判 CH1、skew 判先到者、
  被否决脉冲不入队、`overlap` 全 0；见同文 §5。

步骤 3 已完成并归档的部分（证据在 `design/v2/sr_tank_dual_results.md`）：

- **真实谐振腔双 SR 台架**：`sr_tank_dual_v33.cir` 在 450–500 µs 稳态窗口（8 周期平均）给出
  QREV 316.5 nC/周期/器件、IREV_PK 5.14 A、QFWD 37.0 µC、QOVL_ON **0**（按门状态拆分：
  合计 446 nC 中 112.5 nC 是死区续流、333.8 nC 是交接，没有导通重叠）、单管 SR 损耗 0.664 W。
- **0 Ω 基线（P1 的偏置决定）**：`Roffset=0`、`PGD=0`。实测 di/dt 0.0405–0.0764 A/ns（均值 0.051），
  QREV 只用掉 0.5% 损耗预算的 56%、IREV_PK 只用到 12.5 A 护栏的 41%，没有需要偏置弥补的缺口，
  因此 `sr_timing_v3_roff.lib` 不进基线，调试焊盘保留。
- **顺带发现的模型缺陷已修正**：`sr_timing_v3_2.lib` 的关断比较器把导通期的漏极振铃峰（±100 mV，
  ~44 MHz）当成反偏而锁存关断，栅极导通时长只有 524–1453 ns（均值 754 ns），而 v3_3 稳定在 1455 ns。
  同一 500 µs 台架、非注释行只差一行 `.include`：Vout 1.4752 vs 1.6648 V、沟道只承担 6.7% 的 SR
  能量（v3_3 为 44.8%）、单管损耗 3.32 vs 0.664 W（**5.0×**）、QREV 散布 ±72% vs ±0.09%。
  v3_2 原样保留作快照，`sr_timing_v3_3.lib` 恢复 v2 关断语义（v2 与 v3_3 各量差 ≤0.4%）。

仍未闭环：

- **驱动边沿与手册 23/35 ns 的矛盾**：8.7/3.1 Ω + 1.5/4 A 限流在 6.8 nF 上给 127.9/45.6 ns，
  两者数学上不可同时成立；在拿到手册测试条件前，所有时间量只是下界；
- **PGD 定律无标定来源**，且实测会推迟关断提交（EBD 6.5×），不得进入基线或整机；
- **ARM 与 BON/BOFF 的二维联合角未做**：两者各自单扫过，`BON` 典型值只剩 9.9 ns 裕量这一结论
  仍是在 ARM=1.5 V 下取得的；
- **PRE 在运行中被清除的路径、SECOND 交换的镜像台架**未做（同文 §7）；
- **旧 6.7 nF 口径的角点/轻载/门槛台未切换**：引用 `sr_commutation_v3_results.md` 的
  69.06 nC / 5.851 µJ / 9.362 µJ 时必须注明口径，或改用 g0 的新值；
- **谐振腔台只在 138.5 W**：负载 20 mΩ、83.2 A。200 W 点的 QREV 是外推值（≈0.46 µC），
  需把 `RL` 改为 12.6 mΩ 重跑一次才能进证据；
- **振铃幅度依赖估计的封装 Ld/Ls**：台架的 ~44 MHz 漏极振铃正是 v3_2 缺陷的触发条件，
  真实封装下是否同样触发未验证（不影响 v3_3，它不再对单次振铃响应）；
- 四组整机同版本模型 + 真实偏置/使能 + CT 快速故障链（步骤 4）；
- 器件/磁件/量产图收敛（步骤 5）；EasyEDA PCB、制造与低能量样机（步骤 6）。

本清单不改变上述任何结论，只把“当前到底跑的是哪一版、哪些跑过、哪些没跑”固定下来。
