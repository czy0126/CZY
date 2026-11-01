"""Read sim/v2/comm_v3/sr_commutation_v3.raw cases for independent checks.

Case index 0..7 maps to the eight .step runs in the order printed in the log
(step 1 = PGD0/23n/2n, ..., step 8 = PGD1/200n/1n).  Cross-check by reading
the '.step' lines in sr_commutation_v3.log, and by the PGD1 cases having
V(gda) max ~5.58 V instead of ~10.9 V.

Usage (project root):
    from tools.comm_v3_probe import Case
    c = Case(0)
    c.at('I(Vsa)', 19.834e-6)
    c.max_between('I(Vsa)', 17e-6, 22e-6)
    c.integral('V(d1)', 'I(Vsa)', 19.95e-6, 20.5e-6)

The optional raw argument selects another stepped file with the same layout:
    c = Case(1, 'sim/v2/comm_v3/sr_commutation_v3_roff.raw')
"""
import numpy as np
import ltspice

RAW = 'sim/v2/comm_v3/sr_commutation_v3.raw'
_CACHE: dict[str, "_Parsed"] = {}


class _Parsed:
    def __init__(self, raw: str) -> None:
        self.l = ltspice.Ltspice(raw)
        self.l.parse()
        self.names = self.l.getVariableNames()


def _parsed(raw: str) -> "_Parsed":
    if raw not in _CACHE:
        _CACHE[raw] = _Parsed(raw)
    return _CACHE[raw]


class Case:
    def __init__(self, idx: int, raw: str = RAW) -> None:
        p = _parsed(raw)
        self.idx = idx
        self.t = np.asarray(p.l.get_time(idx))
        self._data = {n: np.asarray(p.l.get_data(n, idx)) for n in p.names if n != 'time'}

    def v(self, name: str) -> np.ndarray:
        return self._data[name]

    def at(self, name: str, t: float) -> float:
        return float(np.interp(t, self.t, self._data[name]))

    def _mask(self, t0: float, t1: float) -> np.ndarray:
        return (self.t >= t0) & (self.t <= t1)

    def max_between(self, name: str, t0: float, t1: float) -> float:
        return float(self._data[name][self._mask(t0, t1)].max())

    def min_between(self, name: str, t0: float, t1: float) -> float:
        return float(self._data[name][self._mask(t0, t1)].min())

    def integral(self, name_a: str, name_b: str, t0: float, t1: float) -> float:
        """Integral of a*b over [t0, t1], e.g. V(d1)*I(Vsa)."""
        m = self._mask(t0, t1)
        return float(np.trapezoid(self._data[name_a][m] * self._data[name_b][m], self.t[m]))

    def integral_abs(self, name_a: str, name_b: str, t0: float, t1: float) -> float:
        m = self._mask(t0, t1)
        return float(np.trapezoid(np.abs(self._data[name_a][m] * self._data[name_b][m]), self.t[m]))
