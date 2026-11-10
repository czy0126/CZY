"""Apply the two CT sense nets (CS1 / CS2) to a fresh copy of the power-rail candidate.

Same write step as the rails, same protocol module: copy, settle+ping, invoke,
save debounce, reopen readback, verify.  The parent
``dcx_main_board_g1_power_rails.eprj2`` is only read (hash-checked), never
opened in place.
"""
from __future__ import annotations

from pathlib import Path

from apply_increment import apply
import route_kelvin as K

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "dcx_main_board_g1_power_rails.eprj2"
TARGET = HERE / K.CANDIDATE
BODY = K.R.emit_js(K.copper(), K.vias())  # kept for the offline test


if __name__ == "__main__":
    raise SystemExit(apply(K, SOURCE, "kelvin"))
