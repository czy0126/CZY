"""Tests for the consolidated protection/SOA table."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import protection_soa_table as soa

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "design/v3/power_priority/protection_soa_table.json"


@pytest.fixture(scope="module")
def table() -> dict:
    return soa.build()


def test_the_committed_table_is_current(table: dict) -> None:
    stored = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert table == stored


def test_every_run_has_eight_devices(table: dict) -> None:
    for run in table["results"]["runs"]:
        assert len(run["devices"]) == 8
        assert {r["device"] for r in run["devices"]} == {
            f"{n}{s}" for n in (1, 2, 3, 4) for s in ("a", "b")}


def test_the_window_definition_is_not_merged(table: dict) -> None:
    for run in table["results"]["runs"]:
        assert run["window"] in ("post_trip", "saved_window")
    assert table["results"]["window_definitions"]["post_trip"]
    assert table["results"]["window_definitions"]["saved_window"]


def test_the_unarmed_control_is_excluded(table: dict) -> None:
    sources = {run["source_json"] for run in table["results"]["runs"]}
    assert not any("unarmed" in name for name in sources)


def test_a_null_is_declared_and_never_turned_into_zero(table: dict) -> None:
    for run in table["results"]["runs"]:
        for row in run["devices"]:
            for name, value in row.items():
                if value is None and name != "device":
                    assert (name in run["unrecorded_fields"]
                            or name in run["null_by_design_fields"])


def test_the_summary_takes_the_worst_device(table: dict) -> None:
    by_run = {run["run"]: run for run in table["results"]["runs"]}
    for summary in table["results"]["summary"]:
        run = by_run[summary["run"]]
        worst = max(run["devices"], key=lambda r: r["forward_peak_a"])
        assert summary["worst_forward_peak_a"] == worst["forward_peak_a"]
        assert summary["worst_forward_device"] == worst["device"]


def test_every_source_hash_is_recorded(table: dict) -> None:
    for run in table["results"]["runs"]:
        assert len(run["source_sha256"]) == 64
        int(run["source_sha256"], 16)


def test_the_table_does_not_claim_a_vendor_soa(table: dict) -> None:
    res = table["results"]
    assert res["vendor_soa_available"] is False
    assert res["reverse_current_components_resolved"] is False
    assert "screening list" in " ".join(res["limits"])


def test_the_compare_runner_emits_base_and_candidate() -> None:
    rows = soa.compare_runs("probe", ("protection_candidate_48v_120a_prot_a.json", 48.0,
                                      "prot_a_oc1v", "base"))
    assert [r["role"] for r in rows] == ["compare_base", "candidate"]
    assert all(r["case"] == "prot_a_oc1v" for r in rows)
