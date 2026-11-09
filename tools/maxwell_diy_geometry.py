"""Create DESIGN-OWNED concept STEP magnetics, independent of supplier geometry.

Requires cadquery only. This is neither Maxwell FEA nor a manufacturable winding.
Usage:
  python tools/maxwell_diy_geometry.py --write
  python tools/maxwell_diy_geometry.py --check
The STEP solids are a *stranded current geometry proxy*. They do not connect
insulated individual foils, represent the real 3:1:1 winding or the CT 100 turns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "design/v3/maxwell/diy_magnetics_concept.json"
OUT = ROOT / "design/v3/maxwell/generated_concept"


def load_spec() -> dict:
    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if spec["fabrication_approved"] is not False or spec["maxwell_solved"] is not False:
        raise ValueError("Concept geometry cannot certify Maxwell or fabrication")
    names = [x["id"] for x in spec["cases"]]
    if len(names) != len(set(names)) or len(names) < 6:
        raise ValueError("Missing or repeated magnetic cases")
    for case in spec["cases"]:
        if case["type"] in ("LR_ELP38", "T_ELP32"):
            if case["turns"] < 1 or not 0 <= case["gap_mm"] < 3.0:
                raise ValueError("Invalid turns or gap")
            if case["core_body_height_mm"] <= case["plate_height_mm"]:
                raise ValueError("Invalid E-core/I-plate geometry")
        if case["type"] == "CT_CONCEPT" and case["secondary_turns"] != 100:
            raise ValueError("CT ratio must be traced to design")
    return spec


def block(cq, xmin, ymin, zmin, sx, sy, sz):
    return cq.Workplane("XY").box(sx, sy, sz).translate(
        (xmin + sx/2, ymin + sy/2, zmin + sz/2))


def build_elp(cq, case):
    g = case["geometry"]
    width = float(g["core_outer_x_mm"])
    depth = float(g["core_depth_y_mm"])
    e_height = float(case["core_body_height_mm"])
    plate_height = float(case["plate_height_mm"])
    back = float(g["backplate_thickness_mm"])
    gap = float(case["gap_mm"])
    center_w = float(g["center_leg_x_mm"])
    window = float(g["window_width_each_mm"])
    leg = (width-center_w-2*window)/2
    if leg <= 0 or plate_height + gap >= plate_height + e_height - back:
        raise ValueError("Geometry produces negative leg or cut-through core")
    if not 0 < center_w < width:
        raise ValueError("Invalid winding aperture")
    zback = plate_height + e_height - back
    xmin, ymin = -width/2, -depth/2
    backpiece = block(cq, xmin, ymin, zback, width, depth, back)
    left = block(cq, xmin, ymin, plate_height, leg, depth, zback-plate_height)
    right = block(cq, width/2-leg, ymin, plate_height, leg, depth, zback-plate_height)
    mid = block(cq, -center_w/2, ymin, plate_height+gap,
                center_w, depth, zback-plate_height-gap)
    ebody = backpiece.union(left).union(right).union(mid)
    iplate = block(cq, xmin, ymin, 0, width, depth, plate_height)

    # Ring solids intentionally have NO real series solder connection.
    # Eddy-current/AC loss computations may NOT use this stranded proxy.
    turns = int(case["turns"])
    foil_t = float(g["foil_thickness_z_mm"])
    space_z = float(g["foil_axial_pitch_mm"])
    z0 = float(g["first_foil_center_z_mm"])
    inner_x = center_w + 2*float(g["winding_clearance_x_mm"])
    outer_x = inner_x + 2*float(g["foil_width_radial_mm"])
    inner_y = depth + 2*float(g["winding_clearance_y_mm"])
    outer_y = inner_y + 2*float(g["foil_width_radial_mm"])
    if (outer_x >= width-2*leg or z0-foil_t/2 < plate_height+gap
            or z0+(turns-1)*space_z+foil_t/2 > zback):
        raise ValueError("Foil proxy intersects ferrite/airgap/window envelope")
    rings = []
    for index in range(turns):
        z = z0 + index*space_z
        outside = block(cq, -outer_x/2, -outer_y/2, z-foil_t/2,
                        outer_x, outer_y, foil_t)
        inside = block(cq, -inner_x/2, -inner_y/2, z-foil_t/2-0.1,
                       inner_x, inner_y, foil_t+0.2)
        rings.append(outside.cut(inside).val())
    foil = cq.Compound.makeCompound(rings)
    term_x = (inner_x+outer_x)/4
    center_z = z0+(turns-1)*space_z/2
    face_wire = cq.Workplane("XZ", origin=(term_x, 0, center_z)).rect(
        float(g["foil_width_radial_mm"])*0.65, max(foil_t, turns*space_z)).val()
    sheet = cq.Face.makeFromWires(face_wire)
    a = cq.Assembly(name=case["id"])
    a.add(ebody, name=case["body_names"]["core"])
    a.add(iplate, name=case["body_names"]["plate"])
    a.add(foil, name=case["body_names"]["winding_copper"])
    a.add(sheet, name=case["body_names"]["winding_terminal_sheet"])
    return a


def build_ct(cq, case):
    """Toroid and 4 pin envelopes ONLY; CT's 100 actual turns are NOT modeled."""
    g = case["geometry"]
    ro, ri, h = (float(g["outer_diameter_mm"])/2,
                 float(g["inner_diameter_mm"])/2, float(g["height_mm"]))
    if not 0 < ri < ro or h <= 0:
        raise ValueError("Bad CT geometry")
    toroid = cq.Workplane("XY").circle(ro).circle(ri).extrude(h)
    a = cq.Assembly(name=case["id"])
    a.add(toroid, name="CT_CORE_PROXY")
    for i, (px, py) in enumerate(case["pin_centers_mm"], start=1):
        a.add(block(cq, px-1, py-1, -0.5, 2, 2, 0.5),
              name=f"CT_PIN_CONCEPT_{i}")
    return a


def write_case(cq, case, path: Path):
    if case["type"] in ("LR_ELP38", "T_ELP32"):
        a = build_elp(cq, case)
    elif case["type"] == "CT_CONCEPT":
        a = build_ct(cq, case)
    else:
        raise ValueError("Unknown magnetic model type")
    a.save(str(path), exportType="STEP")
    data = path.read_bytes()
    if not data.startswith(b"ISO-10303-21;") or len(data) < 5000:
        raise RuntimeError("STEP export missing or too small")
    expected = (list(case["body_names"].values()) if "body_names" in case
                else ["CT_CORE_PROXY"])
    for name in expected:
        if name.encode() not in data:
            raise RuntimeError(f"STEP body identity lost: {name}")
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def build_report(out: Path, *, write: bool):
    spec = load_spec()
    try:
        import cadquery as cq
    except ImportError as exc:
        raise RuntimeError("Install cadquery on concept CAD host") from exc
    if write:
        out.mkdir(parents=True, exist_ok=True)
    result = []
    for case in spec["cases"]:
        path = out/(case["id"] + ".step")
        if write:
            meta = write_case(cq, case, path)
        else:
            if not path.is_file():
                raise RuntimeError("Missing generated STEP: " + str(path))
            data = path.read_bytes()
            if not data.startswith(b"ISO-10303-21;") or len(data) < 5000:
                raise RuntimeError("Corrupt STEP: " + str(path))
            meta = {"sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data)}
        result.append({"id": case["id"], "file": path.name,
                       "status": "CONCEPT_STEP_NOT_SOLVED_NOT_FAB", **meta})
    manifest = {
        "status": "CAD_GENERATED_NO_MAXWELL_SOLVE",
        "source": CONTRACT.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        "cases": result,
        "manufacturer_geometry_verified": False,
        "solver_executed": False,
        "fab_release": False,
    }
    if write:
        (out/"manifest.json").write_text(
            json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    elif json.loads((out/"manifest.json").read_text(encoding="utf-8")) != manifest:
        raise RuntimeError("Source/STEP manifest mismatch")
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    p.add_argument("--output", type=Path, default=OUT)
    a = p.parse_args()
    print(json.dumps(build_report(a.output, write=a.write), indent=2))


if __name__ == "__main__":
    main()
