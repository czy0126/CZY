# 仿真 deck 事实（冷启动 / 时间轴 / raw / 塌缩）

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- 仿真文件

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
- **2 fF 的 v3_4 软轨配对已跑完，资格只写在分析记录里**：`run_prot03_bage_diagnostic.py` 的
  `run_manifest.json` 把 `both_320us_qualified`/`pre_fault_1mv_qualified`/`fabrication_approved`
  **恒写 false**（设计使然），完成与否只看
  `protection_candidate_50v_120a_prot_b_paired_agefix_2f.json`、
  `prot03_bage_agefix_2f_B_{CONTROL,CANDIDATE}_vs_v3_3.json` 与
  `tools/prot03_50v_evidence_decision.py --write` 生成的 `B_2fF_agefix` 段。
  **软轨对候选完全惰性**：v3_3 与 v3_4 在候选 220–320 µs 的 23,540 个采样点逐位相同；
  控制首个差异在 **228.884000 µs**（trip 215.0359 µs 之后，正是 v3_3 压步长的死区）。
  0–220 µs 两侧七项指标差值恰好 0.0——模型改动在窗口内函数值不变时 LTspice 给逐位相同轨迹，
  这不是缓存。`prot03_bage_model_check.py` 的 `post_window_scan` 只定位分岔时刻、**不测峰值**，
  不要把这段写成 220 µs 之外的测量或硬件 SOA 证据。见
  `docs/D1_EXECUTION_KIT/26_B组2fF软轨配对跑满320us与逐位比对.md`。
- **PROT-03 的两条判据在 50 V 上不能同时成立**（2026-11-03 四份对照跑完，结论冻结）：
  要同时满足「故障前 35 µs 内 `V(out)` 配对 ≤1 mV」和「两个 320 µs 窗口都跑满」。
  `_thrmute_control.cir` 只把 `Bprot` 的触发常数（1.0/1.8 V → 100 V）改掉，**精确配对**
  （故障前差 **0.000000 mV**，触发前 961 298 / 824 449 个采样点逐位相同），但按 PID 终止在
  **250.151 / 254.980 µs**；`_noclamp_control.cir` 只把 `PROT_KILL` 的 `Vt .5`→`10`，跑满
  320 µs，故障前却仍差 **13.201 / 17.474 mV**。**漏流不是原因**：`prot_switch_leak_probe.cir`
  实测两个门槛的关断漏流都是 **1.001e-9 A**，13–17 mV 是求解器路径改变（开关节点导通点不同），
  不是残余钳位——所以不要试图用降低漏流来"修"配对。两条判据互斥时**不许二选一当通过**：
  `paired_change_can_be_attributed_to_protection` 对 noclamp 行是 false，50 V 的保护收益只能
  写成"截断切片值"或"完整但未配对"。六次运行已填进
  `docs/D1_EXECUTION_KIT/templates/simulation_run_register_PROT03_2026-11-03.csv`（新副本，
  不改空白模板），两个 thrmute 行 `full_duration` 写 `KILLED_BY_PID`，端口/账本列 `PENDING`；
  `tools/test_prot03_run_register.py` 逐行回查。见 `PROT02_独立故障锁存候选对照_2026-11-03.md` §5.6/§7。
  **实跑入口**是 `tools/run_d1_50v_matched_cases.py`（见"运行与测试"）：它只判 320 µs 完整性，
  `run_manifest.json` 的 `pre_fault_1mV_paired_verified`、`ten_physical_gate_shutdown_verified`、
  `fabrication_approved` 恒为 false；配对与否要另用 `protection_candidate_compare.py` 才算得出来。
- **cshunt 阶梯非单调，别按"再加一点更好"往上扫**：50 V 的 B 控制三档停点分别是
  **1 fF 254.980 µs（超时被杀）/ 2 fF 264.515 µs（求解器自己放弃）/ 5 fF 235.890 µs（超时被杀）**，
  5 fF 比 1 fF 还少 19.1 µs。三条尾部步长都到亚飞秒（0.02–0.32 fs），**cshunt 只挪动塌缩发生的
  时刻与退出方式，不移除塌缩**；`cshunt` 对失败实例 `xsr3:x2:Bage`（行为源）没有直接作用，
  "再多一点"没有机制依据。**≤1 mV 配对那条从来不是瓶颈**：1/2/5 fF 三档故障前差都是
  0.000000 mV，卡住的始终是"控制跑满 320 µs"。10 fF 因此没跑。5 fF 的 B 候选两侧 `trip_s`
  都是 `null`（`V(oc)` 峰 0.7069/0.7063 V < 1 V）：候选被自己 1.8 V 的比较器在 185.278 µs 切掉，
  比控制的 215.058 µs 早 29.78 µs，原边电流没把 CT 负载推到 1 V。见
  `18_50V成对数值收敛扫参与执行.md` 末节与 `solver_sweep_5f_*`。
- **登记表的 `deck_sha256` 是仓库规范化 LF 文本的散列，不是 LTspice 实际打开的字节**：
  这台机器的 `.cir` 工作区是 CRLF（`git ls-files --eol` 显示 `i/lf w/crlf`），
  LTspice 批处理读的是 CRLF 字节。两者只差换行符，但按字节算哈希就不相等——2 fF A 组与
  5 fF B 组两次都撞上。规则是：登记表写 `canonical_deck_sha256()`（CRLF→LF 后）的值，
  执行时的 CRLF 散列另存 `prot03_{2f_A,5f_B}_deck_hash_provenance.json`，
  `test_prot03_run_register.py` 逐条回查两个值。**RAW/LOG 的 sha256 不做任何归一化**——
  那是波形字节，不是文本。
- **B 源的正电流离开节点，所以锁存清除项是 `+V(node)*(1n/TAU)`，不是 `-V`**：
  `-V` 是正反馈。这个 bug 一直没暴露，因为五个功率级候选的 `Vddp` 恒 12 V ⇒ `V(uvlo)≡0`，
  清除分支**从未被选中**；第一次真正掉电重启的 `prot_latch_restart_check.cir` 直接发散到 **1e86**。
  改这一行对已发布 raw 的数值影响为零（分支不可达），但任何重启动 deck 都必须用 `+V`。
  另外这个显式积分器要求 `.tran` 最大步长远小于 τ=100 ns——**10 ns** 可用，100 ns 发散。
  测试 `test_the_latch_clear_terms_drain_the_capacitor` 逐份锁死。
  重启时序只在**逻辑级子电路**里验证（`sim/v3/prot_latch_restart_check.cir`，
  `protection_candidate_compare.py --restart-raw` 出 `protection_restart_check.json`）：
  20 µs 掉电后 `inhib` 保持 1、双锁存清零、软启动斜坡内脉冲不锁存、`V(ss)` 过 4.8 V 后
  **9.72007 ms** 重新 arming、10.3 ms 脉冲重新锁存。它**不证明功率级能重启动**，
  也不覆盖斜坡段（那段门极仍被驱动，只能靠控制器自己的 OC，本 deck 没建模）；
  完整功率级重启需要 9.6 ms 软启动，装不进 320 µs 故障窗口。
- **逐器件保护表不能混窗口**：`protection_soa_table.json`（`tools/protection_soa_table.py`）
  把 `sr_fault_probe_*`（`post_trip`）与 `protection_candidate_*`（`saved_window`）并排，
  同一台 48 V deck 的 `drain_min_v` 因此是 −2.825 对 −4.890 V——**不要相减**，也不要把
  285.01 A（post-trip 峰）与 292.61 A（全窗峰）当成重复测量。候选对照 JSON **不保存反向峰**，
  表里是 `null` 并在 `unrecorded_fields` 里列出，不是 0；`gate_last_rise_us` 对从未升高的
  器件也是合法 `null`（`null_by_design_fields`）。没有厂家 SOA 曲线，380 A 只是询样筛选目标；
  反向电流是端口量，**不许按 `Vgs` 拆体二极管/沟道**（第二轮审核已撤回该推理）。
- `Tstart` 会**重排保存的时间轴**：raw 里的 `0..120 us` 实际是 `880..1000 us`。
  任何窗口都要同时记录 `raw_time_start_s` 与 `display_offset_us`（manifest 已如此）。
  这两个值现在由 `current_manifest.deck_timing()` 从 deck 的 `.tran` 行解析，并与 LTspice 日志里的
  `FROM 0 TO x` 交叉校验（`tools/test_current_manifest.py`）；**不要再手抄**，也不要从日志反推。
- 冷启动 raw 10.7 GB、1400 万点、31 变量。PyLTSpice 是纯 Python 逐行解析，
  `load()` 一次约 20 分钟、约 3.5 GB 内存。只想看尾部时**不要**整文件加载：
  ASCII raw 每个时间点占 31 行（首行 `序号<TAB><TAB>时间`，其余每行一个值），
  可 seek 到文件尾部、对齐到非 TAB 开头的行后逐记录解析。
- **二进制 raw 的布局已有权威实现：`tools/poc_raw_evidence.py:inspect_raw()`**。
  头是 **UTF-16LE**，`Flags: real`，`Binary:\n` 之后每条 = **1 个 double 时间 + (N−1) 个 float32**，
  `stride = 8 + 4×(N−1)`（23 变量 = **96 B**），并用
  `size == offset + No.Points × stride` 做整除自检。**不要自己按全 double 解**：
  184 B 的读法不报错，只给出胡说八道（把时间读成 **2.097e6**）。要新写读取器时先看这个文件。
- **二进制 raw 是边算边写的，而且失败运行的头里 `No. Points` 是真实条数**：
  2026-11-09 在 `_probe_10a_sr_on_itl4.raw`（118 410 072 B，收敛失败）上核对，
  头写 1 233 422 = `(size − offset) // 96`，余 0。所以"跑到哪了"不必等进程退出，
  直接按 stride 数记录即可。（ASCII 早停运行的头部仍是 0，PyLTSpice 因此拒读——
  见 `ascii_raw_window.py` 文档串。）
- `tools/ascii_raw_window.py --step-profile` 按模拟时间分箱报 dt，并给每个阈值**第一次**
  低于它的步长。日志只报最后那一点（"Time step too small … trouble with node a1"），
  读起来像单点事件；实际 10 A SR_ON 从 0.5 ms 起步长就压在 **9.758e-19** 地板上，
  1.355 ms 是求解器**放弃**的时刻，不是**开始**挣扎的时刻。`uic` deck 的 t=0 第一步
  约 1e-13 s，所以"第一次短步"永远是初态——要传 `t0` 越过它再叫塌缩。
- **10 A SR_ON 的 1.3551 ms 塌缩是矩阵条件数问题，单加 `gmin=1e-10` 就能跑满**（2026-11-09，winsrv）：
  默认设置下 deck 在 **1.3551245612727640e-03 s** 放弃；只加 `itl4=100` 仍在
  1.3550837502308854e-03 s 放弃（165.3 s）⇒ 不是"迭代次数不够"，是那一步不可解；
  只把 `.options` 改成 `... method=gear gmin=1e-10`（deck 只多 11 字节）则完整跑到 8 ms
  （9 453 598 点 / 907 547 068 B / 1121.1 s / 64 线程 / 日志无错误行）。
  `method=trap`、把 `Vreg` 斜坡提前 1 ms、把斜坡上限压到 8.0 V 也都能越过 ⇒ 不是单一物理事件，
  但**唯一的充分单变量开关是 `gmin`**。
- **用 `gmin=1e-10` 得到的 10 A 数不是默认模型的证据**：同选项的 5 A SR_ON 对照（1520.2 s）
  九项 `.meas` 最大偏移 **0.5233 %**（`poc_vout_6_8_avg` +0.4244 %）。偏移远小于本项目的
  测量离散度，但它不是零 ⇒ 引用 10 A SR_ON 必须同时写明"非默认求解器选项"，
  **不得与 5 A 的默认设置证据并列成同一口径**。
- **PoC 低电流证据现状 = 三条全窗 + 一条塌缩**（`sim/v3/poc_*_comparison_model_only.json` 与同名 `.log`）：
  5 A SR_ON、5 A SR_OFF、10 A SR_OFF 均为 8 ms 全窗 `RAW_ALL_FINITE_AND_TIME_COMPLETE`；
  **10 A SR_ON 在默认设置下没有有效结果**。raw 不入 Git（0.55–0.91 GB），JSON 里的
  `raw_sha256`/`log_sha256` 是它们的唯一身份；`.log` 按 `.gitattributes` 的
  `sim/v3/poc_*.log -text` 逐字节入库（LTspice 日志本身就 CRLF/LF 混排）。数值一律读 JSON，不要从日志手抄。
- **6–8 ms 是启动窗平均，不是稳态点**：10 A SR_ON（0.2 Ω）与 5 A SR_ON（0.4 Ω）的
  `poc_vout_6_8_avg` 只差 0.53 %，负载翻倍电压几乎不降。机制未定（时间常数、窗口相位都可能），
  但足以说明这个平均值不能当稳态量用 —— 跨载比较（启动时间、SR VGS、二极管电流）先定窗口语义。
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
- **裸芯筛选会系统性漏掉胶和标签**：`d1_staged_target_screen.json` 的"剩余 3.65 mm"只减了
  裸芯+I 片，`catalogue_core_stack` 补上四项非磁芯项（胶 0.08 / 标签 0.06 / 压块 0.5 / 沉槽 −0.5）
  后是 **3.51 mm**；**ELP43 因此从"过"翻成"不过"**（2.10 → 1.96 mm，差 0.04 mm 越过 2 mm 预留）。
  高度与磁通是两个筛子：过 16 mm 预留的只有 ELP32/ELP38，其中过三匝面积筛选的只有 ELP38。
  高度上限从 `d1_staged_target_policy.json` 读，**不要写死 16/10**——改了 policy 而工具不跟，就是
  一份看起来通过的旧结论。
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

