"""Lock the pad-identity semantics used by the driver-ECO reopen audit.

The committed `g1_pads.json` snapshot forced `Layer: 1` on every component pad
(the generator never read the real layer), while a reopened board reports
through-hole pads on layer 12.  Polygon pads also store absolute board
coordinates, so a component move translates them.  Neither is a footprint
change, but a real shape/net change must still fail.
"""

import importlib.util
import sys
from pathlib import Path

G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
sys.path.insert(0, str(G1))
spec = importlib.util.spec_from_file_location("g1_driver_eco", G1 / "audit_driver_eco.py")
eco = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eco)


def pad(ref, number, net, shape, layer=1, x=0.0, y=0.0):
    return {"ref": ref, "PadNumber": number, "Net": net, "Pad": shape,
            "Layer": layer, "X": x, "Y": y, "Rotation": 0}


def test_snapshot_forced_layer_one_does_not_fake_a_footprint_change():
    old = [pad("J_IN", "1", "VIN_P", ["ELLIPSE", 94.5, 94.5], layer=1)]
    new = [pad("J_IN", "1", "VIN_P", ["ELLIPSE", 94.5, 94.5], layer=12)]
    assert eco.pads_match(old, {"J_IN": (0.0, 0.0)}, new, {"J_IN": (0.0, 0.0)})


def test_free_pad_layer_is_still_part_of_its_identity():
    old = [pad(None, "PRI_A", "SW", ["ELLIPSE", 40.0, 40.0], layer=1)]
    new = [pad(None, "PRI_A", "SW", ["ELLIPSE", 40.0, 40.0], layer=12)]
    assert not eco.pads_match(old, {}, new, {})


def test_polygon_translated_with_its_component_is_not_a_change():
    shape_old = ["POLYGON", [100.0, -200.0, "L", 110.0, -200.0, 110.0, -190.0]]
    shape_new = ["POLYGON", [400.0, -500.0, "L", 410.0, -500.0, 410.0, -490.0]]
    old = [pad("U2", "11", "PGND", shape_old, x=105.0, y=-195.0)]
    new = [pad("U2", "11", "PGND", shape_new, x=405.0, y=-495.0)]
    assert eco.pads_match(old, {"U2": (105.0, -195.0)}, new, {"U2": (405.0, -495.0)})


def test_polygon_shape_change_within_a_component_is_detected():
    shape_old = ["POLYGON", [100.0, -200.0, "L", 110.0, -200.0, 110.0, -190.0]]
    shape_new = ["POLYGON", [400.0, -500.0, "L", 412.0, -500.0, 412.0, -490.0]]
    old = [pad("U2", "11", "PGND", shape_old, x=105.0, y=-195.0)]
    new = [pad("U2", "11", "PGND", shape_new, x=405.0, y=-495.0)]
    assert not eco.pads_match(old, {"U2": (105.0, -195.0)}, new, {"U2": (405.0, -495.0)})


def test_footprint_pad_offset_change_is_detected_beyond_tolerance():
    old = [pad("C10", "2", "PGND", ["RECT", 31.5, 35.4, 0], x=30.0)]
    new = [pad("C10", "2", "PGND", ["RECT", 31.5, 35.4, 0], x=30.1)]
    assert eco.pads_match(old, {"C10": (0.0, 0.0)}, new, {"C10": (0.0, 0.0)})
    assert not eco.pads_match(old, {"C10": (0.0, 0.0)}, new, {"C10": (0.0, 0.0)}, tol_mil=0.05)
    far = [pad("C10", "2", "PGND", ["RECT", 31.5, 35.4, 0], x=31.0)]
    assert not eco.pads_match(old, {"C10": (0.0, 0.0)}, far, {"C10": (0.0, 0.0)})


def test_editor_rounding_is_within_the_tolerance():
    old = [pad("C103", "1", "VCC12", ["RECT", 31.5, 35.4, 0], x=-27.557, y=0.013)]
    new = [pad("C103", "1", "VCC12", ["RECT", 31.5, 35.4, 0], x=-27.595, y=-0.045)]
    assert eco.pads_match(old, {"C103": (0.0, 0.0)}, new, {"C103": (0.0, 0.0)}, tol_mil=0.1)


def test_rect_size_or_net_change_is_detected():
    old = [pad("C10", "2", "PGND", ["RECT", 31.5, 35.4, 0])]
    assert not eco.pads_match(old, {"C10": (0.0, 0.0)},
                              [pad("C10", "2", "VOUT", ["RECT", 31.5, 35.4, 0])], {"C10": (0.0, 0.0)})
    assert not eco.pads_match(old, {"C10": (0.0, 0.0)},
                              [pad("C10", "2", "PGND", ["RECT", 41.5, 35.4, 0])], {"C10": (0.0, 0.0)})
