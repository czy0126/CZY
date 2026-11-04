"""The Bage comparison must accept only the declared one-line model change."""
from __future__ import annotations

from pathlib import Path

import pytest

import generate_prot03_bage_diagnostic as gen
import hotfault_diagnostic as hot
import prot03_bage_model_check as c


def _real_pair():
    variant, role = "shunt_2f", "B_CONTROL"
    parent = (gen.SIM / gen.ROLE_FILES[variant][role]).read_text(encoding="utf-8")
    child = gen.deck_content(variant, role)
    return variant, role, parent, child


def test_the_generated_pair_is_accepted_and_names_its_single_difference():
    variant, role, parent, child = _real_pair()
    declared = c.verify_pair(variant, role, parent, child, gen.model_content())
    assert len(declared) == 1
    assert gen.INCLUDE_OLD in declared[0] and gen.INCLUDE_NEW in declared[0]


def test_a_circuit_edit_beside_the_model_include_is_refused():
    variant, role, parent, child = _real_pair()
    edited = child.replace("Rflt_hot flt_hot 0 1m", "Rflt_hot flt_hot 0 2m", 1)
    assert edited != child
    with pytest.raises(ValueError, match="not the declared agefix derivative"):
        c.verify_pair(variant, role, parent, edited, gen.model_content())


def test_a_second_model_change_is_refused():
    variant, role, parent, child = _real_pair()
    altered = gen.model_content().replace("-1m*limit((10-V(age,S))/0.1,0,1)", "-1m", 1)
    assert altered != gen.model_content()
    with pytest.raises(ValueError, match="not the one declared by the generator"):
        c.verify_pair(variant, role, parent, child, altered)


def test_a_window_beyond_a_deck_stop_is_refused_before_any_raw_is_read():
    variant, role, parent, child = _real_pair()
    with pytest.raises(ValueError, match="exceeds a deck's saved stop"):
        c.compare(Path("missing.raw"), Path("missing.raw"), parent, child, window_us=400.0)


def write_raw(path: Path, points: int, step_s: float, values: dict[str, float],
              after_us: float, after: dict[str, float]) -> None:
    """Structurally exact ASCII raw: constant values, replaced after after_us."""
    names = hot.NAMES
    lines = ["Title: synthetic\n", f"No. Variables: {len(names) + 1}\n",
             f"No. Points: {points}\n", "Variables:\n", "\t0\ttime\ttime\n"]
    lines += [f"\t{i}\t{name}\tvoltage\n" for i, name in enumerate(names, start=1)]
    lines.append("Values:\n")
    for k in range(points):
        t = k * step_s
        row = after if t >= after_us * 1e-6 else values
        lines.append(f"{k}\t\t{t:.12e}\n")
        lines += [f"\t{row[name]:.12e}\n" for name in names]
    path.write_text("".join(lines), encoding="latin-1")


DECK_TEXT = """\
.param VIN=50 RL=15.4m
.tran 0 2320u 2000u 1u uic
Vfltctl_hot ctl_hot 0 PWL(0 0 2150u 0 2250u 5 2320u 5)
Sflt_hot out flt_hot ctl_hot 0 HOTFLT
Rflt_hot flt_hot 0 1m
.model HOTFLT SW(Ron=1m Roff=1G Vt=2.5)
.end
"""


def test_the_post_window_scan_finds_the_first_differing_sample(tmp_path: Path):
    base = {name: 0.0 for name in hot.NAMES}
    base.update({"V(oc)": 0.5, "I(Lr)": -50.0, "V(out)": 1.89})
    deviated = dict(base)
    deviated["I(Lr)"] = -51.0
    write_raw(tmp_path / "same_a.raw", 601, 0.5e-6, base, 1000.0, {})
    write_raw(tmp_path / "same_b.raw", 601, 0.5e-6, base, 1000.0, {})
    write_raw(tmp_path / "late.raw", 601, 0.5e-6, base, 250.0, deviated)
    same = c.first_divergence(tmp_path / "same_a.raw", tmp_path / "same_b.raw",
                              220e-6, 300e-6)
    assert same["identical_over_common_prefix"]
    assert same["first_difference_s"] is None
    late = c.first_divergence(tmp_path / "same_a.raw", tmp_path / "late.raw",
                              220e-6, 300e-6)
    assert not late["identical_over_common_prefix"]
    assert late["first_difference_s"] == pytest.approx(250e-6, abs=1e-12)
    assert late["difference_kind"] == "value"
    assert late["compared_samples"] > 0


def test_the_shared_window_reports_the_model_induced_deltas(tmp_path: Path):
    base = {name: 0.0 for name in hot.NAMES}
    base.update({"V(oc)": 0.5, "I(Lr)": -50.0, "V(out)": 1.89,
                 "I(VSa1)": -100.0, "I(VSb1)": -90.0})
    variant_values = dict(base)
    variant_values.update({"I(Lr)": -51.0, "V(out)": 1.90})
    # The ramp 2150->2250 us engages at 2200 us absolute = 200 us saved.
    trip = {"V(oc)": 1.2}
    write_raw(tmp_path / "base.raw", 441, 0.5e-6, base, 210.0, {**base, **trip})
    write_raw(tmp_path / "variant.raw", 441, 0.5e-6, variant_values, 210.0,
              {**variant_values, **trip})
    record = c.compare(tmp_path / "base.raw", tmp_path / "variant.raw",
                       DECK_TEXT, DECK_TEXT)
    results = record["results"]
    assert results["base"]["trip_s"] == pytest.approx(210e-6, abs=1e-9)
    # ipri_peak_a is a magnitude: |-51| - |-50| = +1 A.
    assert results["delta"]["ipri_peak_a"] == pytest.approx(1.0, abs=1e-6)
    assert results["relative"]["ipri_peak_a"] == pytest.approx(0.02, abs=1e-6)
    assert results["delta"]["pre_fault_vout_mean_v"] == pytest.approx(0.01, abs=1e-6)
    assert results["base"]["sr_forward_peak_a"] == pytest.approx(100.0)
    assert results["base"]["sr_reverse_peak_a"] == pytest.approx(-90.0)
    assert record["checks"]["the_comparison_window_is_covered_by_both_raws"]
    assert record["checks"]["the_window_stays_inside_both_decks"]
