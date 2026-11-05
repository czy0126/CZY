"""Tests for the value-only ECO executor.

The batch has been executed, so the claims worth locking are now about the
*record* rather than the plan:

* the ECO table no longer asks for a value edit -- the board took all 37, and
  the proof is that ``build()`` is empty while the rows still exist as
  ``ALREADY_CONFORMS`` (only their MPN is open);
* the committed plan still lists those 37 and every one is what the saved
  board reads, so an executed run cannot be mistaken for a stale plan or for
  an unapplied one;
* the twelve package/device rows are still outside the plan: ``modify`` has no
  footprint setter, and a plan that listed one would be a promise the API
  cannot keep;
* the rendered body stays pure ASCII and differs from the dry run by exactly
  the APPLY token, so "the dry run passed" can never describe a different
  script from the one that edits.

Run:
    python -m pytest tools/test_native_value_eco.py -q
"""

from __future__ import annotations

import json

import pytest

import native_value_eco as eco


@pytest.fixture(scope="module")
def plan() -> dict:
    """What the ECO table asks for today -- empty once the batch has run."""
    return eco.build()


@pytest.fixture(scope="module")
def committed() -> dict:
    """The committed plan: the record of the batch that was executed."""
    return json.loads(eco.PLAN.read_text(encoding="utf-8"))


def test_the_eco_table_no_longer_asks_for_a_value_edit(plan):
    """A non-empty plan here means a row regressed after the batch ran."""
    table = json.loads(eco.ECO.read_text(encoding="utf-8"))
    assert {r["ref"] for r in table["rows"] if r["eco_class"] == eco.EXECUTED_CLASS} == set()
    assert plan["edits"] == []


def test_the_committed_plan_records_the_executed_batch(committed):
    """The record must equal what the saved board reads, ref by ref."""
    board = eco._board_values()
    assert committed["count"] == len(committed["edits"]) == 37
    wrong = [(e["ref"], e["to"], board.get(e["ref"]))
             for e in committed["edits"] if board.get(e["ref"]) != e["to"]]
    assert wrong == []


def test_a_package_change_is_never_in_the_plan(committed):
    """``modify`` has no footprint setter; listing one would be a false promise."""
    planned = {e["ref"] for e in committed["edits"]}
    table = json.loads(eco.ECO.read_text(encoding="utf-8"))
    for ref in ("C5", "R3", "Cin", "Cout", "Cr", "D_BT", "Lr", "CT",
                "T1", "T2", "T3", "T4"):
        row = next(r for r in table["rows"] if r["ref"] == ref)
        assert row["eco_class"] == "NATIVE_DEVICE_CHANGE", ref
        assert ref not in planned, ref


def test_every_edit_actually_moves_the_value(committed):
    for e in committed["edits"]:
        assert e["from"], e["ref"]
        assert e["to"], e["ref"]
        assert e["from"] != e["to"], f"{e['ref']} would be a no-op"


def test_the_target_is_written_in_the_schematic_value_style(committed):
    """The string lands in the editor's Value field, so it must read like one.

    A bare number ("5360") would be accepted by the editor and then drawn as
    5360 -- a different part from 5.36k.  Every target therefore carries a unit.
    """
    for e in committed["edits"]:
        assert any(u in e["to"] for u in ("Ω", "uF", "nF", "pF")), (e["ref"], e["to"])
        assert not e["to"][0].isdigit() or "Ω" in e["to"] or e["to"][-2:] in ("uF", "nF", "pF")


def test_the_edits_are_in_natural_reference_order(committed):
    refs = [e["ref"] for e in committed["edits"]]
    assert refs == sorted(refs, key=eco._natural)
    # the naive string sort would put R101 before R2 in a mixed list
    assert eco._natural("R2") < eco._natural("R20") < eco._natural("R101")


def test_the_dry_run_body_and_the_apply_body_differ_only_in_the_token():
    dry = eco.render(apply=False)
    live = eco.render(apply=True)
    assert eco.APPLY_OFF in dry and eco.APPLY_ON not in dry
    assert eco.APPLY_ON in live
    assert dry.replace(eco.APPLY_OFF, eco.APPLY_ON) == live


def test_the_rendered_body_carries_every_planned_edit(plan):
    body = eco.render(apply=False)
    # The literal is ASCII-escaped for the command line, so compare it after
    # parsing -- which also proves the embedded literal is valid JSON, and which
    # is what catches an unsubstituted placeholder: it parses as [] and cannot
    # equal a non-empty plan.  (It cannot be caught by searching for the marker,
    # because an empty plan renders back to the marker's own text.)
    start = body.index("/*__PLAN__*/") + len("/*__PLAN__*/")
    literal = json.loads(body[start:body.index(";", start)])
    assert literal == [{"ref": e["ref"], "want": e["to"]} for e in plan["edits"]]


def test_the_body_is_pure_ascii_so_the_gbk_command_line_cannot_mangle_it():
    """The ohm sign is U+03A9; the Windows console code page cannot carry it."""
    for apply in (False, True):
        body = eco.render(apply=apply)
        assert body.isascii(), [c for c in body if not c.isascii()][:5]


def test_the_body_never_calls_a_setter_that_does_not_exist():
    """Only modify() exists; a footprint or device setter would throw at runtime."""
    body = eco.render(apply=True)
    for forbidden in ("setFootprint", "modifyFootprint", "setDevice", "modifyDevice"):
        assert forbidden not in body, forbidden
    assert "sch_PrimitiveComponent.modify" in body


def test_the_committed_plan_is_current(plan):
    """An executed batch must not read as a stale plan."""
    assert eco.stale_reason(plan) is None


def test_a_plan_whose_edit_is_not_on_the_board_is_stale(tmp_path, monkeypatch, committed):
    """Mutate one target: the record no longer matches the board, so it is stale."""
    broken = json.loads(json.dumps(committed))
    broken["edits"][0]["to"] = "999kΩ"
    target = tmp_path / "value_eco_plan.json"
    target.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(eco, "PLAN", target)
    reason = eco.stale_reason(eco.build())
    assert reason and "not_on_the_board=" in reason
    assert committed["edits"][0]["ref"] in reason


def test_write_plan_refuses_to_erase_an_executed_record(monkeypatch, tmp_path, committed):
    """Regenerating now would write an empty plan over the only account of the run."""
    target = tmp_path / "value_eco_plan.json"
    target.write_text(json.dumps(committed), encoding="utf-8")
    monkeypatch.setattr(eco, "PLAN", target)
    with pytest.raises(SystemExit, match="refusing to overwrite that record"):
        eco.main(["--write-plan"])
    assert json.loads(target.read_text(encoding="utf-8")) == committed
