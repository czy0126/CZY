"""The SR fault waveforms must be screened against the vendor charts, not beside them.

SOURCE-03 is not satisfied by quoting "285 A continuous / 1140 A pulse" next to
a measured 285 A: those figures describe a case-limited steady state and a
first-quadrant pulse, while the SR conducts in the *third* quadrant.  The screen
therefore has to say, per device and per quadrant, which vendor curve (if any)
governs.  These tests pin that reporting: the first quadrant is compared to the
digitised SOA, the third quadrant is explicitly reported as outside the chart's
domain, and the die power is carried through the digitised Zth.

The RAW-derived checks skip when the gigabyte-scale files are absent, exactly
like the other simulation tests in this repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
SCREEN = PP / "sr_soa_screen.json"
DIGITIZED = PP / "vendor_soa_digitized.json"
RAW = {
    "48v_120a": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.raw",
    "48v_120a_cshunt": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_cshunt_srprobe.raw",
    "50v_120a_cshunt": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.raw",
}
DEVICES = [f"{pair}{side}" for pair in (1, 2, 3, 4) for side in "AB"]


def screen() -> dict:
    return json.loads(SCREEN.read_text(encoding="utf-8"))


def test_the_screen_cites_the_digitized_chart_it_was_taken_from():
    data = screen()
    digitized = json.loads(DIGITIZED.read_text(encoding="utf-8"))
    assert data["source"]["sha256"] == digitized["source"]["sha256"]
    assert data["source"]["vendored_pdf"] == digitized["source"]["pdf"]


def test_every_device_carries_a_quadrant_record_in_every_run():
    for case, run in screen()["results"]["runs"].items():
        assert sorted(run["devices"]) == sorted(DEVICES), case
        for name, record in run["devices"].items():
            for key in ("vds_max_v", "first_quadrant", "third_quadrant"):
                assert key in record, (case, name, key)


def test_the_first_quadrant_is_compared_point_by_point_and_passes():
    runs = screen()["results"]["runs"]
    for case, run in runs.items():
        for name, record in run["devices"].items():
            first = record["first_quadrant"]
            assert first["samples"] > 0, (case, name)
            assert first["samples_compared"] == first["samples"], (case, name)
            assert first["peak_utilization"] < 1.0, (case, name, first["peak_utilization"])


def test_the_third_quadrant_is_reported_as_outside_the_chart_not_scored():
    data = screen()
    assert data["results"]["quadrants"]["third_quadrant_screened_by_the_chart"] is False
    assert data["results"]["quadrants"]["first_quadrant_is_the_drawn_domain"] is True
    for run in data["results"]["runs"].values():
        for name, record in run["devices"].items():
            assert record["third_quadrant"]["samples"] > 0, name
            assert record["third_quadrant"]["peak_current_a"] < 0.0, name


def test_the_die_power_is_carried_through_the_digitized_zth():
    data = screen()
    for case, run in data["results"]["runs"].items():
        thermal = run["thermal"]
        assert thermal["peak_die_power_w"] > thermal["steady_state_die_power_w"], case
        assert thermal["peak_rise_k"] > 0.0
        # a 190-215 W pulse of a few tens of microseconds cannot approach the
        # 175 C junction limit through a 1 K/W package
        assert thermal["peak_rise_k"] < 60.0, (case, thermal["peak_rise_k"])
        assert thermal["steady_state_die_power_w"] >= 0.0


def test_the_thermal_convolution_reproduces_its_closed_form():
    from sr_soa_screen import thermal_rise

    # A Zth that does not depend on time makes the superposition collapse to
    # (P_end - P_start) * Z, whatever the binning is.
    trace = [[1e-6, 0.5], [1.0, 0.5]]
    times = [i * 1e-6 for i in range(21)]
    power = [0.0] * 5 + [100.0] * 16
    assert thermal_rise(times, power, trace, bin_s=1e-6) == pytest.approx(50.0)


@pytest.mark.parametrize("case", sorted(RAW))
def test_the_screen_can_be_regenerated_when_its_raw_is_present(case):
    if not RAW[case].is_file():
        pytest.skip(f"{RAW[case].name} is gitignored")
    from sr_soa_screen import screen_case

    recorded = screen()["results"]["runs"][case]
    assert screen_case(case) == recorded
