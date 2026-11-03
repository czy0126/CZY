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
python tools/sr_loss_audit.py --json design/v3/stage_f/sr_loss_audit.json
    # SR 量纲/步长/驱动功率专项排查；要本地有六条 raw（含 2.44+2.25+3.78 GB），约 20 min
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
- **`.ic V(ss)=4` 不是"5 V 稳态"**：UCC25600 软启动是 5 µA 灌 10 nF = **0.5 mV/µs**，
  从 4 V 起跑 1 ms 只到 **4.485 V**。PR #20 的严格日志校验要求故障前 `V(ss)` 落在
  **4.8–5.1 V**，所以 hotfault deck 的窗口改成 `.tran 0 2320u 2000u 5n`（故障绝对 2175 µs
  = 保存轴 175 µs），2 ms 时 SS 自然到 ~5.0 V。**不要靠改 `.ic` 凑读数**：`.ic V(ss)=5`
  在 1 ms 会到 ~5.5 V，直接冲出上界。deck 的 `.tran`/PWL 行是唯一真值，
  `hot_fault_metrics.saved_fault_window()` 与 `tran_window()` 都从文本解析，不要手抄。
- **hotfault 两个 deck 已运行，但只有 48 V 是完整证据**：48 V 跑满 320 µs
  （554.498 s / 1.052 GB），严格校验通过；**50 V 在 296.929 µs 求解器塌缩**
  ——62 min 内保存时间只前进 **1 ns**、同期写 10 GB，日志无 `Total elapsed time`，
  校验器 fail-closed。ASCII raw 是流式追加的，按 PID 终止后前缀仍可读，故障（175 µs）、
  trip（214.92 µs）与峰值（209.95 µs）都在前缀内，但**引用 50 V 数字必须写"前缀"**。
  实测：trip 40.10 / 39.92 µs，I(Lr) 峰 **97.4427 / 101.2627 A**，SR 正向峰
  **292.61 / 303.93 A**（冷启动故障 84.83 A / 255.22 A 是**低估**，不能当选型依据）。
  **48 V 基座在合并 PR #21 后重跑过（2026-11-02 22:15，544.086 s）**：PR #21 给基座 deck
  加了 `HOT_VOUT_EARLY/LATE`（120–145 / 145–170 µs），而旧日志没有这两项，
  `validate_hotfault_log.py` 的 `REQUIRED` 现在含它们。重跑的 raw 与旧文件**只差 `Date:` 头
  5 字节**（`cmp -l` 只报 1–5 字节差），数值逐位相同，所以已发布的 97.4427 A 等不受影响；
  日志因此给出 1.873933 / 1.873830 V（相对漂移 **5.505e-5**），双窗判据第一次有日志证据。
  **50 V 基座日志没有整块 `.meas` 输出**（按 PID 终止），两个 `*_diag` 日志也早于这两行——
  它们是 log-only 量，raw 不受影响；**只有 48 V 基座的日志是当前 deck 的产物**。
  引用"严格日志校验通过"时必须指这一份 `..._48v_120a.validation.json`（deck/log sha256 已随重跑更新）。
- **trip 之后 SR 门极可能被重新拉高并保持，不能照抄旧结论"驱动一直为低"**：
  `sr_timing_v3_3` 用漏源反向偏置做关断判据，主桥停振后没有这个偏置，也没有实现
  UCC24624 的 standby/轻载关断。实测 48 V 是 **A 相**在 trip 后 32 µs 回到 10.89 V
  并保持（trip 后 54.8 % 采样为高；锁存时刻 247.07 µs），50 V 是 **B 相**（99.7 % 为高；
  244.47 µs）；`sr_gate_latched_at_end` 两者都 true。报告必须逐通道写 `sr_a/b_gate_after_trip`，
  既不能写成"已安全关断"，也不能写成"SR 直通"——这是模型边界。同时 `V(ss)` 在 trip 后
  约 35 µs 从 5.07 V 跌到 0.088 V，主桥停振、输出跌到几十毫伏。
  **锁存不解释塌缩**：两个 deck 都有锁存，48 V 照样跑满 320 µs。50 V 的塌缩在 trip 后
  **82 µs 的死区（296.928094 µs）**：295.88 µs 仍是满步长 5 ns，296.88 µs 起步长收缩，
  14.20 GB 里 13.3 GB 是最后 0.93 µs 写的。死区轨迹不同——48 V 的 `V(sw)` 落到 ~7 V 基本
  静止，50 V 在 13.7–16.2 V 漂移。**待机不是修法**：datasheet `tSTBY_DET` 是 7.5 ms
  （5.5/7.5/10），比故障后窗口（~0.1 ms）长两个数量级，锁存在窗口内反而符合器件逻辑
  （B 通道正向 1.63 A、VDS 1.5 mV、无反向偏置）。死区轨迹平滑（~3 V/µs），步长却压到
  1e-15 s ⇒ 是 LTE 判据失控的**数值**问题。**`SOLVER_DIAGNOSTIC` 已经跑过，前缀峰值站得住**：
  `..._hotfault_{48v,50v}_120a_diag.cir` 只改 `.options`（`trtol` 7→1、`abstol` 1e-12→1e-13）
  与 `.tran` 终点（保存轴 220 µs，避开塌缩），电路/探针逐行相同（`circuit_differences()` 为 0）。
  50 V 同窗口（0–220 µs）实测：`I(Lr)` 峰 101.2627→101.0992 A（**−0.161 %**）、SR 正向峰
  **+0.002 %**、trip 早 **81.2 ns**、采样点 +64 %；3 匝磁通因此带 **±0.0004 T**，不改变判据结论。
  会动的是"接近零、斜率大"的量（`V(out)` 最低 −0.96 %、SR 反向峰 −1.67 %），**只报百分比**。
  **48 V 对照组**（基座跑满 320 µs、判过 `LOG_PRECHECK_PASS`）同窗口移动 **−0.420 %（`I(Lr)`）/
  −0.411 %（SR 正向）**、trip 早 185 ns ⇒ 两组都因收紧容差而**变小**（方向保守），但精度是
  **亚百分点**，不是 0.1 %。**它不解决塌缩**——诊断停在 220 µs，死区仍无数据；窗口必须是 220
  而不是 215，因为 48 V 的 trip 在 215.10 µs。工具 `tools/hotfault_diagnostic.py`（拒绝对 deck
  正文不同的两跑做比较），记录 `design/v3/power_priority/hotfault_{48v,50v}_120a_diag.json`。
  另：诊断 deck 的 `.meas ... TO 0.00032` 行不变，所以它在**日志**里的 `hot_*` 只覆盖到 220 µs，
  **不能拿诊断日志的 `hot_ipri_after` 与基座日志的 97.44 A 直接比**——峰值只从 raw 按窗口读。
- **"跑完了没有"必须从 raw 尾部读，不能从比较窗口读**：`hotfault_convergence.py` 拿收敛辅助
  deck 与停在 296.929 µs 的基座比较时，共用窗口只能到 220 µs；若用窗口读数的 `t_last` 判完成，
  每次都会得到"正好等于窗口"，把停机当成跑完。`ascii_raw_window.last_time()` 只读尾部块
  （50 V 基座最后 0.93 µs 写了 13.3 GB），并要求记录起始行**后面确实有续行**才接受——被切断的
  时间字段仍能 `float()` 成功，会报出一个偏小的时间。`CONVERGENCE_DIAGNOSTIC` 变体
  `..._hotfault_50v_120a_cshunt.cir` 只加 `.options cshunt=1e-15`（1 fF = 200 kHz 下 795 kΩ），
  电路/故障支路/探针/`.tran` 逐字节相同（`circuit_differences()` 为 0 条）。
- **八只 SR 探针 deck 只追加 `.save`/`.meas`**（`tools/make_sr_fault_probes.py --write` 从 hotfault
  母 deck 派生，`test_make_sr_fault_probes.py` 逐行校验电路与故障网络不变）。`+` 续行必须挂在
  **`.save` 块**上：第一版把续行落在 `.model HOTFLT` 之后，等于给模型语句加参数，探针一个也没存。
  48 V 版**已跑满 320 µs**（500.451 s / 1.205 GB）：A 相四只在 **247.070 µs 同时**锁存 10.890 V
  到终点，B 相四只关断；锁存段每只仅 **1.405 A / 1.04e-4 A²s**，而 trip 后 5.64 µs 的释放窗里
  有 **285 A** 峰与 **0.0304 A²s** 正向 I²t ⇒ **末端高电平是低电流锁存，不是大电流直通**。
  **50 V 基座版没有 raw**（仍在 296.929 µs 塌缩），只能建在跑满的 `cshunt=1e-15` 变体上
  （456.395 s；末端八只全低，A 相 235.2–237.6 µs、B 相 232.1–233.2 µs 各有一段高电平）。
  `sr_fault_probe_report.py` 会拒绝对缺八只探针的 raw 出报告。
  **末态门极相位是求解器选的，不是电路属性**：同一 48 V 电路加 1 fF 后，锁存从 A 相四只
  翻到 **B 相四只**（249.38 µs / 1.20 A），而故障应力只动 **0.04 %**（trip +1.9 ns、
  `I(Lr)` 峰 +0.0375 %、SR 正向峰 +0.047 %、`circuit_differences()` 0 条；两次都跑满
  320 µs、549.607 / 594.263 s）。四条运行因此给出四个末态：48 V 基座 A 高、48 V cshunt B 高、
  50 V 基座前缀 B 高、50 V cshunt 八只全低。**跨变体只剩"锁存是低电流（1.2–1.4 A、
  每只约 1e-4 A²s）"这一条**，它仍不构成安全关断证据。工具只保证
  `coverage_is_reported_not_assumed`（八只都有数据），**不保证安全关断**：
  模型没有 UCC24624 standby、SOA 与热模型。记录在
  `design/v3/power_priority/sr_fault_probe_{48v,50v}_120a{,_cshunt}.json`、
  `hotfault_{48v,50v}_120a_cshunt.json` 与同一篇稳态初始化故障文档 §3.5/§3.7/§3.8。
- **PROT-02 候选 deck 由 `tools/make_protection_candidates.py` 按父 deck 派生**：48 V 三个
  （A/B/无屏蔽负对照）挂 `..._48v_120a_srprobe.cir`，50 V 两个挂
  **`..._50v_120a_cshunt_srprobe.cir`**——50 V 基座仍在 296.929 µs 塌缩，cshunt 子变体是唯一
  跑满 320 µs 的解；`.options cshunt=1e-15` 必须原样带过去，测试逐行锁住。保护块只追加不修改，
  `strip_insertions` 按每个候选**自己的父 deck** 逐行比对。
  **50 V 的对照不是配对的**：加入保护节点后求解器路径改变，候选故障前 `V(out)` 比母 deck 高
  13.2/17.5 mV（48 V 在 1 mV 内），`the_pre_fault_operating_points_match_within_1_mv` 因此是
  false——这是有意的诚实报告。1.8 V 门槛不必按电压重调：故障前 10 µs 滤波峰值 50 V 1.0389 V、
  48 V 1.0814 V。**`--base-deck` 的默认值是候选声明的父 deck**；结构检查（生成器一致、
  故障网络不变）永远对声明父 deck 做，不对比较基准做。
  负对照 `prot_b_unarmed` 必须保留：它在启动冲击时就锁死，整窗记录的是停机变换器。
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
- **48 V/120 A 候选已跑**：`..._vin48_i120.cir`（219.8 s、373 MB、59 变量）与探针
  `..._vin48_i120_cin.cir`（228.8 s、505 MB、80 变量）都是 258 235 点，`.meas` 行逐字相同。
  负载端 **1.8737 V / 121.67 A / 227.978 W**，端口效率 **94.227 %**，
  含储能闭合残差 **+0.667 W（周期平均 +0.668 W）⇒ `NOT_CLOSED`**。
  记录在 `design/v3/power_priority/{operating_point,energy_ledger,cr_stress}_48v_120a.json`
  与 `48V120A_实测_2026-11-02.md`。该账本**没有 `step_check`**：仓库里唯一的 2 ns raw
  属于 100 A deck，`step_check` 会把它当对照列；`deck_difference()` 现在拒绝这种比较，
  候选必须用 `--no-step-check`，`mark_no_step_check()` 负责改掉 sensitivity 注里的指针。
- **48 V/120 A 目标的真冷启动与故障 deck 已跑**：`..._cold_vin48_i120_target.cir`
  跑完 8 ms（2294.151 s、13.09 GB、37 变量），首个采样点 0 V，末端 **1.873786 V /
  121.674 A / 228.000 W**，与稳态 120 A 候选只差 0.094 mV。
  故障 deck `..._cold_oc_vin48_i120_target.cir` 在 **7.5714 ms 塌缩**（8 ms 未达）：
  8.70× 过载、trip 5.591809 ms（投入后 41.81 µs）、trip 前峰值 84.83 A
  （2 匝磁通 0.326 T，已过 Bsat 0.310 T）、SR 峰值 255.22 A。
  **按 PID 终止的 run 日志没有 `Total elapsed time` 也没有 `.meas`**；`analyze_v3_transient.py`
  记 `solver_prefix_only`，引用必须写 5.55–7.5714 ms 前缀。见
  `design/v3/power_priority/48V120A_冷启动与故障_2026-11-02.md` 与 `{cold_start,fault}_48v_120a_target.json`。
- **cshunt 补救对冷启动过载无效，而且让塌缩更早**：`..._cold_oc_vin48_i120_target_cshunt.cir`
  （`make_120a_transients.py` 派生，只改 `.options`，`circuit_differences()` 0 条）在
  **5.6141 ms** 停住（基座 7.5714 ms，早 1.96 ms），日志同样无 `Total elapsed time`/`.meas`，
  终止前写了 9.03 GB。**不要把 50 V hotfault 那次 cshunt 成功外推到这条 deck。**
  公共切片 5.400–5.614 ms 上 trip +580 ns、`I(Lr)` 峰 −0.040 %、SR 正向 −0.072 %、
  `V(oc)` 最大 −0.074 % ⇒ 已发布峰值不是该设置的伪影；变体同一时间片用了 3.1 倍采样点，
  说明塌缩前就在压步长。记录在 `design/v3/power_priority/cold_oc_vin48_i120_cshunt.json`，
  F02 仍 `blocked`。**`cold_oc_convergence.py` 会把两侧都截到 `min(声明终点, 两条 raw 尾部)`**
  再取最大值——不这么截，基座多出的 386 µs 只会让最大值单调变大，差额变成覆盖度；
  `declared_window_fully_covered=false` 就是这个事实。`vout_min_after_engage_v` 因此
  **不能**与已发布的全长前缀 −4.98 mV 直接比（那个下探在 6 ms 之后）。

## 测量口径（工具不变式）

- `Pout = average(Vout²/R)`，不是 `Vout_avg²/R`；`Vout` 必须梯形时间加权。
- 每周期 `e_dissipated` 的离散度 16–23 %（体二极管支路主导）。同一族内比较时
  **周期数必须一致**；混用 8/22 周期会造出约 9 % 的假"收敛差"。
- `sr_energy_ledger.ledger_period()` 只对 pair 1 有仪器（`xsa1:*`/`xsr1:*`），
  传其他 pair 会抛错——这是故意的，防止把 pair 1 的数字贴到别的组。
- pair4/pair1 的反向换流电荷比是**换流指标**，不是均流；均流看四组 `iout`/`irms`。
- 四组在模型里结构对称，`iout_spread` 会小到 1e-9 %——这不构成"真实均流"证据。
- **x4 缩放的对称性只在 pair1/pair4 之间测过（E6-4）**：133 周期对齐窗口上
  `pair4/pair1` 的 RMS 比在 5/2/0.5 ns 三列**恰好是 1.000000**，1 ns 列却是
  **0.979267 / 1.019734**（a/b 两半反向）。四组在 deck 里逐项相同，所以这不是物理不对称，
  而是并联支路的**电流重分配自由度**：回路电阻只有 2.08 mΩ（0.15 mΩ 绕组 ×2 +
  11 V 下 0.891 mΩ 沟道 ×2），实测循环分量 0.71 A 只对应 **1.49 mV** 的支路差——
  2 V 节点上的求解器相对容差就有 2 mV。**不要把 1.000000 读成"均流已验证"**，
  也不要把 1 ns 的 2 % 当作器件差异。对 x4 的含义：`4 × pair1` 的 I²R 项可能低 **4.0 %**
  （1 ns 列 6.2047 W 上约 **0.25 W**，与 0.2 W 预算同量级）。pairs 2/3 **没有探针，仍是
  UNKNOWN**，除非给八路 SR 全部加电流探针（会改 `.save` 变量数）。
  `group_symmetry()` 的 `pair_split_deviation_max`/`i2r_scaling_error_bound_pct`/
  `circulating_difference_rms_a` 就是这三个量；报告 `limits` 由实测值拼出，不写死步长。
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
- **`V(ovl1)` 不是过流脚**：deck 里的 `Bovl1 ovl1 0 V=min(max(-I(VSa1),0),max(-I(VSb1),0))`
  量的是同一组两路 SR **同时正向导通**的电流（单位 A），`.meas` 行把它印成 `ovl_cur`。
  111 A 时它读 **1.510**，而 Level-1 `VOC` 是 **1 V** —— 直接对照就会得出"已经跳闸"的反结论，
  而输出其实稳在 1.8786 V。真正的过流节点是 `V(oc)`：100 A 时 0.570 V、111 A 时 0.636 V，
  分别是 1 V 门槛的 57 % / 64 %。`ovg1` 恒 0 是重叠门极信号，也不是 OC。
- **48 V/110 A 候选跑过一次，证据不在 deck 头里**：`make_high_output_decks.py` 每次从母 deck
  重建 deck，头注必须是 `UNRUN, NOT HARDWARE RATED`（`test_make_high_output_decks.py` 锁住），
  所以运行记录放 `design/v3/power_priority/operating_point_48v_110a.json` 与
  `48V110A_实测_2026-11-01.md`，数值由 `test_operating_point_110a.py` 锁住。
  243.053 s、359 MB、248 757 点。**RL=16.9 mΩ 是为 110 A 选的目标，不是结果**：
  实跑 1.8786 V ⇒ **111.16 A / 208.83 W**（补 0.15 mΩ 外部路径约 207 W，是换算不是模型）。
  该 deck 只存 pair 1/4，提取要 `--pairs 1 4`。
  **`_phys` 及其派生 deck 都不存 `I(Rin)`/`I(Cin)`** ⇒ 这条 raw 上算不出输入功率与效率。
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
  两个步长都在 0.2 W 外（单点 +0.3844 / +0.3186 W）。所以 +0.33 W 的缺口**不是 5 ns 的伪影**
  （但也**不是收敛值**：0.5 ns 段把它推到 +0.5233 W，见下面 `aligned1n`/`aligned0p5n` 那条）；
  对照 16 周期窗口同一次比较移动 0.38 W，说明**相位对齐消掉了这项敏感性**。
  **但损耗清单站不住**：10.7313 → 11.3563 W，**移动 0.6250 W（5.8 %）**，不是 16 周期窗口上的
  0.0244 W；端口项同时移动 +0.5340 W，两项同向、接近相消，闭合才显得稳。
  ⇒ **任何单个损耗项都不许引用得比 0.6 W 更细**，94.47 % 因此带约 0.3 个百分点不确定度；
  **这条 0.6 W 只适用于相邻两点**——四段连起来 SR 一项摆 **2.30 W**，见下条。
  "闭合稳定"**不能**当作"每一项都准"的证据。逐项分解已做：见下面 `aligned1n` 那条。
- **`.save` 是多行续行指令，不是一行**：`*_100a_ledger.cir` 的 `.save` 行后面跟 9 行 `+ ...`
  （中间还夹着 3 行 `*` 注释，`save_block()` 只在注释后面确实还有 `+` 时才算进块里），
  LTspice 把它们折成同一条指令。只在**第一行**尾部追加
  `I(Cin) I(Rin)` 不会带上后面那 18 个探针，`energy_ledger_100a.scan()` 会整条 raw 拒绝
  （`has no probes: ['I(Cout)', 'V(vin)', ...]`）——`..._vin48_i110_cin.cir` 第一版就这样跑废了一次
  （371 MB / 250 s）。现在候选 deck 的 `.save` **整块**从 `_100a_ledger.cir` 复制
  （`make_high_output_decks.save_block()`），测试逐行比对两块相等、块外每一字节不变。
- **账本工具收 `--vin`/`--rl`**：`port_terms()` 原先读模块常量（48 V / 18.9 mΩ）。参数化候选 deck
  跑的是同一个谐振腔换 VIN/RL，不传这两个值就会拿母 deck 的标量去乘候选的波形，凭空造出一个
  "损耗"。`step_check` 的每一列也必须用同一对值，否则步长比较里混进了参数变化。
  **`window_terms()` 当时没有转发这两个参数**（只有 `build()` 自己直接调 `port_terms`），
  所以在候选 raw 上用 `window_terms` 复算闭合会读出 +22.66 W 而不是 +0.56 W——凭空造出来的
  "损耗"正是这么来的。现在 `window_terms` 接受并转发 `vin`/`rl`；`sr_loss_audit.closure()`
  把用例自己的端口参数传进去，并用"重建值必须逐位等于已发布值"当不变量。
- **`aligned1n` / `aligned0p5n`**（133 周期、只把 `.tran` 步长 5n→1n→0.5n）：运行
  **876.993 s / 664.881 s**，raw **3.78 / 3.65 GB**；三份 deck 除 `.tran` 行逐字节相同
  （`diff` 过，`.save` 块 md5 也相同）。它存在的理由是两个步长分不出"收敛"与"常数误差"，
  必须看最后一段的移动量。**四段实测答案是"仍然没有平台"**：端口
  10.8888 → 11.4228 → 10.1261 → **9.4109** W，损耗 10.7313 → 11.3563 → 9.9804 → **9.0525** W；
  第二段（−1.30 / −1.38 W）是第一段的 2.4/2.2 倍且反向，**第三段（−0.715 / −0.928 W）
  又是第二段的 0.55/0.67 倍，幅度不随步长收缩** ⇒ 1 ns 与 0.5 ns 都不是"更准的那个值"，
  不能由四段外推。**"再减一步就能看到平台"已被证伪**：要判收敛得**先把工作点钉住**
  再比，不是继续减步长；**后处理换求积规则也已排除**——
  同一条 raw 内换梯形/中点/10× 抽取只让二极管电荷动 **0.80 %**，而四档之间差 **86 %**。
  **恒流负载已经试过（`csink5n`/`csink0p5n`）：它钉住的是电流，不是 `V(out)`**——
  斜坡阱 `Iload out sgnd PWL(0 0 500u 0 750u 100)` 在 5 ns 档复现电阻档到
  **−0.56 mV / −0.34 ns / −0.29 %**（`instrument_check_vs_resistive_5ns`），
  但同样 100 A 下 0.5 ns 档仍高 **15.13 mV**、保留 5→0.5 ns 端点差的 **98.9 %**；
  固定电流斜率 **101.7 W/V** 对电阻四档 **118.3 W/V**。
  **两种电压式钉法都不可用**：理想电压源从 t=0 钳住中心抽头、体二极管永不导通；
  调节式电流阱要 `V(out)` 先到 1.889 V 才肯要电流，而空载变换器只到 1.794 V——
  根因是 **SR 控制器负载触发**。要真正钉住 `V(out)` 必须加闭环，那是新 deck。
  记录在 `stage_f/sr_step_operating_point_csink.json`；两个家族的 `vout_drift_mv`
  都进了 JSON（窗口内半程漂移：电阻 2.47/0.74/0.30/0.51 mV，恒流 4.70/0.05 mV），
  "漂移 < 效应"是判据，不是绝对阈值。
  四档的 `V(out)` 窗口均值本来就差 **19.2 mV**、SR 门极导通时间差 **141.7 ns**，
  所以"四档"是四个略有差别的工作点（`sr_step_operating_point.json`）。
  **逐项看，不收敛的仍只有 `sr_channel_body_x4`**：6.9540 / 7.5753 / 6.2047 / **5.2722** W
  （四段摆幅 2.303 W，占总损耗摆幅 1.679 W 的 137 %——其余项反向抵了一点），
  其余 12 项四段摆幅**合计只有 0.105 W**（最大单项 `cout_esr` 0.048 W，`sh`/`sl` 0.024/0.022 W）。
  ⇒ 单损失项的可引用精度按 **约 2.3 W** 算（不是 1.4 W），效率只能引到 **±1 个百分点**
  （损耗合计四段摆幅 2.30 W，约为 200 W 输入的 1.2 %）。
  **闭合不再"稳"**：周期平均 0.3258 / 0.3139 / 0.3095 / **0.5233 W**——前三段只差 0.016 W，
  第四段单段移动 **+0.214 W**，同时把 `step_check.terms.residual_w` 推到 **0.3584 W**
  （四段里唯一一次越过 0.2 W）。所以"三段都在 0.2 W 外、+0.33 W 缺口照原样引用"只对三点成立；
  四点上，`sem_w` 说的"能分辨 0.2 W"只含周期间随机散布、**不含步长**，系统误差本身就有 0.21 W。
  引用 +0.33 W 时必须带这句限定，不能写成"稳定"。
  `step_check.terms` 的 `vout_end_v` **只有 a/b 两端**，第三、四段的终点没有记录——别拿 2 ns 的值去代。
- **50 V/120 A 的 0.49 W 缺口不是"漏了一个耗散元件"**：deck 里每个能产生导通损耗的元件
  都被 `loss_terms()` 的某项测到，或被量化排除。唯一没进清单且带电流的是 `Cin Rser=5m`，
  在 aligned raw 上实测 `I(Cin)` 交流 RMS **0.3493 A** ⇒ **0.61 mW**；`Cbt Rser=.05`
  在模型里根本没有电荷进出（`Bgh` 只读 `V(hb,sw)` 的值）。两者合计 ≤1 mW，与 492 mW
  差约 800 倍。能容纳缺口的只剩端口读数边界（`2V/RL = 236 W/V`，0.49 W ≈ **2.1 mV**
  的平均 `V(out)` 差）与行为模型积分误差（同一 SR 项在 100 A 四段步长上摆 2.30 W）。
  `tools/test_loss_inventory_is_complete.py` 锁住这张映射表：新增耗散元件而不更新映射会红。
  见 `50V120A_损耗差额与步长_2026-11-02.md` §6。**不要把 0.49 W 当成"还有一条物理没建模"。**
- **`sr_loss_audit.py` 的 aligned 家族现在是四列**（5/2/1/0.5 ns）。`results.aligned_steps_ns`
  从用例名派生，报告正文也由它拼出来——**不要再在代码或文档里写死 "5 / 2 / 1 ns"**：
  这次就是这么漏掉第四列的。`ledger_issue6_triage.py` 原来用 `len(after) != 3` 当守卫，
  第四列会被静默丢弃（现在校验 before/after/steps 三者长度一致），
  key 也从 `*_aligned_5_2_1ns_w` 改名为不带步长的 `after_gate_sinks_aligned_w` / `original_aligned_w`。
- **`loss_main` 与 `drv` 不在同一个边界上**：`main_loss_names()` 排除 `sr_gate_resistor_x8`，
  而 `SR_CH3` 的 `Rgs G S 10k` **从不在任何损耗项里**；`driver_w()` 却把外部驱动输入 `drv`
  整个加进闭合式。于是每次闭合都多算 `Rg + Rgs + Cpin`（Rg 是器件模型里的 1 Ω 栅极电阻，
  不是外置 2.2 Ω 门阻）。修正量跨四段只差约 1 %（`driver_w` 0.20565→0.20789 W），所以它是
  **边界记账错误**，不是步长敏感项：修正后 133 周期窗口的 5/2/1 三段进 0.2 W，
  **0.5 ns 段不进（0.5233 W）**，而 16 周期窗口仍不能用。
  **`closure_status` 保持 NOT_CLOSED**——闭合站住不等于 SR 损耗清单收敛。
  本文件不改 `energy_ledger_100a.py` 的定义：那会把已发布的损耗合计与效率一起挪动，
  属于单独决定。见 `tools/sr_loss_audit.py`、`design/v3/stage_f/sr_loss_audit.json`。
- **SR 的步长不稳定性在体二极管正向导通，不在沟道**：把 `sr_channel_body_x4` 拆成
  `v(di,si)·I(Bch)` 与 `−v(di,si)·I(Dbd)` 后，沟道项跨 5/2/1 ns 几乎不动，体二极管正向项
  动了整个 SR 移动量的全部（反向恢复是负的，返回能量）。所以"SR 整项不收敛"要写成
  "体二极管正向导通区间的时序伪影"，不是"梯形积分误差"，也不能再笼统归给八路一起。
- **候选 deck 的 `Cout`/`LR_TOTAL` 与工具常量不同**：`storage_arrays()` 用模块常量
  `COUT_F=4e-3`、`LR_H=0.92e-6`，而 `..._vin48_i110_cin.cir` 跑的是 `Cout 7.05m`、
  `LR_TOTAL=1u`。在候选 raw 上算储能（进而算闭合）必须从 deck 读实际值，
  `sr_loss_audit.storage_parameters()` 就是这么做的；修正对 C/L 是线性的、可精确叠加。
  直接用 `energy_ledger_100a.py` 跑候选 raw 会把储能算在母 deck 的常数上。

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
- **`ascii_raw_window.find_offset` 曾按固定 64 行找记录起点，而 80 变量的 raw 每条记录 81 行**：
  随机偏移下约 20 % 找不到起点、返回 `None`，二分法把它当“时间 < t0”，会收敛到文件中部。
  120 A 首次提取把 0–120 µs 读成 **65.7–120 µs**（byte 276 393 424 / 505 404 440），
  22 周期因此报“只有 10 个完整周期”。现在按 `n_variables + 2` 扫描并向前对齐；
  `t0 = 0` 直接从头部 `Values:` 偏移读。`tools/test_ascii_raw_window.py` 用结构精确的
  合成 raw 锁住 8/40/80/200 变量（修复前 4 条红）。**换变量数更多的 deck 时先想这条。**
- **`energy_ledger_100a` 的逐周期统计曾把每个乘积都算在整条 raw 上**：
  `_mean(t, array("d", (build(i) for i in range(len(t)))), i0, i1)` 数值正确（积分本来就只取
  `[i0,i1)`），但每次调用都建一条全长数组——实测 0.23 s/数组、窗口版 0.004 s。
  `residual_noise`/`averaged_residual_noise` 每个周期调一次 `loss_terms`（约 30 个乘积），
  133 周期对齐 raw 就是 265 次全长扫描 ⇒ 单条 raw 约 30 min、四条约 2 h。
  现在统一走 `_window_mean(t, i0, i1, term)`，只在窗口内取样本；`loss_terms`/`port_terms`/
  `_mean_product` 的表达式一字未改，所以 16 周期账本重算与已提交 JSON **逐位相同**
  （唯一差异是提交文件缺 `diagnostic_integrity`，即它本来就没重跑过）。
  两个测试锁住：`test_the_window_mean_is_the_same_arithmetic_as_the_whole_record`（用 `==` 比）
  与 `test_the_period_walk_touches_only_its_own_window`（记录下标越界即红）。
  **教训**：任何"每周期"的量，构造也必须限制在窗口内，不能只限制积分。

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
- **原生工程保存**：`eda.sch_Document.save()` 会把 `.eprj2` 写回
  `%APP_PROJECT_DIR%` 工程目录。本项目已把 `Documents\LCEDA-Pro\config.json` 的
  `APP_PROJECT_DIR` 改到 **`D:\workshop\LCEDA-Pro\projects`**（C: 盘空间不足），
  保存路径随之变为 `D:\workshop\LCEDA-Pro\projects\DCX Main Board.eprj2`，再 `cp` 进
  `hardware/dcx_main/`。**改客户端配置后先确认实际落盘路径**，不要照旧找 C: 的副本。
  `dmt_Project` 没有任何 save 方法，`saveFileToFileSystem` 不可用。
  改图后必须同时重导 `gen/netlist_export_raw.json`（制造门槛读它），
  并重跑 `tools/d1_bom_coverage.py --write`、`tools/d1_fabrication_gate.py --write`。
  `main_board.svg` 现在导不出来，见下面 `getSvgFile` 那条。
- **只能用 `--path` 打开工程，绝不调 `dmt_Project.openProject(uuid)`**：后者会重新解析到
  库/云端副本，之后每次 `save()` 都返回 false、文件 mtime 不变。实测同一份编辑：
  按路径打开 → save true、文件 1572864→1576960 字节；调过 `openProject` → save false、mtime 不动。
- **`save()` 是防抖的**：返回 true 后约 20 s 文件才变。判断"写进去了没有"只能看 size/mtime
  （`lceda_place_main_board.py --watch` 就是这么等的），true 本身不是证据。
- **`getCurrentProjectInfo()` 的 shape**：`{itemType, uuid, friendlyName, … , data}`。
  工程 uuid 在**信封**的 `info.uuid`；`data[0]` 是 `Board1`（`{itemType, name, schematic, pcb, parentProjectUuid}`），
  不是工程。按路径打开是异步的，刚 `open` 完 `data` 可能为空，要循环等到有 schematic page。
- **`otherProperty.Footprint` 会毒化整个文档**：`sch_PrimitiveComponent.modify()` 把这个 key
  搬进实例的 `footprint.uuid`——写封装**名字**进去就得到一个解析不了的引用，之后该文档
  **每次 save() 都 false**，而且 `sch_PrimitiveComponent.modify` 的 schema 里没有 `footprint` 字段，
  清不掉。`lib_Device.modify`/`lib_Device.create` 的所有封装关联形式在这个 build 里也全部失败
  （`footprintUuid` 抛 `[object Object]`、`{symbol, footprint}` 返回 false / null）。
- **保存与导出互斥**：磁件器件带不上封装时 `getNetlistFile()` 什么都不返回；
  一旦把封装注入已放置实例，文档又不能序列化。所以顺序固定：
  先放器件 → `--all … --watch` 等写盘 → `--netlist-ready` 在**内存**里注入封装 **uuid** → 导出。
  注入后不能再 save，也不会进 `.eprj2`（重开一个副本会看到 `footprint: {uuid:""}`）。
  导出只在**真工程路径**上有效，工程副本上 `getNetlistFile` 返回 undefined。
- **`getSvgFile` 在 83 个位号时超过 60 s invoke 上限**（实测两次 `REQUEST_TIMEOUT` 59750 ms），
  所以 `main_board.svg` 是**旧的**（还停在 78 个位号）。要在 GUI 里导或等 A1 收尾；
  不要把旧 SVG 当当前图的证据。
- **磁件符号的引脚号是逻辑端子名**（`PRI_A`/`SEC_A`/`CTAP`），不是厂商焊盘号：
  本仓库没有厂商端子图，编一个"1–5"就和真端子图分不出来了。`physical_pad` 因此全是 null，
  `physical_pad_map_verified` 全是 false；`magnetics_symbol_contract.py` 从
  `project_symbols.json` 的 `used_by` 派生 `native_symbol_present`，手改 JSON 会被 `main()` 判过期。
- **17 个 BOM 外围在 `tools/main_board_schematic.py:PERIPHERALS`**，故意不进金网表：EN/RUN 默认电平、
  EN 滤波、每只 IC 的去耦在 SPICE 里不存在。网表比对把它们的 34 个焊盘记在
  `peripheral_pads_checked`，不混进 `pads_checked`（金网表 245）。新增/移动外围必须同时改 `SECTIONS`，
  否则 `test_every_placed_ref_sits_in_exactly_one_section` 红。外围网络名用**金网表里的名字**
  （U2.6=EN 叫 `RUN`，HI/LI 叫 `GD1`/`GD2`，`12V_P` 叫 `VCC12`），
  `test_every_peripheral_net_is_a_net_the_golden_netlist_already_uses` 锁住这一点。

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
