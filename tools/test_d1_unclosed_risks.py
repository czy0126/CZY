"""Simulation derived risk assessment must not promote modeled output to a rating."""
from __future__ import annotations

import json
import pytest
import d1_unclosed_risks as r


def test_real_fault_peak_fails_two_turns_not_three():
    j = r.build()
    e = j["evidence"]
    assert e["48v_120a_fault_peak_primary_a"] == pytest.approx(84.826801, abs=1e-3)
    assert e["lr_2turn_flux_at_fault_peak_t"] > e["lr_0p9_bsat_limit_t"]
    assert e["lr_3turn_flux_at_fault_peak_t"] < e["lr_0p9_bsat_limit_t"]
    assert j["continuous_power_approved"] is False


def test_actual_partial_fault_and_loss_gaps_cannot_be_marked_done():
    j = r.build()
    assert j["evidence"]["48v_120a_fault_solver_prefix_only"]
    assert j["evidence"]["48v_120a_fault_vss_at_engage_v"] < 4.0
    assert j["evidence"]["50v_120a_model_loss_residual_w"] > j["evidence"]["target_residual_w"]
    assert j["evidence"]["50v_120a_model_closure_status"] == "NOT_CLOSED"
    assert all(x["blocked"] for x in j["risks"])


def test_settled_fault_evidence_is_recorded_without_unblocking_anything():
    """ELE-08's value is that the fault now lands on a measured settled state.
    Recording it must not promote the gate: no 50 V counterpart, no hardware."""
    j = r.build()
    e = j["evidence"]
    assert e["hotfault_48v_120a_stable_at_design_point"] is True
    assert e["hotfault_48v_120a_pre_fault_vss_v"] >= 4.8
    assert e["hotfault_48v_120a_solver_completed"] is True
    assert e["hotfault_48v_120a_lr_peak_before_trip_a"] == pytest.approx(97.442664, abs=1e-4)
    # The settled fault is worse than the cold-start fault for the 2-turn core.
    assert (e["hotfault_48v_120a_2turn_flux_at_fault_peak_t"]
            > e["lr_2turn_flux_at_fault_peak_t"])
    assert e["hotfault_48v_120a_2turn_flux_at_fault_peak_t"] > e["lr_0p9_bsat_limit_t"]
    assert e["hotfault_48v_120a_3turn_flux_at_fault_peak_t"] < e["lr_0p9_bsat_limit_t"]
    assert e["hotfault_50v_120a_stable_at_design_point"] is True
    assert e["hotfault_50v_120a_pre_fault_vss_v"] >= 4.8
    assert e["hotfault_50v_120a_solver_completed"] is False
    assert e["hotfault_50v_120a_solver_prefix_only"] is True
    assert e["hotfault_50v_120a_lr_peak_before_trip_a"] == pytest.approx(101.2627, abs=1e-3)
    assert (e["hotfault_50v_120a_lr_peak_before_trip_a"]
            > e["hotfault_48v_120a_lr_peak_before_trip_a"])
    assert e["hotfault_50v_120a_2turn_flux_at_fault_peak_t"] > e["lr_0p9_bsat_limit_t"]
    assert e["hotfault_50v_120a_3turn_flux_at_fault_peak_t"] < e["lr_0p9_bsat_limit_t"]
    # Both decks latch one SR gate after trip; only 50 V stalls, so the register
    # must keep the latch as a per-deck fact rather than a stall explanation.
    assert e["hotfault_48v_120a_sr_gate_latched_at_end"] is True
    assert e["hotfault_50v_120a_sr_gate_latched_at_end"] is True
    assert all(x["blocked"] for x in j["risks"])


def test_the_loss_gap_is_not_a_short_window_artifact_but_stays_blocked():
    """ELE-09's decisive leg: 133 aligned periods confirm the same ~0.49 W.

    The short 22-period window was the thing under suspicion, so the register
    must carry both readings and show that the gap barely moved while the
    long window can resolve the 0.2 W target.  Recording that must not unblock
    anything -- an unresolved gap is still an unresolved gap.
    """
    j = r.build()
    e = j["evidence"]
    assert e["50v_120a_aligned_window_periods"] == 133
    assert e["50v_120a_aligned_loss_residual_w"] == pytest.approx(0.492054, abs=1e-5)
    assert e["50v_120a_aligned_loss_residual_w"] > e["target_residual_w"]
    # "Stable" here means the window change moved it by far less than the gap
    # itself; it is not a claim that the gap is acceptable.
    assert abs(e["50v_120a_loss_residual_moves_between_windows_w"]) < 0.05
    assert abs(e["50v_120a_loss_residual_moves_between_windows_w"]) < (
        e["50v_120a_aligned_loss_residual_w"] / 2)
    assert e["50v_120a_aligned_resolves_0p2_w"] is True
    # The inventory audit bounds every un-inventoried dissipative element to
    # about a milliwatt, so the 0.49 W gap cannot be a missing component.
    assert e["50v_120a_cin_ac_rms_a"] > 0.0
    assert e["50v_120a_cin_esr_loss_w"] < 1e-3
    assert e["50v_120a_aligned_loss_residual_w"] > 100 * e["50v_120a_cin_esr_loss_w"]
    # The four 100 A step lengths are not one operating point, and no
    # quadrature rule reproduces their difference -- so the next experiment
    # pins the load rather than changing the integration.
    assert e["sr_step_checks_ok"] is True
    assert e["sr_step_charge_quadrature_rel"] < 0.02
    assert e["sr_step_charge_cross_raw_rel"] > 10 * e["sr_step_charge_quadrature_rel"]
    assert e["sr_step_vout_spread_mv"] > 10.0
    assert e["sr_step_on_time_spread_ns"] > 50.0
    # The SR term is not a passive readout: across the same four runs it moves
    # ~118 W/V against the port's ~200 W/V, so a millivolt of Vout is worth
    # about a tenth of a watt and the 0.49 W gap sits at that resolution.
    assert e["sr_step_loss_per_volt_w"] > 10.0
    assert 0.2 < e["sr_step_loss_sensitivity_vs_port"] < 5.0
    assert e["sr_step_loss_per_volt_w"] * 1e-3 > 0.05
    assert e["50v_120a_model_closure_status"] == "NOT_CLOSED"
    assert all(x["blocked"] for x in j["risks"])


def test_a_pinned_current_does_not_pin_the_operating_point():
    """ELE-09 follow-up: the prescribed current-source load has now been run.

    Both legs draw exactly 100 A, so the resistive family's 1 A load difference
    cannot be the cause of the surviving spread.  What survives is the model's
    own V(out) moving with the step, which is why "pin the current" may no
    longer be prescribed as the next experiment -- only a closed Vout loop can
    pin the operating point.
    """
    j = r.build()
    e = j["evidence"]
    assert e["sr_csink_checks_ok"] is True
    # The effect survives at a fixed current ...
    assert e["sr_csink_vout_delta_mv"] > 10.0
    assert e["sr_csink_diode_loss_spread_x8_w"] > 1.0
    # ... and it is essentially the whole resistive spread, not a fraction.
    assert e["sr_csink_spread_ratio_vs_resistive"] > 0.9
    # The sink pins the current, not the operating point: its own drift is
    # recorded and stays below the cross-leg difference it explains.
    assert 0.0 < e["sr_csink_vout_drift_worst_mv"] < e["sr_csink_vout_delta_mv"]
    # Two independent routes to V(out) -- change the step, or change the load --
    # give the same order of sensitivity, which is what makes "the SR loss
    # follows V(out)" usable rather than a coincidence of one run family.
    assert 0.5 < e["sr_csink_loss_per_volt_w"] / e["sr_step_loss_per_volt_w"] < 2.0
    e02 = next(x for x in j["risks"] if x["id"] == "E02")
    assert "constant-current sink" in e02["next_evidence"]
    assert "pin Iout with a current-source load" not in e02["next_evidence"]
    assert all(x["blocked"] for x in j["risks"])


def test_committed_register_is_reproducible():
    assert json.loads(r.OUT.read_text(encoding="utf-8")) == r.build()


def test_the_solver_diagnostic_bounds_the_prefix_peaks_without_unblocking():
    """PR #20's alternative to the prefix was run; it bounds, it does not approve.

    The 50 V base run stalls at 296.93 us, so its published peaks came from a
    single solver configuration.  The diagnostic re-solves the same circuit
    over 0..220 us with trtol 7->1 and abstol 1e-12->1e-13, which measures the
    numerical error of those peaks instead of assuming it.
    """
    j = r.build()
    e = j["evidence"]
    assert e["hotfault_50v_120a_diag_checks_ok"] is True
    assert e["hotfault_50v_120a_diag_solver_completed"] is True
    assert e["hotfault_50v_120a_diag_window_us"] == pytest.approx(220.0, abs=1e-6)
    # Measured, not a tolerance: the tighter solve moves the peak by 0.16 %.
    assert e["hotfault_50v_120a_diag_ipri_peak_rel"] == pytest.approx(-0.0016144, abs=1e-6)
    assert abs(e["hotfault_50v_120a_diag_sr_forward_peak_rel"]) < 1e-3
    assert abs(e["hotfault_50v_120a_diag_trip_delta_ns"]) < 200
    # The control is the 48 V deck whose base run passed the strict log check.
    # It moves more than the 50 V case, and in the same (safe) direction.
    assert e["hotfault_48v_120a_diag_checks_ok"] is True
    assert e["hotfault_48v_120a_diag_ipri_peak_rel"] == pytest.approx(-0.0041994, abs=1e-6)
    assert e["hotfault_48v_120a_diag_sr_forward_peak_rel"] == pytest.approx(-0.0041141, abs=1e-6)
    assert abs(e["hotfault_48v_120a_diag_trip_delta_ns"]) < 200
    assert e["hotfault_48v_120a_diag_ipri_peak_rel"] < e["hotfault_50v_120a_diag_ipri_peak_rel"]
    f01 = next(x for x in j["risks"] if x["id"] == "F01")
    assert "SOLVER_DIAGNOSTIC is now run" in f01["next_evidence"]
    assert "48 V control" in f01["next_evidence"]
    # A numerical bound is still simulation, so nothing unblocks.
    assert f01["blocked"] is True
    assert all(x["blocked"] for x in j["risks"])
    assert j["continuous_power_approved"] is False



def test_the_eight_device_probe_localizes_the_high_gate_without_unblocking():
    """ELE-10's 48 V half is measured; it must not be mistaken for safe shutdown.

    All four A-side gates latch at the same instant and hold to the end, but
    the final latch carries ~1.4 A while the hundreds of amps flow during the
    release delay.  The 50 V eight-device window does not exist, so F03 stays.
    """
    j = r.build()
    e = j["evidence"]
    assert e["sr_fault_probe_48v_checks_ok"] is True
    assert e["sr_fault_probe_48v_reached_tstop"] is True
    assert e["sr_fault_probe_48v_solver_prefix_only"] is False
    assert e["sr_fault_probe_48v_devices_high_at_end"] == ["1A", "2A", "3A", "4A"]
    assert e["sr_fault_probe_48v_latch_start_us"] == pytest.approx(247.070287, abs=1e-5)
    assert e["sr_fault_probe_48v_latch_duration_us"] == pytest.approx(72.929713, abs=1e-5)
    # The latch is low-current; the 285 A peak is in the release window.
    assert e["sr_fault_probe_48v_latch_max_current_a"] == pytest.approx(1.405253, abs=1e-5)
    assert e["sr_fault_probe_48v_a_forward_peak_post_a"] == pytest.approx(285.014, abs=1e-2)
    assert e["sr_fault_probe_48v_latch_max_i2t_abs_a2s"] < (
        0.01 * e["sr_fault_probe_48v_a_forward_i2t_post_a2s"])
    # A is released later than B, and its gate-high I2t covers most of its
    # post-trip forward I2t (the channel, not the body diode, carries it).
    assert (e["sr_fault_probe_48v_a_drive_release_us"]
            > e["sr_fault_probe_48v_b_drive_release_us"])
    assert e["sr_fault_probe_48v_a_gate_high_i2t_a2s"] > (
        0.5 * e["sr_fault_probe_48v_a_forward_i2t_post_a2s"])
    # Independent cross-check: the probe's 1A release must equal the base
    # JSON's pair-1 figure, which was produced by a different run and tool.
    assert e["sr_fault_probe_48v_a_drive_release_us"] == pytest.approx(
        e["hotfault_48v_120a_first_sustained_drive_stop_us"], abs=1e-6)
    f03 = next(row for row in j["risks"] if row["id"] == "F03")
    assert f03["blocked"] is True
    assert "eight-device" in f03["next_evidence"] or "eight-SR" in f03["next_evidence"]
    assert "50 V" in f03["next_evidence"]
    assert all(x["blocked"] for x in j["risks"])


def test_f03_is_a_hard_sr_shutdown_blocker_independent_of_the_oc_trip():
    data = r.build()
    metrics = data["evidence"]
    assert metrics["hotfault_48v_full_duration_sr_gate_high"] is True
    assert metrics["hotfault_50v_prefix_and_sr_gate_high"] is True
    assert metrics["hotfault_48v_sr_a_gate_final_v"] > 10.0
    assert metrics["hotfault_50v_solver_prefix"] is True
    f03 = next(row for row in data["risks"] if row["id"] == "F03")
    assert f03["priority"] == "P0" and f03["blocked"]
    assert data["next_priority"][0] == "F03"


def test_the_cshunt_child_is_a_solver_aid_not_a_replacement_for_the_base():
    """The 50 V base still stalls; the cshunt child supplies the complete axis.

    The register must carry both facts, and the child must be quoted through
    its prefix deltas -- "it reached 320 us" alone would promote a solver
    change into a base-run claim.
    """
    j = r.build()
    e = j["evidence"]
    assert e["hotfault_50v_120a_cshunt_checks_ok"] is True
    assert e["hotfault_50v_120a_cshunt_variant_completed"] is True
    assert e["hotfault_50v_120a_cshunt_base_completed"] is False
    assert abs(e["hotfault_50v_120a_cshunt_ipri_peak_rel"]) < 0.01
    assert abs(e["hotfault_50v_120a_cshunt_sr_forward_peak_rel"]) < 0.01
    assert e["hotfault_50v_120a_cshunt_trip_delta_ns"] > 0
    # The base record is still a prefix of the same solve.
    assert e["hotfault_50v_120a_solver_completed"] is False
    assert e["hotfault_50v_120a_solver_prefix_only"] is True
    f01 = next(row for row in j["risks"] if row["id"] == "F01")
    assert "cshunt" in f01["next_evidence"]
    assert all(x["blocked"] for x in j["risks"])


def test_the_50v_eight_device_record_is_complete_but_not_safe_shutdown():
    """The cshunt child answers the eight-device question for 50 V.

    Its end state has no high gate, while the stalled base prefix did.  The
    register must carry both observations: neither is a safety proof, and the
    difference is exactly why the end state cannot be treated as a circuit
    property.
    """
    j = r.build()
    e = j["evidence"]
    assert e["sr_fault_probe_50v_cshunt_reached_tstop"] is True
    assert e["sr_fault_probe_50v_cshunt_solver_prefix_only"] is False
    assert e["sr_fault_probe_50v_cshunt_devices_high_at_end"] == []
    assert e["sr_fault_probe_50v_cshunt_final_latch_devices"] == []
    # The base prefix saw the opposite end state; both facts stay recorded.
    assert e["hotfault_50v_120a_sr_gate_latched_at_end"] is True
    assert e["hotfault_50v_120a_solver_prefix_only"] is True
    f03 = next(row for row in j["risks"] if row["id"] == "F03")
    assert "solver" in (f03["blocker"] + f03["next_evidence"])
    assert all(x["blocked"] for x in j["risks"])


def test_the_48v_control_flips_the_latched_phase_without_moving_the_stress():
    """If 1 fF changes which phase latches, the phase is not a circuit property.

    The base 48 V run latches all four A gates; the same circuit with
    cshunt=1 fF latches all four B gates at 249.38 us.  The fault stress moves
    less than 0.5 %, so this is not a different fault -- it is the dead-state
    trajectory choosing which phase crosses the SR turn-on threshold.
    """
    j = r.build()
    e = j["evidence"]
    assert e["sr_fault_probe_48v_devices_high_at_end"] == ["1A", "2A", "3A", "4A"]
    assert e["sr_fault_probe_48v_cshunt_devices_high_at_end"] == ["1B", "2B", "3B", "4B"]
    assert e["hotfault_48v_120a_cshunt_checks_ok"] is True
    assert e["hotfault_48v_120a_cshunt_base_completed"] is True
    assert e["hotfault_48v_120a_cshunt_variant_completed"] is True
    assert abs(e["hotfault_48v_120a_cshunt_ipri_peak_rel"]) < 0.01
    assert abs(e["hotfault_48v_120a_cshunt_sr_forward_peak_rel"]) < 0.01
    assert e["hotfault_48v_120a_cshunt_circuit_differences"] == 0
    # The latch keeps its low-current character; only its phase changed.
    assert 1.0 < e["sr_fault_probe_48v_cshunt_latch_max_current_a"] < 1.5
    f03 = next(row for row in j["risks"] if row["id"] == "F03")
    assert "phase" in f03["blocker"]
    f03_blocked = f03["blocked"]
    assert f03_blocked is True
    assert all(x["blocked"] for x in j["risks"])




def test_the_cshunt_aid_does_not_complete_the_cold_overload():
    """The 50 V rescue does not transfer: this deck stalls 1.96 ms earlier.

    Recording it as a negative result keeps the aid from being re-proposed as
    an untried prescription.  The common slice also bounds the pre-stall peaks:
    the aid moves them by less than a tenth of a percent, so the published
    84.83 A / 255.22 A are not artifacts of this solver setting.
    """
    j = r.build()
    e = j["evidence"]
    assert e["cold_oc_cshunt_variant_completed"] is False
    assert e["cold_oc_cshunt_base_t_last_us"] == pytest.approx(7571.41, abs=0.1)
    assert e["cold_oc_cshunt_variant_t_last_us"] == pytest.approx(5614.06, abs=0.1)
    assert e["cold_oc_cshunt_variant_t_last_us"] < e["cold_oc_cshunt_base_t_last_us"]
    assert e["cold_oc_cshunt_declared_window_covered"] is False
    assert e["cold_oc_cshunt_circuit_differences"] == 0
    assert abs(e["cold_oc_cshunt_ipri_peak_rel"]) < 0.001
    assert abs(e["cold_oc_cshunt_sr_forward_peak_rel"]) < 0.001
    assert abs(e["cold_oc_cshunt_trip_delta_s"]) < 1e-6  # 580 ns, still 1e-4 relative
    f02 = next(row for row in j["risks"] if row["id"] == "F02")
    assert "cshunt" in (f02["blocker"] + f02["next_evidence"])
    assert f02["blocked"] is True
    assert all(x["blocked"] for x in j["risks"])
