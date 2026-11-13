"""The manufacturing pages are the RFQ's frozen sibling, not a restatement of it.

An RFQ asks a supplier what they can offer across candidates.  A manufacturing
input page answers a different question: given one chosen part, what must the
winder make, what must be measured when it comes back, and what is still a
requirement rather than a drawing.

The tests below are the properties those pages have to hold -- one candidate
frozen, the transformer and the Lr kept on their own cores, simulation-derived
flux never called a measurement, and a backfill table that starts empty.
"""

from __future__ import annotations

import csv
import json
import re

import pytest

import magnetics_manufacturing_input as mmi

ROOT = mmi.ROOT
REFS = ["T1", "T2", "T3", "T4", "Lr", "CT"]


@pytest.fixture(scope="module")
def devs() -> list[dict]:
    return mmi.devices()


@pytest.fixture(scope="module")
def pages(devs) -> dict[str, str]:
    return {d["ref"]: mmi.render(d) for d in devs}


@pytest.fixture(scope="module")
def requested() -> dict:
    return json.loads((ROOT / "hardware/dcx_main/vendor_terminal_request.json").read_text(encoding="utf-8"))


def section(text: str, title: str) -> str:
    """Body of one ``## ...title...`` section, up to the next ``## ``."""
    match = re.search(rf"^## [^\n]*{re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"section {title!r} is missing"
    return match.group(1)


def test_every_part_gets_exactly_one_page(devs):
    assert [d["ref"] for d in devs] == REFS


def test_the_committed_pages_are_current():
    assert mmi.main(["--check"]) == 0


def test_the_transformer_and_the_inductor_do_not_share_a_core(pages):
    """The 2026-11-05 review's point: these are per-use candidates.

    The Lr failed the L*I/(N*A) screen on ELP32 and moved to ELP38; that says
    nothing about the transformers, whose flux is set by voltage integration.
    A page that quietly put all six on one core would erase the decision.
    """
    for ref in ("T1", "T2", "T3", "T4"):
        candidate = section(pages[ref], "冻结候选")
        assert "ELP32" in candidate, ref
        assert "ELP38" not in candidate, f"{ref} must not be frozen on the Lr's core"
    candidate = section(pages["Lr"], "冻结候选")
    assert "ELP38" in candidate
    assert "ELP32_I32" not in candidate


def test_each_page_freezes_exactly_one_candidate(pages):
    for ref in REFS:
        candidate = section(pages[ref], "冻结候选")
        rows = [line for line in candidate.splitlines() if line.startswith("| ") and not line.startswith("| 项目")]
        assert rows, ref
        core_rows = [r for r in rows if "磁芯" in r.split("|")[1]]
        assert len(core_rows) == 1, f"{ref} must name exactly one core set"
        assert "候选" not in core_rows[0] or "候选：无" in core_rows[0], (
            f"{ref} still offers a menu instead of a decision")


def test_the_flux_figures_are_labelled_simulation_not_measurement(pages):
    """A raw from a deck is a simulation; a measurement is what comes back."""
    for ref in REFS:
        assert "实测磁密" not in pages[ref], f"{ref} calls a deck integral a measurement"
    for ref in ("T1", "T2", "T3", "T4"):
        assert "仿真波形积分" in pages[ref]


def test_every_logical_terminal_has_a_requirement_row(pages, requested):
    """Physical pads are a requirement, not a number to invent.

    ``vendor_terminal_request.json`` already carries every terminal with a null
    ``vendor_physical_terminal_id``.  The Lr is not in that file -- it has two
    terminals the board netlist already names -- so its requirement comes from
    the netlist instead, and the page still must not invent a pad number.
    """
    by_ref = {d["ref"]: d for d in requested["devices"]}
    netlist = (ROOT / "design/v3/pcb/board_netlist.csv").read_text(encoding="utf-8").splitlines()
    lr_terminals = [(r["pin"], r["net"]) for r in csv.DictReader(netlist) if r["ref"] == "Lr"]
    assert len(lr_terminals) == 2, lr_terminals
    for ref in REFS:
        table = section(pages[ref], "端子需求")
        if ref == "Lr":
            terminals = lr_terminals
        else:
            terminals = [(p["logical_terminal"], p["required_circuit_net"]) for p in by_ref[ref]["pins"]]
        for logical, net in terminals:
            assert logical in table, (ref, logical)
            assert net in table, (ref, net)
        assert "待商家提供" in table, ref
        assert "physical_pad" not in pages[ref], (
            f"{ref} writes a physical pad id; there is no vendor drawing to read one from")


def test_each_page_states_its_test_conditions(pages):
    """A part without a test method is a part nobody can reject."""
    for ref in REFS:
        tests = section(pages[ref], "首件试验条件")
        assert "判据" in tests, ref
        assert "条件" in tests, ref
        assert "UNKNOWN" not in tests or "待厂家" in tests, (
            f"{ref}: a test condition cannot itself be UNKNOWN")


def test_every_page_carries_a_blank_measurement_backfill(pages):
    """The columns to fill on the first article, empty by design."""
    for ref in REFS:
        backfill = section(pages[ref], "实测回填")
        table = [line for line in backfill.splitlines() if line.startswith("| ")]
        assert len(table) >= 3, ref
        # Only the header starts with "| "; the separator starts with "|-", so it
        # is not in ``table`` and dropping one row is enough.
        rows = table[1:]
        values = [line.split("|")[2].strip() for line in rows]
        assert values and all(v == "—" for v in values), f"{ref}: {values[:3]}"
        labels = " ".join(line.split("|")[1] for line in rows)
        for field in ("件号", "日期", "L"):
            assert field in labels, (ref, field)


def test_no_page_claims_a_release(pages):
    for ref in REFS:
        assert mmi.STATUS in pages[ref]
        for word in ("APPROVED", "已放行", "签核通过"):
            assert word not in pages[ref], (ref, word)


def test_the_lr_page_says_which_number_to_wind(pages):
    """1.0 uH is the screening ceiling; the part is trimmed to the tank target."""
    lr = pages["Lr"]
    assert "L_external" in lr
    assert "筛选上限" in lr
    assert "0.920" in lr or "0.92" in lr


def test_lr_supplier_page_separates_1uH_sizing_from_real_external_target(pages):
    lr=section(pages["Lr"], "冻结候选")
    assert "筛选上限 AL（非量产目标）" in lr
    assert "250.0 nH/T^2" in lr
    assert "0.92 uH 模型外置目标 AL（待漏感首件修正）" in lr
    assert "230.0 nH/T^2" in lr
    assert "筛选上限1.00 uH 对应解析气隙（不可直接加工）" in lr
    assert "0.9461 mm" in lr
    assert "0.92 uH 预估外置气隙（待漏感测量和厂家标定）" in lr
    assert "1.0309 mm" in lr
    assert "121.515 A 高偏磁止损门槛" in lr
    assert "103.513 A" in lr and "225.391 mm²" in lr
    assert "不能直接加工" in lr or "不可直接加工" in lr


def test_the_ct_page_rejects_the_two_pad_footprint(pages):
    ct = pages["CT"]
    assert "4 个独立" in ct or "四个独立" in ct
    assert "2 pad" in ct or "两脚" in ct


def test_a_page_that_has_not_frozen_a_core_says_so(devs, pages):
    """The CT has no core selected at all; the header must not imply otherwise."""
    for dev in devs:
        if dev.get("frozen", True):
            assert "尚未选定" not in pages[dev["ref"]], dev["ref"]
        else:
            assert "尚未选定" in pages[dev["ref"]], dev["ref"]


def test_the_gap_window_is_ordered_by_inductance():
    """A wider gap means less inductance, so the low-L bound is the widest gap.

    Printed the other way the page reads "0.1374 - 0.1077 mm", which a machinist
    cannot grind to and which still passes every text-level test.
    """
    from magnetics_design import core_gap_m

    low, high = mmi.gap_window_mm(10e-6, 0.10, 3, 130e-6, 6300)
    nominal = core_gap_m(10e-6, 3, 130e-6, 6300) * 1e3
    assert low < nominal < high, (low, nominal, high)


def test_the_pages_are_deterministic(devs):
    assert mmi.render(devs[0]) == mmi.render(mmi.devices()[0])
