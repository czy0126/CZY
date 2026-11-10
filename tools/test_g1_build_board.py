"""The G1 board had no committed producer.

`dcx_main_board_g1.eprj2` was built by `tmp_g1_probe/g1_build.py`, which is an
untracked scratch directory: the placement of the 30 control parts exists only
there and on the saved board, so the committed board could not be rebuilt from
the repo.  This module pins the replacement -- `g1_placement.json` is the
authored placement, derived from the board's own readback, and the slices are a
function of that file alone.

The tests are offline: the slice builder never opens the editor, and the same
checks the tool runs against a live readback are exercised on the committed
dump.
"""
import importlib.util
import json
from pathlib import Path

G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
spec = importlib.util.spec_from_file_location("g1build", G1 / "build_g1_board.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

MIL = 39.37007874015748


def load(name: str) -> dict:
    return json.loads((G1 / name).read_text(encoding="utf-8"))


def data() -> tuple[dict, dict, dict]:
    return load("g1_pads.json"), g.inventory(), g.netlist()


def test_the_placement_is_every_component_on_the_board_and_nothing_else():
    dump, inv, nets = data()
    rows = g.placement_from_board(dump, inv, nets)
    assert [r["ref"] for r in rows] == sorted(c["ref"] for c in dump["components"])
    assert len(rows) == 77


def test_every_placed_part_keeps_its_supplier_part():
    dump, inv, nets = data()
    rows = {r["ref"]: r for r in g.placement_from_board(dump, inv, nets)}
    assert rows["QH"]["lcsc"] == inv["QH"]["supplier_id"]
    assert rows["Lr"]["lcsc"] == inv["Lr"]["supplier_id"]
    assert all(r["lcsc"].startswith("C") for r in rows.values())


def test_the_pad_nets_match_the_committed_netlist():
    dump, inv, nets = data()
    rows = {r["ref"]: r for r in g.placement_from_board(dump, inv, nets)}
    # The 9-pad MOSFET is the case where a blank pin and a missing pin differ.
    assert rows["QH"]["nets"] == {"1": "SW", "2": "SW", "3": "SW", "4": "GH",
                                  "5": "VIN_P", "6": "VIN_P", "7": "VIN_P",
                                  "8": "VIN_P", "9": "VIN_P"}
    for ref, row in rows.items():
        assert row["nets"] == {k: v for k, v in nets[ref].items() if v}, ref


def test_the_committed_placement_file_is_what_the_board_dump_derives():
    dump, inv, nets = data()
    committed = load("g1_placement.json")
    assert committed["rows"] == g.placement_from_board(dump, inv, nets)
    assert committed["board"] == {"w_mm": dump["board"]["w_mm"], "d_mm": dump["board"]["d_mm"]}


def test_the_slice_wires_every_pad_and_converts_to_mil_with_y_up():
    dump, inv, nets = data()
    rows = g.placement_from_board(dump, inv, nets)
    js = g.slice_js([(r["ref"], r) for r in rows])
    for r in rows:
        assert js.count(f'"ref": "{r["ref"]}"') == 1, r["ref"]
    qh = next(r for r in rows if r["ref"] == "QH")
    # PCB storage is mil, Cartesian Y up; the authored placement is mm, Y down.
    assert f'"x": {round(qh["x_mm"] * MIL, 3)}' in js
    assert f'"y": {round(-qh["y_mm"] * MIL, 3)}' in js
    # Blank pins are dropped rather than sent as empty strings.
    assert '"net": ""' not in js


def test_check_reports_a_moved_part_a_wrong_net_and_a_missing_part():
    dump, inv, nets = data()
    rows = g.placement_from_board(dump, inv, nets)
    assert g.check_placement(rows, dump, inv, nets) == []
    moved = json.loads(json.dumps(rows))
    moved[0]["x_mm"] += 1.0
    assert any("moved" in p for p in g.check_placement(moved, dump, inv, nets))
    wrong = json.loads(json.dumps(rows))
    wrong[0]["nets"] = dict(list(wrong[0]["nets"].items())[:-1] or [("1", "WRONG")])
    wrong[0]["nets"]["1"] = "WRONG"
    assert any("net" in p for p in g.check_placement(wrong, dump, inv, nets))
    short = rows[:-1]
    assert any("missing" in p for p in g.check_placement(short, dump, inv, nets))
