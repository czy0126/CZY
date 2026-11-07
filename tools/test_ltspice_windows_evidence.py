"""Evidence identity tests; must never rerun, rewrite, or fabricate LTspice logs."""
from __future__ import annotations

import hashlib
import json

import pytest

import bias_cut_revision_b as rev
import bias_cut_timing as timing
import ltspice_windows_evidence as h


def test_reconstructed_windows_deck_hash_is_exact_for_lf_and_crlf(tmp_path):
    deck = tmp_path / "demo.cir"
    data = b"Demo LTspice\nR1 1 0 10\n.end\n"
    deck.write_bytes(data)
    expected = hashlib.sha256(data.replace(b"\n", b"\r\n")).hexdigest()
    assert h.original_windows_deck_sha256(deck) == expected
    assert h.actual_file_sha256(deck) != expected
    deck.write_bytes(data.replace(b"\n", b"\r\n"))
    assert h.original_windows_deck_sha256(deck) == expected
    assert h.actual_file_sha256(deck) == expected


def test_semantic_change_still_invalidates_historical_hash(tmp_path):
    deck = tmp_path / "test.cir"
    deck.write_bytes(b"Test\nR1 a 0 22\n.end\n")
    old = h.original_windows_deck_sha256(deck)
    deck.write_bytes(b"Test\nR1 a 0 23\n.end\n")
    assert h.original_windows_deck_sha256(deck) != old


def test_cr_only_or_non_spice_files_are_not_silently_normalized(tmp_path):
    deck = tmp_path / "n.cir"
    deck.write_bytes(b"A\rB\r")
    with pytest.raises(ValueError, match="plain LF/CRLF"):
        h.original_windows_deck_sha256(deck)
    deck.write_bytes(b"A\x00B\n")
    with pytest.raises(ValueError, match="plain LF/CRLF"):
        h.original_windows_deck_sha256(deck)
    other = tmp_path / "data.log"
    other.write_text("real log\n", encoding="utf-8")
    assert h.original_windows_deck_sha256(other) == hashlib.sha256(
        b"real log\r\n").hexdigest()
    assert h.actual_file_sha256(other) == hashlib.sha256(
        other.read_bytes()).hexdigest()
    unsupported = tmp_path / "probe.raw"
    unsupported.write_bytes(b"binary\r\n")
    with pytest.raises(ValueError, match="only"):
        h.original_windows_deck_sha256(unsupported)


def test_rev_b_original_report_shas_bind_complete_decks_not_new_waveforms():
    report = json.loads((rev.OUT / "report.json").read_text(encoding="utf-8"))
    assert report["hardware_qualified"] is False
    assert report["fabrication_approved"] is False
    for name, case in rev.CASES.items():
        deck = rev.OUT / f"{name}.cir"
        log = rev.OUT / f"{name}.log"
        # Critical: no semantic difference in model can hide behind EOL healing.
        assert deck.read_text(encoding="utf-8") == rev.deck(**case), name
        assert report["cases"][name]["deck_sha256"] == (
            h.original_windows_deck_sha256(deck)), name
        assert report["cases"][name]["log_sha256"] == h.original_windows_deck_sha256(log)


def test_rev_b_timing_original_report_hashes_bind_complete_decks_and_logs():
    report = json.loads(timing.JSON_PATH.read_text(encoding="utf-8"))
    assert report["hardware_qualified"] is False
    assert report["measured"] is False
    for name in timing.cases():
        deck = timing.OUT / f"{name}.cir"
        log = timing.OUT / f"{name}.log"
        assert deck.read_text(encoding="utf-8") == timing.deck(name), name
        assert report["decks"][name]["cir_sha256"] == (
            h.original_windows_deck_sha256(deck)), name
        assert report["decks"][name]["log_sha256"] == h.actual_file_sha256(log)
