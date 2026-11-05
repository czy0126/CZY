"""Render and audit the value-only ECO for the native EasyEDA Pro main board.

``hardware/dcx_main/placeholder_eco.json`` classifies every one of the 61
placeholders by what the board can actually do to it.  This tool is the
executor for one class only -- ``NATIVE_VALUE_EDIT`` -- because that is the only
class the editor's scripting API can complete:

* the placed library device carries the vendor attributes (LCSC part, datasheet,
  JLCPCB class), and ``sch_PrimitiveComponent.modify`` can change
  ``otherProperty.Value`` while leaving those untouched;
* there is no device setter and no footprint setter in this build, so a row
  whose package or device is wrong cannot be fixed this way -- it stays a
  ``GUI_DEVICE_SWAP`` and is deliberately absent from the plan.

The plan is a committed JSON file so the exact edit set is reviewable and a
later run can be compared against it.  The editor body is a template
(``hardware/dcx_main/gen/value_eco.js``) whose plan literal and APPLY token are
substituted here; nothing about the edit set lives in the JavaScript.

Usage:
    python tools/native_value_eco.py --write-plan      # regenerate the plan
    python tools/native_value_eco.py --check           # is the committed plan current?
    python tools/native_value_eco.py --code            # print the dry-run body
    python tools/native_value_eco.py --code --apply    # print the editing body
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
TEMPLATE = HW / "gen/value_eco.js"
ECO = HW / "placeholder_eco.json"
PLAN = HW / "gen/value_eco_plan.json"
INVENTORY = HW / "gen/native_inventory_raw.json"

PLAN_MARK = "/*__PLAN__*/[];"
APPLY_OFF = "const APPLY = false;"
APPLY_ON = "const APPLY = true;"
EXECUTED_CLASS = "NATIVE_VALUE_EDIT"


def _natural(ref: str) -> tuple[str, int]:
    """R2 before R20 before R101; the register's own order is not natural."""
    m = re.match(r"([A-Za-z]+)(\d+)$", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


def build() -> dict:
    """The plan: exactly the rows the ECO table says the editor can finish."""
    eco = json.loads(ECO.read_text(encoding="utf-8"))
    edits = []
    for row in eco["rows"]:
        if row["eco_class"] != EXECUTED_CLASS:
            continue
        edits.append({
            "ref": row["ref"],
            "from": row["native_value"],
            "to": row["target_value"],
            "acceptance": row["eco_acceptance"],
        })
    edits.sort(key=lambda e: _natural(e["ref"]))
    return {
        "status": "VALUE_ECO_PLAN",
        "source": "hardware/dcx_main/placeholder_eco.json",
        "executor": "TOOL_NATIVE_VALUE_ECO",
        "template": "hardware/dcx_main/gen/value_eco.js",
        "scope": ("Value property only. The placed library device and its footprint "
                  "are not changed by this batch; every other row is a GUI step."),
        "count": len(edits),
        "edits": edits,
    }


def render(apply: bool = False) -> str:
    """The editor body, with the plan inlined and APPLY flipped if asked.

    Both substitutions are asserted to occur exactly once: a template edit that
    reintroduced a second literal would otherwise let the plan silently disagree
    with the copy that runs.
    """
    body = TEMPLATE.read_text(encoding="utf-8")
    if body.count(PLAN_MARK) != 1:
        raise SystemExit(f"{TEMPLATE}: expected exactly one {PLAN_MARK!r}")
    # ensure_ascii keeps the literal pure ASCII: the body travels through the
    # Windows command line, whose GBK code page cannot carry the ohm sign.  JSON
    # "Ω" is the same string to the JavaScript parser, so nothing about the
    # plan changes -- only its transport encoding.
    literal = json.dumps([{"ref": e["ref"], "want": e["to"]} for e in build()["edits"]],
                         ensure_ascii=True, indent=2)
    body = body.replace(PLAN_MARK, f"/*__PLAN__*/{literal};")
    if apply:
        if body.count(APPLY_OFF) != 1:
            raise SystemExit(f"{TEMPLATE}: expected exactly one {APPLY_OFF!r}")
        body = body.replace(APPLY_OFF, APPLY_ON)
    return body


def _board_values() -> dict[str, str]:
    """ref -> Value as the *saved* native board reads it, from the inventory dump."""
    if not INVENTORY.is_file():
        return {}
    body = json.loads(INVENTORY.read_text(encoding="utf-8"))
    value = body.get("value") or {}
    if value.get("status") != "INVENTORY":
        return {}
    return {c["ref"]: c.get("value") for c in value.get("components") or [] if c.get("ref")}


def stale_reason(plan: dict) -> str | None:
    """None when the committed plan is still a true record of this ECO.

    There are two ways for a plan to be current, and the second one exists
    because the first would condemn a *successful* run:

    * **before execution** it equals what the ECO table asks for right now;
    * **after execution** every one of its edits is what the saved board reads.
      The table then classifies those rows ``ALREADY_CONFORMS``, so a freshly
      built plan is empty -- comparing the record against it would report the
      completed batch as stale.

    Anything else is stale, and the reason names the refs that disagree.
    """
    if not PLAN.is_file():
        return f"{PLAN} does not exist"
    committed = json.loads(PLAN.read_text(encoding="utf-8"))
    if committed == plan:
        return None
    board = _board_values()
    planned = {e["ref"]: e["to"] for e in committed.get("edits", [])}
    pending = {e["ref"]: e["to"] for e in plan["edits"]}
    missing = sorted(set(pending) - set(planned), key=_natural)
    moved = sorted((r for r in set(pending) & set(planned) if pending[r] != planned[r]), key=_natural)
    unapplied = sorted((r for r in planned if board.get(r) != planned[r]), key=_natural)
    if not missing and not moved and not unapplied:
        return None
    return (f"stale plan {PLAN.name}: added={missing} "
            f"changed={[(r, planned[r], pending[r]) for r in moved]} "
            f"not_on_the_board={unapplied}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--write-plan", action="store_true", help="regenerate the committed plan")
    group.add_argument("--check", action="store_true", help="fail if the committed plan is stale")
    group.add_argument("--code", action="store_true", help="print the editor body")
    ap.add_argument("--apply", action="store_true",
                    help="with --code: flip APPLY so the body edits instead of reporting")
    args = ap.parse_args(argv)
    if args.apply and not args.code:
        ap.error("--apply only means something with --code: it flips the token in the body")

    plan = build()
    if args.write_plan:
        # Once the batch has run, the plan is the record of what was executed and
        # the table no longer asks for those rows -- so a plain regeneration would
        # replace 37 edits with an empty list and destroy the only account of them.
        if not plan["edits"] and PLAN.is_file():
            old = json.loads(PLAN.read_text(encoding="utf-8")).get("edits", [])
            board = _board_values()
            if old and all(board.get(e["ref"]) == e["to"] for e in old):
                raise SystemExit(
                    f"{PLAN.name} records {len(old)} executed edits and the saved board matches "
                    "all of them; refusing to overwrite that record with an empty plan")
        PLAN.parent.mkdir(parents=True, exist_ok=True)
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
        print(f"wrote {PLAN.relative_to(ROOT)}: {plan['count']} value edits")
        return 0
    if args.check:
        reason = stale_reason(plan)
        if reason:
            raise SystemExit(reason)
        recorded = json.loads(PLAN.read_text(encoding="utf-8")).get("edits", []) if PLAN.is_file() else []
        if recorded and not plan["edits"]:
            print(f"executed record current: all {len(recorded)} edits read back from the saved board")
        else:
            print(f"plan current: {plan['count']} value edits")
        return 0
    if args.code:
        # The console is GBK; the body is written to stdout only when redirected
        # to a UTF-8 file.  Say so rather than die on the ohm sign.
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(render(apply=args.apply))
        return 0

    print(f"{plan['count']} value edits "
          f"({sum(1 for e in plan['edits'] if e['from'] != e['to'])} actually change a value)")
    for e in plan["edits"]:
        print(f"  {e['ref']:>5} {e['from'] or '(none)':>8} -> {e['to']}")
    print("\nthen: python tools/native_value_eco.py --code > /tmp/value_eco.js  "
          "# dry run; add --apply to edit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
