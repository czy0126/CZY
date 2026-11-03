"""The Python port of the 50 V matched-case runner keeps the PowerShell contract.

The port exists because the analysis machine's execution policy forbids ``.ps1``
files and pytest cannot drive PowerShell.  These tests pin the parts a port can
silently drift on: the deck gates, the run-id shape, the dry run, the refusal to
overwrite an archive, and -- most important -- that a dead solver still leaves
its evidence behind with all three safety flags false.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import run_d1_50v_matched_cases as runner

ROOT = Path(__file__).resolve().parent.parent


def test_every_committed_50v_deck_passes_the_same_gates():
    assert len(runner.DECKS) == 4
    for case in runner.DECKS:
        assert (runner.SIM / runner.DECKS[case]).is_file()
        runner.validate_deck(case, runner.deck_text(case))


@pytest.mark.parametrize("needle,reason", [
    ("cshunt=1e-15", "solver options changed"),
    (".tran 0 2320u 2000u 5n uic", "320 us save window changed"),
    ("../../models/", "model includes changed"),
])
def test_a_deck_that_lost_a_gate_is_rejected(needle, reason):
    text = runner.deck_text("A_CANDIDATE").replace(needle, "X")
    with pytest.raises(ValueError, match=reason):
        runner.validate_deck("A_CANDIDATE", text)


def test_an_unknown_case_is_named_not_guessed(capsys):
    with pytest.raises(SystemExit, match="unknown case NO_SUCH_CASE"):
        runner.main(["--cases", "NO_SUCH_CASE"])


@pytest.mark.parametrize("run_id", ["d1_50v_001", "A01", "x" * 36])
def test_a_legal_run_id_is_accepted(run_id):
    assert runner.check_run_id(run_id) == run_id


@pytest.mark.parametrize("run_id", ["", "ab", "has space", "x" * 37, "_leading", "bad/slash"])
def test_an_illegal_run_id_is_refused(run_id):
    with pytest.raises(SystemExit):
        runner.check_run_id(run_id)


def test_the_dry_run_names_all_four_cases_and_promises_no_raw(capsys):
    assert runner.main([]) == 0
    out = capsys.readouterr().out
    assert out.count("DRY_RUN") == 4
    assert "NO NEW RAW" in out


def test_the_manifest_never_claims_more_than_duration():
    report = runner.manifest("d1_50v_001", [])
    assert report["pre_fault_1mV_paired_verified"] is False
    assert report["ten_physical_gate_shutdown_verified"] is False
    assert report["fabrication_approved"] is False


SWEEP = ("shunt_2f", "shunt_5f", "shunt_10f")


def test_the_published_variant_is_the_frozen_deck_set():
    assert runner.decks_for("published") == runner.DECKS
    assert runner.decks_for("published") is not runner.DECKS


@pytest.mark.parametrize("variant", SWEEP)
def test_a_sweep_variant_names_the_generated_decks(variant):
    decks = runner.decks_for(variant)
    assert set(decks) == set(runner.DECKS)
    for case, name in decks.items():
        assert name == f"d1_prot03_{variant}_{case}.cir"
        assert (runner.SIM / name).is_file()


@pytest.mark.parametrize("variant", SWEEP)
def test_a_sweep_deck_passes_only_its_own_cshunt_gate(variant):
    """Control and candidate must share one shunt: mixing 1 fF with 5 fF is the
    exact mistake the sweep exists to prevent."""
    for case in runner.DECKS:
        text = runner.deck_text(case, variant)
        runner.validate_deck(case, text, variant)
        with pytest.raises(ValueError, match="solver options changed"):
            runner.validate_deck(case, text, "published")


def test_the_manifest_records_which_sweep_it_belongs_to():
    report = runner.manifest("sweep_001", [], "shunt_5f")
    assert report["variant"] == "shunt_5f"
    assert report["required_cshunt_farads"] == "5e-15"
    assert report["fabrication_approved"] is False
    assert runner.manifest("d1_50v_001", [])["variant"] == "published"


def test_the_dry_run_can_name_a_sweep_variant(capsys):
    assert runner.main(["--variant", "shunt_2f"]) == 0
    out = capsys.readouterr().out
    assert out.count("DRY_RUN") == 4
    assert "d1_prot03_shunt_2f_A_CANDIDATE.cir" in out


def test_an_unknown_variant_is_refused():
    with pytest.raises(SystemExit):
        runner.main(["--variant", "shunt_9f"])


def test_a_dead_solver_in_a_sweep_keeps_the_variant_in_the_manifest(tmp_path):
    run_id = "d1_swp_pyt"
    stage = runner.SIM / f"d1_{run_id}_A_CONTROL.cir"
    try:
        with pytest.raises(SystemExit, match="incomplete runs retained"):
            runner.main(["--execute", "--run-id", run_id, "--cases", "A_CONTROL",
                         "--variant", "shunt_2f", "--ltspice", sys.executable,
                         "--archive-root", str(tmp_path)])
        report = json.loads((tmp_path / run_id / "run_manifest.json").read_text(encoding="utf-8"))
        assert report["variant"] == "shunt_2f"
        assert report["required_cshunt_farads"] == "2e-15"
        assert report["cases"][0]["source"] == "d1_prot03_shunt_2f_A_CONTROL.cir"
        archived = tmp_path / run_id / "A_CONTROL" / stage.name
        source = runner.SIM / runner.decks_for("shunt_2f")["A_CONTROL"]
        assert runner.sha256(archived) == runner.sha256(source)
    finally:
        for suffix in (".cir", ".raw", ".log"):
            (runner.SIM / f"d1_{run_id}_A_CONTROL{suffix}").unlink(missing_ok=True)


def test_an_existing_archive_is_refused(tmp_path):
    (tmp_path / "d1_50v_001").mkdir()
    with pytest.raises(SystemExit, match="refuse overwrite archive"):
        runner.main(["--execute", "--run-id", "d1_50v_001", "--ltspice", str(runner.__file__),
                     "--archive-root", str(tmp_path)])


def test_a_dead_solver_keeps_the_evidence_and_the_flags_false(tmp_path):
    run_id = "d1_50v_pyt"
    stage = runner.SIM / f"d1_{run_id}_A_CONTROL.cir"
    try:
        with pytest.raises(SystemExit, match="incomplete runs retained"):
            runner.main(["--execute", "--run-id", run_id, "--cases", "A_CONTROL",
                         "--ltspice", sys.executable, "--archive-root", str(tmp_path)])
        report = json.loads((tmp_path / run_id / "run_manifest.json").read_text(encoding="utf-8"))
        record = report["cases"][0]
        assert record["state"] == "FAILED_KEEP_EVIDENCE"
        assert "LTspice exit" in record["reason"]
        assert record["solver_finished"] is False
        assert record["raw_sha256"] is None
        assert report["pre_fault_1mV_paired_verified"] is False
        assert report["ten_physical_gate_shutdown_verified"] is False
        assert report["fabrication_approved"] is False
        archived = tmp_path / run_id / "A_CONTROL" / stage.name
        assert runner.sha256(archived) == runner.sha256(runner.SIM / runner.DECKS["A_CONTROL"])
    finally:
        for suffix in (".cir", ".raw", ".log"):
            (runner.SIM / f"d1_{run_id}_A_CONTROL{suffix}").unlink(missing_ok=True)
