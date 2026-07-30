"""Tests for FreeGSNKE current_vec sync helper."""

from __future__ import annotations

from mast_freegsnke.tokamak_currents import set_tokamak_currents


def test_set_tokamak_currents_updates_current_vec() -> None:
    class _Coil:
        def __init__(self) -> None:
            self.current = 0.0

    class _Tok:
        def __init__(self) -> None:
            self.coils = [("A", _Coil()), ("B", _Coil())]
            self.coil_order = {"A": 0, "B": 1}
            self.current_vec = [0.0, 0.0]
            self.calls = []

        def set_coil_current(self, name: str, value: float) -> None:
            i = self.coil_order[name]
            self.coils[i][1].current = float(value)
            self.current_vec[i] = float(value)
            self.calls.append((name, float(value)))

    tok = _Tok()
    applied = set_tokamak_currents(tok, {"A": 1.5, "B": -2.0, "missing": 9.0})
    assert applied == ["A", "B"]
    assert tok.current_vec == [1.5, -2.0]
    assert tok.coils[0][1].current == 1.5
