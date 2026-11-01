# BSC010N04LS6 校准替身模型 `models/sr_device_v3.lib` —— 台架结果

日期：2026-10-31
器件：Infineon BSC010N04LS6（OptiMOS6 40 V，1.0 mOhm，PG-TDSON-8 FL / SuperSO8）
数据来源：`references/datasheets/bsc010n04ls6.txt`（Rev. 2.3, 2022-07-21, Final Data Sheet）
台架：`sim/v2/sr_device_bench_*.cir`（LTspice 26.0.2，批处理 `-b`）
运行日志：`sim/v2/sr_device_bench_*.log`（本文所有数值均取自这些日志）

## 0. 结论

`models/sr_device_v3.lib` 的 `SR_DEVICE` 子电路在 15 个手册目标上**全部 PASS**：
以 typ 为目标、判据 ±20%（手册另给 max 的，同时核对未超 max）。
偏差集中在同一个根因上：**Cgs 折中**导致 Qg -17.4%、Qgd -17.5%、Qgs +16.5%；
其次是单时间常数二极管的 **Qrr +16.6% / trr -15.4%**。其余 9 项误差均 < 12%，Vth 落在 1.3-2.3 V 内。

## 1. 决策记录：官方模型还是行为模型（必须显式，不得静默混用）

任务决策规则：若官方模型报告确认"已下载到 LTspice 可用的官方模型且通过探针"，
则应把官方网表包成 `SR_DEVICE`；否则建校准行为子电路。

`design/v2/official_model_report.md` 的实际结论是**分裂的**，不能简单读成"官方模型可用"：

| 官方变体 | 默认求解器（任务规定的直接批处理命令） | `-alt` 求解器 |
|---|---|---|
| L1 `BSC010N04LS6_L1` | **失败**：`Time step too small ... trouble with node "xdc:x1:e_eds2#branch"` | 通过，探针 16 个 .meas 全有值 |
| L3 `BSC010N04LS6` | 同一内部节点失败 | 通过一次 60 us 瞬态 |
| L0 `BSC010N04LS6_L0` | 通过 | 通过 |

并且报告实测出 L1 的**硬缺陷**：VDS=40 V / VGS=10 V 时饱和电流约 **11.2 kA**（`.dc` 交叉核对 10.5 kA），
手册 ID 上限 285 A；L0 同样 7.5 kA。即官方模型只在其低 VDS 欧姆区可信。

报告第 6 节自己的建议是：
> "可以用官方模型，但要按'参考模型'用，不能当签核模型。"
> "对 `models/sr_device_v3.lib` 的输入：……构建校准替身；替身必须明确标注'官方 L1 在饱和区不可用'。"

**本任务的判定**：官方模型在本任务强制的验证协议下（直接 `-b` 命令；日志不得出现
`Time step too small` / `Analysis failed`）**不是可用的 LTspice 模型**——L1/L3 直接产出这些行。
要让它跑必须改用 `-alt`，那已不是"直接命令"的默认路径；且其 kA 级饱和电流与关断应力场景直接冲突。
因此走**行为校准分支**，与报告的 §6.3 建议一致。

**没有静默混用**：`models/sr_device_v3.lib` 中没有任何一行来自厂商网表（0 行复制）；
厂商文件原样保留在 `references/models/infineon_optimos_pspice_40v/`，未修改。
lib 头部（PROVENANCE 段）写明了这一否决理由。
若后续需要官方 L1 的低 VDS 参考值，应单独用 `-alt` 包一个**另一个名字**的子电路做对照，
不要并入 `SR_DEVICE`——本文件没有这样做。

## 2. 模型结构

```
.subckt SR_DEVICE D G S params: TJ=25 LD=0.3n LS=0.8n LG=2.5n RG=1 CSCALE=1
.subckt SR_DEVICE_KELVIN D G S K params: ... LK=0.4n ...
```

| 块 | 实现 | 关键点 |
|---|---|---|
| 沟道 | `Bch`：`Ids = Vds/(R*(1+(|Vds|/(R*Isat))**3)**(1/3))` | 对 Vds 奇对称 → 反向导通不被钳零；R 与 Isat 都随 Vgs 变 |
| Rds(Vgs) | 三项指数 `R0+R1*exp(-(Vgs-Vk)/T1)+R2*exp(-(Vgs-Vk)/T2)`，Vk=1.65 V（拟合拐点，**不是** VGS(th)） | 拟合手册 Rds(on)-Vgs 曲线，残差 < 2.5% |
| Isat(Vgs) | softplus 型 `KP*[s*ln(1+exp((Vgs-Vz)/s))]**p`，平滑限幅到 1364 A | 拟合输出特性饱和点 |
| 电容 | **电荷定义** `Q=<expr>`（Cgd/Cds 非线性，Cgs 常数） | Qg 是仿真积分结果，不是硬编码波形 |
| 体二极管 | `DB`：IS=5e-11, N=1.05, RS=1m, TT=27n | TT 产生反向恢复 |
| 封装 | `Ld/Ls/Lg/Rg`（默认 0.3n/0.8n/2.5n/1.0） | 参数化，Kelvin 变体另加 `Lk` |
| 温度 | `TJ` 三次多项式只缩放 Rds(on) | 见 §6 限制 |

**封装寄生 ESTIMATE（无厂商数据，lib 中已显式标注）**

| 参数 | 估计范围 | 默认 |
|---|---|---|
| LD 漏极键合 | 0.15 .. 0.5 nH | 0.30 nH |
| LS 源极键合 | 0.40 .. 1.2 nH | 0.80 nH |
| LG 栅极键合 | 1.50 .. 3.5 nH | 2.50 nH |
| RG 内部栅阻 | 0.5 .. 2.0 ohm | 1.0 ohm |
| LK Kelvin 源 | 0.2 .. 0.6 nH | 0.4 nH |
| 功率回路有效源感 | 0.7 .. 2.5 nH | 按布局设 LS |

### 2.1 与现有 v2 台架的对接（drop-in）

`sim/v2/sr_commutation_sweep.cir` 目前把 SR 器件写成
`Sa da 0 ga 0 MOSCHANNEL` + `Da 0 da BODY` + 外部 `Cda da 0 2n`（外部电容）。
替换方式（引脚顺序 D-G-S 一致）：

```
Xsr da ga 0 SR_DEVICE
```

- 体二极管（`Dbd`）、Coss（`Cds`）、Crss/Ciss 都已包含在子电路内，不要再并 `Da/BODY`。
- **必须去掉或重估外部 `Cda 2n`**：本模型在 20 V 已给出 1.5 nF，低 VDS 可达 6 nF，
  保留 2 nF 会把 Coss 双计。
- 栅极驱动仍接 `ga`；`TON/TOFF` 等时序逻辑属于 `sr_timing_v2.lib`，不在器件模型内。
- 若外部回路已单独建模布局电感，应把 `LD/LS` 设小或设 0，避免与封装估计重复。
- `SR_DEVICE_KELVIN` 用于需要独立源极返回的四端场合（K 不要与 S 短接成同一网，
  否则 Lk/Ls 并列，LTspice 会报 over-defined matrix——本台架即用 1 ohm 独立返回）。

## 3. 台架清单（全部 `sim/v2/`，全部直接 `-b` 运行通过）

| 台架 | 分析 | 覆盖 | 主要 .meas |
|---|---|---|---|
| `sr_device_bench_dc_fwd.cir` | `.dc` + `.step` | 正向 ID-VDS，VGS=10/4.5/3.0 V | RDS50, ID1V, ID02 |
| `sr_device_bench_dc_fwd_low.cir` | `.dc` | 正向 ID-VDS，VGS=2.5 V | ID02/ID05/ID10/IDMAX |
| `sr_device_bench_vth.cir` | `.dc` | VDS=VGS，ID=250 uA | VTH, ID@1.5/2.0/2.3 |
| `sr_device_bench_3q.cir` | `.dc` | 第三象限，VGS=0（体二极管） | VSD50/10/100, IDM1V |
| `sr_device_bench_qg.cir` | `.tran` | 栅电荷，VDD=20 V，ID=50 A，Ig=5 mA | QG, QG45, QGS, QGD, VPLATEAU |
| `sr_device_bench_caps.cir` | `.tran` | 0→40 V 刚性斜坡（1 V/us），VGS=0 | QOSS20, COSS/CRSS @10/20/40 V |
| `sr_device_bench_ciss2.cir` | `.tran` + `.step` | VDS=10/20 V，栅极 0→0.4 V 小信号斜坡 | CISS |
| `sr_device_bench_turnoff.cir` | `.tran` | 20 V/50 A 钳位感性关断 | VSWON, ILON, VPK, DV |
| `sr_device_bench_qrr.cir` | `.tran` + `.step` | 反向恢复，IF=10 A，diF/dt=400 A/us，VR=20 V | QRR, TRR, IRR（CS=0/1） |
| `sr_device_bench_kelvin.cir` | `.dc` | `SR_DEVICE_KELVIN` 解析与导通核对（VGS=10 V） | RON, ID1 |

电容的取法：用**刚性电压斜坡**，`C = I/slope`，`Qoss = INTEG -I(Vd)`。
曾用 1 mA 恒流源版本（`qoss`）得到 22.8 nC，与解析电荷 73.0 nC 矛盾，判为 uic 下的数值伪像并弃用；
刚性斜坡既是被测电压强制、又能复现解析电荷，是标准定义，故采用。

## 4. 目标 vs 仿真（主表）

判据：以 typ 为目标，误差 ±20% 内 PASS；手册给出 max 的一并核对。
误差 = (仿真-typ)/typ。

| # | 参数 | 手册 typ (max) | 仿真值 | 误差 | 判定 |
|---|---|---|---|---|---|
| 1 | Rds(on) @VGS=10 V, 50 A | 0.89 mOhm (1.0) | 0.8975 mOhm | +0.84% | PASS |
| 2 | Rds(on) @VGS=4.5 V, 50 A | 1.1 mOhm (1.4) | 1.1191 mOhm | +1.73% | PASS |
| 3 | VGS(th) @ID=250 uA | 1.3 .. 2.3 V | 1.875 V | 在区间内 | PASS |
| 4 | Ciss @VDS=20 V | 4600 pF (6000) | 5139.6 pF | +11.73% | PASS |
| 5 | Coss @VDS=20 V | 1500 pF (2000) | 1508.1 pF | +0.54% | PASS |
| 6 | Crss @VDS=20 V | 38 pF (66) | 39.48 pF | +3.91% | PASS |
| 7 | Qoss | 73 nC (97) | 73.00 nC | -0.00% | PASS |
| 8 | Qg (0..10 V) | 67 nC (83) | 55.37 nC | -17.35% | PASS |
| 9 | Qg (0..4.5 V) | 32 nC | 29.14 nC | -8.94% | PASS |
| 10 | Qgs | 12 nC | 13.98 nC | +16.47% | PASS |
| 11 | Qgd | 8.1 nC (12) | 6.679 nC | -17.54% | PASS |
| 12 | Vplateau | 2.7 V | 2.719 V | +0.69% | PASS |
| 13 | VSD @IF=50 A | 0.80 V (1.0) | 0.8004 V | +0.05% | PASS |
| 14 | trr（VR=20 V, IF=10 A, 400 A/us） | 30 ns (60) | 25.38 ns | -15.39% | PASS |
| 15 | Qrr（同条件） | 97 nC (194) | 113.1 nC | +16.63% | PASS |

补充：所有 15 项的仿真值也都**未超手册 max**（Rds 0.898<1.0 / 1.119<1.4；Ciss 5.14<6.0 nF；
Qoss 73.0<97；Qg 55.4<83；Qgd 6.68<12；trr 25.4<60；Qrr 113<194；VSD 0.800<1.0）。

RG：手册 typ 1 ohm；模型参数 `RG` 默认 1.0 ohm（参数设定，非独立仿真结果）。

手册把 Qoss、Qgd、trr、Qrr 标注为 "defined by design, not subject to production test"，
对这类量 ±20% 已是偏严的判据；本模型仍全部落在 ±20% 内。

## 5. 附加仿真结果（手册无单一目标，用于形状/趋势核对）

**正向 ID-VDS（`dc_fwd`，log 的 step 1/2/3 = VGS 10/4.5/3.0 V）**

| VGS | ID@0.2 V | ID@1.0 V | Rds@50 A |
|---|---|---|---|
| 10 V | 222.5 A | 962.4 A | 0.8975 mOhm |
| 4.5 V | 178.4 A | 763.4 A | 1.1191 mOhm |
| 3.0 V | 73.18 A | 156.2 A | 2.6705 mOhm |
| 2.5 V | 14.89 A | 15.99 A（IDMAX=15.994） | 未到 50 A |

VGS=2.5 V 时 ID 在 1 V 后饱和在 ~16 A，与 3.0 V/156 A 一起给出陡峭的阈值区（Vth=1.875 V）。

**第三象限（`3q`，VGS=0）**

| 量 | 仿真 |
|---|---|
| VSD @10 A | 0.7167 V |
| VSD @50 A | 0.8004 V |
| VSD @100 A | 0.8692 V |
| 反向电流 @VSD=1 V | 210.5 A |

**电容的 VDS 依赖（`caps`/`ciss2`，与手册 Diagram 11 数字化的典型曲线对照）**

| VDS | Coss 仿真 | Coss 手册曲线 | 偏差 | Crss 仿真 | Crss 手册曲线 | 偏差 |
|---|---|---|---|---|---|---|
| 10 V | 3393.9 pF | 3400 pF | -0.18% | 186.2 pF | 192 pF | -3.0% |
| 20 V | 1508.1 pF | 1504 pF | +0.27% | 39.48 pF | 38.5 pF | +2.6% |
| 40 V | 861.3 pF | ~860 pF（曲线外推，估计） | +0.15% | 26.76 pF | 27 pF | -0.9% |

| VDS | Ciss 仿真 | Ciss 手册曲线 | 偏差 |
|---|---|---|---|
| 10 V | 5283.3 pF | 4790 pF | +10.3% |
| 20 V | 5139.6 pF | 4640 pF | +10.8% |

在仿真的 10/20/40 V 三点上，Coss/Crss 与数字化曲线的偏差 < 3%（拟合区间为 0.5-40 V）；
Ciss 的 +10% 是常数 Cgs 折中的直接结果（见 §6 第 2 条），不是 VDS 依赖拟合误差。

**反向电流没有被钳零**：VGS=0 时沟道关断，50 A 反向电流经体二极管在 0.80 V 建立；
1 V 时达 210 A。这是"不得人为钳零"的直接反证。

**栅电荷（`qg`）**

Qg=55.37 nC @10 V；Qg=29.14 nC @4.5 V；Qgs=13.98 nC；Qgd=6.679 nC；Vplateau=2.719 V。
Qg 由恒流 5 mA 充电、`.meas` 取 V(g)=10 V 的时刻积分得到，**不是表驱动波形**。

**20 V / 50 A 钳位感性关断（`turnoff`）**

| 量 | 仿真 |
|---|---|
| 关断前 IL | 51.87 A（uic+IC=50，导通期间电感承受 VDD，故已爬升 ~1.9 A） |
| 导通压降 Vsw | 48.74 mV → 0.940 mOhm（含 Ld/Ls 上 2 A/us 的 ~2.1 mV 压降） |
| Vsw 峰值 | 21.13 V（VDD=20，过冲 1.13 V） |
| Vsw 10-90% dv/dt | 2.456 V/ns |
| 关断后 Vsw | 21.03 V（VDD + 续流二极管 Vf） |

**Kelvin 变体（`kelvin`）**：VGS=10 V、VDS=0.1 V 时 ID=111.4 A，Rds=0.89767 mOhm，
与 3 脚版 0.89752 mOhm 相差 0.02%，证明 `SR_DEVICE_KELVIN` 可解析且未改变沟道；
K 经 1 ohm 独立返回，`Lk` 与 `Ls` 不构成并列。

**反向恢复（`qrr`）**：CS=0 只留体二极管 → Qrr=113.1 nC、trr=25.38 ns、Irr=-8.93 A。
CS=1 打开电容 → Qrr=179.4 nC、trr=31.58 ns（电容电荷叠加，非二极管本征值；仅作灵敏度参考）。

## 6. 这个模型**不能**声称什么

1. **饱和区 / 短路 / SOA 电流不可用**。Isat 只由手册输出特性的 50 A、160 A 点拟合，
   40 V/10 V 驱动下会给出 kA 级（与官方 L1 同病）。不得用它算短路电流、雪崩或 40 V 关断应力电流；
   关断应力只能由外部钳位电路决定（本台架即如此）。
2. **Qg/Qgd/Ciss 的折中是模型级属性**，不是可同时满足的三个独立目标：
   为兼顾 Ciss 曲线（~4.6 nF）与 Qg（需 ~6.6 nF），Cgs 固定 5.1 nF，导致 Qg -17.4%、
   Qgd -17.5%、Qgs +16.5%。三者都在 ±20% 内，但**不能**声称精确复现栅电荷波形。
3. **trr 与 Qrr 不能同时命中**：单个 `TT` 只有一个时间常数。TT=27 ns 时 Qrr +16.6%、trr -15.4%，
   是折中值，不是物理拟合。Qrr 的温度依赖未建模。
4. **封装寄生是 ESTIMATE**（§2 表），不是手册值；Kelvin 源感 LK 同样是估计。
5. **温度只作用于 Rds(on)**：`TJ` 只缩放沟道电阻；体二极管、电容、Qrr/trr 均在 deck 温度（默认 27 C）求值，
   且**没有自热网络**，不能做瞬态热仿真。
6. **未建模**：栅漏电、雪崩/击穿、体二极管正向恢复、Crss 在 40 V 以上的外推、封装热阻。
7. **不是厂商模型**，内部结构与官方 L1 无关；只是在手册数据点上校准的替身。
   与官方 L1 的交叉一致仅限低 VDS 区（Rds、Vf），不得宣称"等价于官方模型"。
8. 关断/开通波形的绝对值依赖外部栅极驱动与布局寄生；`SR_DEVICE` 只保证器件端行为。

## 7. 复现与验证

```bash
cd "D:/workshop/design_48v-2v"
for n in dc_fwd dc_fwd_low vth 3q qg caps ciss2 turnoff qrr kelvin; do
  rm -f sim/v2/sr_device_bench_$n.log sim/v2/sr_device_bench_$n.raw
  timeout 200 "D:/ADI/LTspice/LTspice.exe" -b "sim/v2/sr_device_bench_$n.cir"
done
```

每个 `.log` 的独立检查（本次全部满足）：
- 含 `Total elapsed time`（10/10）；
- 不含 `Error:` / `Time step too small` / `Singular matrix` / `Analysis failed` / `FAIL`（10/10）；
- 上表依赖的每个 `.meas` 都有数值。

## 8. 残余偏差与后续建议

| 项 | 现状 | 建议 |
|---|---|---|
| Qg -17.4% | Cgs 折中 | 若下游对 Qg 敏感，可改用 Cgs=6.3 nF（Qg≈67，但 Ciss≈+37% 超 ±20%）——需要明确取舍 |
| Qrr/trr | 单 TT 折中 | 需双时间常数或行为 Qrr 源；或在应用层按手册 Qrr 保守计损耗 |
| Qoss 台架 | 恒流源版本数值伪像 | 已改用刚性斜坡；若换 LTspice 版本应复测 |
| 自热 | 无 | 若要 Tj 瞬态，需外接 Cauer/Foster 热网络到 `TJ` 参数 |
| 官方 L1 对照 | 未并入 | 需要低 VDS 参考时可另建 `-alt` 包装子电路，不并入 `SR_DEVICE` |
