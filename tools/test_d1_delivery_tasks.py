"""Engineering delivery WBS sanity checks (task ownership and dependencies)."""
from __future__ import annotations

import csv
from pathlib import Path

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
