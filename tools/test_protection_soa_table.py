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
    assert all(r["comparison_basis"] == "declared_parent" for r in rows)


def test_a_control_based_run_records_its_basis() -> None:
    rows = soa.compare_runs("probe", ("protection_candidate_48v_120a_prot_a.json", 48.0,
                                      "prot_a_oc1v", "base", "topology_matched_control"))
    assert all(r["comparison_basis"] == "topology_matched_control" for r in rows)



def test_hashes_are_portable_between_windows_and_linux_checkout(tmp_path):
    text = '{"x": 1,\n  "y": 2\n}\n'
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(text.encode("utf-8"))
    crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert soa.sha256(lf) == soa.sha256(crlf)


def test_parent_basis_50v_comparisons_are_explicitly_unpaired(table):
    runs = [run for run in table["results"]["runs"] if run.get("case")]
    parent = [run for run in runs if run["comparison_basis"] == "declared_parent"]
    assert len(parent) == 8
    for run in parent:
        if run["vin_v"] == 50.0:
            # The declared 50 V parent sits 13-18 mV away from the candidate
            # before the fault, so its stress deltas are exploratory only.
            assert not run["paired_pre_fault"]
            assert not run["paired_change_can_be_attributed_to_protection"]
            assert run["pre_fault_vout_delta_mv"] > 13
        else:
            assert run["paired_pre_fault"]
            assert run["paired_change_can_be_attributed_to_protection"]
            assert abs(run["pre_fault_vout_delta_mv"]) < 1
    assert table["checks"]["unpaired_50v_parent_comparisons_not_claimed_as_paired"]


def test_control_based_50v_rows_report_the_verdict_they_measured(table):
    """PROT-03 rows must exist and must not overstate what they measured.

    The verdict itself is data: a re-run that misses the 1 mV criterion makes
    ``paired_pre_fault`` false and this test still passes, because it checks the
    verdict against the recorded delta rather than against 1 mV.
    """
    rows = [run for run in table["results"]["runs"]
            if run.get("comparison_basis") == "topology_matched_control"]
    assert {run["source_json"] for run in rows} == {
        "protection_candidate_50v_120a_prot_a_paired.json",
        "protection_candidate_50v_120a_prot_b_paired.json"}
    for run in rows:
        assert run["vin_v"] == 50.0
        rec = json.loads((ROOT / "design/v3/power_priority" / run["source_json"])
                         .read_text(encoding="utf-8"))
        assert run["paired_pre_fault"] == (run["pre_fault_vout_delta_mv"] <= 1.0)
        # Attribution needs both clauses: the same pre-fault state *and* a
        # complete window.  A truncated comparison is still paired, but its
        # benefit may only be quoted over the common slice.
        assert run["paired_change_can_be_attributed_to_protection"] == (
            run["paired_pre_fault"] and rec["coverage"]["declared_window_fully_covered"])
        side = "base" if run["role"] == "compare_base" else "candidate"
        assert run["reached_declared_window"] == rec["coverage"][f"{side}_reached_saved_stop"]
    assert table["checks"]["control_based_rows_come_from_paired_records"]


def test_an_incomplete_row_is_prefix_only_and_never_attributed(table):
    for run in table["results"]["runs"]:
        if not run["reached_declared_window"]:
            assert run["solver_prefix_only"]
            assert not run["paired_change_can_be_attributed_to_protection"]


def test_report_coverage_is_taken_from_evidence_not_hardcoded():
    data = soa.compare_runs("50vcmp", (
        "protection_candidate_50v_120a_prot_b.json", 50.0,
        "prot_b_fast10u_1p8v", "cshunt=1e-15"))
    assert all(x["reached_declared_window"] for x in data)
    assert all(not x["solver_prefix_only"] for x in data)
