"""Read a pin -> net map out of EasyEDA schematic primitives.

Why this exists
---------------
Every manufacturing export of a ``--path``-opened native EasyEDA Pro project
returns null.  Measured on 2026-11-10 against the active G1 board:

* ``sch_ManufactureData.getNetlistFile`` -> null
* ``sch_ManufactureData.getSimulationNetlistFile`` -> null
* ``sch_ManufactureData.getBomFile`` -> null
* ``sch_Net.getCurrentProjectAllNets()`` -> ``[]`` (also with the page open)
* ``sch_Netlist.getNetlist(...)`` -> undefined

The primitive database is still readable, and the editor itself put the net
name on every wire: ``sch_PrimitiveWire`` exposes ``getState_Net()`` beside
``getState_Line()``, and every component pin exposes its schematic coordinate.
So connectivity can be *read* instead of *exported* -- with one condition.

Why it can be trusted
---------------------
Reading is only evidence if it is checked against something the editor produced
by itself.  The same ``reconstruct()`` run on
``hardware/dcx_main/dcx_main_board.eprj2`` reproduces
``hardware/dcx_main/gen/netlist_export_raw.json`` -- the Nov 6 editor export --
exactly: 83 designators, tick for tick, including the five pins the export
itself leaves as ``""`` (D_CT1..D_CT4 pin 2, U2 pin 2).
``hardware/dcx_main/g1/export_live_netlist.py`` enforces that before it reports
the G1 board.

The method is deliberately narrow and fails closed:

* a wire with no net name is refused (nothing to assign);
* two different nets meeting at one coordinate are refused (ambiguous);
* a pin strictly inside a wire segment is refused rather than guessed at -- an
  EasyEDA pin sits on a wire endpoint, and a pin on the interior means the
  primitive set is not the shape this reader assumes.

``reconstruct()`` returns
``{"refs": {ref: {pin: net}}, "unmatched": [...], "wire_count": n}``.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _key(x: float, y: float) -> tuple[float, float]:
    """Schematic coordinates as an exact lookup key (primitive grid is 0.01)."""
    return (round(float(x), 3), round(float(y), 3))


def _net_through(segments: list[tuple], point: tuple[float, float]) -> str | None:
    """The net of a segment that passes strictly through ``point``, if any."""
    px, py = point
    for x1, y1, x2, y2, net in segments:
        if (x2 - x1) * (py - y1) != (y2 - y1) * (px - x1):
            continue
        if min(x1, x2) < px < max(x1, x2) or min(y1, y2) < py < max(y1, y2):
            return net
    return None


def reconstruct(capture: dict) -> dict:
    """Turn a CONNECTIVITY capture into ``{ref: {pin: net}}`` plus diagnostics."""
    value = capture.get("value") if isinstance(capture, dict) else None
    if not (isinstance(capture, dict) and capture.get("ok")
            and isinstance(value, dict) and value.get("status") == "CONNECTIVITY"):
        raise ValueError("capture is not an EasyEDA CONNECTIVITY read")

    endpoints: dict[tuple[float, float], str] = {}
    segments: list[tuple] = []
    for wire in value.get("wires") or []:
        x1, y1, x2, y2 = (float(v) for v in wire["line"])
        net = wire.get("net")
        if not isinstance(net, str) or not net:
            raise ValueError(f"wire {wire['line']} carries no net name")
        for point in (_key(x1, y1), _key(x2, y2)):
            if point in endpoints and endpoints[point] != net:
                raise ValueError(
                    f"two nets meet at {point}: {endpoints[point]} and {net}")
            endpoints[point] = net
        segments.append((x1, y1, x2, y2, net))

    refs: dict[str, dict[str, str]] = {}
    unmatched: list[dict] = []
    for component in value.get("components") or []:
        ref = component.get("ref")
        if not ref:
            # No designator means no netlist identity; the editor has the same.
            continue
        pins: dict[str, str] = {}
        for pin in component.get("pins") or []:
            number = str(pin.get("number"))
            point = _key(pin["x"], pin["y"])
            if point in endpoints:
                pins[number] = endpoints[point]
                continue
            interior = _net_through(segments, point)
            if interior is not None:
                raise ValueError(
                    f"{ref} pin {number} sits inside a wire of net {interior}; "
                    "this reader only assigns pins that sit on a wire endpoint")
            pins[number] = ""
            unmatched.append({"ref": ref, "pin": number, "x": point[0], "y": point[1]})
        refs[ref] = pins

    return {"refs": refs, "unmatched": unmatched, "wire_count": len(segments)}


def diff_netlists(reference: dict, candidate: dict) -> dict:
    """Per-designator, per-pin difference between two ``{ref: {pin: net}}`` maps."""
    only_reference = sorted(set(reference) - set(candidate))
    only_candidate = sorted(set(candidate) - set(reference))
    changed: list[dict] = []
    for ref in sorted(set(reference) & set(candidate)):
        pins: dict[str, dict] = {}
        for pin in sorted(set(reference[ref]) | set(candidate[ref])):
            before = reference[ref].get(pin)
            after = candidate[ref].get(pin)
            if before != after:
                pins[pin] = {"reference": before, "candidate": after}
        if pins:
            changed.append({"ref": ref, "pins": pins})
    return {
        "refs_only_in_reference": only_reference,
        "refs_only_in_candidate": only_candidate,
        "changed": changed,
        "changed_ref_count": len(changed),
        "identical": not (only_reference or only_candidate or changed),
    }
