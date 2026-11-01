"""Tests for tools/ci_check.py.

CI's only job is to answer two questions: did the offline suite pass, and are
the generated files still the ones the tools produce?  The second question is a
pure comparison, so it is tested without invoking pytest or LTspice.
"""

from __future__ import annotations

import json

from ci_check import MANIFEST, compare_manifests, main


def manifest(entries, missing=None, timing=None):
    return {
        "entries": entries,
        "missing": missing or [],
        "deck_timing": timing or [],
    }


def test_identical_manifests_have_no_differences():
    entry = {"path": "a.cir", "bytes": 3, "sha256": "abc"}
    assert compare_manifests(manifest([entry]), manifest([entry])) == []


def test_a_changed_hash_is_reported_by_path():
    old = manifest([{"path": "a.cir", "sha256": "old"}])
    new = manifest([{"path": "a.cir", "sha256": "new"}])
    diff = compare_manifests(old, new)
    assert len(diff) == 1 and "a.cir" in diff[0] and "sha256" in diff[0]


def test_an_added_or_removed_source_is_reported():
    old = manifest([{"path": "a.cir", "sha256": "x"}])
    new = manifest([{"path": "b.cir", "sha256": "y"}])
    diff = " ".join(compare_manifests(old, new))
    assert "b.cir" in diff and "not in the committed manifest" in diff
    assert "a.cir" in diff and "no longer produced" in diff


def test_a_new_missing_file_is_reported():
    diff = compare_manifests(manifest([]), manifest([], missing=["gone.json"]))
    assert "gone.json" in diff[0]


def test_a_deck_timing_drift_is_reported():
    old = manifest([], timing=[{"deck": "d.cir", "display_offset_us": 880.0}])
    new = manifest([], timing=[{"deck": "d.cir", "display_offset_us": 0.0}])
    diff = compare_manifests(old, new)
    assert diff and "d.cir" in diff[0] and "display_offset_us" in diff[0]


def test_a_missing_raw_is_allowed_because_raws_are_not_in_git():
    old = manifest([{"path": "sim/v3/run.raw", "sha256": "skipped-large-raw"}])
    new = manifest([], missing=["sim/v3/run.raw"])
    assert compare_manifests(old, new) == []


def test_a_missing_non_raw_file_still_fails():
    old = manifest([{"path": "design/v3/x.json", "sha256": "x"}])
    new = manifest([], missing=["design/v3/x.json"])
    diff = " ".join(compare_manifests(old, new))
    assert "no longer produced" in diff and "now missing" in diff


def test_the_generated_date_is_not_compared():
    """The manifest is dated; a stale date alone must not fail CI."""
    old = {"generated": "2026-10-31", **manifest([])}
    new = {"generated": "2026-11-01", **manifest([])}
    assert compare_manifests(old, new) == []


def test_the_baseline_doc_and_ci_files_are_hashed():
    """Issue #4 asks for one baseline and a light CI; both must be in the
    manifest, or "current candidate" does not include the thing that says it."""
    committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = {row["path"] for row in committed["entries"]}
    for rel in (
        "design/v3/当前候选基线_2026-11-01.md",
        "tools/ci_check.py",
        "tools/test_ci_check.py",
        "tools/test_baseline_doc.py",
        "requirements.txt",
        ".github/workflows/ci.yml",
    ):
        assert rel in paths, rel


def test_skip_tests_does_not_claim_the_suite_passed(monkeypatch, capsys):
    """--skip-tests exists for quick local checks; it must not print a test result
    it did not produce."""
    committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
    monkeypatch.setattr("ci_check.regenerate", lambda: committed)
    assert main(["--skip-tests"]) == 0
    out = capsys.readouterr().out
    assert "suite passed" not in out
    assert "manifest is current" in out


def test_checkout_changes_mtime_without_changing_content():
    old = manifest([{"path":"tools/x.py","bytes":3,"sha256":"same","mtime":1}])
    fresh = manifest([{"path":"tools/x.py","bytes":3,"sha256":"same","mtime":2}])
    assert compare_manifests(old, fresh) == []


def test_present_raw_mtime_drift_is_still_reported():
    old = manifest([{"path":"sim/v3/run.raw","bytes":200,"sha256":"skipped-large-raw","mtime":1}])
    fresh = manifest([{"path":"sim/v3/run.raw","bytes":200,"sha256":"skipped-large-raw","mtime":2}])
    assert "mtime" in " ".join(compare_manifests(old, fresh))


def test_missing_raw_status_row_in_clean_checkout_is_not_a_mismatch():
    old = manifest([{"path":"sim/v3/run.raw","kind":"raw","bytes":400,
                     "sha256":"skipped-large-raw","mtime":123}])
    fresh = manifest([{"path":"sim/v3/run.raw","kind":"raw","status":"missing"}],
                     missing=["sim/v3/run.raw"])
    assert compare_manifests(old, fresh) == []
