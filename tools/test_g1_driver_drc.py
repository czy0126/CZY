"""Lock the read-only DRC runner: confirmed API call, path-open protocol, md5 guard."""

import importlib.util
from pathlib import Path

G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
spec = importlib.util.spec_from_file_location("g1_drc", G1 / "run_driver_drc.py")
drc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drc)


def test_the_body_uses_the_confirmed_drc_signature():
    body = (G1 / "driver_drc.js").read_text(encoding="utf-8")
    assert "eda.pcb_Drc.check(true, false, true)" in body
    assert "dmt_EditorControl.openDocument" in body


def test_the_open_uses_path_not_open_project():
    args = drc.build_open_args(Path("board.eprj2"))
    assert args[1:3] == ["open", "--path"]
    assert args[3].endswith("board.eprj2")
    assert args[-2:] == ["--headless", "true"]


def test_the_session_is_closed_with_destroy():
    assert drc.build_close_args("s1")[1:] == ["session", "close", "--session", "s1", "--destroy"]


def test_invoke_args_carry_the_timeout_and_code():
    args = drc.build_invoke_args("s1", "return 1;", 12345)
    assert args[1:6] == ["invoke", "--session", "s1", "--ext-uuid", "eda"]
    assert args[6:8] == ["--timeout", "12345"]
    assert args[-2:] == ["--code", "return 1;"]


def test_md5_detects_a_changed_board(tmp_path):
    before = tmp_path / "a.eprj2"
    after = tmp_path / "b.eprj2"
    before.write_bytes(b"one")
    after.write_bytes(b"one")
    assert drc.md5(before) == drc.md5(after)
    after.write_bytes(b"two")
    assert drc.md5(before) != drc.md5(after)
