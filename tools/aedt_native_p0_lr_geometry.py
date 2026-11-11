# -*- coding: utf-8 -*-
"""Build a REAL editable Maxwell3D project with the 2-turn ELP38 concept geometry.

Use the shipped AEDT ScriptEnv (no PyAEDT dependency). This is geometric
magnetic preparation, NOT a solver run, validated inductance, AC loss, OEM CAD,
true series-connected winding, physical Lr pads or fabrication qualification.
"""
import os
import sys
import traceback
import json
import hashlib

ROOT = r"D:\workshop\design_48v-2v"
OUT = os.path.join(ROOT, "design", "v3", "maxwell", "local_runs")
RESULT = os.path.join(OUT, "aedt_native_lr_geometry_result.txt")
TARGET = os.path.join(OUT, "ELP38_Lr_2turn_0920uH_NATIVE_FROM_CONTRACT_NOT_FOR_FAB.aedt")
SOURCE = os.path.join(ROOT, "design", "v3", "maxwell", "diy_magnetics_concept.json")
CASE_ID = "ELP38_Lr_2turn_0920uH"

def dim(x):
    return str(x) + "mm"

def box(editor, name, x, y, z, dx, dy, dz, material):
    editor.CreateBox(
        ["NAME:BoxParameters",
         "XPosition:=", dim(x), "YPosition:=", dim(y),
         "ZPosition:=", dim(z), "XSize:=", dim(dx),
         "YSize:=", dim(dy), "ZSize:=", dim(dz)],
        ["NAME:Attributes", "Name:=", name, "Flags:=", "",
         "Color:=", "(152 142 96)", "Transparency:=", 0.25,
         "PartCoordinateSystem:=", "Global",
         "MaterialValue:=", '"' + material + '"',
         "SolveInside:=", True])
    return name

def unite(editor, pieces):
    editor.Unite(["NAME:Selections", "Selections:=", ",".join(pieces)],
                 ["NAME:UniteParameters", "KeepOriginals:=", False])

def ring(editor, idx, z, case):
    g = case["geometry"]
    inner_x = float(g["center_leg_x_mm"]) + 2 * float(g["winding_clearance_x_mm"])
    inner_y = float(g["core_depth_y_mm"]) + 2 * float(g["winding_clearance_y_mm"])
    radial = float(g["foil_width_radial_mm"])
    outer_x, outer_y = inner_x + 2 * radial, inner_y + 2 * radial
    foil = float(g["foil_thickness_z_mm"])
    outer = "LR_OUTER_" + str(idx)
    inner = "LR_VOID_" + str(idx)
    # Isolated rectangular copper annuli: not connected to each other,
    # not a manufacturable coil and not usable for terminal-current FEA.
    box(editor, outer, -outer_x/2, -outer_y/2, z-foil/2,
        outer_x, outer_y, foil, "copper")
    box(editor, inner, -inner_x/2, -inner_y/2, z-foil/2-0.05,
        inner_x, inner_y, foil+0.10, "vacuum")
    editor.Subtract(
        ["NAME:Selections", "Blank Parts:=", outer, "Tool Parts:=", inner],
        ["NAME:SubtractParameters", "KeepOriginals:=", False])

def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    project = oDesktop.NewProject()
    project.InsertDesign("Maxwell 3D", "Lr_2turn_geometry_only", "Magnetostatic", "")
    design = project.SetActiveDesign("Lr_2turn_geometry_only")
    editor = design.SetActiveEditor("3D Modeler")
    # One source of geometry facts: the reviewed *concept* contract.
    # Do not assign a real N97 100 C B-H or coil current to isolated annuli.
    with open(SOURCE, "rb") as h:
        raw = h.read()
    spec = json.loads(raw)
    matches = [c for c in spec["cases"] if c["id"] == CASE_ID]
    if len(matches) != 1 or spec["maxwell_solved"] is not False or spec["fabrication_approved"] is not False:
        raise ValueError("Unreviewed or promoted magnetic concept")
    case = matches[0]
    g = case["geometry"]
    if case["turns"] != 2 or case["type"] != "LR_ELP38" or abs(case["gap_mm"]-1.031)>1e-6:
        raise ValueError("Lr2 concept contract changed: do not reuse geometry")
    w, depth = float(g["core_outer_x_mm"]), float(g["core_depth_y_mm"])
    centre, win = float(g["center_leg_x_mm"]), float(g["window_width_each_mm"])
    side = (w-centre-2*win)/2
    plate = float(case["plate_height_mm"])
    eheight = float(case["core_body_height_mm"])
    back = float(g["backplate_thickness_mm"])
    zback = plate+eheight-back
    if min(w,depth,side,plate,back)>0 and zback>plate+case["gap_mm"]:
        pass
    else:
        raise ValueError("Concept has impossible ferrite dimensions")
    box(editor, "I38_FERRITE_PROXY", -w/2, -depth/2, 0, w, depth, plate, "ferrite")
    box(editor, "E_BACK", -w/2, -depth/2, zback, w, depth, back, "ferrite")
    box(editor, "E_LEFT", -w/2, -depth/2, plate, side, depth, zback-plate, "ferrite")
    box(editor, "E_RIGHT", w/2-side, -depth/2, plate, side, depth, zback-plate, "ferrite")
    box(editor, "E_CENTRE", -centre/2, -depth/2, plate+case["gap_mm"],
        centre, depth, zback-plate-case["gap_mm"], "ferrite")
    unite(editor, ["E_BACK", "E_LEFT", "E_RIGHT", "E_CENTRE"])
    for i in range(int(case["turns"])):
        ring(editor, i+1,
             float(g["first_foil_center_z_mm"]) + i*float(g["foil_axial_pitch_mm"]),
             case)
    names = list(editor.GetObjectsInGroup("Solids"))
    required = ["I38_FERRITE_PROXY", "E_BACK", "LR_OUTER_1", "LR_OUTER_2"]
    missing = [x for x in required if x not in names]
    if missing:
        raise RuntimeError("Missing resulting solids: " + repr(missing) + " from " + repr(names))
    project.SaveAs(TARGET, True)
    if not os.path.isfile(TARGET) or os.path.getsize(TARGET) < 10000:
        raise RuntimeError("No saved AEDT concept project")
    with open(RESULT, "w") as h:
        h.write("AEDT_3D_NATIVE_GEOMETRY_CREATED_NOT_SOLVED_NOT_FOR_FAB\n")
        h.write("target=" + TARGET + "\n")
        h.write("solids=" + repr(names) + "\n")
        h.write("source_sha256=" + hashlib.sha256(raw).hexdigest() + "\n")
        h.write("gap_mm=" + str(case["gap_mm"]) + "; turns_proxy=" + str(case["turns"]) + "\n")
        h.write("real_series_winding=False; verified_N97_100C_BH=False\n")
    try:
        ScriptEnv.Shutdown()
    except:
        pass

try:
    main()
except:
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    with open(RESULT, "w") as h:
        h.write("FAILED\n" + traceback.format_exc())
    try:
        ScriptEnv.Shutdown()
    except:
        pass
