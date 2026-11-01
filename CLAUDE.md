# CLAUDE.md — 项目操作事实与陷阱

本文件记录**无法从代码直接看出**的操作事实。设计结论看 `design/v2/` 与 `design/v3/`，不要在本文重复数字。

## 运行与测试

```bash
python -m pytest tools -q          # 全部离线工具测试，必须全绿
python tools/make_round4_decks.py  # 生成 round-4 deck（改母 deck 后必须重跑）
python tools/magnetics_design.py --json design/v3/magnetics/magnetics_design.json
python tools/draw_magnetics.py --out design/v3/magnetics   # 含 winding_connections.svg（带 DOT 端子图）
python tools/winding_polarity.py --out design/v3/magnetics # 端子 DOT 表 + 首件极性记录（由 deck 派生）
python tools/make_magnetics_manifest.py   # 改磁件包任一文件后重跑（含 SVG/源工具）
python tools/thermal_precheck.py --json design/v3/stage_f/thermal_precheck.json
python tools/passive_requirements.py --json design/v3/bom/passive_requirements.json
python tools/passive_requirements.py --cin-raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.raw \
    --json design/v3/bom/passive_requirements.json   # 追加输入电流（需先有探针 raw）
python tools/lr_design.py --json design/v3/bom/lr_design.json   # Lr 匝数/气隙/Isat 表
python tools/cout_bank.py --json design/v3/bom/cout_bank.json   # Cout 并联数量与主导约束
python tools/cr_stress.py --json design/v3/bom/cr_stress.json   # 由 I(Lr) 积分重建 v_Cr
python tools/ct_design.py --json design/v3/bom/ct_design.json  # CT 传递链/负载与分压（10 Ω 已冻结）
python tools/oc_network_check.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.raw \
    --burden 10 --rd1 10k --json design/v3/bom/oc_network_ct10.json   # 实测 OC 网络，需带 V(oc*) 的变体 raw
python tools/connector_budget.py --json design/v3/bom/connector_budget.json  # 输出铜排/接点预算
python tools/output_path_budget.py --json design/v3/pcb/output_path_budget.json  # 板上 100 A 平面方块数（读摆放）
python tools/board_netlist.py --json design/v3/pcb/board_netlist.json \
    --csv design/v3/pcb/board_netlist.csv   # 主功率板逐脚网表，由 v3 deck 派生
python tools/powerup_checklist.py --md design/v3/stage_f/上电检查表.md \
    --json design/v3/stage_f/powerup_checklist.json   # 上电检查表，判据由各 JSON 渲染
python tools/current_manifest.py --scope v3 \
    --json design/v3/manifest_current_candidate.json   # 可复现当前清单（v2 仍是不带 --scope 的默认）
python tools/extract_op_point.py <raw> --rl <ohm> --periods 22 --json <out>
python tools/energy_ledger_100a.py --json design/v3/stage_f/energy_ledger_100a.json
    # 100 A 同窗口端口能量账；默认读 ..._100a_ledger.raw（424 MB，不入 Git）
python tools/ci_check.py            # pytest + 重新生成 v3 manifest 并逐项比对
python tools/ci_check.py --skip-tests   # 只查生成文件是否过期
python tools/make_control_board.py --check   # 控制验证板：重生成 + 网表 + ERC（需本机 KiCad 10.0）
python tools/main_board_mechanical.py --check   # A5 机械摆放（1:1）：重生成 + SVG/PNG + DRC（需 KiCad 10.0）
```

LTspice 批处理：`/d/ADI/LTspice/LTspice.exe -b -ascii deck.cir`。
**结束 LTspice 只能按 PID**：`kill <pid>`（`ps -W` 查）。禁止 `taskkill //IM LTspice.exe`
——权限分类器会拒绝，且会误杀其他会话的仿真。
`ps -W` 里的进程名是 **`LTspice`（没有 `.exe`）**，所以 `ps -W | grep LTspice.exe` 会返回空，
看起来像"仿真早就退出了"。判断跑没跑看 raw 是否在长大、以及 `rm` 是否报
`Device or resource busy`；不要信名字 grep。批量模式一次要跑十几分钟到数十分钟
（120 µs 窗口 176 s / 224 s；670 µs 约 2.4 GB、~40 min），别按"没输出"判死。

**不要随手重跑 `python tools/make_round4_decks.py`**：`main()` 会重写全部已冻结 deck，
刷新 mtime，破坏"raw 与 deck 是否同一输入"的比对（见下）。只用它新增 deck 时，
单独 `import make_round4_decks as m; m.write(name, m.<变体>())`，只写目标文件。

## 仿真文件

- `uic` 且无 `.ic` = 真正的零初态（冷启动）。只要有一行 `.ic`，即使 `uic` 也**不是**冷启动；
  `tools/task_package1_summary.py:cold_start()` 会检查并拒绝。
- `Tstart` 会**重排保存的时间轴**：raw 里的 `0..120 us` 实际是 `880..1000 us`。
  任何窗口都要同时记录 `raw_time_start_s` 与 `display_offset_us`（manifest 已如此）。
  这两个值现在由 `current_manifest.deck_timing()` 从 deck 的 `.tran` 行解析，并与 LTspice 日志里的
  `FROM 0 TO x` 交叉校验（`tools/test_current_manifest.py`）；**不要再手抄**，也不要从日志反推。
- 冷启动 raw 10.7 GB、1400 万点、31 变量。PyLTSpice 是纯 Python 逐行解析，
  `load()` 一次约 20 分钟、约 3.5 GB 内存。只想看尾部时**不要**整文件加载：
  ASCII raw 每个时间点占 31 行（首行 `序号<TAB><TAB>时间`，其余每行一个值），
  可 seek 到文件尾部、对齐到非 TAB 开头的行后逐记录解析。
- **deck 在仿真运行期间被重新生成**会导致 raw 与当前 deck 不是同一输入
  （例：raw 头缺 `.save V(pre*)`，说明运行开始时 deck 尚无该行）。比对 mtime：
  raw 的 mtime 不是开始时间，开始时间 ≈ raw mtime − 日志运行时长。
  另一个独立信号：raw 头的 `No. Variables`（旧冷 raw 31，含 `V(pre*)` 的是 37）。
- **严重过载（1 mΩ 对 20 mΩ）约 1.7 ms 后求解器塌缩**：cold_oc 在 t=7.3066 ms
  处步长压到 ~1e-17 s，37 s 只推进 1.6e-13 s，剩余时长不可达。ASCII raw 是流式
  追加的，按 PID 结束进程后**已写出的前缀仍可读**；故障段（5.55 ms 起）数据完好，
  只需在报告里注明终止时刻与原因。不要以为 8 ms deck 就一定产出 8 ms。
- `sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir` 是 1 ms 母 deck 只改 `RL=18.9m` 的副本；
  raw 313 MB、59 变量、216689 点，运行 176.2 s。**只存了 pair1/pair4 的电流**：
  `operating_point_100a.json` 里的 `iout_sum_a` 是 2/4 组之和（约 49.9 A），
  `iout_from_v_a = avg(Vout)/RL` 才是总输出电流（约 99.8 A）。
- 高度最坏值必须用胶/标签的**最大**厚度，不是标称：`height_stack()` 的
  `glue_max_m`/`label_max_m` 默认等于标称值，做公差分析时必须显式传入。

## 测量口径（工具不变式）

- `Pout = average(Vout²/R)`，不是 `Vout_avg²/R`；`Vout` 必须梯形时间加权。
- 每周期 `e_dissipated` 的离散度 16–23 %（体二极管支路主导）。同一族内比较时
  **周期数必须一致**；混用 8/22 周期会造出约 9 % 的假"收敛差"。
- `sr_energy_ledger.ledger_period()` 只对 pair 1 有仪器（`xsa1:*`/`xsr1:*`），
  传其他 pair 会抛错——这是故意的，防止把 pair 1 的数字贴到别的组。
- pair4/pair1 的反向换流电荷比是**换流指标**，不是均流；均流看四组 `iout`/`irms`。
- 四组在模型里结构对称，`iout_spread` 会小到 1e-9 %——这不构成"真实均流"证据。
- 输出电容电流没有直接保存：用四路 SR 电流按 KCL 重建（pair 1/4 实测 ×2 假设 pair 2/3 对称）。
  采信 RMS 前必须校验重建均值与 `iout_from_v_a` 一致（该 deck 差 −0.07 %）；否则符号或比例错了。
  四组同相驱动，纹波电流相加：100 A 点为 52.48 A RMS，不是交错后的 √4×单组。
- 输入侧同理但结论相反：`sim/v3/..._100a_cin.cir`（只在 `.save` 末尾加 `I(Cin) I(Rin)`）
  实测 I(Cin) 交流 RMS 仅 **0.227 A**，因为模型电源是 48 V 串 1 mΩ，而 20 µF 在 200 kHz 是 40 mΩ
  ——纹波走电源不走电容。**这个 0.227 A 不能当选型依据**；选型用半桥输入电流交流 RMS **5.316 A**
  （KCL `I(Rin) − I(Cin)`，RMS 6.746 A）。校验：I_bridge 在 47.6 % 采样点等于 I(Lr)、48.9 % 上为 0，
  且 RMS ≈ √D·Ipri_rms。任何"输入电容纹波"数字先问一句：源阻抗是多少。
- `|I(Lr)|` 的稳态峰值 13.88 A **不是** Lr 的电流规格：冷启动 36.07 A、短路 65 A（OC 13 µs）/
  73.68 A（OC 51.3 µs）。饱和判据 `B = L·I/(N·Ae) ≤ 0.9·Bsat` 用故障峰值；65/74 A 本身来自
  **线性** Lr 模型，真实饱和后 di/dt 更高，所以 0.9 是设计点不是极限。见 `tools/lr_design.py`。
- **实测峰值必须和它跑的那个 L 配对**：`candidate()` 固定电流扫电感是保守的（B∝L 被高估），
  但**实测**峰值的电流里已经含了它自己的 L，换一个电感去算 B 就是错的——`paired_flux()` 因此
  用 `PHYSICAL_PEAKS[case]["external_lr_h"]`，不是候选电感。物理 deck 实测：冷启动 22.53 A
  （1.0 µH 外置 + 7.05 mF）、故障全程 84.02 A（同一 deck，OC 在 5.5998 ms 动作；5.6–5.8 ms
  窗口内 73.12 A）。**2 匝在 84.02 A/1.0 µH 下 B=0.323 T，已越过 Bsat 本身（0.310 T）、
  Isat 80.6 A**，所以 BOM §3.3 里那句"首件漏感 ≥20 nH 就能把 2 匝救回 0.9 判据"
  **只对 73.68 A 的冻结 deck 成立，已被物理 deck 推翻**；3 匝在 84.02 A 下 0.215 T，
  判据线 0.279 T。
  同理，`operating_point_100a.json`（49.73 mVpp）跑的是冻结 deck 的 **4 mF**，而冻结的 Cout
  是 7.05 mF：与本表冻结配置对应的纹波是 `operating_point_100a_cout7m.json` 的 42.76 mVpp。
- **`V(Cr)` 没存，是重建出来的**：v(t)=v(0)+(1/C)∫I(Lr)dt，积分常数由磁通/伏秒平衡定为
  `mean(v_Cr) = mean(V(sw))`。100 A 点实测：直流 23.89 V、峰值 41.36 V、峰峰 34.73 V。
  只看电流不看电压会以为 Cr 的约束是耐压，其实不是——约束是 200 kHz 下的 ESR/发热。
  重建依赖标称 C，容差按比例直接进摆幅。见 `tools/cr_stress.py`。
- **CT 是电流源，整流桥不削波**：`V_oc = mean(R_b·|i_sec|) × 24/35`，线性、无导通下限。
  副边串在谐振腔里，安匝平衡强制 `i_sec = i_pri/N`；`2Vf` 是 CT 必须提供的**合规电压**，
  进磁通（10 Ω 时它比负载自身伏秒还大），**不进信号**。
  本文件曾写"桥在 `R_b·|i_sec| > 2Vf` 之前不导通、额定只有 42 mV、真实门槛 41.5 A"——**那是错的**，
  已被 deck 实测推翻：`V(ocd)` 从 0.004 V 连续升到 1.382 V、无死区，实测 0.834 V 对预测 0.061 V（差 13.7 倍）。
  错模型还导出了"47 Ω + `Rd1` 110 k"的修正，那个组合实测门槛 19.65 A，会在 1.4 倍额定负载就跳闸。
  现在两个量都对：头注的 0.04365 V/A / 22.9 A 由 `(2/π)` 正弦理想化复现；
  实跑峰值/平均是 1.660 而非 π/2，所以真实门槛 **24.2 A**（`..._ct10.raw` 实测 24.18 A，代数 +0.1 %；
  `..._ct47.raw` 47 Ω 实测 0.690 V 对代数 0.700 V，−1.3 %）。**10 Ω / 10 k 保持不变**，
  与 22.9 A 对应的理想负载 10.58 Ω 只差 5.5 %。见 `tools/ct_design.py`、`tools/oc_network_check.py`。
- **输出路径的 0.1 mΩ 预算做不到**：20×2 mm 铜排 80 mm = 0.034 mΩ（0.345 W），可精确算；
  但两处接点按手册常见的 50 µΩ/处就已经把 0.1 mΩ 全部用光，留给铜排的长度为 0。
  `connector_budget.py` 因此返回 `feasible: false` 并给出缺口，**不要**把预算截断到 0 再印一个铜排长度。
  **但 0.1 mΩ 是自选的、不是规格**，而磁件包公布的 92.33 % 效率是按 **0.15 mΩ / 1.495 W** 算的，
  两个口径互相矛盾。工具现在两个都报，设计基准取 0.15 mΩ → 铜排 34.5 µΩ 之后
  **每处接点上限 57.8 µΩ**（`joint_limit()`），这是首件四线法的验收数；
  占位值 50 µΩ 只是假设、不是判据。改 benchmark 前先确认效率口径没变。
  接点电阻在本环境无数据可查，只能标 UNVERIFIED + 首件四线法实测。输入侧同理：6.746 A RMS 下
  2 mm/2 oz 铜箔 100 mm 耗 0.56 W，按 0.1 W/100 mm 需 11.2 mm 宽——卡住的是走线不是端子。
- **Cout 的并联数量由 ESR 决定，不是容量**：470 µF/3 mΩ 料号容量只需 9 只、RMS 只需 5 只、
  ESR 要 15 只；按容量算会少买 6 只，整组 ESR 变 0.33 mΩ。`bank ESR = 单只/N` 只对电容本体成立，
  不含铺铜分布电阻。**0.2 mΩ 是模型 `Rser` 的值，不是规格**——项目没有 Vout 纹波上限定义，
  取 0.1 mΩ 数量翻倍到 30 只。见 `tools/cout_bank.py`。
- **100 A 能量账只在同一窗口内成立**：`energy_ledger_100a.py` 用 16 个门极周期的 raw
  直接积分，`Pin(source)=48·mean(I(Rin))`、`Pout=mean(Vout²/RL)`，逐项损耗 11.117 W、
  Pin−Pout 11.025 W、残差 −0.091 W（目标 0.2 W）。CT 整流桥+负载 0.186 W 是最后补齐的一项。
  SR 门极 B 源不取 `Vreg`，驱动 0.205 W **在端口之外**：真实偏置要付，但模型没计。
  **门极边沿必须去抖**（200 ns）：5 ns 步长下每次上升沿两次穿过 2.5 V，
  不去抖会把 24 个周期数成 48 个。
- **储能必须用三绕组耦合形式**：`E = ½LpIp² + (Lp/18)(Isa+Isb)² + (kLp/3)Ip(Isa+Isb) + ((k−1)Lp/9)IsaIsb`。
  旧写法 `4×½Lp·Ip²` 把副边当空载：k=1 且安匝平衡时正确值收敛到 `½Lp(Ip+S/3)² ≈ 0`，
  实测旧式给 2 mJ、真值 0.75 µJ，**夸大 2600 倍**。
  `Lsa1 out a1` 的 DOT 在 `out`、`Lsb1 b1 out` 的 DOT 在 `b1`，故 `Isa=+I(VSa1)`、`Isb=−I(VSb1)`。
  电容储能**必须由电荷函数在端点求值**（`E(v)=|v|Q(|v|)−∫Q`），不是 ∫v·i：
  后者每通道每周期残留 −290 pJ（8 只合计约 0.2 mW），是求积误差不是物理量。
- **储能端点差 0.232 W 单独报告**（含此前漏掉的 Lct1/Lct2/Cin/Cdh 四项）；并入它才叫
  "含储能闭合残差"，16 周期为 −0.118 W。两个数不是同一个量，引用必须写明。
- **储能端点是周期平均，不是单点采样**：`storage_terms()` 读单个采样点；
  `averaged_storage_terms()` 把每一项在端点所在的那个**门极周期**内做梯形平均。一个门极周期
  （4.9845 µs）与一个谐振周期（4.9473 µs）只差 0.75 %，所以 `|sinc(π·f_tank/f_gate)| ≈ 0.0075`，
  把谐振频率分量压掉约 130 倍。16 周期窗口上两个读数分别是 **−0.118 W 与 −0.222 W**，
  差 0.10 W——`closure_status` 要求**两个读数都在 0.2 W 内、且周期平均读数能分辨 0.2 W**；
  只有单点读数满足不算闭合（`results.closure_including_storage_within_0p2_w` 已经这样算）。
- **`charge_energy_j()` 用闭式原函数**：器件充放电拟合是"分段线性 + 双指数"，积分有初等原函数。
  旧实现每次调用跑 4000 段 Simpson（≈1 ms），只够算两个端点；`storage_arrays()` 需要**每个采样点**
  都算，所以换成闭式（与 Simpson 差 ~1e-9，就是 Simpson 自身误差）。**不要退回 Simpson。**
- **对齐窗口已经跑过，结论是"能分辨、但超目标"（Issue #6）**：133 周期窗口
  周期平均 sd 1.803 W、标准误 **0.157 W**（132 个点）⇒ 能分辨 0.2 W，
  而闭合残差是 **+0.326 W（周期平均）/ +0.384 W（单点）**，在目标外。
  所以 `NOT_CLOSED` 的理由已经不是"分辨不了"，而是"测到了、缺口约 0.3 W"。
  同一条 raw 上 8 / 12 / 133 周期分别给 +0.999 / +0.368 / +0.384 W——短窗口读数由
  停在哪一相决定，端点储能差在 −0.315 / +0.279 / −0.021 W 之间摆。
  **16 周期窗口把损耗算高 0.386 W（11.117 对 10.731 W，3.5 %）**，引用 11.117 W 时
  必须写"16 周期窗口值"。
  同一条 raw 上 `gap_before_ct_w`（`Pin − Pout − 非 CT 损耗`）从 0.094 W 变成 **0.344 W**，
  而 CT 两项只有 0.186 W ⇒ 16 周期窗口上"CT 正好补齐缺口"是窗口巧合。
- **闭合残差在 16 周期窗口上没有 0.2 W 的分辨率**：单周期残差 sd 5.02 W，16 周期标准误
  1.26 W，压到 0.2 W 需约 632 个周期，而 raw 只有 24 个。均值落在目标内是正负相消，不是闭合。
  周期平均估计量把 sd 降到 1.96 W（16 周期、15 个可用点），仍需约 96 个周期。
  根因是**时钟与谐振腔不通约**（200.622 对 202.131 kHz，拍频 1509 Hz）：最短相位对齐窗口是
  **133 个门极周期 = 662.9 µs**，由 `phase_alignment()` 算出，**不要手抄**。
  deck 变体 `ledger_aligned`（`make_physical_decks.py`，只改 `.tran` 的 **Tstop**，880 µs 起始点不动）
  就是为这个窗口准备的；注意 `.tran` 字段序是 `Tstep Tstop Tstart Tmaxstep`。
- **5 ns 对 2 ns（16 周期窗口）**：损耗 11.117→11.141 W（+0.22 %），但 `V(out)` 端点差 7.6 mV，
  4 mF×1.87 V×7.6 mV≈57 µJ 折算 1.3 W，闭合残差 −0.118→**+0.404 W 不收敛**。
  `ledger2n` 变体由 `make_physical_decks.py` 只改 `.tran` 步长生成。
  **上面那句"损耗已收敛"只对 16 周期窗口成立**，见下面 133 周期那一条。
- **"瓶颈是端点采样、不是梯形积分"只对了一半，大项正好错在这一半**：同一个 16 周期窗口上，
  **周期平均**闭合残差在 5 ns 与 2 ns 之间移动 **+0.3803 W**（−0.2223 → +0.1580），
  其中端口项移动 −0.3898 W、周期平均储能项移动 −0.7941 W，**损耗清单只移动 +0.0244 W**
  ——端口项的移动量是损耗清单的 **16 倍**。旧 `step_check.note` 写"端口与损耗是梯形积分、
  会收敛；储能项不收敛"，错的那一半恰是大项；现在 note 由实测 Δ 生成、不再做这个断言，
  `step_check.terms` 也加入了周期平均读数（`stored_period_averaged_w`、
  `closure_period_averaged_w`），因为**报告引用的是周期平均那个数**。
  推论：`sem_w`（对齐窗口 0.157 W）**只描述周期间的随机散布**，不含步长；
  凡说"能分辨 0.2 W"必须同时说明这一点。
- **对齐窗口的步长检验把结论劈成两半（`ledger_aligned2n`，133 周期、只改步长）**：
  **闭合残差站得住**——周期平均 +0.3258 W（5 ns）对 +0.3139 W（2 ns），只移动 **0.0119 W**，
  两个步长都在 0.2 W 外（单点 +0.3844 / +0.3186 W）。所以 +0.33 W 的缺口**不是 5 ns 的伪影**；
  对照 16 周期窗口同一次比较移动 0.38 W，说明**相位对齐消掉了这项敏感性**。
  **但损耗清单站不住**：10.7313 → 11.3563 W，**移动 0.6250 W（5.8 %）**，不是 16 周期窗口上的
  0.0244 W；端口项同时移动 +0.5340 W，两项同向、接近相消，闭合才显得稳。
  ⇒ **任何单个损耗项都不许引用得比 0.6 W 更细**，94.47 % 因此带约 0.3 个百分点不确定度；
  "闭合稳定"**不能**当作"每一项都准"的证据。逐项定位 2 ns 的损耗清单尚未做（需再读一次 2.25 GB raw）。

- JSON 的 `checks` 是**报告不变量**（只有它的 `ok` 是门），`results` 是**物理结果**。
  不要把"未闭合"塞进 `checks.ok`——那会诱使下一个人为了让测试变绿去放宽目标。
  反方向同样要防：`ct_burden_closes_the_gap` 原本是 `checks` 的一项，对齐窗口上它是 0.344 W
  （超 0.2）⇒ 一次诚实的物理发现被报成"工具坏了"。已改名
  `results.ct_terms_account_for_the_gap_before_ct`，差值写进 `gap_before_ct_w`，
  `checks` 只留 `ct_gap_is_reported_as_a_result` 这种结构不变量。**物理量一律进 `results`。**
- **纹波不能用 10 µs 窗口**：ledger 日志的 38.27 mVpp 只覆盖约 2 个周期，漏掉慢包络；
  `operating_point_100a.json` 的 22 周期值是 49.73 mVpp，逼近自选的 50 mV 目标，
  引用时写 22 周期值并说明余量只有 0.27 mV。
- **94.47 % 与 93.06 % 是两个口径**：前者是 deck 电气端口效率（变压器无磁芯损耗元件），
  后者加 0.353 W 磁芯估计；公布的 92.33 % 再含 0.15 mΩ 输出路径与 0.75 W 偏置。
  引用效率必须写明含哪些损耗。
- **主功率板网表是从 deck 派生的，不是重画的**：`board_netlist.py` 解析
  `sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir`，任何 deck 元素必须落在 `PARTS` 或 `SKIP`（带理由）里，
  否则 `UNMAPPED` 直接失败。改 deck 的元素名/节点名后必须重跑，`test_the_generated_files_are_current`
  会逐字节比对提交的 CSV。三条已知映射陷阱：`Bgh/Bgl/Xsr1..4` 是行为模型，板上是 U2/U3–U6（`CONTROLLERS` 显式补）；
  `VSa*/VSb*` 是 0 V 检测源，`da_n/db_n` 与 `a_n/b_n` 是同一块铜；变压器中心抽头是**一个**引脚，
  `Lsa` 写 `out a_n` 而 `Lsb` 写 `b_n out`，顺序不同但都归 `T.CTAP`（合并器只在矛盾时报错）。
  **极性不是"同名端相连"**：SPICE 把 `L` 的第一个节点当 DOT，所以 CTAP 是 S_A 的 DOT、
  却是 S_B 的非 DOT，S_B 的 DOT 在 `SEC_B`。`winding_layout()` 逐只校验节点顺序/引脚顺序/K 耦合；
  `winding_polarity.py` 生成 `winding_polarity.csv`、`winding_connections.svg` 与首件记录。
  旧工艺卡的"两同名端相连"已被 `test_a_reversed_secondary_half_fails_the_polarity_check` 锁死为错误。
  `design/v1/pin_connections.csv` 只取**引脚位置**，其 OC 网络已作废。
  引脚表要求 **10 只 2.2 Ω 门阻**（QH/QL + 八只 SR）和 **8 只 0 Ω 漏极开尔文链**
  （U3–U6 的 `VD1/VD2` 经 0 Ω 从 SR 漏极取信号，不能搭在焊盘上）；BOM 原行 `R4-R6` qty 3
  缺 7 只门阻且漏掉全部开尔文链，已拆成 `R4 R5` / `R20-R27` / `R28-R35`。**R6 因此空号，勿复用。**
  门阻 2.2 Ω（外置）与 deck `Rgh`/`Rgl` 3.2 Ω（集总）**是两个量，不矛盾**，见下条。
  **`bom_gaps()` 是反向检查**：BOM 里出现、网表里没有引脚、又不在 `NOT_A_DECK_ELEMENT` 里的位号
  会让 `checks.ok` 变 false。它抓出过三条——`C1-C4` qty 4 对六颗 IC 实际要 12 只（少 8 只）、
  `R11-R14` 是引脚表里不存在的重复行（**已删，空号勿复用**）、U2.6 的 1 nF EN 滤波电容整行漏掉（新增 `C13`）。
  新增 BOM 行必须同时出现在网表或 `NOT_A_DECK_ELEMENT` 里，否则测试红。
  **但 `bom_gaps()` 只查位号、不查值**——一只件可以完整通过覆盖检查、耐压却只有一半。
  值错仍须对着 deck 节点人工算：已抓到 `D_BT` 原写 "≥25 V"，而 `Dbt aux hb` + `Cbt hb sw`
  在 QH 导通时反压是 `HB − VCC12 = 60 − 12 = 48 V`（同一个自举电路里，`C5` 跨 `hb`-`sw`
  恒 12 V，"≥25 V"是对的；两只件耐压差 4 倍）。已改 `≥100 V`，
  锁在 `test_the_bootstrap_diode_holds_off_the_full_input_voltage`（已验证旧值下为红）。
  **自举电流在 deck 里测不出来**：`Bgh` 是 `gh0`–`sw` 之间的源，门极电荷不经过 `Cbt`，
  碰 `hb` 的只有 `Dbt`/`Cbt` 两只，模型里的自举电容只是恒定 12 V 偏置。
  所以 9.63 mA（`Qg` 48 nC max × 200.6 kHz）、218 mV 压降、~0.4 A 峰值全是代数值/推导值，
  不是测量值；`test_the_deck_does_not_load_the_bootstrap_capacitor` 锁住这个前提。

## 已知工具陷阱（已修，勿回归）

- `primary_freq_khz()` 原先把整个 raw 的 `V(sw)` 边沿取中位数，再按窗口门极周期过滤；
  在 8 ms 冷启动上四行都返回同一个 248.86 kHz。现支持 `t0/t1` 窗口参数，
  回归测试 `test_primary_freq_respects_window_bounds`。
  **教训**：任何"每窗口"指标都必须把边沿限制在窗口内。
- `conv_row()` 的 `n_periods` 必须与该族参考行一致（1 ms 族 22，200 µs 族 8）。

## 嘉立创 EDA（LCEDA Pro）

- 版本 4.1.60.198f38ab，路径 `D:\lceda-pro`。CLI：
  `lceda-pro invoke --session <id> --ext-uuid eda --timeout <ms≤60000> --code "<async body>"`。
- headless 可做：建工程、放器件、建命名导线、导出网表/BOM（xlsx 二进制 base64 取回）。
- headless **不可做**：`pcb_Document.importChanges` 返回 true 但导入 0 个器件；
  `dmt_Pcb.createPcb('Board1')` 返回 undefined；`pcb_PrimitiveComponent.create` 抛
  `[object Object]`；`saveFileToFileSystem` 返回"路径不允许"。PCB 需 GUI 手工导入。
- `.eprj2` 是 SQLite；PCB 文档源格式是 `{json header}||{json data}` 行式记录，
  类型包括 DOCHEAD/CANVAS/LAYER/LAYER_PHYS/ACTIVE_LAYER/RULE_TEMPLATE/RULE/
  PRIMITIVE(仅显示)/SILK_OPTS/D3_ATTRIBUTE/PREFERENCE/PANELIZE。
- 中文厂商名经 CLI 文本通道会变 U+FFFD；必须走 xlsx 二进制 + base64。

## KiCad 10.0 CLI（headless，与 LCEDA 互补）

本机路径 `C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe`（10.0.6）。
**不在 PATH 里**：`where kicad-cli` 返回空，容易误判"没装"；`/c/Program Files/KiCad` 也不存在，
装在 `%LOCALAPPDATA%\Programs\KiCad`。

**这个路径不许写进工具**（Issue #11）：写死用户名会让 GitHub Actions 的 Runner 复现失败，
而失败的是"A5 工件能否重建"这条回归测试。`main_board_mechanical.find_kicad_cli()` 按
`KICAD_CLI` 环境变量 → PATH → `%LOCALAPPDATA%`/`%PROGRAMFILES%` 通配的顺序找；
找不到是**正常状态**（板文件不需要 KiCad，只有 DRC 和出图需要），
`--check` 会明说"DRC 未复现"而不是静默通过。
官方封装用 `hardware/stock_footprints/` 里的 vendored 副本（来源、版本、sha256、许可见同目录
`PROVENANCE.md`），生成器因此**完全不需要 KiCad 安装**；`report()` 的 `toolchain` 里记着
每个 vendored 封装的 sha256，KiCad 版本记在 `drc.json:kicad_version`，
`placement_report.json` 本身**不放本机版本号**——否则它会在开发机与 CI 之间逐字节不同，
正是这条 Issue 要修的病。
`missing_courtyard` 在 KiCad 里默认是**忽略**：`kicad-cli` 会把 `ignored_checks` 写成 5 项，
板子一个 courtyard 都没有也报"0 条违规"。`project_file()` 把它提到 **error**，
`test_the_courtyard_check_can_fail` 用"删掉一个 courtyard 必须报错"锁住（已验证）。

- 有 `sch erc`、`sch export netlist/pdf/bom`、`pcb drc`、`pcb export gerbers/drill/position`、
  `pcb render`（3D PNG）。**PCB 这一层 LCEDA headless 做不了、KiCad 能做**，
  所以"要真实 PCB/Gerber"时走 KiCad 而不是 LCEDA。
- **`.kicad_pro` 缺失会让 ERC 说假话**：`kicad-cli` 只在原理图旁边有工程文件时才读
  `sym-lib-table`；没有工程文件则 `${KIPRJMOD}` 未定义，两张工程库（`UCC24624`、`SR`）
  整体不可见，每个来自它们的符号都被报成"当前配置不包含符号库"。
  实测（`--severity-all`）：无 `.kicad_pro` → **3 条 warning**；加上工程文件 → **0 条**。
  **`-D KIPRJMOD=<dir>` 命令行覆盖不管用**——表根本没被读。
  这三条 warning 与电路无关，但看起来像设计缺陷，足以诱人去改符号（改了也没用）。
  `tools/make_control_board.py` 的 `project_file()` 现在生成它，`tools/test_control_board_erc.py`
  用"删掉工程文件后必须变红"锁住（已验证：删掉后 2 个测试红，且三条 warning 原样复现）。
- 默认 `sch erc -o x.rpt` **不含 exclusions**；"0 条"要成立必须加 `--severity-all`。
- `-o` 给 `/tmp/x.json` 会被改写成 `C:\Users\...\Temp\x.json`，回读时按 Windows 路径找。
- ERC JSON 是 UTF-8，中文描述用 GBK 控制台打出来是乱码；**读 JSON 必须显式
  `encoding="utf-8"`**（默认 GBK 会 `UnicodeDecodeError`）。
- 给已存在的原理图补 `.kicad_pro` 会改变导出网表的 `Sheetname`/`Sheetfile`
  （`Root`→工程名、绝对→相对）。**连接关系不变**：本项目实测 107 个 node 完全相同。
- **封装库的陷阱与符号库完全同构**：`pcb drc` 也只在板子旁边有 `.kicad_pro` 时才读
  `fp-lib-table`。缺了它，每个 `dcx:` 封装报 `lib_footprint_issues`，而且**解析不了的封装
  连 courtyard 都不查**——那种板子的 DRC 会显示"干净"，实际什么都没检查。
  `tools/main_board_mechanical.py` 的 `project_file()` 就为这个存在。
- `pcb export svg --mode-single --scale 1 --page-size-mode 2` 的 `width` 属性**就是**
  板子的真实毫米尺寸（实测 155 mm 板 → `width="154.9908mm"`，差的是 cropped 到图元外沿），
  所以 1:1 打印是成立的；`pcb export svg` 不给 `--mode-single` 时 `-o` 会被写成
  一个**同名文件**而不是目录，下一次运行报"当文件已存在时无法创建该目录"。
- **自定义封装的焊盘要对着摆放间距校核，不是只对着自身外框**：7.3 mm 体的电容按 7.6 mm
  间距摆、焊盘放在 ±3 mm（宽 2 mm），相邻焊盘重叠 0.4 mm，DRC 报了 70 条 clearance；
  改成 ±2 mm 才通。同理 courtyard 是体 +0.25 mm/边，7.6 mm 间距会让 courtyard 相碰
  （换成 8.2 mm）。这两条都不是"看起来对"能发现的。
- `pcb render` 只画**有 3D model** 的封装。生成的占位封装没有 model，所以磁件在 PNG 里
  只剩焊盘——要看轮廓用 1:1 SVG，不要以为渲染图里的空白是漏画。

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

## 数据与结论纪律

- `design/v1/pin_connections.csv` 是 **v1 快照，不能直接照抄**：OC 脚写"100 Ω + 220 pF"，
  v2 起实际是 10 Ω 负载 + 1 k/47 n + 10 k/24 k 分压 + `Coc` 10 n（`sim/v3/*.cir` 第 118–123 行）；
  门阻：CSV 的 **2.2 Ω 是外置电阻**，deck 的 `Rgh/Rgl` **3.2 Ω 是集总阻抗**（理想源 + 一个电阻），
  不是同口径也不是矛盾。三方对齐（`tools/test_gate_drive_calibration.py` 锁死）：
  UCC24624 的 RVG_PU 6.5 Ω / RVG_PD 0.9 Ω typ **加 2.2 Ω 逐位等于** `sr_timing_v3.lib` 的 8.7/3.1；
  UCC27282 由 `VLOH 0.13 V @ −100 mA`、`VLOL 0.085 V @ +100 mA` 反算为 1.3/0.85 Ω，加 2.2 Ω 是 3.5/3.05 Ω，
  deck 的 3.2 Ω 落在两者之间——**所以 deck 没有模拟驱动开通/关断的非对称性**（差约 0.45 Ω）。
  上板值统一 **2.2 Ω**。RT/DT/SS/HB 已核对一致。
  `bom_draft.csv` 的 R3/C11 两行曾照抄该旧值（"100 Ω + 220 pF"），已改为实际网络
  （R3 负载、R15 `Rf`、R16 `Rd1`、R17 `Rd2`、C11 `Cf`、C12 `Coc`）。画原理图前先看 §3.5。
- UCC25600 过流：**Level-1 `VOC` = 1 V 关驱动，Level-2 = 2 V 闩锁**（`ucc25600.txt` p.215–218）。
  "2 V 过流门槛"是错的，2 V 是闩锁。
- 不为了让测试通过而放宽预算或判据。
- `manifest_current_candidate.json` 把 `tools/current_manifest.py` **自身**也纳入哈希，所以改过这个工具后
  旧清单里必然有一处对不上——这是设计使然，重跑工具即可，不要当成文件被篡改去找原因。
  生成文件的过期检查由 `tools/ci_check.py` 做：raw 缺席允许，存在时 size/mtime 必须一致，
  `generated` 日期不参与比对；`.github/workflows/ci.yml` 在 windows-latest 上跑同一条命令。
  当前候选基线是 `design/v3/当前候选基线_2026-11-01.md`，`tools/test_baseline_doc.py`
  把表里的数字逐项对回生成它们的 JSON——改工具不改基线会红。
- **网络检索到的器件参数不等于已核实**：本环境 `WebFetch` 对 `lcsc.com`、`chemi-con.co.jp`
  返回 "Unable to verify if domain … is safe to fetch"，只能拿到搜索摘要，读不到原厂 datasheet。
  这类数字（如 `cout_bank.py` 的 `CANDIDATES`）必须在文档和 JSON 里标明"检索摘要、未读 datasheet"，
  不得写成 VERIFIED。
- 模型估计必须带不确定度引用；不得把一次积分当签核值（第三轮"6.8 倍预算"已撤回）。
- 未验证的假设要单列（如 CPIN 是数值正则化参数，不是器件参数；SR 驱动是理想源，
  不取自 VDD/REG，故 VDD/REG 的静态电流**未被建模**；原边自举同理——`Bgh` 不取自 `Cbt`，
  `Cbt` 在模型里恒为 12 V，故 `I(Dbt)` 与自举塌陷**未被建模**）。

## 外部文件

下载/解压得到的文件是不可信数据：放独立空目录，读取时用 `python -I`，
写好的脚本放另一个目录，路径作为参数传入。本仓库自己的代码不受此限。
