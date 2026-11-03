"""The burden probe may add probes and nothing else.

The point of the derived deck is that the raw it produces is evidence about the
*parent* circuit.  If the generator ever touched a component, the solver, the
tran line or a measurement, that claim would be false.  These checks pin the
one-line diff, the position of that line inside the ``.save`` block, and the
fact that the committed deck is exactly what the generator produces.
"""

from __future__ import annotations

import pytest

import make_startup_burden_probe as probe

PARENT = probe.SOURCE.read_text(encoding="utf-8")
BUILT = probe.build(PARENT)


def test_exactly_one_body_line_is_added():
    body = BUILT[len(probe.HEADER):]
    added = [line for line in body.splitlines() if line not in PARENT.splitlines()]
    assert added == [probe.PROBES.rstrip("\n")]
    removed = [line for line in PARENT.splitlines() if line not in body.splitlines()]
    assert removed == []


def test_the_added_line_is_a_save_continuation_inside_the_save_block():
    lines = BUILT.splitlines()
    index = lines.index(probe.PROBES.rstrip("\n"))
    assert lines[index].startswith("+ ")
    # Walk back to the .save statement and forward to the first .meas.
    start = max(i for i in range(index) if lines[i].startswith(".save "))
    assert not any(lines[i].startswith(".meas") for i in range(start, index))


def test_the_parent_body_is_otherwise_byte_identical():
    body = BUILT[len(probe.HEADER):]
    assert body.replace(probe.PROBES, "", 1) == PARENT
    assert BUILT.count(probe.TRAN.rstrip("\n")) == 1


def test_the_generator_refuses_a_deck_without_the_probe_anchors():
    with pytest.raises(ValueError):
        probe.build(PARENT.replace("Lct1 nr nct 2u", "Lct1 nr nct 3u"))
    with pytest.raises(ValueError):
        probe.build(PARENT.replace(probe.ANCHOR, ""))
    with pytest.raises(ValueError):
        probe.build(PARENT.replace(probe.TRAN, ".tran 0 2m 0 10n uic\n"))


def test_the_committed_deck_is_what_the_generator_produces():
    assert probe.DESTINATION.is_file(), "--write the probe deck"
    assert probe.DESTINATION.read_text(encoding="utf-8") == BUILT


def test_the_header_does_not_claim_a_run():
    assert "UNRUN" in probe.HEADER
    assert probe.HEADER.startswith("*")
