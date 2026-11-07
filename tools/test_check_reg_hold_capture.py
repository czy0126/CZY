"""Synthetic traces are used only as unit-test inputs, never bench evidence."""
import math
import pytest
import check_reg_hold_capture as capture


def trace():
    rows = []
    for i in range(1101):
        t = (i-100)*1e-7
        first = i % 50 < 25
        enabled = t < 10e-6
        rows.append(dict(t_s=t, fault_v=3.3 if 0 <= t < 100e-6 else 0,
                         vdd_v=15, reg_v=11 if enabled else 2,
                         vgs1_v=10 if first and enabled else 0,
                         vgs2_v=10 if not first and enabled else 0,
                         vd1_v=-.2 if first else 5, vd2_v=5 if first else -.2,
                         bias_a=.013, psu_cc=0))
    return rows


def test_exercised_channels_with_stable_bias_pass_only_waveform_criteria():
    result = capture.evaluate(trace())
    assert result["status"] == "WAVEFORM_CRITERIA_PASS_ONLY"
    assert not any(result[k] for k in ("hardware_qualified", "thermal_qualified", "commutation_qualified"))


@pytest.mark.parametrize("key,value", [("vdd_v", 12), ("psu_cc", 1),
                                      ("reg_v", 5), ("vgs1_v", 4), ("fault_v", 0)])
def test_a_single_post_deadline_violation_cannot_be_averaged_away(key, value):
    rows = trace()
    rows[700][key] = value
    assert capture.evaluate(rows)["status"] == "REJECTED"


def test_unstarted_reg_and_preexisting_off_gates_cannot_pass():
    rows = trace()
    for r in rows:
        r.update(reg_v=0, vgs1_v=0, vgs2_v=0)
    result = capture.evaluate(rows)
    assert "reg_started" in result["reasons"]
    assert "channel_1_exercised_before_fault" in result["reasons"]


def test_pretrigger_current_limit_is_rejected_even_if_it_recovers():
    rows = trace()
    rows[10]["psu_cc"] = 1
    assert "no_current_limit" in capture.evaluate(rows)["reasons"]


def test_one_sample_spike_is_not_an_exercised_gate():
    rows = trace()
    for row in rows[:100]: row["vgs1_v"] = 0
    rows[50]["vgs1_v"] = 10
    assert "channel_1_exercised_before_fault" in capture.evaluate(rows)["reasons"]


def test_removing_drain_stimulus_cannot_prove_fault_inhibition():
    rows = trace()
    for r in rows[400:]:
        r["vd1_v"] = r["vd2_v"] = 0
    assert "channel_1_stimulus_continues" in capture.evaluate(rows)["reasons"]


@pytest.mark.parametrize("mode", ["duplicate", "gap", "nan", "truncated"])
def test_bad_timebases_or_missing_evidence_are_rejected(mode):
    rows = trace()
    if mode == "duplicate": rows[10]["t_s"] = rows[9]["t_s"]
    if mode == "gap": del rows[10]
    if mode == "nan": rows[10]["bias_a"] = math.nan
    if mode == "truncated": rows = rows[:-5]
    assert capture.evaluate(rows)["status"] == "REJECTED"


def test_template_cannot_pass_as_a_hardware_capture(tmp_path):
    file = tmp_path/"manifest.json"
    file.write_text('{"capture_kind":"not_captured"}')
    assert capture.check_manifest(file)["status"] == "NOT_READY"
