"""Validate D1 six-lane execution table, dependencies, and physical gates.

This is a planning-data integrity check. It must NEVER open a hardware gate.
    python tools/check_d1_parallel_execution.py
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_CSV = ROOT / "hardware/dcx_main/d1_parallel_execution_2026-11-07.csv"
GATE_JSON = ROOT / "hardware/dcx_main/d1_parallel_gate_matrix_2026-11-07.json"
LANES = {"A_SIM", "B_MAG", "C_PCB", "D_PROT", "E_BIAS", "F_SUPPLY_THERM"}
STATES = {
    "IN_PR", "READY_TO_SEND", "PENDING_EXECUTION", "PENDING_EXTERNAL",
    "BLOCKED_PHYSICAL", "PENDING_NATIVE_EDA", "DRAFT_CONNECTIVITY_ONLY",
    "PENDING_DESIGN", "PENDING_VENDOR_DATA", "BLOCKED_CAD_SIGNOFF",
    "PENDING_BENCH", "BLOCKED_HARDWARE", "DRAFT_PR",
    "PENDING_NATIVE_ERC", "PENDING_TOPOLOGY", "BLOCKED_OEM_MODEL",
    "PENDING_VENDOR", "PENDING_FIXTURE", "EVIDENCE_REVIEW", "VERIFIED",
}
COLUMNS = [
    "task_id", "lane", "priority", "target_window", "owner_role", "status",
    "depends_on", "deliverable", "evidence_required", "linked_issue",
    "linked_pr", "unblocks", "can_parallel_with",
]
REQUIRED_GATES = ("M0_5A", "M0_10A", "M1", "M2", "M3")
HIGH_RISK = {"M1", "M2", "M3"}


def dependencies(row: dict[str, str]) -> list[str]:
    return [x.strip() for x in row["depends_on"].split(",") if x.strip()]


def validate_rows(rows: list[dict[str, str]]) -> dict:
    if len(rows) < 29:
        raise ValueError("parallel lanes or initial D1 work packages missing")
    by_id = {}
    for row in rows:
        if set(row) != set(COLUMNS):
            raise ValueError("task CSV columns drifted")
        task_id = row["task_id"]
        if not re.fullmatch(r"[ABCDEF][0-9]{2}", task_id):
            raise ValueError("invalid task id: " + task_id)
        if task_id in by_id:
            raise ValueError("duplicate task id: " + task_id)
        if row["lane"] not in LANES:
            raise ValueError("unknown lane: " + row["lane"])
        if row["priority"] not in {"P0", "P1", "P2"}:
            raise ValueError("invalid priority: " + task_id)
        if row["status"] not in STATES:
            raise ValueError("invalid task status: " + task_id)
        if row["status"] == "VERIFIED":
            raise ValueError(
                "task cannot be marked VERIFIED without separate "
                "human-verified evidence entry: " + task_id
            )
        for mandatory in ("owner_role", "deliverable", "evidence_required",
                          "target_window"):
            if not row[mandatory].strip():
                raise ValueError(f"{task_id} missing {mandatory}")
        by_id[task_id] = row
    if {r["lane"] for r in rows} != LANES:
        raise ValueError("six independent workstreams required")
    for task_id, row in by_id.items():
        for needed in dependencies(row):
            if needed not in by_id:
                raise ValueError(f"{task_id} depends on unknown task {needed}")
            if needed == task_id:
                raise ValueError(f"{task_id}: self-dependency")
    temporary = set()
    permanent = set()

    def visit(node: str) -> None:
        if node in temporary:
            raise ValueError("cycle in D1 task dependencies: " + node)
        if node in permanent:
            return
        temporary.add(node)
        for needed in dependencies(by_id[node]):
            visit(needed)
        temporary.remove(node)
        permanent.add(node)

    for task_id in by_id:
        visit(task_id)
    for key in ("A01", "A02", "B01", "C01", "C02", "D01", "D02",
                "E01", "E03", "F01", "F02", "F03"):
        if dependencies(by_id[key]):
            if key == "A02" and dependencies(by_id[key]) == ["A01"]:
                continue
            raise ValueError("immediately parallel task unexpectedly blocked: " + key)
    return {"task_count": len(by_id), "lanes": sorted(LANES),
            "dependency_graph_acyclic": True}


def validate_gates(payload: dict, task_rows: list[dict[str, str]]) -> dict:
    ids = {t["task_id"] for t in task_rows}
    gates = payload["gates"]
    if [g["gate_id"] for g in gates] != list(REQUIRED_GATES):
        raise ValueError("missing / reordered physical milestones")
    if payload.get("all_hardware_release") is not False:
        raise ValueError("planning file must never authorize hardware")
    known = set(REQUIRED_GATES)
    for g in gates:
        if not g["prerequisite_task_ids"] or not g["human_evidence"]:
            raise ValueError("missing evidence contract for " + g["gate_id"])
        if set(g["prerequisite_task_ids"]) - ids:
            raise ValueError("gate points to unrecognized task")
        preceding = set(g.get("prerequisite_gate_ids", []))
        if preceding - known:
            raise ValueError("gate references unknown predecessor")
        if preceding - {x["gate_id"] for x in gates[:gates.index(g)]}:
            raise ValueError("future/self-dependent gate")
        if g["gate_id"] in HIGH_RISK and not preceding:
            raise ValueError("physical gate must depend on earlier stage")
        if g.get("hardware_power_on_authorized") is not False:
            raise ValueError("planning data must never auto-enable power")
        if g.get("ready") is not False:
            raise ValueError(
                "plan is not a signed hardware-evidence system: "
                "do not mark gates ready in this JSON"
            )
    if "A03" in next(g for g in gates if g["gate_id"] == "M1")[
        "prerequisite_task_ids"
    ]:
        raise ValueError("5A M1 cannot be blocked by 10A model inrush")
    if next(g for g in gates if g["gate_id"] == "M0_5A")[
        "nature"
    ] != "SIMULATION_ONLY":
        raise ValueError("M0_5A scope drift")
    return {"gates": list(REQUIRED_GATES),
            "hardware_release": False, "all_not_ready": True}


def validate(path_csv: Path = TASK_CSV, path_json: Path = GATE_JSON) -> dict:
    with path_csv.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != COLUMNS:
            raise ValueError("CSV header order and names changed")
        tasks = list(reader)
    gates = json.loads(path_json.read_text(encoding="utf-8"))
    return {**validate_rows(tasks),
            "gate_checks": validate_gates(gates, tasks),
            "scope": "DOCUMENT_ONLY_NOT_HARDWARE_SIGNOFF"}


def main() -> int:
    try:
        result = validate()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID_EXECUTION_PLAN",
                          "hardware_release": False,
                          "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": "PLAN_DATA_VALID",
                      "validation": result,
                      "hardware_release": False},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
