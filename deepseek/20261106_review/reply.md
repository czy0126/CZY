复核结论：两处都是可复算的模型问题，不是措辞问题。下面只给最小补丁。

**1. backfeed()：把 5 mA 降级，禁止由它推断 2.7 V 以下输出**

现状 `IQ_MAX=5e-3` 是 TLV3501 最大静态电流，`shortfall_factor=IQ_MAX/available_at_cm` 等于“最大耗流 ÷ 可用电流”，方向反了：要证明“撑不起来”，应拿**最小**耗流去比。最小耗流数据手册未给，故该结论不能由现有常数推出。

最小补丁（`tools/make_fast_oc_eco.py`）：
- 新增常数 `IQ_BASIS = "datasheet max (5 mA); minimum not in references"`，并在 `backfeed()` 返回中把 `comparator_quiescent_max_a` 明确改名为 `comparator_quiescent_assumed_a`，加 `"assumption": True`、`"sensitivity": {"iq_1mA": ..., "iq_5mA": ...}` 由同一 `available()` 重算，`shortfall_factor` 只在 `assumption` 下出现，字段名改为 `shortfall_factor_under_max_iq_assumption`。
- 删除/改写任何“rail cannot be brought to 2.7 V”式结论；`rail_state_below_minimum` 保持 `UNSPECIFIED`，并加 `"no_inference_below_2v7": "V+ < 2.7 V 时输出电平与耗流均不在 datasheet 范围，不得由本项目常数推断"`。
- 在 `verification()` 的 BF-03/BF-04 的 `pass_criteria` 中去除对 V5I 的任何通过条件（现已是“any value is a result”），保留；但 `expected` 里“must not reach the connector”仍成立，因它只依赖 D3 拓扑，不依赖 IQ。
- `report()["limits"]` 增一条：“backfeed 电流仅为设计最大值下的敏感性；供电低于 2.7 V 不可推断输出，需实测。”
- 测试侧（若有 `test_fast_oc.py` 类）新增断言：`backfeed()["assumption"] is True` 且 `shortfall_factor_under_max_iq_assumption` 与 `IQ_MAX/available_at_cm` 相等，防止有人把假设读成界。

**2. q41_selection()/delay_budget()：可复算但不夸大的门极时间**

现状 `tau_g=(R43+Rg)·Ciss`、`t_th`、`t_miller` 只含 R43=100 Ω，忽略 R40‖R41 与 C40，且 `delay_budget()` 把 `crowbar_fet_turn_on_s` 固定 50 ns，等于把门极时间隐藏成常数。

最小补丁（`tools/make_sr_fault_board.py`）：
- 在 `q41_selection()` 内改为两节点估计，全部用现有常数：
  - 源阻抗 `R_src = R_FAULT_SERIES*R_FAULT_PULLDOWN/(R_FAULT_SERIES+R_FAULT_PULLDOWN)`（1 k‖10 k≈909 Ω），`R_g_tot = R_src + R_CROWBAR_GATE + Q41_RG_MAX`。
  - 前置节点：`tau_in = R_src * FAULT_RC_C`（≈0.91 µs），给出 `t_in_63 = tau_in`。
  - 门极节点：`Ciss≈630 pF`，`t_gate = R_g_tot * Q41_CISS_TYP * ln(Vg/(Vg−Vth))`，其中 `Vg = 3.3*R41/(R40+R41)`（用 `input_default()` 已有公式）。
  - Miller 平台保留 2.2 V 假设，`I_drive=(Vg−2.2)/R_g_tot`，`t_miller=QGD/I_drive`，并输出 `"plateau_assumption_v": 2.2` 与 `"vg_input_v": {"3.3":…, "5.0":…}`，说明 5 V 输入使 `Vg` 升高、两项时间缩短但 Rds 列随之变化，不混用。
  - 输出 `"two_node": {"t_in_63_s","t_gate_to_th_s","t_miller_s","total_estimate_s","is_upper_bound": False,"is_worst_case": False}`，并注明两个节点是串联 RC，**不得相加后再当 worst case**；总量只作估计。
- 在 `delay_budget()` 中把 `"crowbar_fet_turn_on_s": 50e-9` 替换为 `q41_selection()["two_node"]["total_estimate_s"]`，并加字段 `"crowbar_fet_turn_on_basis": "two-node RC + Miller plateau estimate"`、`"is_fixed_50ns": False`。同步更新 `"not_worst_case_reasons"`。
- 为避免重复计数：`delay_budget()` 现在的 `input_rc_s = FAULT_RC_S` 与两节点里的 `t_in_63` 是同一 RC。补丁规定 `input_rc_s` 只保留其作为“反相器/比较器前 RC”的名义值；若 `q41_selection()["two_node"]` 已含 `t_in_63`，则 `delay_budget()` 的 `sr_branch` 用 `q41_selection()["two_node"]["total_estimate_s"]` **替换** `input_rc_s + 50 ns` 两项，而不是并列相加。加注释 `"input_rc counted once, inside two_node; do not add FAULT_RC_S again"`。
- 掉电 10 µs RC：`states()` 的 `FAULT_VDD_CUT` 使用 `vdd_cut()` 的毫秒量级，`gate_discharge()` 的 `passive_tau` 是 µs 量级；补丁在 `delay_budget()` 加 `"excluded": {"vdd_cut_s": vdd_cut()["time_to_reg_uvlo_s"], "rgs_passive_tau_s": gate_discharge()["passive_tau_s"], "reason": "掉电路径不是上升延迟，不得计入 sr_branch"}`，防止读者把 10 µs 输入 RC 与 100 ms VDD 掉电混谈。
- 测试断