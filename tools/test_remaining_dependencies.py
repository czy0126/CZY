"""Tests for the main board's remaining-dependency table.

The table's job is to turn "six checks fail" into "six things a person can go
and do".  A blocker without a concrete exit is the defect it exists to catch,
so the tests check that every blocker is covered and every exit is one of the
declared kinds -- they do not check that the exits have been done.

Run:
    python -m pytest tools/test_remaining_dependencies.py -q
"""

from __future__ import annotations

import json

import pytest

import remaining_dependencies as deps


@pytest.fixture(scope="module")
def data() -> dict:
    return deps.build()


@pytest.fixture(scope="module")
def gate() -> dict:
    return json.loads(deps.GATE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def eco() -> dict:
    return json.loads(deps.ECO.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- coverage
def test_every_blocking_check_has_an_exit(data, gate):
    """The whole point: no blocker is left as a name with nothing behind it."""
    covered = {row["gate_check"] for row in data["exits"]}
    assert set(gate["blockers"]) <= covered
    assert data["uncovered_blockers"] == []


def test_no_exit_names_a_check_that_is_not_blocking(data, gate):
    """An exit for a check that already passes would read as work still owed."""
    assert {row["gate_check"] for row in data["exits"]} <= set(gate["blockers"])


def test_every_exit_is_one_of_the_declared_kinds(data):
    for row in data["exits"]:
        assert row["exit_kind"] in data["exit_kinds"], row["id"]


def test_every_exit_says_something_a_person_can_do(data):
    for row in data["exits"]:
        assert row["exit"].strip(), row["id"]
        assert row["blocked_by"].strip(), row["id"]
        # An exit that is another tool's name is not an exit.
        assert len(row["exit"]) > 40, row["id"]


# ---------------------------------------------------------------- the view
def test_the_counts_are_copied_from_the_gate_and_not_recomputed(data, gate, eco):
    """A view that drifts from its source is worse than no view."""
    assert data["source"]["gate"]["sha256"] == deps._sha256(deps.GATE)
    assert data["source"]["eco"]["sha256"] == deps._sha256(deps.ECO)
    assert data["summary"]["blocking_checks"] == len(gate["blockers"])
    assert data["summary"]["checks_total"] == len(gate["checks"])
    assert data["summary"]["magnetics_without_a_physical_pad"] == len(
        gate["counts"]["magnetics_missing_physical_pads"])
    assert data["summary"]["bom_rows_not_selected"] == len(
        gate["counts"]["bom_rows_not_selected"])
    assert data["summary"]["placeholders"] == eco["counts"]["placeholders"]
    assert data["summary"]["refs_with_a_verified_mpn"] == eco["counts"]["with_verified_mpn"]


def test_the_ref_lists_are_the_ones_the_eco_classified(data, eco):
    rows = eco["rows"]
    device = [r["ref"] for r in rows if r["eco_class"] == "NATIVE_DEVICE_CHANGE"]
    untraced = [r["ref"] for r in rows if r.get("requirement") is None]
    by_id = {row["id"]: row for row in data["exits"]}
    assert by_id["native_device_change"]["refs"] == device
    assert by_id["part_selection"]["refs_without_a_requirement"] == untraced


def test_the_magnetics_exit_names_the_parts_without_a_pad(data, gate):
    by_id = {row["id"]: row for row in data["exits"]}
    assert by_id["magnetics_physical_pads"]["refs"] == list(
        gate["counts"]["magnetics_missing_physical_pads"])


def test_the_evidence_files_are_the_ones_the_gate_reads(data, gate):
    """A page that names a slightly different filename sends the reader to
    create a file the gate will never look at."""
    by_id = {row["id"]: row for row in data["exits"]}
    for row_id, key in (("native_erc", "native_erc"),
                        ("routed_pcb", "pcb_to_schematic"),
                        ("fab_package", "fab_approval"),
                        ("protection_signoff", "protection_design")):
        assert by_id[row_id]["evidence_file"] == gate["manual_evidence"][key]["path"]


# ---------------------------------------------------------------- honesty
def test_the_page_does_not_release_the_board(data, gate):
    assert data["source"]["gate"]["release_approved"] is False
    assert data["source"]["gate"]["status"] == gate["status"]
    assert data["status"] == "MAIN_BOARD_REMAINING_DEPENDENCIES"


def test_the_table_assigns_no_owner_and_no_date(data):
    """Zero decision owners is the fact the register reports; inventing one
    here would read as an assignment nobody accepted."""
    for row in data["exits"]:
        for invented in ("owner", "reviewer", "due", "due_date", "eta"):
            assert invented not in row, f"{row['id']} carries a {invented}"
    assert "Not a schedule" in deps.render(data)


# ---------------------------------------------------------------- artefacts
def test_the_committed_files_are_current(data):
    for path, text in deps.write(data):
        assert path.is_file(), f"{path} is missing -- run --write"
        assert path.read_text(encoding="utf-8") == text, f"{path} is stale -- run --write"


def test_the_markdown_lists_every_exit_by_id(data):
    text = deps.render(data)
    for row in data["exits"]:
        assert f"### `{row['id']}`" in text, row["id"]
