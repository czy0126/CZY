"""The filled PROT-03 run registers must agree with the records they quote.

A run register is only useful if it cannot drift from the JSON it summarises.
Every cell here is re-derived from the source record or from the deck file; the
RAW hashes are checked only when the gigabyte-scale file is present locally,
because RAWs are gitignored and CI must not pretend to have them.  A rerun
register quotes a second, independent execution of the same decks; its raws
live under the ignored archive root, so the check follows the path the row
itself names instead of assuming ``sim/v3``.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "docs/D1_EXECUTION_KIT/templates"
TEMPLATE = KIT / "simulation_run_register.csv"
PP = ROOT / "design/v3/power_priority"

# run_id -> (source record, side in that record)
SOURCES = {
    "P02-50V-A-CAND": ("protection_candidate_50v_120a_prot_a_paired.json", "candidate"),
    "P02-50V-A-THRMUTE": ("protection_candidate_50v_120a_prot_a_paired.json", "base"),
    "P02-50V-A-NOCLAMP": ("protection_candidate_50v_120a_prot_a_noclamp_paired.json", "base"),
    "P02-50V-B-CAND": ("protection_candidate_50v_120a_prot_b_paired.json", "candidate"),
    "P02-50V-B-THRMUTE": ("protection_candidate_50v_120a_prot_b_paired.json", "base"),
    "P02-50V-B-NOCLAMP": ("protection_candidate_50v_120a_prot_b_noclamp_paired.json", "base"),
}

# A second, independent execution of the same four 50 V decks: both controls
# stall at the frozen points and every physical column reproduces the first
# run, so the stall is a property of the decks, not of one lucky execution.
RERUN_SOURCES = {
    "P03-RERUN-A-CAND": ("protection_candidate_50v_120a_prot_a_paired_d1_50v_20261103.json",
                         "candidate"),
    "P03-RERUN-A-THRMUTE": ("protection_candidate_50v_120a_prot_a_paired_d1_50v_20261103.json",
                            "base"),
    "P03-RERUN-B-CAND": ("protection_candidate_50v_120a_prot_b_paired_d1_50v_20261103.json",
                         "candidate"),
    "P03-RERUN-B-THRMUTE": ("protection_candidate_50v_120a_prot_b_paired_d1_50v_20261103.json",
                            "base"),
}

# The PR 30 solver sweep: a second cshunt, both sides of one pairing.  This is
# the first 50 V pair where the control reaches the end of the saved window at
# all, so the rows quote a full-window comparison rather than a prefix.
SWEEP_2F_SOURCES = {
    "P03-SWEEP-2F-A-CAND": ("protection_candidate_50v_120a_prot_a_paired_shunt_2f.json",
                            "candidate"),
    "P03-SWEEP-2F-A-THRMUTE": ("protection_candidate_50v_120a_prot_a_paired_shunt_2f.json",
                               "base"),
}

REGISTERS = {
    KIT / "simulation_run_register_PROT03_2026-11-03.csv": SOURCES,
    KIT / "simulation_run_register_PROT03_rerun_2026-11-03.csv": RERUN_SOURCES,
    KIT / "simulation_run_register_PROT03_sweep_2f_2026-11-03.csv": SWEEP_2F_SOURCES,
}

CASES = [(path, run_id) for path, sources in REGISTERS.items() for run_id in sources]


def register(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def row(path: Path, run_id: str) -> dict[str, str]:
    return next(r for r in register(path) if r["run_id"] == run_id)


def record(name: str) -> dict:
    return json.loads((PP / name).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def canonical_deck_sha256(path: Path) -> str:
    """Hash Git's logical LF text, independent of Windows CRLF checkout.

    This normalization applies ONLY to .cir source. Never normalize binary or
    ASCII LTspice RAW hashes, whose exact recorded bytes remain authoritative.
    """
    if path.suffix.lower() != ".cir":
        raise ValueError("canonical_deck_sha256 is restricted to SPICE .cir")
    return hashlib.sha256(path.read_bytes().replace(b"\\r\\n", b"\\n")).hexdigest()


def local_raw(row_: dict[str, str]) -> Path:
    """The row names where its raw lives; drop the trailing note."""
    return ROOT / row_["raw_external_location"].split(" (")[0]


@pytest.mark.parametrize("path", list(REGISTERS))
def test_the_register_uses_the_blank_template_columns(path: Path):
    with TEMPLATE.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    with path.open(encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == header


@pytest.mark.parametrize("path", list(REGISTERS))
def test_every_row_names_a_record_and_a_role_this_repository_has(path: Path):
    rows = register(path)
    sources = REGISTERS[path]
    assert [r["run_id"] for r in rows] == list(sources)
    for r in rows:
        name, side = sources[r["run_id"]]
        assert (PP / name).is_file(), name
        assert r["notes"].startswith(name), r["run_id"]
        assert f"{side} gate/peak" in r["notes"], r["run_id"]


@pytest.mark.parametrize("path,run_id", CASES)
def test_the_saved_stop_and_pairing_numbers_are_copied_not_typed(path: Path, run_id: str):
    r = row(path, run_id)
    name, side = REGISTERS[path][run_id]
    rec = record(name)
    cov = rec["coverage"]
    assert float(r["last_saved_us"]) == pytest.approx(cov[f"{side}_t_last_us"], abs=5e-4)
    assert float(r["base_delta_mv"]) == pytest.approx(
        rec["results"]["pre_fault"]["vout_mean_delta_mv"], abs=5e-7)
    assert float(r["pre_fault_vout_v"]) == pytest.approx(
        rec["results"]["pre_fault"][side]["vout_mean_v"], abs=5e-10)
    # A stop that the solver reached prints an elapsed time; a PID-terminated
    # prefix cannot, so the two columns have to agree on which one happened.
    if cov[f"{side}_reached_saved_stop"]:
        assert r["full_duration"].replace(".", "", 1).isdigit(), r["full_duration"]
    else:
        assert r["full_duration"] == "KILLED_BY_PID", r["full_duration"]


@pytest.mark.parametrize("path,run_id", CASES)
def test_the_deck_hash_is_the_file_the_row_names(path: Path, run_id: str):
    r = row(path, run_id)
    deck = ROOT / r["deck_path"]
    assert deck.is_file(), deck
    assert canonical_deck_sha256(deck) == r["deck_sha256"], run_id


@pytest.mark.parametrize("path,run_id", CASES)
def test_local_raw_hashes_match_when_the_raw_is_present(path: Path, run_id: str):
    raw = local_raw(row(path, run_id))
    if not raw.is_file():
        pytest.skip(f"{raw} is gitignored and not local")
    assert sha256(raw) == row(path, run_id)["raw_sha256"], run_id


@pytest.mark.parametrize("run_id", list(SWEEP_2F_SOURCES))
def test_a_sweep_row_names_a_sweep_deck_and_the_cshunt_it_ran_with(run_id: str):
    """A 2 fF row must not be mistakable for the published 1 fF evidence: the
    deck it names is a PR 30 sweep deck, and the `.options` line on disk still
    carries the 2 fF the row claims."""
    import generate_prot03_solver_sweep as sweep

    r = row(KIT / "simulation_run_register_PROT03_sweep_2f_2026-11-03.csv", run_id)
    deck = ROOT / r["deck_path"]
    options = [ln.strip() for ln in deck.read_text(encoding="utf-8").splitlines()
               if ln.startswith(".options")]
    assert r["solver_options"] == "cshunt=2e-15"
    assert options == [sweep.ANCHOR.replace("1e-15", sweep.VARIANTS["shunt_2f"])], options
    assert deck.name.startswith("d1_prot03_shunt_2f_"), deck.name


def test_no_row_claims_a_port_ledger_it_never_measured():
    for path in REGISTERS:
        for r in register(path):
            for field in ("output_current_a", "output_voltage_v", "input_power_w",
                          "output_power_w", "energy_closure_residual_w"):
                assert r[field] == "PENDING", (r["run_id"], field)
            assert "not measured" in r["notes"], r["run_id"]



def test_staged_windows_crlf_deck_hashes_are_not_mislabeled_as_repository_hashes():
    """For both 2fF A cases, prove earlier recorded SHA is CRLF exact bytes.
    The full-window analysis and RAW/LOG hashes remain unchanged by this fix.
    """
    record_path = KIT / "simulation_run_register_PROT03_sweep_2f_2026-11-03.csv"
    provenance = json.loads((PP / "prot03_2f_A_deck_hash_provenance.json").read_text(encoding="utf-8"))
    assert provenance["source_line_ending_cause"] == "Windows staged .cir CRLF versus Git .cir LF"
    for item in provenance["records"]:
        row_ = row(record_path, item["run_id"])
        assert row_["deck_path"] == item["repo_path"]
        source = ROOT / item["repo_path"]
        logical = source.read_bytes().replace(b"\r\n", b"\n")
        assert b"\r" not in logical
        assert hashlib.sha256(logical).hexdigest() == item["git_lf_sha256"] == row_["deck_sha256"]
        staged = logical.replace(b"\n", b"\r\n")
        assert hashlib.sha256(staged).hexdigest() == item["executed_crlf_sha256"]
        assert item["electrical_netlist_or_solver_settings_changed"] is False
    assert len(provenance["records"]) == 2
    assert not provenance["hardware_protection_approved"]
