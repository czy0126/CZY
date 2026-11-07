# 已知工具陷阱（已修，勿回归）

> 从 `CLAUDE.md` 拆出（2026-11-06）。**本文件不自动加载**。
> 家的分布与热区见 [`../../CLAUDE.md`](../../CLAUDE.md)，
> 一条一条的硬规则见 [`TRAP_INDEX.md`](TRAP_INDEX.md)。
> 旧引用里的「CLAUDE.md §小节名」按那里的表解析到本文件。

## 本文件目录

- 已知工具陷阱（已修，勿回归）

## 已知工具陷阱（已修，勿回归）

- **提交物里给文本文件记的 SHA256 必须按 LF 规范字节算**：Git 存 LF，而 Windows 工作区可能是 CRLF
  （`core.autocrlf=true`，或 KiCad 把 `.kicad_sch` / `.kicad_pcb` 重新写成 CRLF）。
  按 `read_bytes()` 原样哈希会让 CI（LF 检出）和本地（CRLF）对同一文件得出不同值：
  `pcb/manufacturing/index.json` 的 4 个 `schematic_sha256`、fast_oc 的 `board_sha256`，
  以及 `pcb/fast_oc/fab/manifest.json` 的 board 哈希都曾因此只在 CI 上红。
  现在统一走 `tools/text_identity.py` 的 `sha256_file()`（文本 CRLF→LF，二进制保持原字节；
  后缀表也住在那里）。**任何新的"文本文件记哈希"都改用它。**

- **`Path.read_text(newline=...)` 是 Python 3.13 才有的参数**：开发机是 3.13，而
  `.github/workflows/ci.yml` 固定 `python-version: "3.12"`，于是 `tools/agent_docs.py`
  与 `tools/test_agent_docs.py` 在 CI 上以
  `TypeError: Path.read_text() got an unexpected keyword argument 'newline'` 红掉
  （test_agent_docs 7 个用例）。要保留 CRLF 原样读取就用 `agent_docs.read_text_exact()`
  （bytes → utf-8），它等价于 `newline=""` 且 3.12 可用。
  `Path.write_text(newline=)` 是 3.10 起就有的，不受影响。

- `primary_freq_khz()` 原先把整个 raw 的 `V(sw)` 边沿取中位数，再按窗口门极周期过滤；
  在 8 ms 冷启动上四行都返回同一个 248.86 kHz。现支持 `t0/t1` 窗口参数，
  回归测试 `test_primary_freq_respects_window_bounds`。
  **教训**：任何"每窗口"指标都必须把边沿限制在窗口内。
- `conv_row()` 的 `n_periods` 必须与该族参考行一致（1 ms 族 22，200 µs 族 8）。
- **`hotfault_convergence.py` 的窗口覆盖判据曾按固定 1 ps 卡**：采样点不可能落在窗口终点上，
  `window_peaks` 返回的是边界**之前**的最后一个点，所以容差必须是一个积分步长。5 fF B 候选的
  220 µs 切片止于 219.9966 / 219.9990 µs（两条 raw 都覆盖整窗），旧判据报 false。
  现在 `max_step_s()` 从 deck 的 `.tran` 取 Tmaxstep（这里 5 ns）当容差，并写进
  `results.coverage_tolerance_s`。`reached_stop()`（整条 raw 是否跑到终点）**不受影响**，
  仍是 1 ns——两者是不同的问题。
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

- **差动控制的 `SW` 的 `Vt` 符号**：`S50 VDD_IN VMID VDD_IN BC_GATE SWPM` 的控制量是
  `V(VDD_IN) - V(BC_GATE)`，恒 ≥ 0，所以 `.model SWPM SW(... Vt=2.0 ...)` 正号才是
  "|Vgs| > 2 V 才闭合"。T3 第一版写成 `Vt=-2.0`，开关常闭、VDD_SR 在 1 ms 就到 12.87 V，
  而 ENABLE 只高了 1.09 µs——物理不可能，才反查到符号。**判据：先算控制量的符号范围。**
- **`.meas` 碰到一个不在 `.save` 里的节点会中止整份测量列表**（`Voltage not found`），
  不是只丢那一条。加了新 `.meas` 就先确认它读的每个节点都在 `SAVE` 里；否则整份 log
  只剩前面的几条，看起来像"跑到一半崩了"。
- **测传播延迟用 `INTEG(if(V(BC_GATE)<13.5,1,0)) FROM a TO b`，不要用 TRIG/TARG 的 RISE 计数**：
  初值点在 LTspice 里贡献一次边沿，`RISE=2` 会落回 t≈0，得到 3.66e-7 这种"延迟"。
  窗口积分与窗口长度无关，也不会被 t=0 的假边沿骗。
- **`MAX(-I(V1))` 抓的是理想开关的纳秒门极尖峰**，不是电阻电流：T3 曾把 4.67 A 当成浪涌，
  实际限流电阻上只有约 0.62 A。量哪个器件的电流就用 `MAX I(<ref>)`。
- **分段负载写成硬 `if(V(x)>Vth,I1,I0)` 会让慢上电 deck 报
  "Convergence Failure: Time step too small ... trouble with instance BLOAD"**；
  用 `I=I0+I1/(1+exp(-(V(x)-Vth)/0.05))` 平滑后一次通过。

