"""Lock the byte-identity convention of the signal-increment review receipts.

The report was first generated on a CRLF worktree, so its ``*_sha256`` fields
hashed bytes Git never stores. Git keeps text as LF; a verifier on a clean
checkout would compute a different digest for the same receipt. The fix is the
repo-wide convention in ``docs/agent/TRAPS.md``: hash ``text_identity.canonical_bytes``.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
REPORT = G1 / "lr_signal_review_report.json"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(G1))
from text_identity import sha256_file  # noqa: E402


def test_digest_ignores_checkout_line_endings(tmp_path):
    import review_signal_stubs as rev

    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "ok": true\n}\n')
    crlf.write_bytes(b'{\r\n  "ok": true\r\n}\r\n')
    assert rev.digest(lf) == rev.digest(crlf)


def test_report_hashes_the_receipts_as_git_stores_them():
    if not REPORT.exists():
        pytest.skip("review report not captured on this checkout")
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["readback_sha256"] == sha256_file(G1 / "lr_signal_review_readback.json")
    assert report["drc_sha256"] == sha256_file(G1 / "lr_signal_review_drc_raw.json")
    assert "LF-canonical" in report["hash_convention"]
