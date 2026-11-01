"""Regression tests for tools/meas_table.py log parsing.

The fixtures below are verbatim lines from LTspice 26.0.2 logs.  Two flat-line
shapes are easy to confuse: in `V(d1)=-0.265  AT 4.009e-06` the comparison level
is -0.265 and the *result* is the time after AT, while in `MAX(V(g2) )=0 FROM ...`
the result is the number right after the `=`.  Reading the first `=` in the first
shape silently yields -0.265 instead of 4.009 us.
"""

from __future__ import annotations

from pathlib import Path

from meas_table import parse_log

FLAT_LOG = """\
Circuit: D:\\workshop\\design_48v-2v\\sim\\v2\\verify_tie_exact.cir

tc1: V(d1)=-0.265  AT 4.00927173913e-06
g2max: MAX(V(g2) )=0 FROM 4e-06 TO 6e-06
g1_dly: g1r-tc1=1.67260016361e-07
pre_final: V(pre)=0.9999905229
find_at: V(c2f) =0 at 5.9e-06
"""

SWEPT_LOG = """\
Measurement: qrev_cyc
  Step	QREV_CYC
     1	9.5155e-08
     2	9.3221e-08

Measurement: ebd_cyc
  Step	EBD_CYC
     1	6.7884e-06
     2	1.0381e-06

.step pgd=0
.step pgd=1
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_when_measurement_takes_the_time_not_the_comparison_level(tmp_path: Path) -> None:
    _, table = parse_log(write(tmp_path, "flat.log", FLAT_LOG))
    assert table["tc1"][1] == 4.00927173913e-06


def test_max_with_window_takes_the_value_not_the_window_end(tmp_path: Path) -> None:
    _, table = parse_log(write(tmp_path, "flat.log", FLAT_LOG))
    assert table["g2max"][1] == 0.0


def test_param_and_find_lines(tmp_path: Path) -> None:
    _, table = parse_log(write(tmp_path, "flat.log", FLAT_LOG))
    assert table["g1_dly"][1] == 1.67260016361e-07
    assert table["pre_final"][1] == 0.9999905229


def test_find_measurement_takes_the_value_not_the_sample_time(tmp_path: Path) -> None:
    _, table = parse_log(write(tmp_path, "flat.log", FLAT_LOG))
    assert table["find_at"][1] == 0.0


def test_swept_log_still_joins_steps_and_labels(tmp_path: Path) -> None:
    labels, table = parse_log(write(tmp_path, "swept.log", SWEPT_LOG))
    assert labels == ["pgd=0", "pgd=1"]
    assert table["qrev_cyc"] == {1: 9.5155e-08, 2: 9.3221e-08}
    assert table["ebd_cyc"][1] == 6.7884e-06
