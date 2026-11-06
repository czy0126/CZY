"""Engineering delivery WBS sanity checks (task ownership and dependencies)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import performance_first_design as perf

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "hardware/dcx_main/d1_delivery_tasks.csv"
FIELDS = {"id","priority","workstream","owner_role","earliest_workday",
          "target_workday","depends_on","deliverable","acceptance","status","blocker"}


def tasks() -> list[dict[str, str]]:
    with TASKS.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert set(reader.fieldnames or []) == FIELDS
        return list(reader)


def test_all_tasks_have_real_deliverables_and_roles():
    rows = tasks()
    ids = [r["id"] for r in rows]
    assert len(rows) >= 12 and len(set(ids)) == len(ids)
    assert any(r["status"] == "deferred" for r in rows)
    assert any("PCB" in r["workstream"] or "PCB" in r["id"] for r in rows)
    for row in rows:
        assert row["owner_role"] and row["deliverable"] and row["acceptance"]
        assert row["status"] in {"blocked","in_progress","deferred","done"}
        if row["status"] == "blocked":
            assert row["blocker"]


def test_dependencies_form_dag_and_never_reference_nonexistent_tasks():
    lookup = {r["id"]:r for r in tasks()}
    visited = set()
    visiting = set()

    def walk(key):
        if key in visiting:
            raise AssertionError(f"cycle: {key}")
        if key in visited:
            return
        visiting.add(key)
        for dep in filter(None, lookup[key]["depends_on"].split(";")):
            assert dep in lookup and dep != key
            walk(dep)
        visiting.remove(key)
        visited.add(key)

    for key in lookup:
        walk(key)
    assert len(visited) == len(lookup)


def test_release_has_explicit_cad_pcb_and_manufacturing_gates():
    lookup = {r["id"]:r for r in tasks()}
    assert set(lookup["QA-01"]["depends_on"].split(";")) >= {"CAD-03","MFG-02"}
    assert set(lookup["CAD-03"]["depends_on"].split(";")) >= {"MAG-01","BOM-01","CAD-02"}
    assert lookup["THERM-01"]["status"] == "deferred"
    assert lookup["QA-01"]["status"] != "done"



def test_performance_first_not_fab_release_depends_on_high_margin_hardware():
    lookup = {r["id"]: r for r in tasks()}
    assert set(lookup["QA-01"]["depends_on"].split(";")) >= {
        "PERF-01", "PERF-02", "PROT-02", "ELE-10"}
    for key in ("PERF-01", "PERF-02", "PROT-02"):
        assert lookup[key]["priority"] == "P0"
        # Not done is the invariant.  PROT-02 may be in_progress: a candidate
        # comparison exists for 48 V, but the 50 V record and the hardware
        # design do not, so it must not reach "done".
        assert lookup[key]["status"] in {"blocked", "in_progress"}
        assert lookup[key]["acceptance"]
    assert lookup["THERM-01"]["status"] == "deferred"


def test_the_performance_first_ripple_target_is_the_one_the_rfq_quotes():
    """PERF-02 and the RFQ row state the same requirement; they must not drift.

    The delivery task used to repeat a literal (>=78.72Arms) that no artefact
    produced, while the RFQ computed it from the rated-point ripple.  Both are
    now derived from ``cout_bank.json``'s sizing point, so the test recomputes
    the target from that bank instead of trusting either file's text.
    """
    bank = json.loads((ROOT / "design/v3/bom/cout_bank.json")
                      .read_text(encoding="utf-8"))["requirements"]
    target = bank["irms_a"] * perf.COUT_RIPPLE_MARGIN
    assert target > bank["irms_a"]
    lookup = {r["id"]: r for r in tasks()}
    assert f">={target:.2f}Arms" in lookup["PERF-02"]["acceptance"]
    _, rows = perf.build()
    cout = next(r for r in rows if r["group"] == "Cout_bank_high_voltage")
    assert f"{target:.2f}Arms" in cout["unlimited_cost_request"]
