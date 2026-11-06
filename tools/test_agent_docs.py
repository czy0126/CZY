"""Lock the CLAUDE.md hot-zone contract.

The hub is loaded into every session, so the only generated part of it must be
reproducible from `docs/agent/TRAP_INDEX.md` and must fail when a hand edit,
a broken index row, or a dangling home file sneaks in.  Each test below breaks
one of those on a temporary copy -- the committed files are never mutated.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import agent_docs as ad


@pytest.fixture()
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the real docs tree whose paths replace the module globals."""
    shutil.copytree(ad.AGENT_DIR, tmp_path / "docs" / "agent")
    hub = tmp_path / "CLAUDE.md"
    shutil.copyfile(ad.HUB, hub)
    monkeypatch.setattr(ad, "ROOT", tmp_path)
    monkeypatch.setattr(ad, "AGENT_DIR", tmp_path / "docs" / "agent")
    monkeypatch.setattr(ad, "INDEX", tmp_path / "docs" / "agent" / "TRAP_INDEX.md")
    monkeypatch.setattr(ad, "HUB", hub)
    return tmp_path


def test_the_committed_hot_zone_is_the_projection() -> None:
    assert ad.check() == 0


def test_the_hot_zone_has_exactly_the_starred_rules() -> None:
    rows = ad.index_rows()
    starred = [r["rule"] for r in rows if r["star"] == ad.STAR]
    text = ad.HUB.read_text(encoding="utf-8")
    _, block, _ = ad.split_block(text)
    hot = [line for line in block.splitlines() if line.startswith("| ")][1:]
    assert len(hot) == len(starred)
    for rule in starred:
        assert any(rule in line for line in hot), rule


def test_a_crlf_checkout_still_matches(tree: Path) -> None:
    # CI checks out with core.autocrlf, so the hub and the index arrive as
    # CRLF while a developer's work tree may be LF.  The projection must use
    # whichever newline the file already has, or every Windows run would drift.
    def crlf(p: Path) -> None:
        text = ad.read_text_exact(p)
        p.write_text(text.replace("\r\n", "\n").replace("\n", "\r\n"),
                     encoding="utf-8", newline="")

    crlf(tree / "CLAUDE.md")
    for md in (tree / "docs" / "agent").glob("*.md"):
        crlf(md)
    assert ad.check() == 0
    assert ad.write(quiet=True) == 0
    assert ad.check() == 0


def test_a_hand_edited_hot_row_fails(tree: Path) -> None:
    hub = tree / "CLAUDE.md"
    text = ad.read_text_exact(hub)
    _, block, _ = ad.split_block(text)
    # Edit inside the generated block only: the same sentence also appears in
    # §一的 prose table, and prose is allowed to be hand-written.
    edited = text.replace(block, block.replace("起任何仿真", "随时"))
    assert edited != text
    hub.write_text(edited, encoding="utf-8", newline="")
    assert ad.check() == 1


def test_a_missing_home_file_fails(tree: Path) -> None:
    # COMMANDS.md is the home of several rules; deleting it must not pass.
    (tree / "docs" / "agent" / "COMMANDS.md").unlink()
    assert ad.check() == 1


def test_write_is_idempotent(tree: Path) -> None:
    hub = tree / "CLAUDE.md"
    assert ad.write(quiet=True) == 0
    first = hub.read_bytes()
    assert ad.write(quiet=True) == 0
    assert hub.read_bytes() == first


def test_write_restores_a_corrupted_block(tree: Path) -> None:
    hub = tree / "CLAUDE.md"
    text = ad.read_text_exact(hub)
    _, block, _ = ad.split_block(text)
    hub.write_text(text.replace(block, ad.BEGIN + ad._newline(text) + ad.END), encoding="utf-8", newline="")
    assert ad.check() == 1
    assert ad.write(quiet=True) == 0
    assert ad.check() == 0


def test_a_row_with_the_wrong_column_count_is_an_error(tree: Path) -> None:
    index = tree / "docs" / "agent" / "TRAP_INDEX.md"
    index.write_text(index.read_text(encoding="utf-8") + "\n| ★ | 少了家 | 随时 |\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="expected 4 columns"):
        ad.index_rows(index)


def test_a_missing_marker_pair_is_an_error(tree: Path) -> None:
    hub = tree / "CLAUDE.md"
    text = ad.read_text_exact(hub)
    hub.write_text(text.replace(ad.END, ""), encoding="utf-8", newline="")
    with pytest.raises(SystemExit, match="exactly one"):
        ad.check()


def test_an_empty_star_set_refuses_to_blank_the_hot_zone(tree: Path) -> None:
    rows = ad.index_rows()
    for r in rows:
        r["star"] = ""
    with pytest.raises(SystemExit, match="no starred rows"):
        ad.render_block(rows)
