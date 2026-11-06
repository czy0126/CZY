"""What the input capacitor has to carry, and what the model refuses to say.

The 0.227 A in `I(Cin)` is a property of the 1 mohm source, not of the capacitor
bank: the bridge ripple goes through the source in this deck.  These tests pin the
structure of the report (deck line, published number, worst case, no part names)
and leave the arithmetic of the cascade to the report itself.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import cin_bank as cb

REPO = Path(__file__).resolve().parent.parent
PASSIVE = REPO / "design/v3/bom/passive_requirements.json"
REPORT = REPO / "design/v3/bom/cin_bank.json"
PROBE_DECKS = [
    REPO / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cin.cir",
    REPO / "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i110_cin.cir",
    REPO / "sim/v3/sr_tank_dual_v33_ss_1ms_vin48_i120_cin.cir",
    REPO / "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i110_cin.cir",
    REPO / "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
]
FREQ = 200.622e3
CHECKS = {
    "the_deck_runs_the_capacitor_the_probe_raws_were_taken_on",
    "the_published_100a_requirement_is_reproduced",
    "the_worst_case_is_not_below_the_design_load",
    "every_table_row_is_computed_from_the_same_current",
    "no_part_is_named",
}


def _measurement(raw: str, ac_rms: float, ipri: float) -> dict:
    """The shape `measure()` returns, without needing a multi-hundred-MB raw."""
    return {
        "raw": raw,
        "bridge_ac_rms_a": ac_rms,
        "ipri_peak_a": ipri,
        "cin_ac_rms_a": 0.2271,
        "bridge_ac_peak_model_a": 366.0,
        "spike_sample_share": 0.0022,
        "i2t_in_spike_samples_pct": 1.335,
        "bridge_ac_rms_without_switching_spikes_a": ac_rms * 0.98665,
    }


FAKE = [
    _measurement("sr_tank_dual_v33_ss_1ms_100a_cin.raw", 5.3157, 13.8814),
    _measurement("sr_tank_dual_v33_ss_1ms_vin48_i120_cin.raw", 6.3587, 15.5901),
]


def _tank() -> dict:
    return json.loads((REPO / "design/v3/bom/lr_design.json").read_text(encoding="utf-8"))["tank"]


def _published() -> dict:
    return json.loads(PASSIVE.read_text(encoding="utf-8"))["cin"]


def _committed() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_the_deck_line_parses_into_capacitance_and_esr() -> None:
    cin = cb.deck_cin()
    assert cin["positive_node"] == "vin"
    assert cin["negative_node"] == "0"
    assert cin["capacitance_f"] == pytest.approx(20e-6)
    assert cin["esr_ohm"] == pytest.approx(5e-3)


def test_every_probe_deck_runs_the_same_input_capacitor() -> None:
    """The currents are only comparable if all five decks load the same part."""
    for path in PROBE_DECKS:
        assert cb.deck_cin(path)["element"] == "Cin vin 0 20u Rser=5m", path.name


def test_doubling_the_capacitance_halves_the_capacitive_ripple() -> None:
    small = cb.ripple_row(20e-6, 6.0, 0.0, FREQ, 48.0)
    large = cb.ripple_row(40e-6, 6.0, 0.0, FREQ, 48.0)
    assert small["xc_ohm"] == pytest.approx(2.0 * large["xc_ohm"])
    assert small["dv_pp_sinusoidal_v"] == pytest.approx(2.0 * large["dv_pp_sinusoidal_v"])


def test_the_esr_enters_in_quadrature_so_it_cannot_be_added_to_the_reactance() -> None:
    row = cb.ripple_row(20e-6, 6.3587, 5e-3, FREQ, 48.0)
    assert row["z_ohm"] == pytest.approx(math.hypot(row["xc_ohm"], 5e-3), rel=1e-12)
    assert row["z_ohm"] < row["xc_ohm"] + 5e-3
    # At 20 uF the capacitor is 39.7 mohm, so the model's 5 mohm ESR is a small part
    # of the impedance; ESR only takes over at 120 Hz, not at 200 kHz.
    assert row["z_ohm"] / row["xc_ohm"] < 1.01
    big = cb.ripple_row(1000e-6, 6.3587, 10e-3, FREQ, 48.0)
    assert big["z_ohm"] < 1.01 * 10e-3


def test_the_ripple_falls_monotonically_as_the_bank_grows() -> None:
    table = [cb.ripple_row(c, 6.36, 5e-3, FREQ, 48.0) for c in cb.CAPACITANCE_TABLE_F]
    volts = [row["dv_pp_sinusoidal_v"] for row in table]
    assert volts == sorted(volts, reverse=True)


def test_a_hard_source_keeps_the_ripple_in_the_capacitor() -> None:
    assert cb.source_share(0.0, 20e-6, 5e-3, FREQ) == 0.0
    assert cb.source_share(1e3, 20e-6, 5e-3, FREQ) == pytest.approx(1.0, abs=0.03)
    # The deck's 1 mohm source sends only a few percent of the ripple through the part,
    # which is why the 0.227 A trace is not the requirement.
    assert cb.source_share(1e-3, 20e-6, 5e-3, FREQ) < 0.03


def test_an_unequal_bank_puts_the_current_in_the_big_part() -> None:
    example = cb.per_part((4.7e-6, 22e-6), 6.0, 0.05)
    assert example["max_part_irms_a"] == pytest.approx(6.0 * 22.0 / 26.7)
    assert example["per_part"][1]["share_frac"] == pytest.approx(22.0 / 26.7)
    assert example["per_part"][0]["irms_a"] != pytest.approx(3.0)


def test_the_esr_ceiling_is_per_part_not_for_the_whole_bank() -> None:
    example = cb.per_part((10e-6, 10e-6), 6.0, 0.02)
    assert [part["esr_max_ohm"] for part in example["per_part"]] == [pytest.approx(0.04)] * 2


def test_build_reports_the_rated_point_and_the_worst_measured_load() -> None:
    results = cb.build(FAKE, cb.deck_cin(), _tank(), _published())["results"]
    assert results["bridge_ac_rms_a_at_100a"] == pytest.approx(5.3157)
    assert results["bridge_ac_rms_a_at_worst_measured_load"] == pytest.approx(6.3587)
    assert results["requirement_rise_from_100a_pct"] == pytest.approx(19.62, abs=0.02)
    assert results["ipri_peak_a_at_worst_measured_load"] == pytest.approx(15.5901)


def test_build_refuses_a_set_with_no_100a_measurement() -> None:
    with pytest.raises(SystemExit):
        cb.build(FAKE[1:], cb.deck_cin(), _tank(), _published())


def test_build_refuses_an_empty_set() -> None:
    with pytest.raises(SystemExit):
        cb.build([], cb.deck_cin(), _tank(), _published())


def test_the_committed_report_reproduces_the_published_100a_requirement() -> None:
    committed = _committed()
    assert committed["results"]["bridge_ac_rms_a_at_100a"] == pytest.approx(
        _published()["bridge_ac_rms_a"], rel=1e-9
    )
    assert all(committed["checks"].values())


def test_the_worst_measured_load_is_the_48v_120a_run() -> None:
    results = _committed()["results"]
    assert "vin48_i120" in results["worst_measured_load_raw"]
    assert results["bridge_ac_rms_a_at_worst_measured_load"] == pytest.approx(6.3587, abs=5e-3)


def test_the_gates_are_structure_and_the_numbers_are_results() -> None:
    committed = _committed()
    assert set(committed["checks"]) == CHECKS
    for key in (
        "bridge_ac_rms_a_at_worst_measured_load",
        "requirement_rise_from_100a_pct",
        "ripple_at_the_simulated_point_percent_of_vin",
        "esr_for_a_1w_budget_ohm",
    ):
        assert key in committed["results"]
        assert key not in committed["checks"]


def test_the_committed_report_names_no_part() -> None:
    text = json.dumps(_committed(), ensure_ascii=False).lower()
    for word in ("mpn", "lcsc", "part_number"):
        assert word not in text
    assert _committed()["no_capacitor_datasheet_in_repository"] is True


def test_the_esr_budget_is_one_watt_over_the_current_squared() -> None:
    committed = _committed()
    current = committed["results"]["bridge_ac_rms_a_at_worst_measured_load"]
    assert committed["esr_budget"]["bank_esr_ceiling_ohm"] == pytest.approx(1.0 / (current * current))


def test_the_spike_clipping_is_reported_as_a_sensitivity_not_as_the_requirement() -> None:
    """The requirement uses the whole waveform; the clip only says how much the spikes weigh."""
    committed = _committed()
    results = committed["results"]
    assert results["ac_rms_with_spikes_clipped_to_20a_a"] < results["bridge_ac_rms_a_at_worst_measured_load"]
    assert 0.0 < results["i2t_in_spike_samples_pct"] < 10.0
    assert results["the_repetitive_peak_is_ipri_not_the_model_spike"] is True
