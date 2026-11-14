"""V17 near-pad Kelvin sense routes after R28..R35 SR-channel relocation.

Actual F.Cu SEC_n_A/B resistor pad1 to corresponding SR pad6; no switching-
power or gate conduction is routed. These signals are on the SEC drain
switch-node; actual OEM pinout, Kelvin pickup parasitics and EMC still need
physical review. Safe design requires *short* routes, not merely DRC=0.
"""
from __future__ import annotations
import json,math
from shapely.geometry import Point,LineString,box
import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as ground
import g2_v17_route_conservative_signal as signal
import g2_v17_bcu_short_control_bridges as bcu
import g2_v17_u2_fine_escape as fine
import g2_v17_local_primary_gate_routes as gate

OUT=base.G/"g2_v17_short_sr_drain_kelvin_NOT_FOR_FAB.json"
WIDTH=.20
CLEARANCE=.25  # stronger than native min 0.2 mm

def _pad(pads,ref,pin,net):
    match=[p for p in pads if p["ref"]==ref
           and p["number"]==pin and p["net"]==net and p["layer"]==1]
    if len(match)!=1:
        raise ValueError(f"Pad numbering drift {ref}.{pin}[{net}]")
    return match[0]

def generate():
    native,slots=base.load()
    xy=layout.layout(native)
    pads=base.transferred_pad_records(native,xy)
    power=ground.generate()
    sg=json.loads(signal.OUT.read_text("utf8"))
    bg=json.loads(bcu.OUT.read_text("utf8"))
    fg=json.loads(fine.OUT.read_text("utf8"))
    gg=json.loads(gate.OUT.read_text("utf8"))
    shas={"source_v15_sha":base.sha(base.NATIVE),
          "source_layout_sha":base.sha(layout.OUT),
          "source_pgnd_sha":base.sha(ground.OUT),
          "source_signal_sha":base.sha(signal.OUT),
          "source_bcu_sha":base.sha(bcu.OUT),
          "source_gd_sha":base.sha(fine.OUT),
          "source_gate_sha":base.sha(gate.OUT)}
    if (sg["source_V17_sha"]!=shas["source_layout_sha"] or
        bg["source_signal_sha"]!=shas["source_signal_sha"] or
        fg["source_bcu_sha"]!=shas["source_bcu_sha"] or
        gg["source_gd_sha"]!=shas["source_gd_sha"]):
        raise ValueError("SR Kelvin model source drift")
    via_groups=("planned_via_in_pad_sites",
                "additional_local_driver_reg_pgnd_and_Cout_stitches",
                "control_U1_U2_PGND_via_sites",
                "auxiliary_12V_S_and_12V_via_sites",
                "auxiliary_pgnd_return_via_sites",
                "control_U1_VCC12_feed_via_sites")
    vias=[(v["net"],Point(v["x_mm"],v["y_mm"]),.35)
          for field in via_groups for v in power[field]]
    vias.extend((v["net"],Point(v["x_mm"],v["y_mm"]),.35)
                for part in bg["bridges"] for v in part["via_sites"])
    vias.extend((v["net"],Point(v["x_mm"],v["y_mm"]),.35)
                for v in fg["via_sites"])
    obs=[(p["net"],p["geom"],p["layer"]) for p in pads]
    for item in slots["slots"]:
        obs.append(("",box(item["x_min_mm"],item["y_min_mm"]+13,
                           item["x_max_mm"],item["y_max_mm"]+13).buffer(.6),1))
    tracks=[(r["net"],LineString(seg)) for r in sg["segments"]
            for seg in r["segments"]]
    tracks += [(r["net"],LineString(seg)) for r in fg["routes"]
               if r["layer"]=="F.Cu" for seg in r["segments"]]
    tracks += [(r["net"],LineString(seg)) for r in gg["routes"]
               for seg in r["segments"]]
    for key in ("input_pgnd_to_QL_pad_target",
                "control_U2_pgnd9_to_exposed_pgnd11_link"):
        tracks.append(("PGND",LineString(power[key]["path_mm"])))
    result=[]
    old_width,old_clear=signal.WIDTH,signal.MINCLEAR
    try:
        signal.WIDTH=WIDTH
        signal.MINCLEAR=CLEARANCE
        for i in range(1,5):
            for bank in ("A","B"):
                net=f"SEC{i}_{bank}"
                resistor=f"R{28+2*(i-1)+(bank=='B')}"
                sr=f"SR{i}{bank}"
                start=_pad(pads,resistor,"1",net)["geom"].centroid.coords[0]
                end=_pad(pads,sr,"6",net)["geom"].centroid.coords[0]
                dist=math.dist(start,end)
                if not (2.<dist<3.2):
                    raise ValueError("SR Kelvin too long / resistor placement drift "+net)
                if abs(xy[resistor][1]-54.5)>.001:
                    raise ValueError("SR sense resistor must be in y54.5 row "+resistor)
                candidate=[list(start),list(end)]
                if signal.path_collision(candidate,net,obs,tracks,vias):
                    raise ValueError("SR Kelvin crosses foreign copper/slot "+net)
                tracks.append((net,LineString(candidate)))
                result.append({"net":net,"from":resistor+".1","to":sr+".6",
                               "layer":"F.Cu","width_mm":WIDTH,
                               "actual_length_mm":round(dist,5),
                               "segments":[candidate]})
    finally:
        signal.WIDTH,signal.MINCLEAR=old_width,old_clear
    data={"status":"V17_SHORT_SR_KELVIN_NATIVE_DRC_REQUIRED_NOT_FOR_FAB",
          **shas,"routes":result,
          "control_signal_only":True,"kelvin_loop_inductance_extracted":False,
          "real_sr_oem_pinout_confirmed":False,
          "short_circuit_risk_passed":False,
          "native_drc_verified":False,"emc_approved":False,"fab_release":False}
    OUT.write_text(json.dumps(data,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"routes":len(result),
                      "max_length_mm":max(x["actual_length_mm"] for x in result),
                      "mean_length_mm":round(sum(x["actual_length_mm"] for x in result)/len(result),3)}))
    return data

if __name__=="__main__":
    generate()
