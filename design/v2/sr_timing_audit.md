# SR_TIMING v2 审核：对 UCC24624 (SLUSD48C Rev.C) 的时序/状态机核对

日期 2026-10-31。范围：`models/sr_timing_v2.lib` 的时序与门控逻辑、`sim/v2/sr_good.cir`、`sr_bad_order.cir`、`sr_simultaneous.cir` 的验证能力。不含 SR 功率器件、磁件、REG 外部电路。**本文件只做审核与 v3 修正要求；未修改任何模型或 deck。**

## 0. 输入、哈希与运行环境

| 文件 | sha256（前 16 位） |
|---|---|
| models/sr_timing_v2.lib | 412e07a9256576d0 |
| sim/v2/sr_good.cir | 9dc2e199f578cd72 |
| sim/v2/sr_bad_order.cir | 7f191a07b782b370 |
| sim/v2/sr_simultaneous.cir | 6c829460745f3f21 |
| sim/v2/sr_commutation_sweep.cir | 645a6005e9f2a782 |
| deepseek/v2/model_review.md | b0e28833539e2fb6 |
| references/datasheets/ucc24624.txt | a081a7feb4cb89e0 |

运行：LTspice 26.0.2，`-b`，Normal solver，27 C。所有主 deck 的 .log 均含 `Total elapsed time`，无 `Error:` / `Time step too small` / `Singular matrix` / `Analysis failed`，`.meas` 均有数值。诊断 deck 的故意失败单独标注。

**结论摘要**

1. 标称门槛、155 ns 开通延时、475 ns on-blank、650 ns off-blank、1.5 V ARM、REG UVLO/预启动资格在标称点上成立；三个现有 deck 可复现（第 3 节）。
2. **P0**：双通道没有真正的“同时请求”仲裁。顶层靠 `BLOCK=req1` 这一条未写入文档的固定优先级补丁让 CH1 赢；把这条补丁去掉、只保留 `OTHER>0.5` 电平互锁，两路 Q 会同时停在 0.5，仿真在同时开通时刻直接不收敛（实测 1.1651 us，`Time step too small`，节点 `req1`）。`sr_simultaneous` 无法暴露该缺陷（实测 g2 恒为 0）。
3. **P0**：PGD 律未校准，且门驱上升沿 10-90% = 127.9 ns，是手册 23 ns typ / 40 ns max（6.8 nF）的 3.2-5.6 倍；现有反向电流/Qrev 数字只能当替身趋势，不能签核。
4. **P1 缺项**：155/275 ns 自适应延时、275 ns tMGPU + 200 uA 保持、VSS 330 uA 偏置、standby、-35/-100 mV 两级比例门驱、UVLO 2 V 强/弱下拉、各门槛的 min/max 角。
5. DeepSeek 六条：1 条 CONFIRMED（PGD），2 条 PARTIAL（互锁、PRE 窗口），3 条 WRONG（blanking 起点、off 计时、短脉冲）。错因是把模型中 `I=V(node)`（1 ns 快速复位）误读成“保持”。

---

## 1. 手册要求的 SR 行为（逐条引用）

| # | 行为 | 数值（typ，min/max） | 出处 |
|---|---|---|---|
| 1 | 开通门槛 VTHVGON，VD 下降穿越 | -265 mV（-435 / -160） | p6 §7.5 |
| 2 | 关断门槛 VTHVGOFF，VD 上升穿越 | +10.5 mV（2 / 18） | p6 §7.5 |
| 3 | VSS 偏置电流，外接 Roffset 抬高关断门槛 | 330 uA（260/400）；VTHOFF_eff = 10.5 mV + 330 uA*Roffset；建议 <70 mV、Roffset<212 ohm | p16 §8.3.3，Eq.2，Figure 8-6 |
| 4 | 开通传播延时 tdVGON | 155 ns（110 / 225） | p7 §7.6 |
| 5 | 自适应开通延时：轻载/burst/短导通时 155→275 ns | 275 ns；另一通道随后开通则复位到 155 ns；VDS 在导通中点 < -40 mV 连续 8 周期复位 | p18 §8.3.4.5 |
| 6 | On-time blanking tONMIN：开通后 475 ns 内无论 VDS 都保持导通 | 475 ns（325 / 625） | p17 §8.3.4.1；p7 §7.6 |
| 7 | Off-time blanking tOFFMIN：关断后且 VD 升过 1.5 V 起 650 ns 内禁止再开通 | 650 ns（440 / 855） | p17 §8.3.4.2；p7 §7.6 |
| 8 | 再武装 ARM：每个周期只有在 VD 升过 1.5 V 后、TOFFMIN 到期才 armed | VTHARM = 1.5 V（1.4 / 1.7） | p18 §8.3.4.4；p6 §7.5 |
| 9 | 预启动资格：REG 升过 VREGON 之前，VD1 或 VD2 必须已升过 VTHARM | 条件性要求，违反则“不能保证正常开关” | p3 Pin 3；p20 §8.4.3；p13 Figure 8-2 |
| 10 | REG UVLO | VREGON 4.5 V（4.1/4.8），VREGOFF 4.0 V（3.63/4.25），迟滞 0.5 V | p6 §7.5 |
| 11 | REG 稳压/门驱钳位 | VREG 11 V（9.9/11.9）；VG 高钳位 10.9 V（9.95/11.68） | p6 §7.5；p19 §8.3.5 |
| 12 | 门驱能力 | 源 1.5 A（0.9/2.4），灌 4 A（2.6/6.7）；RVG_PU 6.5 ohm（3.5/11.25），RVG_PD 0.9 ohm（0.2/1.5）；tr 23 ns（13/40），tf 35 ns（19/40）@6.8 nF | p6 §7.5；p7 §7.6 |
| 13 | tMGPU：前 275 ns 全驱动，之后约 200 uA 弱保持 | 275 ns（180/370） | p15 §8.3.2；p7 §7.6 |
| 14 | 比例门驱：VDS 调到 -35 mV（VTHPGD_LO），按上一周期导通时间的前半段禁用；到上一个周期 90% 仍未达 -35 mV 则强制 -100 mV（VTHPGD_HI） | -35 mV（-80/0）；-100 mV（-165/-40） | p15 §8.3.2；p6 §7.5 |
| 15 | 双通道互锁：一路开通阻止另一路开通（“gate prohibited by interlock”） | 无数值 | p18 §8.3.4.3；p17 Figure 8-7 |
| 16 | 关断传播延时 tdVGOFF | 23 ns（5.5 / 40） | p7 §7.6 |
| 17 | Standby：CH1 平均频率 <9 kHz 持续 7.5 ms 进入；>15.6 kHz 持续 7.5 ms 退出；退出后忽略首个 SR 周期 | 9 kHz（6.55/12.2）；15.6 kHz（11.5/21）；7.5 ms（5.5/10） | p20 §8.3.6、§8.4.2；p7 §7.6 |
| 18 | UVLO 下 VG 下拉：REG>2 V 强下拉，REG<2 V 弱下拉 | 无数值 | p20 §8.4.1 |

---

## 2. DeepSeek `model_review.md` 逐条核对

行号指 `models/sr_timing_v2.lib` 经 `tr -d '\r' | nl -ba` 后的 1-38 行。

### 2.1 先说明一个根因：`I=V(node)` 是复位，不是保持

该库用 1 nF 电容 + B 电流源做模拟锁存/计时。对 `Bxxx n+ n- I=...`，正电流从 n+ 流出，`dV(n+)/dt = -I/C`。因此：

- `I = -(1-x)` → x 在 ~1 ns 内升到 1（置位）；
- `I = +V(x)` → x 在 ~1 ns 内降到 0（**复位**）；
- `I = 0` → 保持。

`Bpre` L8 的 `V(PRE,S)`、`Buv` L11 的 `-V(uv)*(-1)`、`Ba` L18 的 `V(armstate,S)`、`Btarm` L22 的 `V(tarm,S)`、`Bton` L25 的 `V(ton,S)`、`Bage` L27 的 `V(age,S)`、`Btoff` L29 的两个 `V(toff,S)`，全部是复位分支。DeepSeek 把前三处读成“保持/累加”，这是它三条 WRONG 的共同原因。

### 2.2 逐条判定

#### 发现 1：blanking 起点与“新 D 下穿不重置” —— **WRONG**

原文：“tarm 在 armstate 为低时持续累加……blanking 实际是‘最后一次 ARM 事件后固定等待’，新一次 D 下穿 ONTH 并不会重置 blanking……第二个脉冲的 blanking 被前一个脉冲吃掉一部分。”

- 机制读反：L22 `Btarm` 在 `armstate>0.5` 时 `I=-1m`（计时上升），在 `armstate<0.5` 时 `I=V(tarm)`（复位到 0）。所以 tarm 是“D 升过 1.5 V 后”的计时，门极一开就复位；不是“armstate 低时累加”。
- “以最后一次 ARM 事件为锚、新 D 下穿不重置”正是手册 §8.3.4.4 的要求：“armed ... only at off-time blanking TOFFMIN expiring after the VD pin voltage rises 1.5 V above the VSS pin”。不是缺陷。
- 实测（诊断 deck `t5_offblank.cir`，SR_CH 单通道，OK=1）：D 在 1.71 us 升过 1.5 V（ARM），1.86 us 再次下穿 -265 mV；门极第二次升到 2 V 在 **2.5433 us**，即从 1.86 us 起等了 683 ns，正好是 ARM(1.71)+650 ns+155 ns 再叠加门驱上升。若按 DeepSeek 的“每次 D 下穿重新计 650 ns”，门极应在约 2.69 us（2.665 us 加门驱上升）才到 2 V；实测不是。

判定：**WRONG**。唯一的真实点（新 D 下穿不重置）是手册规定行为。

#### 发现 2：off 计时由 `age>BON` 门控 —— **WRONG**

原文：“Btoff 用 age（Q 低电平持续时间）……age>BON 才允许 off 计时……存在 Q=1 期间 D 超 OFFTH 但不计时的盲区。”

- L27 `Bage`：`if(Q>0.5, 计时, V(age))`。Q 高时 age 从 0 开始累加，Q 低时复位。所以 **age 是“已开通时间”，不是“Q 低电平时间”**。
- L29 `Btoff`：`D>OFFTH` 且 `age>BON` 才计时；这正是手册 §8.3.4.1 的 475 ns on-blank：“During the on-time blanking time, the SR keeps conducting regardless of its drain to source voltage.” 所谓“盲区”就是 on-blank，是要求，不是缺陷。
- 实测（`t4_onblank.cir`）：D 在 **1.3056 us** 升过 +10.5 mV，门极到 2 V 的下降在 **1.6989 us**，即在门槛穿越后又保持了 **393.3 ns**；Q 在 1.1651 us 开通，on-blank 到 1.6401 us，再加 23 ns 延时与门驱下降，1.6989 us 与预期一致。若没有 on-blank，门极会在 ~1.36 us 就降到 2 V。

判定：**WRONG**。计时起点应是“开通”，模型确实如此；这不是被 BON 推迟的 TOFF，而是手册的 on-blank。

#### 发现 3：互锁为电平型、同时请求可双置位 —— **PARTIAL**

原文：“Bq 中 OTHER>0.5 时强制 Q 放电……两路 Q 同时从 0 上升时彼此都看不到对方 >0.5……可能同时置位……无先到先得仲裁。”

- 对 `SR_CH` 本身（L31）成立：互锁只是 `OTHER>0.5` 放电，是电平型，没有交叉耦合的“谁先谁赢”锁存。
- 但对实际顶层 `SR_TIMING` 不成立：L13/L14 把 X1 的 BLOCK 接 S(0)、X2 的 BLOCK 接 `req1`。于是 req1 为高时 req2 被强制 0，同时请求在进入 Q 竞争之前就被 CH1 拿走。实测 `sr_simultaneous`：g1_max=10.8904 V，**g2 恒为 0**（raw 解析），Q1 到 1；该 raw 未保存 q2，不能据此断言 q2=0。
- 该“保护”是未写入文档的固定优先级补丁，不是仲裁器。把 BLOCK 去掉、只留 Q 电平互锁（诊断 deck `t1_qrace.cir`，未改 lib，直接例化两个 `SR_CH`，BLOCK=0）：两路 D 完全相同，ton1=ton2=0.155742，q1=q2 同时停在 **0.5**，门极均为 0，仿真在 **1.1651 us** 报 `Convergence Failure: Time step too small ... trouble with node "req1"`。也就是说，最坏情况不是“双开通”，而是“两路都到 0.5、谁都不导通且求解失败”。
- 若两路请求有 1 ns 级偏斜，先到者 Q 先过 0.5，后到者被 `OTHER>0.5` 拉回，能出单路；但余量只有一个 1 ns tau。真实硅片不应依赖这个。

判定：**PARTIAL**。机制描述基本对，但“可能同时置位”在本 netlist 中被 BLOCK 掩盖；真正的缺陷是“没有仲裁器、同时性由未文档化的固定优先级和 1 ns 模拟竞争决定”，并且去掉补丁后不收敛。

#### 发现 4：短脉冲被“吞掉”而非滤除 —— **WRONG**

原文：“短脉冲若 D 在 TON 内回升到 OFFTH 以上，toff 因 age 未过 BON 不启动，Q 保持——短脉冲被‘吞掉’而非滤除，行为偏向保持导通。”

- 若 D 在 155 ns 内回升到 -265 mV 以上，L23 `req` 立刻变 0，L25 `ton` 复位，不会开通：这是滤除。实测 `sr_good` 中 8.01-8.1 us 的 90 ns 负脉冲没有产生任何门极脉冲（g1 只有一个脉冲，见第 8 节）。
- 若 D 保持负超过 155 ns，SR 正常开通；此后即使 D 在 475 ns 内回升，on-blank 强制保持到 475 ns。这是手册 §8.3.4.1 的原文要求，不是“吞掉”。
- 唯一可讨论的是 on-blank 的参考点：模型从 Q>0.5（1.1651 us）起算，门极 10% 在 1.1712 us、90% 在 1.2991 us。相对 10% 只差 6.1 ns；相对 90% 差 134 ns。手册说“after the SR is turned on”，未定义是命令还是 VG 90%，v3 需明确并固定。

判定：**WRONG**。滤除与保持都符合手册。

#### 发现 5：REG 先升时 PRE 可能漏判 —— **PARTIAL**

原文：“Buv 在 REG>4.5 置位、REG<4 复位；Bok 需 PRE>0.5 且 uv>0.5……若 REG 快速穿过 1~4.5 区间，PRE 可能来不及置位。”

- L11 的 UVLO 描述基本对（4.5/4.0 是 typ；无 4.1/3.63 角）。
- L8 的 PRE 窗口是 REG 在 (1, 4.5) 且 max(D1,D2)>1.5 时置位，REG<1 时 `I=V(PRE)` 是**复位**，不是 DeepSeek 说的“保持”。
- “快速穿过 1~4.5”在手册配置下不成立：REG 由 11 V LDO 从 VDD 供电，IREGLIM typ 60 mA（min 41/max 95），CREG=2.2 uF，斜率 = 60m/2.2u = **27.27 V/ms**（18.6~43.2 V/ms）。1→4.5 V 需要 **128 us**（81~188 us）；1→4.1 V 需要 114 us。1 ns tau 的锁存不可能漏。即使 VDD 走 pass-through，2.2 uF 也把边沿拉到百 us 量级。
- 真正的边界错误：(i) 上边界用 4.5 V typ，而手册保证的最早 VREGON 是 **4.1 V**；0.4 V 在 27.27 V/ms 下是 **14.7 us** 的“假接受”窗口，真实 4.1 V 片子已经使能，模型仍允许 ARM。(ii) 下边界 1 V 无手册依据；有效 VD>1.5 事件若落在 REG<1 V（上电最初约 36.7 us），模型丢弃，而手册只要求“在 VREGON 之前”。(iii) PRE 是永久锁存，强于手册的“不能保证正常开关”，项目中已按此保守处理，但应标注为假设。
- `sr_bad_order` 实测：REG PWL (0,0)(0.1u,0)(0.2u,11)；REG 在 **0.1409 us** 越过 4.5 V（1→4.5 窗口 31.8 ns），D1 到 **1.0038 us** 才越过 1.5 V，晚了 863 ns；PRE 终值 0，g1/g2 均 0。这是合法的“偏置先于漏极事件”负例，但它没有测试“D 已经 >1.5、REG 快速穿过窗口”的竞争，因为窗口内 D=0。

判定：**PARTIAL**。快速斜坡漏判在物理上不成立；真实问题是 4.5 vs 4.1 的边界和 1 V 地板。

#### 发现 6：PGD 未校准 —— **CONFIRMED**

原文：“PGD=1 用 `limit(3+(-V(D)-.035)*80,2.6,10.9)` 平滑律，斜率 80、偏置 0.035 均无数据支撑。”

- L33 确为 `limit(3+(-D-0.035)*80, 2.6, 10.9)`：D=-35 mV 时 3 V，D=-100 mV 时 8.2 V，D=0 时钳到 2.6 V。手册要求的是把 VDS 调节到 -35 mV（VTHPGD_LO）或 -100 mV（VTHPGD_HI），门压从 11 V 降到接近 MOS Vth；并且前半个导通时间按上一周期导通时间禁用比例门驱、到 90% 未达 -35 mV 才强制 -100 mV。这些一个都没有。
- 追加：(i) PGD=0 也没有 275 ns tMGPU 后的 200 uA 弱保持；(ii) 门驱等效为 8.7 ohm 源/3.1 ohm 灌的纯 RC，1.5 A/4 A 限流在 6.7 nF 下根本达不到（0 V 时 (10.9-0)/8.7=1.25 A；(10.9)/3.1=3.5 A）；(iii) 实测 tr(10-90%)=**127.9 ns**，tf(90-10%)=**45.6 ns**，手册 @6.8 nF 为 23/35 ns typ、40/40 ns max。开通沿慢 3.2~5.6 倍，使 SR 沟道建立晚约 105 ns（相对 23 ns typ），直接改变反向电流与 Qrev。
- 因此项目文件里“23 ns PGD0 超 0.5% 预算 1.10x、40 ns 超 1.30x”的结论只能作为替身趋势；在门驱沿与 PGD 律校准前不能用于芯片选择或签核。

判定：**CONFIRMED**，并扩大为“PGD 律 + 门驱边沿”两项。

---

## 3. 重点问题 (a)-(e)

### (a) 同时请求是否会双置位

分三层：

1. **本 netlist 的顶层**：不会双置位，但也不是仲裁的结果。L14 把 CH2 的 BLOCK 接到 `req1`，只要 req1 为高，req2 恒 0；两路 D 完全相同时 CH1 无条件先拿到请求。实测 `sr_simultaneous`：g1_max=10.8904 V，g2_max=0，Q1 到 1；该 raw 未保存 q2，不能据此断言 q2=0。这个“通过”是构造出来的。
2. **只有 Q 电平互锁时**（诊断 `t1_qrace.cir`，BLOCK=0）：两路 ton 完全相同（0.155742），q1、q2 同时升到 **0.5**，drv 均为 0，门极均为 0，仿真在 **1.1651 us** 不收敛（`Time step too small`，节点 `req1`）。这是代数环在对称点无唯一解：req 是理想电压源，依赖 OTHER(Q)，Q 又依赖 req。
3. **有微小偏斜时**：先到者 Q 先过 0.5，后到者被 `OTHER>0.5` 拉回；能出单路，但余量是 1 ns tau，且没有“先到先得”的状态位。

结论：`OTHER>0.5` 电平互锁本身不足以仲裁；当前靠固定优先级补丁避免，属于未文档化行为。v3 必须用显式仲裁状态机（见第 6 节 P0-1）。

### (b) off 计时由 `age>BON` 而不是 ARM 事件

- 这是**对的**：`age` 是开通时间，`age>BON` 就是 475 ns on-blank；手册要求 on-blank 内不管 VDS 都保持导通。
- 650 ns off-blank 由 `tarm>BOFF` 实现，锚在 ARM（VD>1.5）事件，不是 `age`。
- 实测 `t4_onblank`：D 在 1.3056 us 越过 +10.5 mV，门极 2 V 下降到 1.6989 us，保持 393.3 ns，符合 475 ns on-blank。
- 唯一需在 v3 明确的是 on-blank 的参考点（Q 命令 / VG 10% / VG 90%）。当前从 Q 起算，相对 VG 10% 早 6.1 ns，相对 VG 90% 早 134 ns。建议以“门极命令 + 校准的 tdVGON”或 VG 10% 为准，并在文档中固定。

### (c) blanking 不被新的 D 下穿复位

- 这是**手册要求**：§8.3.4.2/§8.3.4.4 明确 650 ns 从“关断后 VD 升过 1.5 V”起算，不是从每次 D 下穿 -265 mV 起算。模型 L22 正是这样。
- 实测 `t5_offblank`：ARM 1.71 us，第二次 D 下穿 1.86 us，门极 2 V 上升 2.5433 us；从 D 下穿算是 683 ns，从 ARM 算是 833 ns（650+155+门驱）。若每次 D 下穿重置，会在 ~2.69 us 才开，实测不是。
- 结论：不是缺陷；DeepSeek 发现 1 的核心指控不成立。

### (d) REG 快速穿过 1~4.5 V 时的 PRE 窗口

- 物理上不可能“快”：CREG=2.2 uF、IREGLIM typ 60 mA → 27.27 V/ms；1→4.5 V 需 128 us（min 电流 41 mA 时 188 us，max 95 mA 时 81 us）。1 ns 的 PRE 锁存有充分时间。
- 真正的窗口边界问题：
  - 上边界 4.5 V（typ）应为 **VREGON(min)=4.1 V**；0.4 V / 27.27 V/ms = **14.7 us** 的假接受。
  - 下边界 1 V 无依据；0→1 V 约 36.7 us，此间的有效 VD>1.5 事件被丢弃。
  - PRE 是永久锁存；手册只说违例后“不能保证正常开关”，不是必然锁死。项目已按保守处理，v3 应保留“violation flag”但允许重新上电复位。
- `sr_bad_order` 只验证了“REG 先到 11 V、D 后来才动”的永久禁止，没有覆盖 D 已高、REG 快速穿过窗口的竞争。

### (e) `sr_simultaneous` 能否暴露 (a)

**不能。** 五个原因：

1. `Ed2 d2 0 d1 0 1` 把 D2 做成 D1 的 1:1 拷贝，两路激励在求解器里完全相同；真实同时请求应是独立边沿。
2. L14 的 `BLOCK=req1` 让 CH2 在 CH1 请求期间根本无法提出请求；同时性在进入 Q 竞争前已被消除。
3. 实测只有 CH1 动作：g1_max=10.8904 V，g2_max=0；该 raw 未保存 q2，无法区分 q2=0 与 q2 被 BLOCK/OTHER 压住。
4. `.meas` 只测 `gate_max MAX V(g1)` 和 `pre_final`，没有测 g2、没有测 `min(g1,g2)` 重叠、没有测 Q1/Q2 同时性；即使 g2 异常，log 也不会报。
5. 没有反向顺序（D2 先）、没有 1/5/50 ns 偏斜、没有“赢家导通期间输家请求”的用例，也没有负对照（故意去掉仲裁应失败）。

因此该 deck 的“未见 >2 V 门极重叠”是空结论；它不能区分“正确仲裁”与“CH2 被结构性禁用”。

---

## 4. 审核新增、DeepSeek 未列的缺陷

| # | 缺陷 | 证据/影响 |
|---|---|---|
| A1 | 无 VSS 330 uA 偏置电流源；外接 Roffset 在模型里不产生任何门槛偏移 | L6/L16 无 330u 源；手册 p16 §8.3.3。当前“Roffset=0”结论无法用模型验证非零值 |
| A2 | 无 standby（9/15.6 kHz、7.5 ms、退出忽略首周期） | L1-38 无频率检测；手册 p20 §8.3.6 |
| A3 | 无 155/275 ns 自适应；TON 只是固定参数 | L6/L24-25；手册 p18 §8.3.4.5 |
| A4 | 无 275 ns tMGPU + 200 uA 弱保持 | L33/L35；手册 p15 §8.3.2 |
| A5 | 无 -35/-100 mV 两级比例门驱、无前半小时禁用、无 90% 强制 | L33；手册 p15 |
| A6 | 门驱 tr/tf 与手册不符：127.9/45.6 ns vs 23/35 typ、40/40 max | 实测 t4/t5 raw；L35/L37。反向电流与 Qrev 的主要不确定项 |
| A7 | 1.5 A/4 A 限流在 6.7 nF 下从未触发；等效为 8.7/3.1 ohm 纯 RC | L35；0 V 时 1.25 A，10.9 V 时 3.5 A |
| A8 | UVLO 的 REG>2 V 强下拉 / <2 V 弱下拉未建模；Bdrive 始终 3.1 ohm 强下拉 | L35；手册 p20 §8.4.1 |
| A9 | 默认值为 typ；ONTH/OFFTH/ARM/TON 可参数覆盖，但 VREGON 4.5 / VREGOFF 4.0 与 PRE 的 1 V / 4.5 V 边界硬编码，且无角组合 | L6/L8/L11；手册 p6 的 min/max 列 |
| A10 | VREGON 上边界用 4.5 而非 4.1；PRE 1 V 地板无依据 | L8/L11；见 3(d) |
| A11 | 参数命名混淆：`TOFF=23n` 是关断传播延时，`BOFF=650n` 才是 off-blank | L6；易在 deck 中传错 |
| A12 | req 为理想电压源，与 Q 形成代数环；对称点不收敛 | 实测 t1_qrace 1.1651 us 失败 |
| A13 | 互锁强制关断已导通通道，手册只说“阻止开通”；无最小导通保持/故障标志 | L31；手册 p17 Figure 8-7、p18 §8.3.4.3 |
| A14 | 手册门驱参数彼此不自洽：6.8 nF 全摆幅约 74 nC，硬 1.5 A 源需 49 ns，而 tr=23 ns 对应约 2.6 A 平均（高于 IVGSOURCE max 2.4 A）。v3 不能同时硬编码 1.5 A 与 23 ns | p6 §7.5（IVGSOURCE 0.9/1.5/2.4 A；tr 13/23/40 ns @6.8 nF）；计算 74 nC/23 ns |

---

## 5. 模型 vs 手册真值表

### 5.1 功能真值表

| 项目 | 手册 | v2 实现 | 判定 |
|---|---|---|---|
| VTHVGON -265 mV | p6 | L23 `D<ONTH`，L6 默认 -0.265 | 标称一致，无角 |
| VTHVGOFF +10.5 mV | p6 | L29 `D>OFFTH` | 标称一致，无 2/18 mV 角 |
| VSS 330 uA 偏置 | p16 | 无 | 缺 |
| tdVGON 155 ns | p7 | L24-25，TON | 标称一致（实测 D 到 Q 155.8 ns） |
| 155→275 ns 自适应 | p18 | 无 | 缺 |
| tONMIN 475 ns | p17 | L26-27 `age>BON` | 一致（Q 高 498.5 ns = 475 ns on-blank + 23.5 ns 延时；D 过门槛后门极再保持 393 ns 至 2 V） |
| tOFFMIN 650 ns | p17 | L21-22 `tarm>BOFF`，锚 ARM | 一致（ARM 1.71 us 到 VG 2 V 2.543 us，833 ns = 650+155+门驱；D 下穿后 683 ns） |
| VTHARM 1.5 V | p6/p18 | L18，L6 | 标称一致 |
| 预启动资格 | p3/p20 | L7-9 + L12 | 部分：4.5 vs 4.1，1 V 地板，永久锁存 |
| VREGON/VREGOFF | p6 | L11 4.5/4.0 | typ 一致，无角 |
| 互锁 | p18 | L23 + L31 + L14 | 部分：无仲裁，固定优先级补丁，强制关断 |
| Standby | p20 | 无 | 缺 |
| tMGPU 275 ns / 200 uA | p15 | 无 | 缺 |
| PGD -35/-100 mV | p15 | L33 经验律 | 错 |
| 门驱 1.5 A/4 A、6.5/0.9 ohm | p6 | L35 | 部分：限流不触发，tr 127.9 ns |
| VG 10.9 V 钳位 | p6 | L33 min(10.9,REG) | 一致 |
| tdVGOFF 23 ns | p7 | L28-29 | 标称一致（on-blank 到期 1.6401 us 到 Q 下降 1.6636 us 为 23.5 ns；VG 90% 再迟 2.3 ns） |
| UVLO 2 V 下拉强度 | p20 | L35 恒强 | 缺 |
| 退出 standby 忽略首周期 | p20 | 无 | 缺 |

### 5.2 仲裁真值表（v3 必须满足；v2 实测）

| req1 | req2 | q1 | q2 | v3 要求 | v2 顶层 | v2 仅 Q 互锁 |
|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 保持 | 保持 | 保持 |
| 1 | 0 | 0 | 0 | TON1 后 q1=1 | 是 | 是 |
| 0 | 1 | 0 | 0 | TON2 后 q2=1 | 是 | 是 |
| 1 | 1 | 0 | 0 | 恰好一个赢，优先级有定义 | CH1 赢（靠 BLOCK） | **两路 0.5，求解失败** |
| 1 | 1 | 0 | 1 | q1 被阻止，q2 保持 | 是 | 是 |
| 1 | 1 | 1 | 0 | q2 被阻止，q1 保持 | 是 | 是 |
| 1 | 1 | 1 | 1 | 禁止；强制双关 + fault | 未建模 | 未建模 |

---

## 6. v3 修正清单（保留引脚 D1 D2 G1 G2 REG S PRE）

### P0（不做就不能用于换流/反向电流判定）

**P0-1 仲裁状态机，替换 `OTHER>0.5` 电平互锁 + `BLOCK=req1`**

每通道一个数字状态：`UVLO / WAIT_ARM / IDLE / TON_DLY / ON_BLANK / ON / OFF_BLANK / FAULT`。显式锁存，不用 1 ns 模拟节点。

```
arm_ch   = (vd_ch > VTHARM) and (vg_other == 0)          // 上升沿事件，锁存
offok_ch = (t - t_arm_ch) >= T_OFFBLANK                  // 650n，锚 ARM 事件
req_ch   = (vd_ch < VTHON) and (state_ch == IDLE) and offok_ch
           and ok and (vg_other == 0) and !fault
grant1   = req1 and !q2 and !lock2
grant2   = req2 and !q1 and !lock1
// 同一求解步 req1 & req2：固定优先级 CH1（写入文档），或先到先得 + 1 个最小分辨时间
// lock1 在 CH1 赢时置位，CH1 关断并过 OFF_BLANK 后清零；lock2 对称
on grant_ch: state=TON_DLY; t_req=t; delay=next_delay_ch
TON_DLY 到期且 req_ch 仍真且 grant_ch: state=ON_BLANK; t_on=t; vg=drive
ON_BLANK:  vg 强制高，忽略 vd，直到 t_on + T_ONBLANK (475n)
ON:        if vd > VTHOFF_eff: state=OFF_BLANK; vg 在 T_VGOFF (23n) 后拉低; t_off=t
OFF_BLANK: 等 (vd > VTHARM) 且 (t - t_arm) >= 650n，然后 IDLE
if q1 and q2: fault=1; 双关; 记录（正常不可达）
```

`req` 不要再用理想电压源直接驱动 Q；用状态位 + 带滞回的比较器/开关，避免 A12 的代数环。v3 的 `sr_simultaneous` 必须同时保存 q1、q2、g1、g2 并测 `min(g1,g2)`。

**P0-2 门驱边沿与 PGD 校准**

- 门驱必须复现 tr=23 ns typ / 40 ns max、tf=35 ns typ / 40 ns max（6.8 nF），而不是 8.7 ohm/3.1 ohm 纯 RC 的 127.9/45.6 ns。注意 A14：6.8 nF 全摆幅约 74 nC，硬 1.5 A 源需 49 ns，23 ns 对应约 2.6 A 平均；不能同时硬编码 1.5 A 限流和 23 ns tr。v3 应以 tr/tf 为主约束，用分段电流源/受控电阻拟合（把拟合出的隐含电流写进模型注释），先用 6.8 nF 负载单独校 tr/tf，再接入 `sr_device_v3.lib` 的非线性 Ciss/Crss；灌沿 4 A/0.9 ohm 同样按 tf 校。
- PGD 律替换为手册两级调节：
  ```
  if t < t_on + 275n: vg = full drive (1.5 A), then 200 uA hold
  pgd_enable = (t - t_on) > 0.5 * T_on_prev
  target = (vd not < -35m by 0.9*T_on_prev) ? -100m : -35m
  loop: adjust vg (11 V ... Vth) so vd -> target
  ```
  比例门驱的“执行器”是 `sr_device_v3.lib` 的 VGS→Rds(on) 曲线；时序模型只输出 VG，不再用固定 Ron 开关。
- 校准判据：6.8 nF 下 tr/tf 在手册 max 内；VDS 在 -35 mV 附近闭环，且在强制模式下到 -100 mV。

**P0-3 475/650/155/23 ns 的参考点固定**

- 475 ns 从“门极开通命令 + 校准的 tdVGON”或 VG 10% 起算，文档二选一；当前从 Q 起算，相对 VG 90% 早 134 ns。
- 650 ns 从 VD 上升穿越 1.5 V 的**边沿**起算（当前是电平锁存，等效但应在文档中写清）。
- 23 ns 是 D 穿越 +10.5 mV 到 VG 开始下降的延时，逐周期有效；当前 `Btoff` 在 `D<=OFFTH` 或 `age<=BON` 时复位，行为正确，但用边沿检测更稳。

### P1（签核前必须有）

**P1-1 自适应 155/275 ns**：按 §8.3.4.5 实现两条规则（burst 检测 + 短导通检测），状态位 `next_delay_ch`，复位条件“另一通道随后开通”和“中点 VDS<-40 mV 连续 8 周期”。

**P1-2 VSS 330 uA 偏置**：在 S 引脚加 330 uA 流出源，`VTHOFF_eff = 10.5m + 330u*Roffset`；保留 S 引脚，外部 Roffset 0/100/212 ohm 可扫；按手册 <70 mV 建议钳位。

**P1-3 Standby**：CH1 平均频率计数，7.5 ms 窗口；<9 kHz 进，>15.6 kHz 出；退出忽略首个 SR 周期；standby 下 VG 主动拉低。

**P1-4 UVLO/门槛角**：参数化 VREGON 4.1/4.5/4.8、VREGOFF 3.63/4.0/4.25、VTHARM 1.4/1.5/1.7、VTHVGON -435/-265/-160 mV、VTHVGOFF 2/10.5/18 mV；预启动资格用 **VREGON(min)=4.1**，去掉 1 V 地板（用 REG<2 V 的 UVLO 下拉阈值作下限，或直接 0）。

**P1-5 UVLO 2 V 下拉强度**：REG>2 V 强下拉，<2 V 弱下拉；standby/UVLO 下都要主动拉低。

### P2（文档/接口清理）

- 参数改名：`TD_VGON=155n`、`TD_VGON_BURST=275n`、`T_ONBLANK=475n`、`T_OFFBLANK=650n`、`TD_VGOFF=23n`、`T_MGPU=275n`，避免 `TOFF`/`BOFF` 混淆。
- 互锁的“强制关断”标注为工程附加保护，不是芯片行为；若保留，加 fault 标志和最小导通保持。
- 保留 `PRE` 引脚作为“预启动资格已满足”的状态输出；v3 内部仍要区分“violation”（REG 先过 4.1 而无 ARM）与“not yet armed”。
- 明确 REG 是外部引脚还是内部 LDO；若保留外部，文档给出 2.2 uF + 60 mA 的斜率范围（27.27 V/ms typ）。

---

## 7. v3 必须通过的最小测试用例

所有用例都要同时保存 q1/q2/g1/g2，并在 .log 里对每个通道和重叠量做 .meas；仅测 g1 不算通过。

| ID | 激励 | 通过判据 | 对应 v2 证据 |
|---|---|---|---|
| S1 | D1=D2 完全相同，同时下穿 -265 mV；10 个周期 | 恰好一个门极 >10 V，另一个 <0.5 V；q1/q2 不同时 >0.5；无求解失败；重复 10 周期一致 | v2 顶层 g2=0 靠 BLOCK；仅 Q 互锁在 1.1651 us 失败 |
| S2 | S1 加偏斜 0/1/5/50 ns，两个方向各一次 | 先请求者赢；无重叠；输家 ton 复位；无 chatter | v2 未测 |
| S3 | 赢家导通期间输家 D 也下穿（故障） | 输家不开通；赢家不被强制关断（或按明确规则关断并置 fault） | v2 强制关断，未测 |
| S4 | 开通后 100/300/470/480 ns 时 D 越过 +10.5 mV | 前三点保持到 475 ns + 23 ns；480 ns 点按 23 ns 关断 | t4：1.3056 us 穿越，1.6989 us 关断 |
| S5 | ARM(VD>1.5) 后 100/600/650/700 ns 再下穿 -265 mV | 前三点不开通；650/700 ns 点按 155 ns 开通 | t5：1.86 us 下穿，2.5433 us 开通 |
| S6 | burst 模式：一路关断后另一路不开；短导通（475 ns 最小开通） | 下一延时 275 ns；另一路随后开通则复位 155 ns；中点 VDS<-40 mV 连续 8 周期复位 | v2 无 |
| S7 | PRE：D>1.5 在 REG=0.5 V 后 REG 斜坡；REG 先到 4.1 V 再出现 D>1.5；REG 用 4.1 V 角 | 第一种必须 armed；第二种必须 violation/不开通；4.1 V 为边界 | bad_order：REG 0.1409 us 到 4.5，D 1.0038 us，PRE=0 |
| S8 | Roffset 0/100/212 ohm | VTHOFF_eff = 10.5/43.5/80.4 mV；PGD 阈值不变 | v2 无 330 uA，恒 10.5 mV |
| S9 | CH1 平均 8 kHz 持续 7.5 ms；16 kHz 持续 7.5 ms | 前者进 standby 且 VG 低；后者退出并忽略首周期 | v2 无 |
| S10 | 6.8 nF 门负载 | tr/tf 10-90 在 13-40/19-40 ns，typ 23/35 | v2 实测 127.9/45.6 ns |
| S11 | 负对照：去掉仲裁或强制 req1=req2=1 | 必须检测到双开通/不收敛，测试判 FAIL | t1_qrace 的 `Time step too small` |
| S12 | 比例门驱：真实 VGS→Rds(on) | VDS 调到 -35 mV；90% 未达则 -100 mV；关断沿随 VG 降低而缩短 | v2 经验律 |

S1/S2/S11 是 P0-1 的验收；S10/S12 是 P0-2 的验收；S4/S5/S7 固定现有正确行为，防止 v3 回归。

---

## 8. 证据索引（本次实际运行）

| 文件 | 关键实测 |
|---|---|
| `sim/v2/sr_good.log` | gate_max=10.8904104233 V；pre_final=0.999991476536；Total elapsed 0.088 s；无错误行 |
| `sim/v2/sr_good.raw`（解析） | g1 单一脉冲 4.177-4.867 us（690 ns）；g2=0；90 ns 负脉冲（8.01-8.1 us）未产生门极 |
| `sim/v2/sr_bad_order.log` | gate_max=0；pre_final=0；Total elapsed 0.087 s |
| `sim/v2/sr_bad_order.raw` | REG 0.1409 us 到 4.5 V，D1 1.0038 us 到 1.5 V；pre 恒 0 |
| `sim/v2/sr_simultaneous.log` | gate_max=10.8904104233 V；pre_final=0.999991476536 |
| `sim/v2/sr_simultaneous.raw` | g1 单一脉冲 4.177-4.867 us；**g2=0**；q1 到 1；d2=d1 |
| `sim/v2/sr_commutation_sweep.log` | 反向峰值 8.942/7.498/9.790/8.332/10.655/9.163 A（step 1-6）；gate_overlap max 6.17 mV |
| `%TEMP%/sraudit/t4_onblank.log` | gate_on 1.1769 us，gate_off 1.6989 us，d_offth 1.3056 us；保持 393.3 ns；tr 127.9 ns、tf 45.6 ns（10/90%，raw 复算） |
| `%TEMP%/sraudit/t5_offblank.log` | g1_rise1 1.1769 us，fall1 1.7604 us，rise2 2.5433 us；ARM 1.71 us，二次 D 下穿 1.86 us |
| `%TEMP%/sraudit/t1_qrace.log` | `Convergence Failure: Time step too small; time = 1.1651e-06 ... node "req1"`；ton1=ton2=0.155742；q1=q2=0.5；g1=g2=0 |

`%TEMP%/sraudit/` 下的 t1/t4/t5 是本次审核的临时诊断 deck，只例化未修改的 `SR_CH`/`SR_TIMING`，不属于项目交付；删掉不影响本文件结论。

**未验证/不可引用**：v2 的任何“反向电流/Qrev 可用于芯片选择”结论（P0-2 未校准）；任何“同时请求已通过”结论（S1/S2 未做）；任何 standby、Roffset、自适应延时、预启动快速斜坡结论（模型缺项）。
