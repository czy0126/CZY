"""Tests for tools/extract_op_point.py on a synthetic ASCII raw.

The 100 A point is the evidence behind the magnetic loss table, so the extractor
is pinned here: Pout must be average(Vout^2/RL) (not Vavg^2/RL), RMS must be
time-weighted, and the window must be the last N *complete* gate periods.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from extract_op_point import operating_point

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


def test_constant_point_uses_vsq_over_r(tmp_path: Path) -> None:
    names = ["V(out)", "V(ga1)", "I(Lr)", "I(VSa1)", "I(VSb1)"]
    # 21 samples, 1 us apart; gate rises at 1, 5, 9, 13, 17 us (4 us period).
    rows: list[list[float]] = []
    for i in range(21):
        t = i * 1e-6
        gate = 10.0 if (i % 4) in (1, 2) else 0.0
        rows.append([t, 2.0, gate, 1.0, -10.0, 0.0])
    raw = make_raw(tmp_path / "flat.raw", names, rows)

    out = operating_point(raw, rl_ohm=0.02, periods=4, pairs=(1,))
    # Last 4 complete periods: the last five rising edges are 1..17 us.
    assert out["window_us"] == pytest.approx([1.0, 17.0], abs=1e-6)
    assert out["periods"] == 4
    assert out["freq_khz"] == pytest.approx(250.0, abs=1e-6)
    assert out["vout_avg_v"] == pytest.approx(2.0)
    assert out["pout_w"] == pytest.approx(200.0)
    assert out["iout_sum_a"] == pytest.approx(10.0)
    assert out["ipri_rms_a"] == pytest.approx(1.0)
    assert out["pair1"]["irms_pair_a"] == pytest.approx(10.0)
    assert out["iout_spread_pct"] == 0.0


def test_pout_is_not_vavg_squared_over_r(tmp_path: Path) -> None:
    names = ["V(out)", "V(ga1)", "I(Lr)", "I(VSa1)", "I(VSb1)"]
    # Square wave 1 V / 3 V with 50 % duty: avg = 2 V, avg(V^2) = 5 V^2.
    rows: list[list[float]] = []
    for i in range(21):
        t = i * 1e-6
        gate = 10.0 if (i % 4) in (1, 2) else 0.0
        vout = 3.0 if (i % 4) in (0, 1) else 1.0
        rows.append([t, vout, gate, 0.0, -1.0, 0.0])
    raw = make_raw(tmp_path / "square.raw", names, rows)

    out = operating_point(raw, rl_ohm=1.0, periods=4, pairs=(1,))
    assert out["vout_avg_v"] == pytest.approx(2.0, abs=0.2)
    assert out["pout_w"] == pytest.approx(5.0, abs=0.5)
    assert out["pout_w"] != pytest.approx(out["vout_avg_v"] ** 2 / 1.0, abs=0.5)
