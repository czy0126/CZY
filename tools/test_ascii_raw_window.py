"""Tests for tools/ascii_raw_window.py on a synthetic ASCII raw."""

from __future__ import annotations

from pathlib import Path

import pytest

from ascii_raw_window import read_window

HEADER = """Title: test
Plotname: Transient Analysis
Flags: real forward nocompression
No. Variables: 3
No. Points:            0
Variables:
\t0\ttime\ttime
\t1\tV(a)\tvoltage
\t2\tV(b)\tvoltage
Values:
"""


def make_raw(path: Path, rows: list[tuple[float, float, float]], truncate: bool = False) -> Path:
    lines = [HEADER]
    for i, (t, a, b) in enumerate(rows):
        lines.append(f"{i}\t\t{t:.12e}\n")
        lines.append(f"\t{a:.12e}\n")
        if not (truncate and i == len(rows) - 1):
            lines.append(f"\t{b:.12e}\n")
    path.write_text("".join(lines), encoding="latin-1")
    return path


def test_window_and_column_mapping(tmp_path: Path) -> None:
    rows = [(0.0, 1.0, 10.0), (1e-6, 2.0, 20.0), (2e-6, 3.0, 30.0), (3e-6, 4.0, 40.0)]
    raw = make_raw(tmp_path / "x.raw", rows)
    t, data = read_window(raw, ["V(b)", "V(a)"], 1e-6, 3e-6)
    assert t.tolist() == [1e-6, 2e-6]
    assert data["V(b)"].tolist() == [20.0, 30.0]
    assert data["V(a)"].tolist() == [2.0, 3.0]


def test_truncated_final_record_is_dropped(tmp_path: Path) -> None:
    rows = [(0.0, 1.0, 10.0), (1e-6, 2.0, 20.0)]
    raw = make_raw(tmp_path / "y.raw", rows, truncate=True)
    t, data = read_window(raw, ["V(b)"], 0.0)
    assert t.tolist() == [0.0]
    assert data["V(b)"].tolist() == [10.0]


def test_missing_trace_raises(tmp_path: Path) -> None:
    raw = make_raw(tmp_path / "z.raw", [(0.0, 1.0, 10.0)])
    with pytest.raises(KeyError):
        read_window(raw, ["V(nope)"], 0.0)
