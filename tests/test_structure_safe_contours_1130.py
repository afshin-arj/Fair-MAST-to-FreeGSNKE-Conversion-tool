"""Structure-masked open-field contours (v11.30.0)."""

from __future__ import annotations

import inspect

import numpy as np

from mast_freegsnke.equilibrium_presentation import (
    PresentationAuthority,
    mask_psi_for_structure_safe_contours,
    plot_equilibrium_curated,
    structure_safe_contour_mask,
)


class _Fil:
    def __init__(self, R, Z, dR=0.02, dZ=0.02, Rfil=None, Zfil=None):
        self.R = R
        self.Z = Z
        self.dR = dR
        self.dZ = dZ
        self.Rfil = np.asarray(Rfil if Rfil is not None else [R], dtype=float)
        self.Zfil = np.asarray(Zfil if Zfil is not None else [Z], dtype=float)


class _Circuit:
    def __init__(self, name: str, fils):
        self.coils = [(name, f) for f in fils]


class _Lim:
    def __init__(self):
        # Unit box limiter
        self.R = np.array([0.2, 1.8, 1.8, 0.2, 0.2], dtype=float)
        self.Z = np.array([-1.5, -1.5, 1.5, 1.5, -1.5], dtype=float)


class _Tok:
    def __init__(self):
        # Solenoid-like stack near R=0.14 and a PF coil
        sol = _Fil(
            0.14,
            0.0,
            dR=0.01,
            dZ=0.02,
            Rfil=np.full(5, 0.14),
            Zfil=np.linspace(-1.0, 1.0, 5),
        )
        pf = _Fil(1.5, 1.0, dR=0.03, dZ=0.04, Rfil=[1.5], Zfil=[1.0])
        self.coils = [("Solenoid", _Circuit("Solenoid", [sol])), ("P4", _Circuit("P4", [pf]))]
        self.limiter = _Lim()


def test_structure_mask_excludes_coil_and_outside_limiter() -> None:
    R, Z = np.meshgrid(np.linspace(0.05, 2.0, 40), np.linspace(-2.0, 2.0, 50), indexing="ij")
    tok = _Tok()
    allow = structure_safe_contour_mask(tok, R, Z, coil_pad=1.35)
    # Outside limiter
    assert not bool(allow[0, 25])  # R~0.05 outside
    # Inside vessel far from coils
    i = int(np.argmin(np.abs(R[:, 0] - 0.9)))
    j = int(np.argmin(np.abs(Z[0, :] - 0.0)))
    assert bool(allow[i, j])
    # On solenoid filament
    i_s = int(np.argmin(np.abs(R[:, 0] - 0.14)))
    j_s = int(np.argmin(np.abs(Z[0, :] - 0.0)))
    assert not bool(allow[i_s, j_s])
    # On PF coil
    i_p = int(np.argmin(np.abs(R[:, 0] - 1.5)))
    j_p = int(np.argmin(np.abs(Z[0, :] - 1.0)))
    assert not bool(allow[i_p, j_p])


def test_mask_psi_nan_on_excluded() -> None:
    R, Z = np.meshgrid(np.linspace(0.05, 2.0, 20), np.linspace(-2.0, 2.0, 20), indexing="ij")
    psi = np.ones(R.shape)
    out = mask_psi_for_structure_safe_contours(psi, R, Z, _Tok())
    assert np.isnan(out).any()
    assert np.isfinite(out).any()


def test_presentation_authority_open_field_default() -> None:
    auth = PresentationAuthority()
    assert auth.show_open_field is True
    assert auth.n_open_contours == 6


def test_curated_defaults_open_field_on() -> None:
    sig = inspect.signature(plot_equilibrium_curated)
    assert sig.parameters["show_open_field"].default is True
