"""Apply PF currents so FreeGSNKE coil flux is non-zero.

FreeGSNKE/freegs4e ``eq.psi()`` uses ``tokamak.getPsitokamak(vgreen)``, which
reads ``tokamak.current_vec`` — **not** ``coil.current`` alone. Assigning
``coil.current = …`` leaves ``current_vec`` at zero → total ψ = plasma_psi only
→ false 0 X-points after child restore (shot 30201).
"""

from __future__ import annotations

from typing import Any, Mapping


def set_tokamak_currents(tokamak: Any, currents: Mapping[str, Any]) -> list[str]:
    """Set named circuit currents via ``set_coil_current`` (updates current_vec).

    Returns list of circuit names that were applied. Missing names are skipped
    (caller may fail-closed separately).
    """
    applied: list[str] = []
    if not currents:
        return applied
    setter = getattr(tokamak, "set_coil_current", None)
    for name, amps in currents.items():
        key = str(name)
        try:
            val = float(amps)
        except (TypeError, ValueError):
            continue
        if callable(setter):
            try:
                setter(key, val)
                applied.append(key)
                continue
            except Exception:
                pass
        # Fallback: sync both coil.current and current_vec by index.
        try:
            order = getattr(tokamak, "coil_order", None) or {}
            if key in order:
                i = int(order[key])
                tokamak.coils[i][1].current = val
                tokamak.current_vec[i] = val
                applied.append(key)
                continue
        except Exception:
            pass
        try:
            for cname, coil in getattr(tokamak, "coils", []) or []:
                if str(cname) == key and hasattr(coil, "current"):
                    coil.current = val
                    # Best-effort: rebuild current_vec from coil.current attributes.
                    get_vec = getattr(tokamak, "getCurrentsVec", None)
                    if callable(get_vec):
                        get_vec()
                    applied.append(key)
                    break
        except Exception:
            continue
    return applied
