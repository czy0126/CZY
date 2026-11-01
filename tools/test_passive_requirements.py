"""Tests for tools/passive_requirements.py.

The output-capacitor ripple is rebuilt by KCL, so the reconstruction is pinned
on a synthetic square wave whose answer is known exactly.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from passive_requirements import (
    capacitor_ripple,
    cr_lr_requirements,
    measure_cin,
    pair_ac_rms,
    path_loss,
    trapezoid_mean,
)
from magnetics_design import OP_100

HEADER = """Title: test
Plotname: Transient Analysis
Flags: real forward nocompression
No. Variables: {nvars}
No. Points:            0
Variables:
\t0\ttime\ttime
{vars}
Values:
"""


def make_raw(path: Path, names: list[str], rows: list[list[float]]) -> Path:
    vars_text = "".join(f"\t{i + 1}\t{name}\tvoltage\n" for i, name in enumerate(names))
    lines = [HEADER.format(nvars=len(names) + 1, vars=vars_text)]
    for i, row in enumerate(rows):
        lines.append(f"{i}\t\t{row[0]:.12e}\n")
        for value in row[1:]:
            lines.append(f"\t{value:.12e}\n")
    path.write_text("".join(lines), encoding="latin-1")
    return path


def square_wave(t: np.ndarray, low: float, high: float, period: float) -> np.ndarray:
    return np.where((t % period) < period / 2, high, low)


def test_trapezoid_mean_of_a_constant_is_the_constant():
    t = np.linspace(0.0, 2.0, 101)
    assert abs(trapezoid_mean(np.full_like(t, 7.5), t) - 7.5) < 1e-12


def test_square_wave_ripple_has_known_mean_and_rms():
    t = np.linspace(0.0, 20e-6, 200001)
    current = square_wave(t, 0.0, 200.0, 2e-6)
    data = capacitor_ripple(t, current)
    assert abs(data["load_mean_a"] - 100.0) < 0.05
    assert abs(data["ripple_rms_a"] - 100.0) < 0.05
    assert abs(data["secondary_pp_a"] - 200.0) < 1e-9
    assert abs(data["ripple_pk_a"] - 100.0) < 0.05


def test_pair_ac_rms_removes_only_the_dc_part():
    t = np.linspace(0.0, 20e-6, 200001)
    pair = square_wave(t, 0.0, 50.0, 2e-6)
    assert abs(pair_ac_rms(t, pair) - 25.0) < 0.05


def test_cr_and_lr_share_the_measured_primary_current():
    data = cr_lr_requirements(OP_100)
    assert data["irms_a"] == OP_100["Ipri_rms_A"]
    assert data["ipk_a"] == OP_100["Ipri_pk_A"]
    expected = 0.5 * 1e-6 * OP_100["Ipri_pk_A"] ** 2
    assert abs(data["lr_energy_at_ipk_j"] - expected) < 1e-12


def test_path_loss_rule_of_thumb():
    assert abs(path_loss(100.0, 0.10e-3) - 1.0) < 1e-9
    assert path_loss(50.0, 0.10e-3) == 0.25


def test_measure_cin_separates_the_rail_mean_from_the_ripple(tmp_path):
    """I(Cin) is pure AC (mean 0, RMS 5 A); the source line carries the DC."""
    t = np.linspace(0.0, 20e-6, 4001)
    icin = square_wave(t, -5.0, 5.0, 2e-6)
    raw = make_raw(tmp_path / "cin.raw", ["I(Cin)", "I(Rin)"],
                   [[tt, c, 4.0] for tt, c in zip(t, icin)])
    data = measure_cin(raw, 0.0, 20.0)
    assert abs(data["cin_mean_a"]) < 0.05
    assert abs(data["cin_rms_ac_a"] - 5.0) < 0.05
    assert abs(data["source_mean_a"] - 4.0) < 1e-9
    assert data["source_rms_ac_a"] < 1e-9
    # KCL: the converter sees I(Rin) - I(Cin) = 4 A DC riding a 5 A square.
    assert abs(data["bridge_mean_a"] - 4.0) < 0.05
    assert abs(data["bridge_rms_a"] - np.sqrt(16.0 + 25.0)) < 0.05
