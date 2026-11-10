"""Apply the two power rails to a fresh copy of the routed candidate and read it back.

The rails are checked offline against `driver_route_readback.json`, but a plan is
not layout.  This is the single write step; the protocol lives in
``apply_increment`` (copy, settle+ping, invoke, save debounce, reopen readback,
verify).  The routed candidate is never opened -- the copy is
``dcx_main_board_g1_power_rails.eprj2``.
"""
from __future__ import annotations

from pathlib import Path

from apply_increment import apply
import route_power_rails as P

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "dcx_main_board_g1_driver_route.eprj2"
TARGET = HERE / P.CANDIDATE
BODY = P.R.emit_js(P.copper(), P.vias())  # kept for the offline test


if __name__ == "__main__":
    raise SystemExit(apply(P, SOURCE, "power_rails"))
