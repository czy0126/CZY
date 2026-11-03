"""Publish a CURRENT-CANDIDATE manifest (review 2026-10-31 round 3, P2).

The old design/baseline/baseline_manifest.json has 304 entries and five known
hash mismatches.  It is history, not a reproduction recipe: re-running every old
bench to make it "unique" again would be busy-work.  This tool emits the small
manifest that actually reproduces the current delivery:

    decks        the round-4 generated decks + the accepted 1 ms deck
    models       the three .lib files those decks include
    scripts      the measurement / summary / test tools
    results      the JSON and markdown that quote numbers
    raws         size + mtime + saved time range (full hash only when small)

Raw time ranges come from design/v2/round4_summary.json when it exists; the raw
saved axis is rebased by Tstart, so both the raw range and the display offset
are written down (the third review asked for that explicitly).

Usage:
    python tools/current_manifest.py
    python tools/current_manifest.py --json design/v2/manifest_current_candidate.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

V3_SOURCES = {
    "deck": [
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct47.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.cir",
        # physical-configuration variants (tools/make_physical_decks.py).  They
        # are what the baseline's Lr turn decision and ripple rows quote.
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_lrmin.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.cir",
        # issue #6: the same instrumented deck saved over the first phase-
        # aligned window (133 gate periods = 662.9 us), and the same window at
        # half the max timestep so the step check covers the quoted number.
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned2n.cir",
        # issue #6 asks for 5 / 2 / 1 ns; the third leg is a .tran step change.
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned1n.cir",
        # issue #6, E6-3's optional <=0.5 ns leg: the 5/2/1 ns loss list is not
        # monotone, so a fourth step tests plateau vs constant error.
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned0p5n.cir",
        # High-output candidates (tools/make_high_output_decks.py): all four
        # 48 V decks were run 2026-11-01/02; the two 50 V non-probe decks are
        # still targets that have never run (the 50 V record used their _cin
        # probes).  Every deck says UNRUN in its header; see the 48V110A,
        # 48V120A and 50V110A_120A records for the measured points.  The _cin
        # decks carry the 100 A ledger's probes.
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.cir",
        "sim/v3/sr_tank_dual_v33_cold_phys.cir",
        "sim/v3/sr_tank_dual_v33_cold_oc_phys.cir",
        "sim/v3/sr_tank_dual_v33_cold_oc_lrmin.cir",
        # 50 V probes (ELE-06) and 48 V/120 A target cold/fault decks (ELE-07).
        # All four were run on 2026-11-02; the run records live in
        # design/v3/power_priority/50V110A_120A_实测_2026-11-02.md and
        # 48V120A_冷启动与故障_2026-11-02.md.
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
        "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir",
        "sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir",
        # CONVERGENCE_DIAGNOSTIC: the cold-overload fault stalls at 7.5714 ms of
        # its 8 ms window.  This child adds cshunt=1 fF and nothing else;
        # tools/cold_oc_convergence.py compares the common 5.4-6.0 ms prefix
        # before any post-stall number is quoted.
        "sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target_cshunt.cir",
        # ELE-08: steady-state-initialized faults.  The .ic precharge is a
        # starting state, not proof of settling; the run records are
        # design/v3/power_priority/hotfault_{48v,50v}_120a.json and
        # 48V120A_稳态初始化故障_2026-11-02.md.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.cir",
        # SOLVER_DIAGNOSTIC variants: same circuit, trtol=1 abstol=1e-13, stop
        # at 220 us on the saved axis.  They bound the prefix peaks; they are
        # not a replacement for the base record.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.cir",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_diag.cir",
        # CONVERGENCE_DIAGNOSTIC: same 50 V circuit, cshunt=1 fF added.  The
        # base stalls at 296.929 us of 320 us; this variant tests whether a
        # finite node capacitance escapes the dead-zone step-size limit cycle.
        # tools/hotfault_convergence.py compares it against the base prefix
        # and records design/v3/power_priority/hotfault_50v_120a_cshunt.json.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt.cir",
        # ELE-10: the eight-device probe deck derived from the completed cshunt
        # variant; the only 50 V deck that can cover 319 us on the saved axis.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.cir",
        # ROBUSTNESS control: the same 1 fF perturbation on the 48 V deck that
        # already completes.  It tests whether the A-phase latch is a circuit
        # property or a solver-trajectory artifact, and its eight-device child
        # records the post-trip gate state on the same terms as 50 V.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt.cir",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt_srprobe.cir",
        # ELE-10: eight-device SR probes.  make_sr_fault_probes.py appends only
        # .save and .meas lines to the hot-fault decks, so these are the same
        # circuit with more instruments.  The 48 V deck completed 320 us; the
        # 50 V base still stalls at 296.929 us and has no full record.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_srprobe.cir",
        # ELE-09: the same 50 V/120 A circuit at half the timestep, and over the
        # first phase-aligned window.  Both change only the .tran line, so the
        # 0.499 W residual can be tested against step and window length.
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_2n.cir",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_aligned.cir",
        # PROT-02: independent latched gate inhibit derived additively from the
        # 48 V eight-SR probe deck.  A isolates the actuation path, B adds the
        # 10 us fast CT path, and the unarmed deck is a negative control for
        # the soft-start blanking.  See PROT02_独立故障锁存候选对照_2026-11-03.md.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_a_oc1v.cir",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_b_fast10u_1p8v.cir",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_b_unarmed.cir",
        # Same protection block on the 50 V cshunt child: the 50 V base still
        # stalls at 296.929 us, so this is the only 50 V solve that reaches the
        # declared window.  The cshunt caveat travels with the record.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.cir",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir",
        "sim/v3/prot_latch_uvlo_check.cir",
        # PROT-02 restart sequencing: logic-level sub-circuit only.  A full
        # power-stage restart needs 9.6 ms of soft-start ramp (0.5 mV/us) and
        # does not fit the 320 us fault window; this deck checks the order
        # (power cycle clears both latches, the ramp is blanked, re-arm then
        # latches again) with ideal PWL sources.
        "sim/v3/prot_latch_restart_check.cir",
    ],
    "model": [
        "models/ucc25600_legacy_behaviour.lib",
        "models/sr_timing_v3_3.lib",
        "models/sr_device_v3.lib",
    ],
    "script": [
        "tools/ascii_raw_window.py",
        "tools/magnetics_design.py",
        "tools/draw_magnetics.py",
        "tools/make_magnetics_manifest.py",
        "tools/extract_op_point.py",
        "tools/thermal_precheck.py",
        "tools/passive_requirements.py",
        "tools/lr_design.py",
        "tools/cout_bank.py",
        "tools/cr_stress.py",
        "tools/ct_design.py",
        "tools/oc_network_check.py",
        "tools/connector_budget.py",
        "tools/board_netlist.py",
        "tools/winding_polarity.py",
        "tools/powerup_checklist.py",
        "tools/energy_ledger_100a.py",
        "tools/sr_loss_audit.py",
        "tools/make_physical_decks.py",
        "tools/make_high_output_decks.py",
        "tools/make_120a_transients.py",
        "tools/make_hot_fault_decks.py",
        "tools/analyze_v3_transient.py",
        "tools/hot_fault_metrics.py",
        "tools/hotfault_diagnostic.py",
        "tools/steady_stress.py",
        "tools/ci_check.py",
        "tools/current_manifest.py",
        "tools/test_ascii_raw_window.py",
        "tools/test_magnetics_design.py",
        "tools/test_draw_magnetics.py",
        "tools/test_extract_op_point.py",
        "tools/test_thermal_precheck.py",
        "tools/test_passive_requirements.py",
        "tools/test_lr_design.py",
        "tools/test_cout_bank.py",
        "tools/test_cr_stress.py",
        "tools/test_ct_design.py",
        "tools/test_oc_network_check.py",
        "tools/test_gate_drive_calibration.py",
        "tools/test_connector_budget.py",
        "tools/test_board_netlist.py",
        "tools/test_powerup_checklist.py",
        "tools/test_energy_ledger_100a.py",
        "tools/test_sr_loss_audit.py",
        "tools/test_make_physical_decks.py",
        "tools/test_make_high_output_decks.py",
        "tools/test_operating_point_110a.py",
        "tools/test_energy_ledger_48v_110a.py",
        "tools/test_operating_point_120a.py",
        "tools/test_energy_ledger_48v_120a.py",
        "tools/test_operating_point_50v.py",
        "tools/test_steady_stress.py",
        "tools/test_analyze_v3_transient.py",
        "tools/test_120a_transients.py",
        "tools/test_make_120a_transients.py",
        "tools/test_hot_fault_metrics.py",
        "tools/test_make_hot_fault_decks.py",
        "tools/test_hotfault_diagnostic.py",
        "tools/hotfault_convergence.py",
        "tools/test_hotfault_convergence.py",
        "tools/cold_oc_convergence.py",
        "tools/test_cold_oc_convergence.py",
        "tools/d1_unclosed_risks.py",
        "tools/test_d1_unclosed_risks.py",
        "tools/make_sr_fault_probes.py",
        "tools/test_make_sr_fault_probes.py",
        "tools/sr_fault_probe_report.py",
        "tools/test_sr_fault_probe_report.py",
        "tools/test_ledger_candidate_parameters.py",
        "tools/test_control_validation_doc.py",
        "tools/test_ci_check.py",
        "tools/test_baseline_doc.py",
        "tools/test_bom_draft.py",
        "tools/test_current_manifest.py",
        "tools/make_protection_candidates.py",
        "tools/protection_candidate_compare.py",
        "tools/test_make_protection_candidates.py",
        "tools/test_protection_candidate_compare.py",
    ],
    "result": [
        "design/v3/magnetics/magnetics_design.json",
        "design/v3/magnetics/operating_point_100a.json",
        "design/v3/magnetics/operating_point_100a_cout7m.json",
        "design/v3/magnetics/operating_point_100a_phys.json",
        "design/v3/magnetics/manifest.json",
        "design/v3/magnetics/height_stackup.csv",
        "design/v3/magnetics/inspection_spec.csv",
        "design/v3/magnetics/winding_polarity.json",
        "design/v3/magnetics/winding_polarity.csv",
        "design/v3/magnetics/first_article_polarity_record.csv",
        "design/v3/stage_f/thermal_precheck.json",
        "design/v3/bom/passive_requirements.json",
        "design/v3/bom/lr_design.json",
        "design/v3/bom/cout_bank.json",
        "design/v3/bom/cr_stress.json",
        "design/v3/bom/ct_design.json",
        "design/v3/bom/oc_network_ct10.json",
        "design/v3/bom/oc_network_ct47.json",
        "design/v3/bom/connector_budget.json",
        "design/v3/bom/bom_draft.csv",
        "design/v3/pcb/board_netlist.csv",
        "design/v3/pcb/board_netlist.json",
        "design/v3/stage_f/powerup_checklist.json",
        "design/v3/stage_f/上电检查表.md",
        "design/v3/stage_f/energy_ledger_100a.json",
        "design/v3/stage_f/energy_ledger_100a_phase_aligned.json",
        "design/v3/stage_f/sr_loss_audit.json",
        # High-output candidates: the run records, their writeups, and the
        # ledgers taken from the probe decks (input power, hence efficiency).
        "design/v3/power_priority/operating_point_48v_110a.json",
        "design/v3/power_priority/scenarios.json",
        "design/v3/power_priority/energy_ledger_48v_110a.json",
        "design/v3/power_priority/operating_point_48v_120a.json",
        "design/v3/power_priority/energy_ledger_48v_120a.json",
        "design/v3/power_priority/cr_stress_48v_120a.json",
        "design/v3/power_priority/sr_loss_audit_48v_120a.json",
        # ELE-06: 50 V probes.
        "design/v3/power_priority/operating_point_50v_110a.json",
        "design/v3/power_priority/operating_point_50v_120a.json",
        "design/v3/power_priority/stress_50v_110a.json",
        "design/v3/power_priority/stress_50v_120a.json",
        "design/v3/power_priority/energy_ledger_50v_110a.json",
        "design/v3/power_priority/energy_ledger_50v_120a.json",
        "design/v3/power_priority/sr_loss_audit_50v_110a.json",
        "design/v3/power_priority/sr_loss_audit_50v_120a.json",
        "design/v3/power_priority/cr_stress_50v_110a.json",
        "design/v3/power_priority/cr_stress_50v_120a.json",
        # ELE-07: true cold start and 8.7x overload on the 15.4 mOhm target.
        "design/v3/power_priority/cold_start_48v_120a_target.json",
        "design/v3/power_priority/fault_48v_120a_target.json",
        # CONVERGENCE_DIAGNOSTIC on the same overload: the cshunt child stalls
        # earlier than the base (5.6141 vs 7.5714 ms), so it is a negative
        # result, not a substitute record.  The record keeps the common slice
        # and states that the declared window was not covered.
        "design/v3/power_priority/cold_oc_vin48_i120_cshunt.json",
        # ELE-08: settled-state faults at 48 V and 50 V, plus the gate register
        # that keeps F01/M01 blocked on this evidence.
        "design/v3/power_priority/hotfault_48v_120a.json",
        "design/v3/power_priority/hotfault_50v_120a.json",
        # SOLVER_DIAGNOSTIC: base vs tightened tolerance over one common window.
        "design/v3/power_priority/hotfault_48v_120a_diag.json",
        "design/v3/power_priority/hotfault_50v_120a_diag.json",
        # CONVERGENCE_DIAGNOSTIC: does a 1 fF node capacitance escape the
        # post-trip stall, and what does it move in the published prefix?
        "design/v3/power_priority/hotfault_50v_120a_cshunt.json",
        # ROBUSTNESS: the 48 V control comparison and its eight-device record.
        "design/v3/power_priority/hotfault_48v_120a_cshunt.json",
        "design/v3/power_priority/sr_fault_probe_48v_120a_cshunt.json",
        # ELE-10: per-device gate/Vds/current over the same 320 us window.
        # 48 V from the base deck; 50 V only from the cshunt child, which is
        # the one 50 V solve that reaches 319 us.
        "design/v3/power_priority/sr_fault_probe_48v_120a.json",
        "design/v3/power_priority/sr_fault_probe_50v_120a_cshunt.json",
        "design/v3/power_priority/unclosed_risk_register.json",
        # ELE-09: the 22-period 5/2 ns pair, the SR decomposition with the
        # gate-drive boundary correction, and the 133-period aligned ledger.
        "design/v3/power_priority/energy_ledger_50v_120a_steps.json",
        "design/v3/power_priority/sr_loss_audit_50v_120a_steps.json",
        "design/v3/power_priority/energy_ledger_50v_120a_aligned.json",
        # PROT-02: two candidates plus the unarmed negative control, and the
        # UVLO sub-circuit that shows a missing bias forces the gate low.
        "design/v3/power_priority/protection_candidate_48v_120a_prot_a.json",
        "design/v3/power_priority/protection_candidate_48v_120a_prot_b.json",
        "design/v3/power_priority/protection_candidate_48v_120a_prot_b_unarmed.json",
        "design/v3/power_priority/protection_candidate_50v_120a_prot_a.json",
        "design/v3/power_priority/protection_candidate_50v_120a_prot_b.json",
        "design/v3/power_priority/protection_uvlo_check.json",
        "design/v3/power_priority/protection_restart_check.json",
    ],
    "doc": [
        "design/v3/magnetics/磁件设计包_2026-10-31.md",
        "design/v3/magnetics/绕组工艺卡_2026-11-01.md",
        "design/v3/magnetics/winding_cross_section.svg",
        "design/v3/magnetics/winding_connections.svg",
        "design/v3/magnetics/height_stackup.svg",
        "design/v3/当前候选基线_2026-11-01.md",
        "design/v3/stage_f/首样验证与额定值判定_2026-10-31.md",
        "design/v3/bom/功率级元件需求与BOM草案_2026-11-01.md",
        "design/v3/pcb/主功率板连接网表_2026-11-01.md",
        "design/v3/power_priority/48V110A_实测_2026-11-01.md",
        "design/v3/power_priority/48V120A_实测_2026-11-02.md",
        "design/v3/power_priority/50V110A_120A_实测_2026-11-02.md",
        "design/v3/power_priority/48V120A_冷启动与故障_2026-11-02.md",
        "design/v3/power_priority/48V120A_稳态初始化故障_2026-11-02.md",
        "design/v3/power_priority/50V120A_损耗差额与步长_2026-11-02.md",
        "design/v3/power_priority/PROT02_独立故障锁存候选对照_2026-11-03.md",
        "pcb/control_validation/控制验证板_设计与测试说明_2026-10-31.md",
    ],
    "config": [
        "requirements.txt",
        ".github/workflows/ci.yml",
    ],
    "raw": [
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned2n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned1n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned0p5n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw",
        # ELE-08 / ELE-09: the two settled-state fault raws, the 2 ns companion
        # and the 133-period aligned run.  Each is identified by size + mtime
        # because it exceeds the hash limit.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.raw",
        # SOLVER_DIAGNOSTIC raws: 1.4 GB each, size + mtime only.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.raw",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_diag.raw",
        # CONVERGENCE_DIAGNOSTIC raw: 0.94 GB, the only 50 V solve that reaches
        # 320 us.  Size + mtime only.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt.raw",
        # ELE-10 48 V eight-device probe raw: 1.2 GB, size + mtime only.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.raw",
        # ELE-10 50 V eight-device probe raw: the cshunt child, size + mtime only.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.raw",
        # ROBUSTNESS (48 V): the 1 fF mother and its eight-device child.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt.raw",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt_srprobe.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_2n.raw",
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_aligned.raw",
        # PROT-02 raws: A is 1.2 GB (size + mtime), B is 1.1 GB; the unarmed
        # control is 0.18 GB and the UVLO sub-circuit is 3 MB, so those two
        # are hashed like every small raw.
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_a_oc1v.raw",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_b_fast10u_1p8v.raw",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_b_unarmed.raw",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.raw",
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.raw",
        "sim/v3/prot_latch_uvlo_check.raw",
        # 236 MB restart sub-circuit raw: hashed like the other small raws.
        "sim/v3/prot_latch_restart_check.raw",
        # The cold-start / cold-OC raws (base and cshunt) are 9-12 GB each and
        # stay out of the hash list; their .log files are the committed
        # measurements.
    ],
}

V2_SOURCES = {
    "deck": [
        "sim/v2/sr_tank_dual_v33_ss_1ms.cir",
        "sim/v2/sr_tank_dual_v33_ss_1ms_full.cir",
        "sim/v2/sr_tank_dual_v33_cold.cir",
        "sim/v2/sr_tank_dual_v33_cold_oc.cir",
        "sim/v2/sr_tank_dual_v33_conv_5n.cir",
        "sim/v2/sr_tank_dual_v33_conv_2n.cir",
        "sim/v2/sr_tank_dual_v33_conv_1n.cir",
        "sim/v2/sr_tank_dual_v33_cpin_50p.cir",
        "sim/v2/sr_tank_dual_v33_cpin_200p.cir",
        "sim/v2/sr_tank_dual_v33_conv1ms_2n.cir",
        "sim/v2/sr_tank_dual_v33_conv1ms_1n.cir",
        "sim/v2/sr_tank_dual_v33_cpin1ms_50p.cir",
        "sim/v2/sr_tank_dual_v33_cpin1ms_200p.cir",
    ],
    "model": [
        "models/ucc25600_legacy_behaviour.lib",
        "models/sr_timing_v3_3.lib",
        "models/sr_device_v3.lib",
    ],
    "script": [
        "tools/tank_metrics.py",
        "tools/sr_energy_ledger.py",
        "tools/steady_state_check.py",
        "tools/round3_summary.py",
        "tools/task_package1_summary.py",
        "tools/fault_metrics.py",
        "tools/ascii_raw_window.py",
        "tools/period_variance.py",
        "tools/make_round4_decks.py",
        "tools/current_manifest.py",
        "tools/test_tank_metrics.py",
        "tools/test_sr_energy_ledger.py",
        "tools/test_steady_state_check.py",
        "tools/test_round3_summary.py",
        "tools/test_task_package1_summary.py",
        "tools/test_make_round4_decks.py",
        "tools/test_fault_metrics.py",
        "tools/test_ascii_raw_window.py",
    ],
    "result": [
        "design/v2/round4_summary.json",
        "design/v2/round3_summary.json",
        "design/v2/round3_energy_ledger_ss.json",
        "design/v2/round3_energy_ledger_284k.json",
        "design/v2/period_variance_cpin1ms.json",
        "design/v2/fault_metrics_sr_tank_dual_v33_cold_oc.json",
        "design/v2/第四轮_证据修正与数值疑点关闭_2026-10-31.md",
    ],
    "raw": [
        "sim/v2/sr_tank_dual_v33_ss_1ms.raw",
        "sim/v2/sr_tank_dual_v33_ss_1ms_full.raw",
        "sim/v2/sr_tank_dual_v33_cold.raw",
        "sim/v2/sr_tank_dual_v33_cold_oc.raw",
        "sim/v2/sr_tank_dual_v33_conv_5n.raw",
        "sim/v2/sr_tank_dual_v33_conv_2n.raw",
        "sim/v2/sr_tank_dual_v33_conv_1n.raw",
        "sim/v2/sr_tank_dual_v33_cpin_50p.raw",
        "sim/v2/sr_tank_dual_v33_cpin_200p.raw",
        "sim/v2/sr_tank_dual_v33_conv1ms_2n.raw",
        "sim/v2/sr_tank_dual_v33_conv1ms_1n.raw",
        "sim/v2/sr_tank_dual_v33_cpin1ms_50p.raw",
        "sim/v2/sr_tank_dual_v33_cpin1ms_200p.raw",
    ],
}

SCOPES = {"v2": V2_SOURCES, "v3": V3_SOURCES}

# Full hashes above this size are skipped: a raw is identified by size, mtime and
# its saved time range, and re-verifying it means re-running the deck anyway.
HASH_LIMIT_BYTES = 256 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def entry(path: str, kind: str) -> dict[str, object]:
    full = ROOT / path
    if not full.exists():
        return {"path": path, "kind": kind, "status": "missing"}
    size = full.stat().st_size
    row: dict[str, object] = {
        "path": path,
        "kind": kind,
        "bytes": size,
        "mtime": full.stat().st_mtime,
        "sha256": sha256(full) if size <= HASH_LIMIT_BYTES else "skipped-large-raw",
    }
    return row


_SPICE_SUFFIX = (("meg", 1e6), ("t", 1e12), ("g", 1e9), ("k", 1e3),
                 ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12), ("f", 1e-15))


def spice_seconds(token: str) -> float:
    """LTspice time literal ('880u', '5n', '8m', '0') -> seconds."""
    text = token.strip().lower()
    if text in ("", "0"):
        return 0.0
    for suffix, scale in _SPICE_SUFFIX:
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * scale
    return float(text)


def deck_timing(rel_path: str, root: Path = ROOT) -> dict[str, object]:
    """Saved-axis range and display offset, read from the deck's own .tran line.

    `Tstart` rebases the axis: `.tran 0 1000u 880u 5n uic` writes 0..120 us into
    the raw, which displays as 880..1000 us.  Both numbers are recorded because
    neither alone says which window a downstream measurement used.

    `cold_start` follows the same rule as tools/task_package1_summary.py: `uic`
    alone is a true zero initial state, but any `.ic` directive means the run
    starts from a specified state no matter what `uic` says.
    """
    deck = root / rel_path
    row: dict[str, object] = {"deck": rel_path}
    if not deck.exists():
        return {**row, "status": "missing"}
    lines = deck.read_text(encoding="utf-8", errors="replace").splitlines()
    tran = next((ln for ln in lines if ln.strip().lower().startswith(".tran")), None)
    if tran is None:
        return {**row, "status": "no .tran"}
    tokens = tran.split()[1:]
    has_uic = any(tok.lower() == "uic" for tok in tokens)
    numeric = [tok for tok in tokens if tok.lower() not in ("uic", "startup")]
    stop = spice_seconds(numeric[1]) if len(numeric) > 1 else 0.0
    start = spice_seconds(numeric[2]) if len(numeric) > 2 else 0.0
    max_step = spice_seconds(numeric[3]) if len(numeric) > 3 else 0.0
    has_ic = any(ln.strip().lower().startswith(".ic") for ln in lines)
    return {
        **row,
        "tran": tran.strip(),
        "raw_time_start_s": 0.0,
        "raw_time_end_s": stop - start,
        "display_offset_us": round(start * 1e6, 9),  # 880u -> 880.0, not 879.9999999999999
        "max_step_s": max_step,
        "has_ic": has_ic,
        "uic": has_uic,
        "cold_start": has_uic and not has_ic,
    }


def log_saved_end_s(log: Path) -> float | None:
    """The end of the saved window as LTspice itself reported it ('FROM 0 TO x')."""
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"FROM 0 TO ([0-9.eE+-]+)", text)
    return float(match.group(1)) if match else None


def run_metadata(summary_path: Path) -> dict[str, object]:
    """Saved-axis range and display offset per result section."""
    if not summary_path.exists():
        return {}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for section in ("operating_point", "full_machine", "cold_start"):
        row = payload.get(section)
        if isinstance(row, dict):
            out[section] = {
                key: row.get(key) for key in ("raw", "raw_time_start_s", "raw_time_end_s",
                                              "display_offset_us", "window_us")
                if key in row
            }
    for section in ("convergence", "convergence_1ms", "cpin_sensitivity"):
        cases = payload.get(section)
        if isinstance(cases, dict):
            out[section] = {
                label: {key: case.get(key) for key in ("raw_time_start_s", "raw_time_end_s",
                                                       "display_offset_us")}
                for label, case in cases.items()
            }
    return out


REPRODUCE = {
    "v2": [
            "python tools/make_round4_decks.py",
            "python tools/task_package1_summary.py --op sim/v2/sr_tank_dual_v33_ss_1ms.raw "
            "--full sim/v2/sr_tank_dual_v33_ss_1ms_full.raw --cold sim/v2/sr_tank_dual_v33_cold.raw "
            "--conv1ms 2n=sim/v2/sr_tank_dual_v33_conv1ms_2n.raw "
            "1n=sim/v2/sr_tank_dual_v33_conv1ms_1n.raw "
            "--cpin1ms 50p=sim/v2/sr_tank_dual_v33_cpin1ms_50p.raw "
            "200p=sim/v2/sr_tank_dual_v33_cpin1ms_200p.raw "
            "--json design/v2/round4_summary.json",
            "python tools/fault_metrics.py --fault-start-ms 5.5 --fault-end-ms 5.6 "
            "--gate \"V(ga1)\" --ascii-window-from-ms 5.4 sr_tank_dual_v33_cold_oc",
            "python tools/period_variance.py 5n=sim/v2/sr_tank_dual_v33_ss_1ms.raw "
            "2n=sim/v2/sr_tank_dual_v33_conv1ms_2n.raw "
            "1n=sim/v2/sr_tank_dual_v33_conv1ms_1n.raw "
            "cpin50p=sim/v2/sr_tank_dual_v33_cpin1ms_50p.raw "
            "cpin200p=sim/v2/sr_tank_dual_v33_cpin1ms_200p.raw "
            "--json design/v2/period_variance_cpin1ms.json",
            "python -m pytest tools -q",
    ],
    "v3": [
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw "
        "--rl 0.0189 --periods 22 --json design/v3/magnetics/operating_point_100a.json",
        "python tools/magnetics_design.py --json design/v3/magnetics/magnetics_design.json",
        "python tools/draw_magnetics.py --out design/v3/magnetics",
        "python tools/make_magnetics_manifest.py",
        "python tools/thermal_precheck.py --json design/v3/stage_f/thermal_precheck.json",
        "python tools/passive_requirements.py --json design/v3/bom/passive_requirements.json",
        "python tools/passive_requirements.py "
        "--cin-raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.raw "
        "--json design/v3/bom/passive_requirements.json",
        "python tools/lr_design.py --json design/v3/bom/lr_design.json",
        "python tools/cout_bank.py --json design/v3/bom/cout_bank.json",
        "python tools/cr_stress.py --json design/v3/bom/cr_stress.json",
        "python tools/ct_design.py --json design/v3/bom/ct_design.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct47.cir",
        "python tools/oc_network_check.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.raw "
        "--burden 10 --rd1 10k --json design/v3/bom/oc_network_ct10.json",
        "python tools/oc_network_check.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct47.raw "
        "--burden 47 --rd1 110k --json design/v3/bom/oc_network_ct47.json",
        "python tools/connector_budget.py --json design/v3/bom/connector_budget.json",
        "python tools/board_netlist.py --json design/v3/pcb/board_netlist.json "
        "--csv design/v3/pcb/board_netlist.csv",
        "python tools/powerup_checklist.py --md design/v3/stage_f/上电检查表.md "
        "--json design/v3/stage_f/powerup_checklist.json",
        "python tools/make_physical_decks.py",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.cir",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.raw --periods 133 "
        "--no-step-check "
        "--json design/v3/stage_f/energy_ledger_100a_phase_aligned.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.raw "
        "--rl 0.0189 --periods 22 --json design/v3/magnetics/operating_point_100a_cout7m.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.raw "
        "--rl 0.0189 --periods 22 --json design/v3/magnetics/operating_point_100a_phys.json",
        "# 11-12 GB cold runs (~37 min each); the .log carries the .meas results used by lr_design.py",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_phys.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_oc_phys.cir",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_oc_lrmin.cir",
        # High-output candidate: generate, run, extract, then the ledger on the
        # probe deck (that deck differs from the candidate only in .save).
        "python tools/make_high_output_decks.py --write",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110.raw "
        "--rl 0.0169 --periods 22 --pairs 1 4 "
        "--json design/v3/power_priority/operating_point_48v_110a.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.cir",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.raw --periods 22 "
        "--vin 48 --rl 0.0169 --no-step-check "
        "--json design/v3/power_priority/energy_ledger_48v_110a.json",
        # 120 A candidate: the same sequence.  The op point was extracted from
        # the probe raw, and the ledger has no step check because this circuit
        # has no second-timestep companion in the repository.
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.raw "
        "--rl 0.0154 --periods 22 --pairs 1 4 "
        "--json design/v3/power_priority/operating_point_48v_120a.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.cir",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.raw --periods 22 "
        "--vin 48 --rl 0.0154 --no-step-check "
        "--json design/v3/power_priority/energy_ledger_48v_120a.json",
        "python tools/cr_stress.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.raw "
        "--from-us 7.6445 --to-us 117.3105 "
        "--json design/v3/power_priority/cr_stress_48v_120a.json",
        "python tools/sr_loss_audit.py --case candidate_48v_120a "
        "--json design/v3/power_priority/sr_loss_audit_48v_120a.json",
        # 50 V family: the same tank at VIN=50 with the loads the report's
        # linear estimate selected (17.8 / 16.3 mOhm).  The operating-point
        # window and the ledger/stress/Cr window differ by a few microseconds
        # because they round to different cycle boundaries; do not mix them.
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.raw "
        "--rl 0.0178 --periods 22 --pairs 1 4 "
        "--json design/v3/power_priority/operating_point_50v_110a.json",
        "python tools/steady_stress.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.raw "
        "--from-us 7.629195812563637 --to-us 117.2912676221502 --vin 50 --rl 0.0178 "
        "--json design/v3/power_priority/stress_50v_110a.json",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.raw "
        "--vin 50 --rl 0.0178 --periods 22 --no-step-check "
        "--json design/v3/power_priority/energy_ledger_50v_110a.json",
        "python tools/sr_loss_audit.py --case candidate_50v_110a "
        "--json design/v3/power_priority/sr_loss_audit_50v_110a.json",
        "python tools/cr_stress.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.raw "
        "--from-us 7.629195812563637 --to-us 117.2912676221502 "
        "--json design/v3/power_priority/cr_stress_50v_110a.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
        "python tools/extract_op_point.py sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw "
        "--rl 0.0163 --periods 22 --pairs 1 4 "
        "--json design/v3/power_priority/operating_point_50v_120a.json",
        "python tools/steady_stress.py --raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw "
        "--from-us 7.631583516341496 --to-us 117.2982368985085 --vin 50 --rl 0.0163 "
        "--json design/v3/power_priority/stress_50v_120a.json",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw "
        "--vin 50 --rl 0.0163 --periods 22 --no-step-check "
        "--json design/v3/power_priority/energy_ledger_50v_120a.json",
        "python tools/sr_loss_audit.py --case candidate_50v_120a "
        "--json design/v3/power_priority/sr_loss_audit_50v_120a.json",
        "python tools/cr_stress.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw "
        "--from-us 7.631583516341496 --to-us 117.2982368985085 "
        "--json design/v3/power_priority/cr_stress_50v_120a.json",
        # 48 V/120 A target transients: regenerate the two decks from their
        # cold parents, run the 8 ms decks (~12 GB / ~37 min each), then stream
        # the raws.  The fault deck may collapse; analyze_v3_transient records
        # the reachable prefix rather than pretending the run finished.
        "python tools/make_120a_transients.py --write",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir",
        "python tools/analyze_v3_transient.py --kind cold "
        "--raw sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.raw "
        "--deck sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir --rl 0.0154 "
        "--json design/v3/power_priority/cold_start_48v_120a_target.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir",
        "python tools/analyze_v3_transient.py --kind fault "
        "--raw sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.raw "
        "--deck sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir --rl 0.0154 "
        "--json design/v3/power_priority/fault_48v_120a_target.json",
        # ELE-08: steady-state-initialized faults.  The extractor checks
        # soft-start completion and output drift first; a .ic precharge alone
        # is not evidence of settling.
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir",
        "python tools/hot_fault_metrics.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw "
        "--deck sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir "
        "--log sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.log --rl 15.4m "
        "--json design/v3/power_priority/hotfault_48v_120a.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.cir",
        "python tools/hot_fault_metrics.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.raw "
        "--deck sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.cir "
        "--log sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.log --rl 16.3m "
        "--json design/v3/power_priority/hotfault_50v_120a.json",
        # SOLVER_DIAGNOSTIC: same circuit, tightened tolerances, 220 us window.
        # The comparison reads both raws over the shorter deck's saved stop and
        # refuses to compare decks whose bodies differ.
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_diag.cir",
        "python tools/hotfault_diagnostic.py "
        "--base-raw sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.raw "
        "--base-deck sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.cir "
        "--diag-raw sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_diag.raw "
        "--diag-deck sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_diag.cir "
        "--base-log sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.log "
        "--diag-log sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_diag.log "
        "--json design/v3/power_priority/hotfault_50v_120a_diag.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.cir",
        "python tools/hotfault_diagnostic.py "
        "--base-raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw "
        "--base-deck sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir "
        "--diag-raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.raw "
        "--diag-deck sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.cir "
        "--base-log sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.log "
        "--diag-log sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_diag.log "
        "--json design/v3/power_priority/hotfault_48v_120a_diag.json",
        # CONVERGENCE_DIAGNOSTIC: same circuit, cshunt=1 fF, full 320 us window.
        # The comparison reads both raws over a shared 220 us prefix (the base
        # stalls at 296.929 us) and judges completion from each raw's tail.
        "/d/ADI/LTspice/LTspice.exe -b -ascii "
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt.cir",
        "python tools/hotfault_convergence.py "
        "--base-raw sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.raw "
        "--base-deck sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.cir "
        "--variant-raw sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt.raw "
        "--variant-deck sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt.cir "
        "--base-log sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.log "
        "--variant-log sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt.log "
        "--json design/v3/power_priority/hotfault_50v_120a_cshunt.json",
        "python tools/d1_unclosed_risks.py --write",
        # ELE-10: regenerate the eight-device probe decks, run the 48 V one, and
        # extract the per-device latch.  The 50 V probe deck has no full raw
        # because its base run still stalls (see ELE-08).
        "python tools/make_sr_fault_probes.py --write",
        "/d/ADI/LTspice/LTspice.exe -b -ascii "
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir",
        "python tools/sr_fault_probe_report.py --case 48v_120a "
        "--json design/v3/power_priority/sr_fault_probe_48v_120a.json",
        # ELE-10, 50 V: the base stalls, so the eight-device record comes from
        # the completed cshunt child.  Its trip comes from the convergence JSON.
        "/d/ADI/LTspice/LTspice.exe -b -ascii "
        "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.cir",
        "python tools/sr_fault_probe_report.py --case 50v_120a_cshunt "
        "--json design/v3/power_priority/sr_fault_probe_50v_120a_cshunt.json",
        # ROBUSTNESS control: the same 1 fF option on the completed 48 V base.
        # The comparison is over the full 320 us window; this run decides
        # whether the 48 V A-phase latch survives a solver-only perturbation.
        "/d/ADI/LTspice/LTspice.exe -b -ascii "
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt.cir",
        "python tools/hotfault_convergence.py "
        "--base-raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw "
        "--base-deck sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir "
        "--variant-raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt.raw "
        "--variant-deck sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt.cir "
        "--base-log sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.log "
        "--variant-log sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt.log "
        "--json design/v3/power_priority/hotfault_48v_120a_cshunt.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii "
        "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt_srprobe.cir",
        "python tools/sr_fault_probe_report.py --case 48v_120a_cshunt "
        "--json design/v3/power_priority/sr_fault_probe_48v_120a_cshunt.json",
        # ELE-09: the 22-period 5/2 ns pair, then the phase-aligned window.
        # The step comparison accepts only decks that differ in .tran step.
        "/d/ADI/LTspice/LTspice.exe -b -ascii sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_2n.cir",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.raw --periods 22 "
        "--vin 50 --rl 0.0163 "
        "--compare-raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_2n.raw "
        "--json design/v3/power_priority/energy_ledger_50v_120a_steps.json",
        "python tools/sr_loss_audit.py "
        "--case candidate_50v_120a candidate_50v_120a_2ns "
        "--compare candidate_50v_120a candidate_50v_120a_2ns "
        "--json design/v3/power_priority/sr_loss_audit_50v_120a_steps.json",
        "/d/ADI/LTspice/LTspice.exe -b -ascii "
        "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_aligned.cir",
        "python tools/energy_ledger_100a.py "
        "--raw sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_aligned.raw "
        "--periods 133 --vin 50 --rl 0.0163 --no-step-check "
        "--json design/v3/power_priority/energy_ledger_50v_120a_aligned.json",
        "python -m pytest tools -q",
        "python tools/ci_check.py",
    ],
}

SCOPE_DESCRIPTION = {
    "v2": "current candidate only: round-4 decks/models/scripts/results + run metadata",
    "v3": "100 A design delivery: v3 decks/raws, magnetics package, "
          "stage-F protocol, BOM package, 48 V/110 A and 120 A candidate "
          "records + deck-derived run metadata",
}

SCOPE_SUPERSEDES = {
    "v2": {
        "path": "design/baseline/baseline_manifest.json",
        "entries": 304,
        "status": "historical; five known hash mismatches, do not reproduce from it",
    },
    "v3": {
        "path": "design/v2/manifest_current_candidate.json",
        "status": "historical; the v2 round-4 package, superseded by this v3 delivery",
    },
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=sorted(SCOPES), default="v2")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=ROOT / "design/v2/round4_summary.json")
    args = ap.parse_args()

    sources = SCOPES[args.scope]
    out_path = args.json or ROOT / f"design/{args.scope}/manifest_current_candidate.json"
    entries = [entry(path, kind) for kind, paths in sources.items() for path in paths]
    decks = [deck_timing(path) for path in sources["deck"]]
    payload = {
        "generated": date.today().isoformat(),
        "scope": SCOPE_DESCRIPTION[args.scope],
        "supersedes": SCOPE_SUPERSEDES[args.scope],
        "entries": entries,
        "missing": [row["path"] for row in entries if row.get("status") == "missing"],
        "deck_timing": decks,
        "raw_run_metadata": run_metadata(args.summary) if args.scope == "v2" else {},
        "reproduce": REPRODUCE[args.scope],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path}  ({len(entries)} entries, {len(payload['missing'])} missing)")


if __name__ == "__main__":
    main()
